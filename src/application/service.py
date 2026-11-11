"""Search and answer service over a workspace (inference only; never trains or fits)."""

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from application.workspace import Chunk, Workspace
from retrieval.bm25 import BM25Document, BM25RetrievalBaseline

MODES = ("bm25", "dense", "hybrid")


class ServiceError(ValueError):
    """User-facing error (bad mode, no index, model unavailable)."""


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if t]


def _ids_digest(chunks: List[Chunk]) -> str:
    return hashlib.sha256("\n".join(c.chunk_id for c in chunks).encode("utf-8")).hexdigest()


class SearchService:
    def __init__(
        self,
        workspace: Workspace,
        checkpoint: Optional[Path] = None,
        tokenizer_model: Optional[Path] = None,
        device: Optional[str] = None,
        notice: str = "",
        rrf_k: int = 60,
        max_top_k: int = 50,
    ) -> None:
        self.notice = notice
        self.rrf_k = rrf_k
        self.max_top_k = max_top_k
        self.workspace = workspace
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.tokenizer_model = Path(tokenizer_model) if tokenizer_model else None
        self.device = device
        self._lock = threading.RLock()
        self._predictor: Any = None
        self._chunks: List[Chunk] = []
        self._bm25: Optional[BM25RetrievalBaseline] = None
        self._matrix: Optional[np.ndarray] = None
        self._loaded_signature: Optional[str] = None

    # -- state -----------------------------------------------------------------------------
    @property
    def has_model(self) -> bool:
        return self.checkpoint is not None and self.tokenizer_model is not None

    def _predictor_or_raise(self) -> Any:
        if not self.has_model:
            raise ServiceError("No model configured: start with --checkpoint and --tokenizer-model")
        if self._predictor is None:
            from language.inference.loader import load_encoder
            from language.inference.predictor import LanguageEncoderPredictor

            assert self.checkpoint is not None and self.tokenizer_model is not None
            encoder = load_encoder(self.checkpoint, self.tokenizer_model, device=self.device)
            self._predictor = LanguageEncoderPredictor(encoder)
        return self._predictor

    def _refresh(self) -> None:
        """Reload passages, BM25 and the dense matrix when the workspace changed."""
        chunks_file = self.workspace.chunks_path
        signature = f"{chunks_file.stat().st_mtime_ns}" if chunks_file.exists() else "none"
        if signature == self._loaded_signature:
            return
        self._chunks = self.workspace.load()
        self._bm25 = None
        if self._chunks:
            bm25 = BM25RetrievalBaseline()
            docs = []
            for chunk in self._chunks:
                toks = _tokens(f"{chunk.title} {chunk.text}")
                if toks:
                    docs.append(BM25Document(chunk.chunk_id, chunk.text, toks))
            if docs:
                bm25.index_documents(docs)
                self._bm25 = bm25
        self._matrix = self._load_matrix()
        self._loaded_signature = signature

    def _load_matrix(self) -> Optional[np.ndarray]:
        meta_path = self.workspace.root / "embeddings.json"
        vec_path = self.workspace.root / "embeddings.npy"
        if not (meta_path.exists() and vec_path.exists()) or not self._chunks:
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("chunks_sha256") != _ids_digest(self._chunks):
            return None
        return np.asarray(np.load(vec_path))

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh()
            docs = {c.doc_id for c in self._chunks}
            info: Dict[str, Any] = {
                "documents": len(docs),
                "passages": len(self._chunks),
                "bm25_ready": self._bm25 is not None,
                "dense_ready": self._matrix is not None,
                "model_configured": self.has_model,
                "checkpoint": str(self.checkpoint) if self.checkpoint else None,
                "notice": self.notice,
            }
            if self.checkpoint:
                manifest = self.checkpoint / "manifest.json"
                if manifest.exists():
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    info["model_sha256"] = data.get("model_sha256")
            return info

    # -- indexing --------------------------------------------------------------------------
    def build_dense_index(self, batch_log: Optional[Any] = None) -> Dict[str, Any]:
        """Embed every passage with the checkpoint (inference only) and save the matrix."""
        with self._lock:
            self._refresh()
            if not self._chunks:
                raise ServiceError("Nothing to index: ingest documents first")
            predictor = self._predictor_or_raise()
            rows = []
            for start in range(0, len(self._chunks), 32):
                batch = self._chunks[start : start + 32]
                rows.append(predictor.embed([f"{c.title}. {c.text}" for c in batch]))
                if batch_log:
                    batch_log(min(start + 32, len(self._chunks)), len(self._chunks))
            matrix = np.concatenate(rows).astype(np.float32)
            np.save(self.workspace.root / "embeddings.npy", matrix)
            meta = {
                "chunks_sha256": _ids_digest(self._chunks),
                "count": len(self._chunks),
                "model_sha256": predictor.encoder.manifest.get("model_sha256"),
            }
            (self.workspace.root / "embeddings.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            self._matrix = matrix
            return meta

    # -- search ----------------------------------------------------------------------------
    def _bm25_rank(self, query: str, top_k: int) -> List[int]:
        if self._bm25 is None:
            return []
        position = {c.chunk_id: i for i, c in enumerate(self._chunks)}
        return [position[r.doc_id] for r in self._bm25.search(query, top_k=top_k)]

    def _dense_rank(self, query: str, top_k: int) -> List[int]:
        if self._matrix is None:
            raise ServiceError("Dense index not built: run `laris app index` (needs a checkpoint)")
        vec = self._predictor_or_raise().embed([query])[0]
        scores = self._matrix @ vec
        return [int(i) for i in np.argsort(-scores)[:top_k]]

    def search(self, query: str, mode: str = "bm25", top_k: int = 5) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            raise ServiceError("Query is empty")
        if mode not in MODES:
            raise ServiceError(f"mode must be one of {MODES}")
        top_k = max(1, min(int(top_k), self.max_top_k))
        with self._lock:
            self._refresh()
            if not self._chunks:
                raise ServiceError("No documents yet: ingest some first")
            pool = max(top_k * 4, 20)
            if mode == "bm25":
                order = self._bm25_rank(query, top_k)
            elif mode == "dense":
                order = self._dense_rank(query, top_k)
            else:
                fused: Dict[int, float] = {}
                for ranking in (self._bm25_rank(query, pool), self._dense_rank(query, pool)):
                    for rank, idx in enumerate(ranking, start=1):
                        fused[idx] = fused.get(idx, 0.0) + 1.0 / (self.rrf_k + rank)
                order = sorted(fused, key=lambda i: (-fused[i], i))[:top_k]
            hits = [self._hit(self._chunks[i], rank) for rank, i in enumerate(order, start=1)]
        return {"query": query, "mode": mode, "hits": hits, "notice": self.notice}

    @staticmethod
    def _hit(chunk: Chunk, rank: int) -> Dict[str, Any]:
        return {
            "rank": rank,
            "chunk_id": chunk.chunk_id,
            "source": chunk.source,
            "title": chunk.title,
            "text": chunk.text,
            "span": [chunk.start, chunk.end],
        }

    # -- answer ----------------------------------------------------------------------------
    def answer(self, question: str, mode: str = "bm25", top_k: int = 3) -> Dict[str, Any]:
        """Extractive answers from the top passages; each is checked to be quoted verbatim."""
        found = self.search(question, mode=mode, top_k=top_k)
        with self._lock:
            predictor = self._predictor_or_raise()
            answers = []
            for hit in found["hits"]:
                result = predictor.qa(hit["text"], question)
                text = (result.get("answer") or "").strip()
                offset = hit["text"].lower().find(text.lower()) if text else -1
                answers.append(
                    {
                        "chunk_id": hit["chunk_id"],
                        "source": hit["source"],
                        "answer": text or None,
                        "no_answer": bool(result.get("no_answer")) or not text,
                        "verbatim_in_passage": offset >= 0,
                        "answer_span_in_passage": [offset, offset + len(text)]
                        if offset >= 0
                        else None,
                    }
                )
        primary = next((a for a in answers if a["answer"] and a["verbatim_in_passage"]), None)
        return {**found, "answers": answers, "primary": primary}
