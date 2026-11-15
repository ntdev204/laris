#!/usr/bin/env python3
"""STS-B leakage check and clean extra-similarity table (T175, D46).

STS-B was drawn from the STS 2012-2017 sets, so any extra English similarity pair that
shares a sentence with the STS-B validation or test split would contaminate gate G05.
This script drops every extra pair whose normalised sentence (either side) appears in
STS-B val or test, writes the surviving pairs to a parquet table with scores scaled to
[0, 1], and writes a report with the counts. It reads data and writes files only;
nothing trains.

Usage: python scripts/check_sts_leakage.py [--config configs/data/english_sources.yaml]
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SENTENCE_KEYS = (("sentence1", "sentence2"), ("sentence_A", "sentence_B"))
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Lower-cases and strips everything except letters and digits so trivial edits do not hide a duplicate."""  # noqa: E501
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def score_spec(source: Dict[str, Any]) -> Tuple[str, float, float]:
    """(score column, low, high) declared per source in the config; never guessed.

    T206: guessing from a list of column names took SICK's NLI `label` (0/1/2) instead of
    `relatedness_score` (1-5), so the column and the native range must be configured.
    """
    field = source.get("score_field")
    low, high = (source.get("score_range") or (None, None))[:2]
    if not field or low is None or high is None or float(high) <= float(low):
        raise ValueError(f"similarity source {source.get('id')} needs score_field and score_range")
    return str(field), float(low), float(high)


def scale_score(value: float, low: float, high: float) -> float:
    """Maps a native score linearly onto [0, 1] (low -> 0, high -> 1), clipped."""
    return max(0.0, min(1.0, (value - low) / (high - low)))


def rows_from_file(path: Path) -> Iterator[Dict[str, Any]]:
    """Yields row dicts from parquet, JSONL(.gz) or TSV files."""
    name = path.name
    if name.endswith(".parquet"):
        yield from pq.read_table(path).to_pylist()
    elif name.endswith(".tsv"):
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            for line in handle:
                cells = line.rstrip("\n").split("\t")
                if len(cells) == len(header):
                    yield dict(zip(header, cells))
    else:
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def extract_pair(row: Dict[str, Any], score_field: str) -> Optional[Tuple[str, str, float]]:
    """Returns (sentence1, sentence2, native score), or None when the row has no usable pair."""
    for left, right in SENTENCE_KEYS:
        if left in row and right in row:
            if row.get(score_field) in (None, ""):
                return None
            try:
                return str(row[left]), str(row[right]), float(row[score_field])
            except ValueError:
                return None
    return None


def stsb_heldout_sentences(stsb_dir: Path) -> Set[str]:
    """Normalised sentences of STS-B validation and test; training sentences are allowed."""
    sentences: Set[str] = set()
    for split in ("val", "test"):
        table = pq.read_table(stsb_dir / f"{split}.parquet")
        for column in ("sentence1", "sentence2"):
            sentences.update(normalise(s) for s in table.column(column).to_pylist())
    return sentences


def filter_pairs(
    pairs: Iterable[Tuple[str, str, float]], blocked: Set[str], seen: Set[Tuple[str, str]]
) -> Tuple[List[Tuple[str, str, float]], Dict[str, int]]:
    """Drops pairs touching blocked sentences, empty sentences and duplicates (unordered)."""
    kept: List[Tuple[str, str, float]] = []
    stats = {"input": 0, "leaked": 0, "duplicate": 0, "empty": 0, "kept": 0}
    for s1, s2, score in pairs:
        stats["input"] += 1
        n1, n2 = normalise(s1), normalise(s2)
        if not n1 or not n2:
            stats["empty"] += 1
        elif n1 in blocked or n2 in blocked:
            stats["leaked"] += 1
        elif (min(n1, n2), max(n1, n2)) in seen:
            stats["duplicate"] += 1
        else:
            seen.add((min(n1, n2), max(n1, n2)))
            kept.append((s1, s2, score))
            stats["kept"] += 1
    return kept, stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config", type=Path, default=REPO_ROOT / "configs/data/english_sources.yaml"
    )
    parser.add_argument("--stsb-dir", type=Path, default=REPO_ROOT / "data/processed/stsb")
    parser.add_argument(
        "--output", type=Path, default=REPO_ROOT / "data/processed/sts_extra_en/train.parquet"
    )
    parser.add_argument(
        "--report", type=Path, default=REPO_ROOT / "reports/verification/T175-sts-leakage.json"
    )
    args = parser.parse_args(argv)

    from laris.research.corpus.acquisition.sources.english_hf import load_sources_config

    config = load_sources_config(args.config)
    blocked = stsb_heldout_sentences(args.stsb_dir)
    seen: Set[Tuple[str, str]] = set()
    kept_all: List[Tuple[str, str, float, str]] = []
    per_source: Dict[str, Dict[str, int]] = {}
    for source in (s for s in config["sources"] if s["role"] == "similarity"):
        field, low, high = score_spec(source)
        raw_dir = REPO_ROOT / "data/raw" / source["id"].lower().replace("-", "_")
        files = sorted(raw_dir.glob("*"))
        pairs = (
            p
            for f in files
            if f.is_file() and not f.name.endswith(".part")
            for p in (extract_pair(r, field) for r in rows_from_file(f))
            if p is not None
        )
        kept, stats = filter_pairs(pairs, blocked, seen)
        per_source[source["id"]] = stats
        kept_all.extend((a, b, scale_score(s, low, high), source["id"]) for a, b, s in kept)
        print(f"{source['id']}: {stats}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "sentence1": [r[0] for r in kept_all],
            "sentence2": [r[1] for r in kept_all],
            "score": [r[2] for r in kept_all],
            "source": [r[3] for r in kept_all],
        }
    )
    pq.write_table(table, args.output)
    report = {
        "task": "T175",
        "rule": "drop any pair sharing a normalised sentence with STS-B validation or test",
        "score_columns": {
            s["id"]: {"field": s.get("score_field"), "range": s.get("score_range")}
            for s in config["sources"]
            if s["role"] == "similarity"
        },
        "stsb_heldout_sentences": len(blocked),
        "kept_pairs": len(kept_all),
        "per_source": per_source,
        "output": str(args.output.relative_to(REPO_ROOT))
        if args.output.is_relative_to(REPO_ROOT)
        else str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"kept {len(kept_all):,} pairs; report {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
