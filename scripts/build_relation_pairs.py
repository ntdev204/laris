#!/usr/bin/env python3
"""Relation pairs for contrastive similarity, derived labels, leakage-free (T197).

Builds positives and hard negatives from data already on disk, with no grader and no model:

* positives: `entailment` (all_nli, wanli_en, scitail_en), `paraphrase_duplicate` (quora_duplicates,
  mrpc_en, paws, paws_swap_en: label 1), `adjacent_sentences` (two consecutive sentences of one
  passage of an MLM source);
* hard negatives: `contradiction` (all_nli, wanli_en), `paws_non_paraphrase` (paws, paws_swap_en:
  label 0, words shared but meaning different), `order_swapped` (the adjacent pair
  in reverse order).

Only training splits are read. Every row carries `label_source: derived`, its `relation`, its
`polarity` (positive or negative), its `source` and `symmetric` (false for order_swapped: both
orders hold the same two sentences, so only an order-aware model can separate them). These are
relation labels, not graded similarity, and are never reported as human similarity data.

Leakage (STS-B validation and test are gate G05 data): a pair is dropped when either sentence has
a normalised exact match in STS-B validation or test, or shares an eight-word window with one of
their sentences. The output is then rescanned by an independent implementation (string tuples
instead of hashes); any hit fails the run. Reads data and writes files only; nothing trains.

Usage:
    .venv/bin/python -I scripts/build_relation_pairs.py \
        --out data/processed/relation_pairs_en/train.parquet \
        --report reports/verification/T197-relation-pairs.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"
RAW = REPO_ROOT / "data" / "raw"

WINDOW = 8
LABEL_SOURCE = "derived"
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
# A sentence ends at . ! ? (plus closing quotes) followed by space and a capital or opening quote.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'\)\]”’]*\s+(?=[\"'“]?[A-Z])")

SCHEMA = pa.schema(
    [
        ("sentence1", pa.string()),
        ("sentence2", pa.string()),
        ("relation", pa.string()),
        ("polarity", pa.string()),
        ("source", pa.string()),
        ("label_source", pa.string()),
        ("symmetric", pa.bool_()),
    ]
)


# --------------------------------------------------------------------------- text keys


def normalise(text: str) -> str:
    """Lower-case and keep letters and digits only (same rule as check_sts_leakage.py)."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def windows(text: str, size: int = WINDOW) -> Iterator[Tuple[str, ...]]:
    """Every run of `size` consecutive normalised words of `text` (none when it is shorter)."""
    tokens = normalise(text).split()
    for i in range(len(tokens) - size + 1):
        yield tuple(tokens[i : i + size])


def _digest(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def pair_key(a: str, b: str) -> int:
    """Order-free hash of a normalised pair, to drop duplicates across sources."""
    x, y = sorted((normalise(a), normalise(b)))
    return _digest(f"{x}\x1f{y}")


# --------------------------------------------------------------------------- leakage guard


class GateIndex:
    """STS-B validation and test sentences: normalised exact strings and eight-word windows."""

    def __init__(self, sentences: Iterable[str]) -> None:
        self.exact: Set[int] = set()
        self.windows: Set[int] = set()
        for sentence in sentences:
            norm = normalise(sentence)
            if norm:
                self.exact.add(_digest(norm))
            for window in windows(sentence):
                self.windows.add(_digest(" ".join(window)))

    def hit(self, sentence: str) -> Optional[str]:
        """'exact' or 'window' when the sentence overlaps the gate data, else None."""
        norm = normalise(sentence)
        if norm and _digest(norm) in self.exact:
            return "exact"
        for window in windows(sentence):
            if _digest(" ".join(window)) in self.windows:
                return "window"
        return None


def rescan(pairs: Iterable[Tuple[str, str]], gate_sentences: Sequence[str]) -> Dict[str, int]:
    """Independent leakage count: normalised strings and word tuples, no hashing."""
    exact = {normalise(s) for s in gate_sentences if normalise(s)}
    grams: Set[Tuple[str, ...]] = set()
    for sentence in gate_sentences:
        grams.update(windows(sentence))
    exact_hits = window_hits = checked = 0
    for a, b in pairs:
        checked += 1
        for sentence in (a, b):
            if normalise(sentence) in exact:
                exact_hits += 1
            elif any(w in grams for w in windows(sentence)):
                window_hits += 1
    return {"pairs_checked": checked, "exact_hits": exact_hits, "window_hits": window_hits}


# --------------------------------------------------------------------------- adjacent sentences


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def adjacent_pair(
    text: str, rng: random.Random, min_words: int, max_words: int
) -> Optional[Tuple[str, str]]:
    """One random pair of consecutive sentences inside one paragraph, or None.

    Paragraphs are split on blank lines first so a pair never straddles a heading or a list.
    Both sentences must have between `min_words` and `max_words` words.
    """
    candidates: List[Tuple[str, str]] = []
    for paragraph in re.split(r"\n\s*\n", text):
        if "\n" in paragraph.strip():
            continue
        sentences = split_sentences(paragraph)
        for left, right in zip(sentences, sentences[1:]):
            if all(min_words <= len(s.split()) <= max_words for s in (left, right)):
                candidates.append((left, right))
    return rng.choice(candidates) if candidates else None


# --------------------------------------------------------------------------- relation rules


class Rule:
    """Which rows of a source become which relation."""

    def __init__(
        self,
        relation: str,
        polarity: str,
        column: Optional[str] = None,
        values: Sequence[Any] = (),
    ) -> None:
        self.relation, self.polarity, self.column, self.values = relation, polarity, column, values

    def accepts(self, row: Dict[str, Any]) -> bool:
        return self.column is None or row.get(self.column) in self.values


PAIR_SOURCES: List[Tuple[str, str, Tuple[str, str], List[Rule]]] = [
    # (source name, parquet path relative to the repository, (column 1, column 2), rules)
    (
        "all_nli",
        "data/processed/all_nli/train.parquet",
        ("premise", "hypothesis"),
        [
            Rule("entailment", "positive", "label", ("entailment",)),
            Rule("contradiction", "negative", "label", ("contradiction",)),
        ],
    ),
    (
        "wanli_en",
        "data/processed/wanli_en/train.parquet",
        ("premise", "hypothesis"),
        [
            Rule("entailment", "positive", "label", ("entailment",)),
            Rule("contradiction", "negative", "label", ("contradiction",)),
        ],
    ),
    (
        "scitail_en",
        "data/processed/scitail_en/train.parquet",
        ("premise", "hypothesis"),
        [Rule("entailment", "positive", "label", ("entailment",))],
    ),
    (
        "quora_duplicates",
        "data/processed/quora_duplicates/train.parquet",
        ("sentence1", "sentence2"),
        [Rule("paraphrase_duplicate", "positive", "label", (1,))],
    ),
    (
        "mrpc_en",
        "data/processed/mrpc_en/train.parquet",
        ("sentence1", "sentence2"),
        [Rule("paraphrase_duplicate", "positive", "label", (1,))],
    ),
    (
        "paws",
        "data/processed/paws/train.parquet",
        ("sentence1", "sentence2"),
        [
            Rule("paraphrase_duplicate", "positive", "label", (1,)),
            Rule("paws_non_paraphrase", "negative", "label", (0,)),
        ],
    ),
    (
        "paws_swap_en",
        "data/raw/paws_swap_en/train-00000-of-00001.parquet",
        ("sentence1", "sentence2"),
        [
            Rule("paraphrase_duplicate", "positive", "label", (1,)),
            Rule("paws_non_paraphrase", "negative", "label", (0,)),
        ],
    ),
]

# MLM sources with plain prose for adjacent sentences (training splits, head of the file).
ADJACENT_SOURCES = ("wikipedia_en", "cc_news_en", "openwebtext_en", "gutenberg_en")


def read_gate_sentences(processed: Path) -> List[str]:
    """Every sentence of STS-B validation and test (the G05 gate data)."""
    out: List[str] = []
    for split in ("val", "test"):
        path = processed / "stsb" / f"{split}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"STS-B {split} split not found at {path}")
        table = pq.read_table(path, columns=["sentence1", "sentence2"])
        out.extend(table.column("sentence1").to_pylist())
        out.extend(table.column("sentence2").to_pylist())
    return out


class Builder:
    """Collects pairs, drops duplicates and leaked pairs, and counts every decision."""

    def __init__(self, gate: GateIndex) -> None:
        self.gate = gate
        self.rows: List[Dict[str, Any]] = []
        self.seen: Set[int] = set()
        self.counts: Dict[str, Counter] = {
            k: Counter()
            for k in (
                "candidate",
                "kept",
                "dropped_exact",
                "dropped_window",
                "dropped_duplicate",
                "dropped_degenerate",
            )
        }

    def add(
        self, source: str, relation: str, polarity: str, a: str, b: str, symmetric: bool = True
    ) -> None:
        key = (source, relation)
        self.counts["candidate"][key] += 1
        a, b = (a or "").strip(), (b or "").strip()
        if not a or not b or normalise(a) == normalise(b):
            self.counts["dropped_degenerate"][key] += 1
            return
        for sentence in (a, b):
            hit = self.gate.hit(sentence)
            if hit:
                self.counts[f"dropped_{hit}"][key] += 1
                return
        # Order-swapped pairs are keyed by order, so they never collide with their adjacent pair.
        dedup = (
            pair_key(a, b) if symmetric else _digest(f"ordered\x1f{normalise(a)}\x1f{normalise(b)}")
        )
        if dedup in self.seen:
            self.counts["dropped_duplicate"][key] += 1
            return
        self.seen.add(dedup)
        self.counts["kept"][key] += 1
        self.rows.append(
            {
                "sentence1": a,
                "sentence2": b,
                "relation": relation,
                "polarity": polarity,
                "source": source,
                "label_source": LABEL_SOURCE,
                "symmetric": symmetric,
            }
        )


def add_pair_source(
    builder: Builder, name: str, path: Path, columns: Tuple[str, str], rules: Sequence[Rule]
) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{name}: {path} not found")
    needed = list({columns[0], columns[1], *(r.column for r in rules if r.column)})
    table = pq.read_table(path, columns=needed)
    for row in table.to_pylist():
        for rule in rules:
            if rule.accepts(row):
                builder.add(name, rule.relation, rule.polarity, row[columns[0]], row[columns[1]])
                break


def add_adjacent_source(
    builder: Builder,
    name: str,
    path: Path,
    rows: int,
    seed: int,
    min_words: int,
    max_words: int,
    with_swapped: bool,
) -> int:
    """One adjacent pair per passage from the first `rows` passages; returns passages read."""
    if not path.exists():
        raise FileNotFoundError(f"{name}: {path} not found")
    rng = random.Random(f"{seed}:{name}")
    read = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=["text"]):
        for text in batch.column("text").to_pylist():
            read += 1
            pair = adjacent_pair(text, rng, min_words, max_words)
            if pair:
                builder.add(name, "adjacent_sentences", "positive", pair[0], pair[1])
                if with_swapped:
                    builder.add(
                        name, "order_swapped", "negative", pair[1], pair[0], symmetric=False
                    )
            if read >= rows:
                return read
    return read


def summarise(builder: Builder) -> Dict[str, Any]:
    keys = sorted(set().union(*(set(c) for c in builder.counts.values())))
    table = {
        f"{source}/{relation}": {
            name: builder.counts[name][(source, relation)] for name in builder.counts
        }
        for source, relation in keys
    }
    per_relation: Dict[str, int] = Counter()
    for (source, relation), n in builder.counts["kept"].items():
        per_relation[relation] += n
    return {"by_source_relation": table, "kept_by_relation": dict(sorted(per_relation.items()))}


def write_parquet(rows: List[Dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = {name: [r[name] for r in rows] for name in SCHEMA.names}
    pq.write_table(pa.table(columns, schema=SCHEMA), out, compression="zstd")


def build(args: argparse.Namespace) -> Dict[str, Any]:
    gate_sentences = read_gate_sentences(PROCESSED)
    builder = Builder(GateIndex(gate_sentences))
    for name, rel, columns, rules in PAIR_SOURCES:
        add_pair_source(builder, name, REPO_ROOT / rel, columns, rules)
    passages: Dict[str, int] = {}
    for name in ADJACENT_SOURCES:
        passages[name] = add_adjacent_source(
            builder,
            name,
            PROCESSED / name / "train.parquet",
            args.adjacent_passages,
            args.seed,
            args.min_words,
            args.max_words,
            with_swapped=True,
        )
    write_parquet(builder.rows, args.out)
    # Independent rescan of the file as written.
    table = pq.read_table(args.out, columns=["sentence1", "sentence2"])
    scan = rescan(
        zip(table.column("sentence1").to_pylist(), table.column("sentence2").to_pylist()),
        gate_sentences,
    )
    report = {
        "task": "T197",
        "label_source": LABEL_SOURCE,
        "out": str(args.out),
        "rows": len(builder.rows),
        "seed": args.seed,
        "window_words": WINDOW,
        "adjacent_passages_read": passages,
        "gate_sentences": len(gate_sentences),
        **summarise(builder),
        "polarity": dict(Counter(r["polarity"] for r in builder.rows)),
        "rescan": scan,
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out", type=Path, default=PROCESSED / "relation_pairs_en" / "train.parquet"
    )
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument(
        "--adjacent-passages",
        type=int,
        default=150_000,
        help="passages read from the head of each MLM source",
    )
    parser.add_argument("--min-words", type=int, default=6)
    parser.add_argument("--max-words", type=int, default=60)
    args = parser.parse_args(argv)
    report = build(args)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    scan = report["rescan"]
    if scan["exact_hits"] or scan["window_hits"]:
        print("LEAKAGE: rescan found STS-B validation or test overlap", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
