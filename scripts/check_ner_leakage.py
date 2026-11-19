#!/usr/bin/env python3
"""Leakage scan of the NER validation and test sentences against stage-1 training data (T187).

For every validation and test sentence of the NER sources (data/processed/few_nerd_en, wnut_17_en)
the scan looks for the same text (letters and digits, lower case) and for any eight-word window (the
window of T178) in the train split of every stage-1 directory (MLM, NLI, paraphrase, similarity, QA,
retrieval, relation pairs). Reads files and writes one report; nothing trains and the NER test rows
are never changed.

A hit means the unlabelled sentence text was seen by stage 1, not that a label leaked: stage 1 has
no entity labels. It still decides how a held-out score is worded, so it is counted per source,
split and stage-1 directory.

Usage:
    python scripts/check_ner_leakage.py \\
        [--out reports/verification/T187-ner-leakage.json] [--workers N]
"""

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.research.corpus.splits.partitioners import retrieval as R  # noqa: E402
from laris.shared.language.loading.dataloader import (  # noqa: E402
    CONTRASTIVE_SIM_DATASET_DIR,
    RETRIEVAL_DATASET_DIRS,
    TASK_DATASET_DIRS,
)

NER_DIRS = {"FEW-NERD-EN": "few_nerd_en", "WNUT-17-EN": "wnut_17_en"}
SAMPLE_HITS = 25

_EXACT: Dict[int, List[int]] = {}
_WINDOWS: Dict[int, List[int]] = {}
_SENTENCES: List[Dict[str, Any]] = []


def stage1_dirs() -> List[str]:
    names = [d for dirs in TASK_DATASET_DIRS.values() for d in dirs]
    names += RETRIEVAL_DATASET_DIRS + [CONTRASTIVE_SIM_DATASET_DIR]
    return sorted(dict.fromkeys(names))


def load_sentences(processed: Path) -> None:
    """Fills the module tables (inherited by the worker processes)."""
    for source, directory in NER_DIRS.items():
        for split in ("val", "test"):
            path = processed / directory / f"{split}.parquet"
            for row in pq.read_table(path, columns=["id", "tokens"]).to_pylist():
                norm = R.normalise(" ".join(row["tokens"]))
                index = len(_SENTENCES)
                _SENTENCES.append(
                    {
                        "id": row["id"],
                        "source": source,
                        "split": split,
                        "text": " ".join(row["tokens"]),
                    }
                )
                if not norm:
                    continue
                _EXACT.setdefault(R.text_digest(norm), []).append(index)
                for key in R._shingles(norm):
                    _WINDOWS.setdefault(key, []).append(index)


def scan_row_group(task: Tuple[str, str, int]) -> Dict[str, Any]:
    """Hits of one row group: {sentence index: [kind, ...]} plus the rows scanned."""
    directory, path, group = task
    parquet = pq.ParquetFile(path)
    columns = [f.name for f in parquet.schema_arrow if pa.types.is_string(f.type)]
    hits: Dict[int, Dict[str, int]] = {}
    rows = 0
    for batch in parquet.iter_batches(batch_size=2000, row_groups=[group], columns=columns):
        rows += batch.num_rows
        for column in columns:
            for text in batch.column(column).to_pylist():
                if not text:
                    continue
                norm = R.normalise(text)
                for index in _EXACT.get(R.text_digest(norm), ()):
                    hits.setdefault(index, {}).setdefault("exact", 0)
                    hits[index]["exact"] += 1
                seen = set()
                for key in R._shingles(norm):
                    for index in _WINDOWS.get(key, ()):
                        if index not in seen:
                            seen.add(index)
                            hits.setdefault(index, {}).setdefault("window", 0)
                            hits[index]["window"] += 1
    return {"directory": directory, "rows": rows, "columns": columns, "hits": hits}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed", type=Path, default=REPO_ROOT / "data/processed")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "reports/verification/T187-ner-leakage.json"
    )
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    parser.add_argument(
        "--only", nargs="+", help="scan only these stage-1 directories (trial runs)"
    )
    args = parser.parse_args(argv)
    load_sentences(args.processed)
    print(
        f"{len(_SENTENCES):,} NER sentences, {len(_EXACT):,} exact keys, "
        f"{len(_WINDOWS):,} window keys",
        flush=True,
    )
    tasks: List[Tuple[str, str, int]] = []
    missing: List[str] = []
    for directory in args.only or stage1_dirs():
        path = args.processed / directory / "train.parquet"
        if not path.is_file():
            missing.append(directory)
            continue
        tasks += [(directory, str(path), g) for g in range(pq.ParquetFile(path).num_row_groups)]
    print(
        f"{len(tasks)} row groups, {len(missing)} directories without a train split: {missing}",
        flush=True,
    )
    per_dir: Dict[str, Dict[str, Any]] = {}
    sentence_hits: Dict[int, Dict[str, Dict[str, int]]] = {}
    started = time.time()
    with mp.get_context("fork").Pool(args.workers) as pool:
        for done, result in enumerate(pool.imap_unordered(scan_row_group, tasks, chunksize=1), 1):
            entry = per_dir.setdefault(
                result["directory"], {"rows": 0, "text_columns": result["columns"]}
            )
            entry["rows"] += result["rows"]
            for index, kinds in result["hits"].items():
                for kind, count in kinds.items():
                    bucket = sentence_hits.setdefault(index, {}).setdefault(result["directory"], {})
                    bucket[kind] = bucket.get(kind, 0) + count
            if done % 50 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} row groups, {time.time() - started:.0f}s", flush=True)
    summary: Dict[str, Dict[str, Any]] = {}
    for source in NER_DIRS:
        for split in ("val", "test"):
            indices = [
                i for i, s in enumerate(_SENTENCES) if s["source"] == source and s["split"] == split
            ]
            hit = [i for i in indices if i in sentence_hits]
            by_dir: Dict[str, int] = {}
            by_kind = {"exact": 0, "window": 0}
            for i in hit:
                for directory, kinds in sentence_hits[i].items():
                    by_dir[directory] = by_dir.get(directory, 0) + 1
                for kind in by_kind:
                    by_kind[kind] += any(kind in k for k in sentence_hits[i].values())
            summary[f"{source}/{split}"] = {
                "sentences": len(indices),
                "sentences_with_a_hit": len(hit),
                "share": round(len(hit) / max(1, len(indices)), 4),
                "sentences_with_exact_hit": by_kind["exact"],
                "sentences_with_window_hit": by_kind["window"],
                "hit_sentences_per_stage1_directory": dict(
                    sorted(by_dir.items(), key=lambda kv: -kv[1])
                ),
            }
    samples = [
        {**_SENTENCES[i], "stage1": sentence_hits[i]}
        for i in sorted(sentence_hits)[:: max(1, len(sentence_hits) // SAMPLE_HITS)][:SAMPLE_HITS]
    ]
    report = {
        "task": "T187",
        "window_words": R.SHINGLE_WORDS,
        "stage1_directories_scanned": {d: v["rows"] for d, v in sorted(per_dir.items())},
        "stage1_directories_without_train_split": missing,
        "summary": summary,
        "sample_hits": samples,
        "note": "A hit is unlabelled text seen by stage 1 (no entity labels there); "
        "NER validation and test rows are never removed.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
