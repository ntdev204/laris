#!/usr/bin/env python3
"""Forward-only measurement of the bi-encoder similarity head (T198).

Loads a checkpoint (any head), builds a `similarity_head: bi_encoder` model from its weights with
the initial scale and bias, and scores (1) STS-B validation and (2) a seeded sample of the T197
relation pairs with `bi_encoder_similarity`, the path trainer, evaluator and predictor share.
Reads data and runs forward passes only: no backward step, no optimizer, no training
authorization. The sealed STS-B test split is never read.

Usage (isolated HOME):
    HOME=$(mktemp -d) .venv/bin/python -I scripts/measure_bi_encoder_head.py \
        <checkpoint-dir> <tokenizer.model> --out reports/verification/T198-bi-encoder-head.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

sys.path.insert(0, "src")
import numpy as np
import pyarrow.parquet as pq
import torch

from laris.model.inference.loader import load_encoder
from laris.shared.language.encoder.transformer import PyTorchTransformerEncoder
from laris.shared.language.loading.checkpoint import load_model_weights
from laris.shared.language.loading.dataloader import build_sequence


def _rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(len(x))
    for v in np.unique(x):  # average ranks for ties
        idx = x == v
        if idx.sum() > 1:
            ranks[idx] = ranks[idx].mean()
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    return float(np.corrcoef(_rank(np.asarray(a)), _rank(np.asarray(b)))[0, 1])


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(score of a positive > score of a negative), ties counted half."""
    scores = np.concatenate([pos, neg])
    ranks = _rank(scores) + 1.0
    n_pos, n_neg = len(pos), len(neg)
    return float((ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


class Scorer:
    def __init__(self, model: Any, tokenizer: Any, device: str, seq_len: int) -> None:
        self.model, self.tok, self.device, self.seq_len = model, tokenizer, device, seq_len

    def _side(self, texts: List[str]) -> tuple:
        built = [build_sequence(list(self.tok.encode_as_ids(t)) if t else [], None, self.seq_len)
                 for t in texts]
        ids, mask = zip(*built)
        width = max(sum(m) for m in mask)
        return (
            torch.tensor([i[:width] for i in ids], device=self.device),
            torch.tensor([m[:width] for m in mask], device=self.device),
        )

    @torch.no_grad()
    def score(self, first: List[str], second: List[str], batch: int = 64) -> Dict[str, np.ndarray]:
        cos, score = [], []
        for i in range(0, len(first), batch):
            a, b = first[i:i + batch], second[i:i + batch]
            out = self.model.bi_encoder_similarity(*self._side(a), *self._side(b))
            cos.append(out["similarity_cosine"].float().cpu())
            score.append(out["similarity_score"].float().squeeze(-1).cpu())
        return {"cosine": torch.cat(cos).numpy(), "score": torch.cat(score).numpy()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("checkpoint", type=Path)
    p.add_argument("tokenizer", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--stsb", type=Path, default=Path("data/processed/stsb/val.parquet"))
    p.add_argument("--relations", type=Path,
                   default=Path("data/processed/relation_pairs_en/train.parquet"))
    p.add_argument("--per-relation", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default="cuda")
    args = p.parse_args()
    if "test" in args.stsb.name:
        raise SystemExit("the sealed STS-B test split is never read")

    enc = load_encoder(args.checkpoint, args.tokenizer, device=args.device)
    cfg = dataclasses.replace(enc.config, similarity_head="bi_encoder")
    model = PyTorchTransformerEncoder(cfg)
    missing = load_model_weights(model, enc.model.state_dict())
    model.to(args.device).eval()
    scorer = Scorer(model, enc.tokenizer, args.device, cfg.max_sequence_length)
    report: Dict[str, Any] = {
        "checkpoint": str(args.checkpoint),
        "head": {"similarity_head": "bi_encoder", "initial_scale": cfg.similarity_initial_scale,
                 "initial_bias": cfg.similarity_initial_bias, "keys_left_at_initial": missing},
        "training_authorization": "not enabled; forward passes only",
    }

    # ---- STS-B validation
    sts = pq.read_table(args.stsb).to_pylist()
    y = np.array([float(r["score"]) for r in sts])
    y = y / 5.0 if y.max() > 1.0 else y
    out = scorer.score([r["sentence1"] for r in sts], [r["sentence2"] for r in sts])
    first600 = slice(0, 600)  # the rows T191 used
    report["stsb_validation"] = {
        "rows": len(sts), "label_mean": float(y.mean()), "label_variance": float(y.var()),
        "spearman": spearman(out["cosine"], y),
        "spearman_first_600_rows_as_T191": spearman(out["cosine"][first600], y[first600]),
        "cosine_mean": float(out["cosine"].mean()), "cosine_std": float(out["cosine"].std()),
        "score_mean": float(out["score"].mean()), "score_std": float(out["score"].std()),
        "mse_to_label": float(((out["score"] - y) ** 2).mean()),
        "mse_of_constant_label_mean": float(y.var()),
    }

    # ---- relation pairs (T197), seeded sample per relation
    rel = pq.read_table(args.relations, columns=["sentence1", "sentence2", "relation",
                                                  "polarity"])
    names = np.array(rel.column("relation").to_pylist())
    polarity = rel.column("polarity").to_pylist()
    s1, s2 = rel.column("sentence1"), rel.column("sentence2")
    rng = np.random.default_rng(args.seed)
    per: Dict[str, Any] = {}
    cos_by: Dict[str, np.ndarray] = {}
    for name in sorted(set(names.tolist())):
        idx = np.flatnonzero(names == name)
        take = np.sort(rng.permutation(idx)[: args.per_relation])
        res = scorer.score([s1[int(i)].as_py() for i in take], [s2[int(i)].as_py() for i in take])
        cos_by[name] = res["cosine"]
        per[name] = {
            "polarity": polarity[int(idx[0])], "rows_in_file": int(len(idx)),
            "rows_scored": int(len(take)), "cosine_mean": float(res["cosine"].mean()),
            "cosine_std": float(res["cosine"].std()), "score_mean": float(res["score"].mean()),
        }
    asym = {"order_swapped"}
    pos = np.concatenate([cos_by[n] for n, v in per.items() if v["polarity"] == "positive"])
    neg_names = [n for n, v in per.items() if v["polarity"] == "negative" and n not in asym]
    neg = np.concatenate([cos_by[n] for n in neg_names])
    report["relation_pairs"] = {
        "per_relation": per,
        "positive_vs_negative_auc_excluding_order_swapped": auc(pos, neg),
        "negatives_used": neg_names,
        "auc_by_negative": {n: auc(pos, cos_by[n]) for n in neg_names},
        "auc_positive_by_negative": {
            f"{p_name} > {n_name}": auc(cos_by[p_name], cos_by[n_name])
            for p_name, v in per.items() if v["polarity"] == "positive" for n_name in neg_names
        },
        "note": "order_swapped holds the same two sentences as its adjacent pair, so a symmetric "
                "bi-encoder gives it the same cosine; it is left out of the AUC (T197 finding).",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
