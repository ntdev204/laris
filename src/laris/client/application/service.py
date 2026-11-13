"""Search and answer service over a workspace (inference only; never trains or fits)."""

import re
import threading
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from laris.client.application.workspace import Chunk, Workspace
from laris.shared.retrieval.bm25 import BM25Document, BM25RetrievalBaseline

MODES = ("bm25", "dense", "hybrid")


class ServiceError(ValueError):
    """User-facing error (bad mode, no index, model unavailable)."""


class NoDocumentsError(ServiceError):
    """The index is empty: no other query can help until something is ingested."""


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if t]


class SearchService:
    def __init__(
        self,
        workspace: Workspace,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        notice: str = "",
        rrf_k: int = 60,
        max_top_k: int = 50,
        model_id: str = "server",
    ) -> None:
        self.model_id = model_id
        self.on_ingest: Optional[Callable[[List[Chunk], List[Chunk]], Dict[str, Any]]] = None
        self.notice = notice
        self.rrf_k = rrf_k
        self.max_top_k = max_top_k
        self.workspace = workspace
        self.embedder = embedder  # embeds through the server (POST /v1/laris/embed)
        self._lock = threading.RLock()
        self._chunks: List[Chunk] = []
        self._bm25: Optional[BM25RetrievalBaseline] = None
        self._matrix: Optional[np.ndarray] = None
        self._loaded_signature: Optional[str] = None

    # -- state -----------------------------------------------------------------------------
    @property
    def has_model(self) -> bool:
        return self.embedder is not None

    def _embed(self, texts: List[str]) -> np.ndarray:
        if self.embedder is None:
            raise ServiceError("No server configured: dense search embeds through the server")
        return np.asarray(self.embedder(texts), dtype=np.float32)

    def _refresh(self) -> None:
        """Reload passages, BM25 and the dense matrix when the workspace changed."""
        signature = self.workspace.revision()
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
        """The dense matrix, only when every passage has a cached vector of this model."""
        if not self._chunks:
            return None
        cached = self.workspace.vectors(self.model_id, [c.chunk_id for c in self._chunks])
        if len(cached) != len(self._chunks):
            return None
        return np.stack([cached[c.chunk_id] for c in self._chunks])

    def ingest(self, chunks: List[Chunk]) -> Dict[str, Any]:
        """Add documents, then let the learning hook build the RAG skill for them."""
        incoming = list(chunks)
        with self._lock:
            counts: Dict[str, Any] = dict(self.workspace.add(incoming))
            everything = self.workspace.load() if self.on_ingest else []
        if self.on_ingest:
            counts.update(self.on_ingest(incoming, everything))
        return counts

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
                "notice": self.notice,
            }
            return info

    # -- indexing --------------------------------------------------------------------------
    def build_dense_index(self, batch_log: Optional[Any] = None) -> Dict[str, Any]:
        """Embed every passage through the server and save the matrix."""
        with self._lock:
            self._refresh()
            if not self._chunks:
                raise ServiceError("Nothing to index: ingest documents first")
            cached = self.workspace.vectors(self.model_id, [c.chunk_id for c in self._chunks])
            missing = [c for c in self._chunks if c.chunk_id not in cached]
            for start in range(0, len(missing), 32):
                batch = missing[start : start + 32]
                vectors = self._embed([f"{c.title}. {c.text}" for c in batch])
                cached.update({c.chunk_id: v for c, v in zip(batch, vectors)})
                if batch_log:
                    batch_log(min(start + 32, len(missing)), len(missing))
            rows = [np.stack([cached[c.chunk_id] for c in self._chunks])]
            matrix = np.concatenate(rows).astype(np.float32)
            ids = [c.chunk_id for c in self._chunks]
            self.workspace.save_vectors(self.model_id, ids, matrix)
            self._loaded_signature = self.workspace.revision()
            self._matrix = matrix
            return {"count": len(ids), "embedder": "server", "model_id": self.model_id}

    # -- search ----------------------------------------------------------------------------
    def _bm25_rank(self, query: str, top_k: int) -> List[int]:
        if self._bm25 is None:
            return []
        position = {c.chunk_id: i for i, c in enumerate(self._chunks)}
        return [position[r.doc_id] for r in self._bm25.search(query, top_k=top_k)]

    def _dense_rank(self, query: str, top_k: int) -> List[int]:
        if self._matrix is None:
            raise ServiceError("Dense index not built: run `laris app index` (needs the server)")
        vec = self._embed([query])[0]
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
                raise NoDocumentsError("No documents yet: ingest some first")
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
        """Extractive question answering needs a QA model; the client holds none (D16)."""
        raise ServiceError(
            "extractive answers need a QA model on the server, which is not available yet; "
            "use search and read the passages"
        )
