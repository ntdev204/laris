#!/usr/bin/env python3
"""Graded similarity labels from an LLM grader (T208, D47): prepare shards, merge the graded ones.

Three steps, no training and no model weights involved:

* `calibration`: STS-B train pairs (human scores known) cut into blind shards. The grader
  sees only `id`, `sentence1`, `sentence2`; the human scores stay in a separate key file.
* `select`: new pairs from data on disk (relation pairs of T197 plus neutral NLI pairs), stratified
  by word overlap so the scores spread over the scale, leakage-guarded against STS-B validation and
  test, cut into blind shards (no source, no relation, no overlap value in the shard).
* `merge`: reads graded shards (`{"id": ..., "score": 0-5 in steps of 0.5}`), checks every id,
  writes `label_source: llm` rows mapped to [0, 1], rescans for leakage, reports the label spread.
  `--calibration` instead reports the Spearman correlation of graded calibration shards with the
  human scores.

Usage:
    D=artifacts/llm_similarity
    .venv/bin/python -I scripts/llm_similarity.py calibration --n 300 --out-dir $D/cal
    .venv/bin/python -I scripts/llm_similarity.py select --n 6000 --out-dir $D/sel
    .venv/bin/python -I scripts/llm_similarity.py merge --dir $D/sel --out <parquet>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_relation_pairs import (  # noqa: E402
    GateIndex,
    normalise,
    read_gate_sentences,
    rescan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"
SHARD_SIZE = 150
LABEL_SOURCE = "llm"
# Relation -> pairs to draw (before overlap stratification); neutral comes from all_nli.
RELATIONS = [
    "entailment",
    "paraphrase_duplicate",
    "contradiction",
    "paws_non_paraphrase",
    "adjacent_sentences",
]
OVERLAP_BINS = [0.0, 0.1, 0.2, 0.35, 0.5, 0.7, 1.01]


def overlap(a: str, b: str) -> float:
    x, y = set(normalise(a).split()), set(normalise(b).split())
    return len(x & y) / len(x | y) if x | y else 0.0


def words(text: str) -> int:
    return len(text.split())


def write_shards(rows: List[Dict[str, Any]], out_dir: Path, prefix: str) -> List[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(0, len(rows), SHARD_SIZE):
        name = f"{prefix}_{i // SHARD_SIZE:03d}.json"
        blind = [
            {"id": r["id"], "sentence1": r["sentence1"], "sentence2": r["sentence2"]}
            for r in rows[i : i + SHARD_SIZE]
        ]
        (out_dir / name).write_text(
            json.dumps(blind, ensure_ascii=False, indent=0), encoding="utf-8"
        )
        names.append(name)
    return names


def cmd_calibration(args: argparse.Namespace) -> int:
    table = pq.read_table(PROCESSED / "stsb" / "train.parquet").to_pylist()
    rng = random.Random(args.seed)
    rows = [
        {
            "id": f"cal{i:04d}",
            "sentence1": r["sentence1"],
            "sentence2": r["sentence2"],
            "human": float(r["score"]),
        }
        for i, r in enumerate(rng.sample(table, args.n))
    ]
    names = write_shards(rows, args.out_dir, "cal")
    (args.out_dir.parent / f"{args.out_dir.name}_keys.json").write_text(
        json.dumps({r["id"]: r["human"] for r in rows}), encoding="utf-8"
    )
    print(json.dumps({"pairs": len(rows), "shards": names}))
    return 0


def _candidates(
    args: argparse.Namespace, rng: random.Random, gate: GateIndex
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    rel = pq.read_table(
        PROCESSED / "relation_pairs_en" / "train.parquet",
        columns=["sentence1", "sentence2", "relation", "source"],
    ).to_pylist()
    by_rel: Dict[str, List[Dict[str, Any]]] = {name: [] for name in RELATIONS}
    for r in rel:
        if r["relation"] in by_rel:
            by_rel[r["relation"]].append(r)
    per = args.pool // (len(RELATIONS) + 1)
    for name, rows in by_rel.items():
        out.extend(rng.sample(rows, min(per, len(rows))))
    nli = pq.read_table(PROCESSED / "all_nli" / "train.parquet").to_pylist()
    neutral = [
        {
            "sentence1": r["premise"],
            "sentence2": r["hypothesis"],
            "relation": "neutral",
            "source": "all_nli",
        }
        for r in nli
        if r["label"] == "neutral"
    ]
    out.extend(rng.sample(neutral, min(per, len(neutral))))
    kept = []
    for r in out:
        a, b = r["sentence1"], r["sentence2"]
        if not (3 <= words(a) <= 60 and 3 <= words(b) <= 60) or normalise(a) == normalise(b):
            continue
        if gate.hit(a) or gate.hit(b):
            continue
        r["overlap"] = overlap(a, b)
        kept.append(r)
    return kept


def cmd_select(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    gate = GateIndex(read_gate_sentences(PROCESSED))
    pool = _candidates(args, rng, gate)
    bins: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(OVERLAP_BINS) - 1)}
    for r in pool:
        for i in range(len(OVERLAP_BINS) - 1):
            if OVERLAP_BINS[i] <= r["overlap"] < OVERLAP_BINS[i + 1]:
                bins[i].append(r)
    per_bin = args.n // len(bins)
    picked: List[Dict[str, Any]] = []
    seen: set = set()
    for rows in bins.values():
        rng.shuffle(rows)
        taken = 0
        for r in rows:
            key = tuple(sorted((normalise(r["sentence1"]), normalise(r["sentence2"]))))
            if key in seen:
                continue
            seen.add(key)
            picked.append(r)
            taken += 1
            if taken >= per_bin:
                break
    rng.shuffle(picked)
    for i, r in enumerate(picked):
        r["id"] = f"sel{i:05d}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    names = write_shards(picked, args.out_dir, "sel")
    meta = {
        r["id"]: {
            "relation": r["relation"],
            "source": r["source"],
            "overlap": round(r["overlap"], 4),
        }
        for r in picked
    }
    (args.out_dir.parent / f"{args.out_dir.name}_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    (args.out_dir.parent / f"{args.out_dir.name}_pairs.json").write_text(
        json.dumps({r["id"]: [r["sentence1"], r["sentence2"]] for r in picked}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "pairs": len(picked),
                "shards": len(names),
                "relations": Counter(r["relation"] for r in picked),
            }
        )
    )
    return 0


def _read_scores(directory: Path, prefix: str) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for path in sorted(directory.glob(f"{prefix}_*.graded.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            score = float(item["score"])
            if not 0.0 <= score <= 5.0 or (score * 2) % 1 != 0:
                raise ValueError(
                    f"{path.name}: score {score} for {item['id']} is not 0-5 in steps of 0.5"
                )
            scores[item["id"]] = score
    return scores


def spearman(x: List[float], y: List[float]) -> float:
    def rank(v: List[float]) -> List[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        ranks = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                ranks[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return ranks

    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def cmd_merge(args: argparse.Namespace) -> int:
    if args.calibration:
        keys = json.loads((args.dir.parent / f"{args.dir.name}_keys.json").read_text())
        graded = _read_scores(args.dir, "cal")
        ids = sorted(set(graded) & set(keys))
        human, llm = [keys[i] for i in ids], [graded[i] / 5 for i in ids]
        report = {
            "pairs_graded": len(graded),
            "pairs_expected": len(keys),
            "spearman": round(spearman(human, llm), 4),
            "mean_human": round(sum(human) / len(human), 4),
            "mean_llm": round(sum(llm) / len(llm), 4),
            "mean_abs_error": round(sum(abs(a - b) for a, b in zip(human, llm)) / len(ids), 4),
        }
        print(json.dumps(report, indent=2))
        return 0
    graded = _read_scores(args.dir, "sel")
    meta = json.loads((args.dir.parent / f"{args.dir.name}_meta.json").read_text())
    pairs = json.loads((args.dir.parent / f"{args.dir.name}_pairs.json").read_text())
    missing = sorted(set(pairs) - set(graded))
    rows = [
        {
            "sentence1": pairs[i][0],
            "sentence2": pairs[i][1],
            "score": graded[i] / 5,
            "source": f"llm:{meta[i]['source']}",
            "label_source": LABEL_SOURCE,
        }
        for i in sorted(graded)
        if i in pairs
    ]
    gate = read_gate_sentences(PROCESSED)
    leak = rescan([(r["sentence1"], r["sentence2"]) for r in rows], gate)
    if leak["exact_hits"] or leak["window_hits"]:
        raise SystemExit(f"leakage hit: {leak}")
    scores = [r["score"] for r in rows]
    mean = sum(scores) / len(scores)
    report = {
        "rows": len(rows),
        "missing_ids": len(missing),
        "leakage_rescan": leak,
        "label_mean": round(mean, 4),
        "label_std": round((sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5, 4),
        "score_histogram": dict(sorted(Counter(round(s * 5, 1) for s in scores).items())),
        "by_relation_mean": {
            rel: round(
                sum(graded[i] / 5 for i in graded if meta[i]["relation"] == rel)
                / max(1, sum(1 for i in graded if meta[i]["relation"] == rel)),
                4,
            )
            for rel in sorted({m["relation"] for m in meta.values()})
        },
    }
    print(json.dumps(report, indent=2))
    if args.out and (args.allow_partial or not missing):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), args.out)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    cal = sub.add_parser("calibration")
    cal.add_argument("--n", type=int, default=300)
    cal.add_argument("--seed", type=int, default=208)
    cal.add_argument("--out-dir", type=Path, required=True)
    sel = sub.add_parser("select")
    sel.add_argument("--n", type=int, default=6000)
    sel.add_argument("--pool", type=int, default=120000)
    sel.add_argument("--seed", type=int, default=208)
    sel.add_argument("--out-dir", type=Path, required=True)
    mer = sub.add_parser("merge")
    mer.add_argument("--dir", type=Path, required=True)
    mer.add_argument("--calibration", action="store_true")
    mer.add_argument("--out", type=Path, default=None)
    mer.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    return {"calibration": cmd_calibration, "select": cmd_select, "merge": cmd_merge}[args.cmd](
        args
    )


if __name__ == "__main__":
    raise SystemExit(main())
