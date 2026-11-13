#!/usr/bin/env python3
"""Vietnamese STEM retrieval-relevance gold for G12 (T98, D05-a). Inference only; trains nothing.

Stages (each writes under `data/processed/gold_vi_stem/`, which Git ignores because the source
passages come from the VIPUBMED machine translation whose licence is not cleared):

  sample    draw the passage corpus and the passages the queries are written from
  pool      BM25 + dense (R1 encoder, inference) pooling, blind annotation sheets, frozen manifest
  reconcile weighted kappa of two label files, adjudication, sealed gold

Roles for this gold were assigned by the owner on 2026-11-13: every label is produced by a
language model (an agent), not by a human, so the manifest records `label_source: llm` and the
evidence is not human gold.
"""

import argparse
import hashlib
import json
import random
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/processed/gold_vi_stem"
SOURCE = ROOT / "data/raw/vi_pubmed_candidate/pubmed22-00000-of-00089-5cd8ea7c3541d46a.parquet"
SEED = 42
CORPUS_SIZE = 4000
N_QUERIES = {"pilot": 20, "dev": 140, "test": 40}
MIN_CHARS, MAX_CHARS = 500, 1800


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def doc_id(text: str) -> str:
    return "vp-" + hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:12]


def cmd_sample(args: argparse.Namespace) -> int:
    rng = random.Random(SEED)
    parquet = pq.ParquetFile(SOURCE)
    groups = list(range(parquet.num_row_groups))
    rng.shuffle(groups)
    docs: Dict[str, str] = {}
    for group in groups:
        for row in parquet.read_row_group(group, columns=["vi"]).to_pylist():
            text = (row["vi"] or "").strip()
            if MIN_CHARS <= len(text) <= MAX_CHARS and doc_id(text) not in docs:
                docs[doc_id(text)] = text
        if len(docs) >= CORPUS_SIZE * 3:
            break
    ids = sorted(docs)
    rng.shuffle(ids)
    corpus_ids = sorted(ids[:CORPUS_SIZE])
    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "corpus.jsonl", [{"doc_id": i, "text": docs[i]} for i in corpus_ids])
    total = sum(N_QUERIES.values())
    pick = rng.sample(corpus_ids, total)
    splits = [s for s, n in N_QUERIES.items() for _ in range(n)]
    rng.shuffle(splits)
    rows = [
        {"query_id": f"q{n:03d}", "split": s, "source_doc_id": d, "passage": docs[d]}
        for n, (d, s) in enumerate(zip(pick, splits), 1)
    ]
    write_jsonl(OUT / "query_sources.jsonl", rows)
    print(f"corpus {len(corpus_ids)} passages; {len(rows)} query sources {N_QUERIES}")
    return 0


def _ngram_copy(query: str, passage: str, n: int = 6) -> bool:
    q = norm(query).split()
    grams = {" ".join(q[i : i + n]) for i in range(len(q) - n + 1)}
    return any(g in norm(passage) for g in grams)


def cmd_pool(args: argparse.Namespace) -> int:
    import numpy as np

    sys.path.insert(0, str(ROOT / "src"))
    from laris.research.evaluation import human_gold as hg
    from laris.research.language.benchmarks.retrieval import (
        RetrievalQuery,
        RetrievalSplit,
        _embedder,
        bm25_scores,
        dense_scores,
    )

    sources = {r["query_id"]: r for r in read_jsonl(OUT / "query_sources.jsonl")}
    queries: Dict[str, str] = {}
    for path in sorted((OUT / "qa").glob("out_*.jsonl")):
        for row in read_jsonl(path):
            queries[row["query_id"]] = row["query"].strip()
    if set(queries) != set(sources):
        print(f"[FAIL] queries cover {len(queries)} of {len(sources)} sources")
        return 1
    copied = [q for q, t in queries.items() if _ngram_copy(t, sources[q]["passage"])]
    corpus = read_jsonl(OUT / "corpus.jsonl")
    ids = [r["doc_id"] for r in corpus]
    texts = [r["text"] for r in corpus]
    qids = sorted(queries)
    split = RetrievalSplit(
        "vi_stem",
        "vi",
        [RetrievalQuery(q, queries[q], sources[q]["source_doc_id"], "") for q in qids],
        ids,
        texts,
        [""] * len(ids),
    )
    bm25 = bm25_scores(split)
    embed, encoder = _embedder(Path(args.checkpoint), Path(args.tokenizer_model), args.device)
    dense = dense_scores(embed([queries[q] for q in qids]), embed(texts))
    rankings: Dict[str, Dict[str, List[str]]] = {"bm25": {}, "dense": {}}
    for system, matrix, k in ((("bm25", bm25, 5)), ("dense", dense, 3)):
        for ri, q in enumerate(qids):
            order = np.argsort(-matrix[ri], kind="stable")[:k]
            rankings[system][q] = [ids[i] for i in order]
    for q in qids:  # the passage the query was written from always joins the pool
        rankings["bm25"][q] = rankings["bm25"][q] + [sources[q]["source_doc_id"]]
    pool = hg.build_pool(rankings, top_k=6, seed=SEED)
    docs = dict(zip(ids, texts))
    items = hg.build_items(pool, queries, docs)
    for it in items:
        it["split"] = sources[it["query_id"]]["split"]
    write_jsonl(
        OUT / "queries.jsonl",
        [
            {
                "query_id": q,
                "query": queries[q],
                "split": sources[q]["split"],
                "source_doc_id": sources[q]["source_doc_id"],
            }
            for q in qids
        ],
    )
    write_jsonl(OUT / "items.jsonl", items)
    guideline = ROOT / "docs/training/D05_GUIDELINE_VI_STEM.md"
    sheets = OUT / "sheets"
    sheets.mkdir(exist_ok=True)
    batches: Dict[str, List[str]] = {}
    for annotator in ("A1", "A2"):
        shuffled = list(items)
        random.Random(f"{SEED}:{annotator}").shuffle(shuffled)
        for b in range(0, len(shuffled), 100):
            name = f"{annotator}_{b // 100:02d}.jsonl"
            hg.write_blind_sheet(shuffled[b : b + 100], sheets / name)
            batches.setdefault(annotator, []).append(name)
    manifest = {
        "task": "T98",
        "label_source": "llm",
        "human_gold": False,
        "guideline_sha256": sha256_file(guideline),
        "queries_sha256": sha256_file(OUT / "queries.jsonl"),
        "items_sha256": sha256_file(OUT / "items.jsonl"),
        "corpus_sha256": sha256_file(OUT / "corpus.jsonl"),
        "source_sha256": sha256_file(SOURCE),
        "pooling": {"bm25_top": 5, "dense_top": 3, "plus_source_passage": True, "seed": SEED},
        "dense_checkpoint": str(args.checkpoint),
        "dense_model_sha256": encoder.manifest["model_sha256"],
        "queries_per_split": N_QUERIES,
        "items_per_split": {s: sum(1 for i in items if i["split"] == s) for s in N_QUERIES},
        "queries_with_6gram_copy": copied,
        "test_split": "sealed: not used for tuning, hard-negative mining or checkpoint choice",
        "sheets": batches,
    }
    (OUT / "freeze_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("items_per_split", "queries_with_6gram_copy")}))
    return 0


def _load_labels(annotator: str, items: List[Dict[str, Any]]) -> Dict[str, int]:
    labels: Dict[str, int] = {}
    for path in sorted((OUT / "labels").glob(f"{annotator}_*.jsonl")):
        for row in read_jsonl(path):
            if row["item_id"] in labels:
                raise ValueError(f"duplicate {row['item_id']} in {annotator}")
            labels[row["item_id"]] = row["label"]
    expected = {i["item_id"] for i in items}
    if set(labels) != expected or any(v not in (0, 1, 2) for v in labels.values()):
        raise ValueError(f"{annotator}: label set incomplete or invalid")
    return labels


def cmd_reconcile(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from laris.research.evaluation import human_gold as hg

    items = read_jsonl(OUT / "items.jsonl")
    split_of = {i["item_id"]: i["split"] for i in items}
    a1, a2 = _load_labels("A1", items), _load_labels("A2", items)
    manifest = json.loads((OUT / "freeze_manifest.json").read_text(encoding="utf-8"))
    report: Dict[str, Any] = {"label_source": "llm", "human_gold": False, "splits": {}}
    adj_path = OUT / "adjudication.json"
    adjudication = json.loads(adj_path.read_text()) if adj_path.exists() else {}
    for split in ("pilot", "dev", "test"):
        ids = [i for i in a1 if split_of[i] == split]
        sub1, sub2 = {i: a1[i] for i in ids}, {i: a2[i] for i in ids}
        adj = {k: v for k, v in adjudication.items() if k in ids}
        result = hg.reconcile(sub1, sub2, adj, threshold=args.threshold)
        gold = result.pop("gold")
        result["disagreement_ids"] = sorted(i for i in ids if a1[i] != a2[i])
        report["splits"][split] = result
        if result["status"] == "accepted" and split != "pilot":
            (OUT / f"gold_{split}.json").write_text(json.dumps(gold, sort_keys=True))
            result["seal_sha256"] = hg.seal_digest(gold, manifest["guideline_sha256"])
    (OUT / "reconcile_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    for split, r in report["splits"].items():
        print(
            split,
            r["items"],
            "kappa_w",
            round(r["weighted_kappa_quadratic"], 4),
            "disagree",
            r["disagreements"],
            r["status"],
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sample").set_defaults(func=cmd_sample)
    pool = sub.add_parser("pool")
    pool.add_argument(
        "--checkpoint", default="artifacts/checkpoints/language_encoder/foundation-r1-run1/best"
    )
    pool.add_argument(
        "--tokenizer-model",
        default="artifacts/tokenizer/foundation-r1-super/candidate/laris_spm_48k_r1.model",
    )
    pool.add_argument("--device", default=None)
    pool.set_defaults(func=cmd_pool)
    rec = sub.add_parser("reconcile")
    rec.add_argument("--threshold", type=float, default=0.85)
    rec.set_defaults(func=cmd_reconcile)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
