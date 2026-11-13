#!/usr/bin/env python3
"""Score BM25 and a dense encoder on the Vietnamese STEM relevance gold (T98 data, T99/T100 use).

Inference only: nothing trains and no optimizer runs. The gold is LLM-labelled (`human_gold: false`)
and pooled, so passages outside the pool count as not relevant; report it as LLM gold.

* `--split dev` is for development decisions.
* `--split test` is sealed. It needs `--final` and `--seal-sha256` equal to the digest in
  `reconcile_report.json`, and a run must be the single final scoring of one candidate (T100).

Without `--checkpoint` only BM25 is scored.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data/processed/gold_vi_stem"
sys.path.insert(0, str(ROOT / "src"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def build_split(split: str, min_label: int) -> Any:
    from laris.research.language.benchmarks.retrieval import RetrievalQuery, RetrievalSplit

    gold: Dict[str, int] = json.loads((GOLD / f"gold_{split}.json").read_text(encoding="utf-8"))
    items = {i["item_id"]: i for i in read_jsonl(GOLD / "items.jsonl")}
    queries = {q["query_id"]: q for q in read_jsonl(GOLD / "queries.jsonl")}
    corpus = read_jsonl(GOLD / "corpus.jsonl")
    relevant: Dict[str, List[str]] = {}
    for item_id, label in gold.items():
        if label >= min_label:
            item = items[item_id]
            relevant.setdefault(item["query_id"], []).append(item["doc_id"])
    judged = sorted({items[i]["query_id"] for i in gold})
    rows = [
        RetrievalQuery(q, queries[q]["query"], docs[0], "", tuple(docs[1:]))
        for q in judged
        if (docs := sorted(relevant.get(q, [])))
    ]
    return RetrievalSplit(
        f"vi_stem_{split}",
        "vi",
        rows,
        [c["doc_id"] for c in corpus],
        [c["text"] for c in corpus],
        [""] * len(corpus),
    ), len(judged)


def metrics(scores: np.ndarray, split: Any) -> Dict[str, Any]:
    from laris.research.language.benchmarks import retrieval as r

    ranks = r.relevant_ranks(scores, split)
    ndcg = r.ndcg_at_10_values(scores, split)
    out: Dict[str, Any] = dict(r.summarise(ranks, ndcg=ndcg))
    values = 1.0 / ranks
    boots = np.random.default_rng(42).choice(values, size=(2000, len(values))).mean(axis=1)
    out["mrr_ci95"] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--min-label", type=int, choices=(1, 2), default=2)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--tokenizer-model", type=Path)
    parser.add_argument("--device")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--seal-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = json.loads((GOLD / "reconcile_report.json").read_text(encoding="utf-8"))
    seal = report["splits"][args.split].get("seal_sha256")
    if seal is None:
        print(f"[FAIL] the {args.split} split is not sealed")
        return 2
    if args.split == "test" and not (args.final and args.seal_sha256 == seal):
        print("[FAIL] the sealed test split needs --final and the matching --seal-sha256")
        return 2
    if args.checkpoint and not args.tokenizer_model:
        print("[FAIL] --checkpoint needs --tokenizer-model")
        return 2

    from laris.research.language.benchmarks import retrieval as r

    split, judged = build_split(args.split, args.min_label)
    result: Dict[str, Any] = {
        "label_source": "llm",
        "human_gold": False,
        "split": args.split,
        "seal_sha256": seal,
        "min_label": args.min_label,
        "queries_judged": judged,
        "queries_with_relevant": len(split.queries),
        "corpus": len(split.doc_ids),
        "systems": {},
    }
    bm25 = r.bm25_scores(split)
    result["systems"]["bm25"] = metrics(bm25, split)
    if args.checkpoint:
        embed, encoder = r._embedder(args.checkpoint, args.tokenizer_model, args.device)
        dense = r.dense_scores(embed([q.text for q in split.queries]), embed(list(split.doc_texts)))
        result["checkpoint"] = str(args.checkpoint)
        result["model_sha256"] = encoder.manifest["model_sha256"]
        result["systems"]["dense"] = metrics(dense, split)
        hybrid = r.rrf_scores([bm25, dense])
        result["systems"]["hybrid_rrf"] = metrics(hybrid, split)
        result["dense_beats_bm25"] = bool(
            result["systems"]["dense"]["mrr"] > result["systems"]["bm25"]["mrr"]
        )
    text = json.dumps(result, indent=1)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
