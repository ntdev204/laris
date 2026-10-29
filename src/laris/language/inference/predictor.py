"""Single-example predictions from a trained language encoder (no gradients, no authorization)."""

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from laris.language.inference.loader import LoadedEncoder
from laris.language.training.dataloader import (
    CLS_ID,
    MASK_ID,
    SEP_ID,
    build_sequence,
)

NLI_LABELS = ("entailment", "neutral", "contradiction")


class LanguageEncoderPredictor:
    def __init__(self, encoder: LoadedEncoder) -> None:
        self.encoder = encoder

    # -- encoding helpers ------------------------------------------------------------------
    def _ids(self, text: str) -> List[int]:
        tok = self.encoder.tokenizer
        return list(tok.encode_as_ids(text)) if text else []

    def _run(self, first: List[int], second: Optional[List[int]] = None) -> Dict[str, Any]:
        import torch

        ids, mask = build_sequence(first, second, self.encoder.seq_len)
        device = self.encoder.device
        with torch.no_grad():
            out = self.encoder.model(
                torch.tensor([ids], dtype=torch.long, device=device),
                attention_mask=torch.tensor([mask], dtype=torch.long, device=device),
            )
        return {"ids": ids, "mask": mask, "out": out}

    # -- tasks -----------------------------------------------------------------------------
    def fill_mask(self, text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Predicts the token for each `[MASK]` in `text` (written literally)."""
        import torch

        pieces = text.split("[MASK]")
        first: List[int] = []
        for i, piece in enumerate(pieces):
            first.extend(self._ids(piece))
            if i < len(pieces) - 1:
                first.append(MASK_ID)
        run = self._run(first)
        positions = [i for i, t in enumerate(run["ids"]) if t == MASK_ID]
        if not positions:
            raise ValueError("Input must contain at least one [MASK] token")
        logits = run["out"]["mlm_logits"][0]
        results = []
        for pos in positions:
            probs = torch.softmax(logits[pos].float(), dim=-1)
            top = torch.topk(probs, top_k)
            results.append(
                {
                    "position": pos,
                    "candidates": [
                        {
                            "token_id": int(i),
                            "token": self.encoder.tokenizer.id_to_piece(int(i)),
                            "probability": float(p),
                        }
                        for p, i in zip(top.values.tolist(), top.indices.tolist())
                    ],
                }
            )
        return results

    def nli(self, premise: str, hypothesis: str) -> Dict[str, Any]:
        import torch

        run = self._run(self._ids(premise), self._ids(hypothesis))
        probs = torch.softmax(run["out"]["nli_logits"][0].float(), dim=-1).tolist()
        best = int(np.argmax(probs))
        return {
            "label": NLI_LABELS[best],
            "probabilities": dict(zip(NLI_LABELS, probs)),
        }

    def paraphrase(self, a: str, b: str) -> Dict[str, Any]:
        run = self._run(self._ids(a), self._ids(b))
        prob = float(run["out"]["paraphrase_prob"][0].float().reshape(-1)[0])
        return {"is_paraphrase": prob >= 0.5, "probability": prob}

    def similarity(self, a: str, b: str) -> Dict[str, Any]:
        run = self._run(self._ids(a), self._ids(b))
        score = float(run["out"]["similarity_score"][0].float().reshape(-1)[0])
        return {"score": score, "score_0_to_5": score * 5.0}

    def qa(self, context: str, question: str, max_answer_tokens: int = 64) -> Dict[str, Any]:
        q_ids, c_ids = self._ids(question), self._ids(context)
        run = self._run(q_ids, c_ids)
        logits = run["out"]["qa_logits"][0].float().cpu().numpy()
        valid = np.asarray(run["mask"], dtype=bool)
        start = np.where(valid, logits[:, 0], -np.inf)
        end = np.where(valid, logits[:, 1], -np.inf)
        n = len(valid)
        score = start[:, None] + end[None, :]
        allowed = np.triu(np.ones((n, n), dtype=bool)) & ~np.triu(
            np.ones((n, n), dtype=bool), k=max_answer_tokens
        )
        score = np.where(allowed, score, -np.inf)
        start_idx, end_idx = np.unravel_index(int(np.argmax(score)), score.shape)
        s, e = int(start_idx), int(end_idx)
        if s == 0 and e == 0:
            return {"answer": None, "start": 0, "end": 0, "no_answer": True}
        ids = [t for t in run["ids"][s : e + 1] if t not in (CLS_ID, SEP_ID, 0)]
        return {
            "answer": self.encoder.tokenizer.decode_ids(ids),
            "start": s,
            "end": e,
            "no_answer": False,
        }

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """L2-normalised [CLS] sentence embeddings, shape (len(texts), d_model)."""
        rows = []
        for text in texts:
            vec = self._run(self._ids(text))["out"]["cls_embedding"][0].float().cpu().numpy()
            rows.append(vec / max(float(np.linalg.norm(vec)), 1e-12))
        return np.stack(rows)
