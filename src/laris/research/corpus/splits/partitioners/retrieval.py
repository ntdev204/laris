"""Leakage-safe partitioning of the retrieval-pair sources (T178, D46 / ADR-022).

Each source becomes ``data/processed/<dir>/{train,val,test}.parquet`` with columns ``query``, ``positive`` and
``source``. The dense-retrieval task trains on them with in-batch negatives only, so no hard negatives are kept.

Rules (all config-driven, ``configs/data/english_partition.yaml``):

* A pair is dropped when either side is empty or when its (query, positive) pair already appeared in any source.
* Splits follow the normalised text of the query (asymmetric sources) or of the connected component of texts that
  share a pair (symmetric sources such as caption pairs), so no query, and no chain of paraphrases, straddles splits.
  The key does not include the source id, so the same query lands in the same split in every source.
* Held-out data is protected: a pair is dropped when a side equals a SQuAD v1 validation/test question or paragraph,
  an STS-B validation/test sentence, a SciFact claim, a SciFact title or abstract, or when the positive shares an
  eight-word window with a SQuAD v1 held-out paragraph or a SciFact abstract. SciFact claims are never trained on.

Reads files and writes files; nothing trains.
"""

import hashlib
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from laris.research.corpus.splits.partitioners.common import bucket_split
from laris.research.corpus.splits.partitioners.english import (
    _ratios,
    _SplitWriters,
    iter_rows,
)
from laris.research.corpus.splits.physical import PhysicalSplitResult

RETRIEVAL_SCHEMA = pa.schema(
    [("query", pa.string()), ("positive", pa.string()), ("source", pa.string())]
)
SHINGLE_WORDS = 8
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Lower-cased text reduced to letters and digits, so trivial edits do not hide a copy."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def text_digest(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def _shingles(normalised: str) -> Iterator[int]:
    """64-bit keys (CRC-32 and Adler-32 of the bytes) of every eight-word window; stable across runs."""
    words = normalised.split()
    for i in range(len(words) - SHINGLE_WORDS + 1):
        data = " ".join(words[i : i + SHINGLE_WORDS]).encode("utf-8")
        yield (zlib.crc32(data) << 32) | zlib.adler32(data)


@dataclass
class Blocklist:
    """Held-out text that retrieval training pairs must not contain."""

    exact: Dict[str, Set[int]] = field(default_factory=dict)  # reason -> digests of normalised text
    shingles: Dict[str, Set[int]] = field(default_factory=dict)  # reason -> shingle keys

    def add_exact(self, reason: str, text: Optional[str]) -> None:
        norm = normalise(text or "")
        if norm:
            self.exact.setdefault(reason, set()).add(text_digest(norm))

    def add_passage(self, reason: str, text: Optional[str]) -> None:
        norm = normalise(text or "")
        if norm:
            self.exact.setdefault(reason, set()).add(text_digest(norm))
            self.shingles.setdefault(reason, set()).update(_shingles(norm))

    def exact_hit(self, norm: str) -> Optional[str]:
        digest = text_digest(norm)
        for reason, digests in self.exact.items():
            if digest in digests:
                return reason
        return None

    def overlap_hit(self, norm: str) -> Optional[str]:
        if not self.shingles:
            return None
        for h in _shingles(norm):
            for reason, hashes in self.shingles.items():
                if h in hashes:
                    return reason
        return None


def build_blocklist(processed_root: Path, raw_root: Path, config: Dict[str, Any]) -> Blocklist:
    """Held-out sets named in ``retrieval_blocklist``; a missing directory is an error, never skipped."""
    spec = config["retrieval_blocklist"]
    block = Blocklist()
    for split in ("val", "test"):
        squad = processed_root / spec["squad_dir"] / f"{split}.parquet"
        for row in iter_rows([squad], ["question", "context"]):
            block.add_exact(f"squad_v1_{split}_question", row["question"])
            block.add_passage(f"squad_v1_{split}_paragraph", row["context"])
        stsb = processed_root / spec["stsb_dir"] / f"{split}.parquet"
        for row in iter_rows([stsb], ["sentence1", "sentence2"]):
            block.add_exact(f"stsb_{split}_sentence", row["sentence1"])
            block.add_exact(f"stsb_{split}_sentence", row["sentence2"])
    sci = raw_root / spec["scifact_dir"]
    for row in iter_rows([sci / spec["scifact_queries"]], ["text"]):
        block.add_exact("scifact_claim", row["text"])
    for row in iter_rows([sci / spec["scifact_corpus"]], ["title", "text"]):
        block.add_exact("scifact_title", row["title"])
        block.add_passage("scifact_abstract", row["text"])
    return block


def _group_pairs(spec: Dict[str, Any], files: List[Path]) -> Iterator[Tuple[str, str]]:
    """Raw (query, positive) text pairs of one source, in file order."""
    kind = spec.get("kind", "pair")
    if kind == "msmarco":
        for row in iter_rows(files, ["query", "passages"]):
            passages = row.get("passages") or {}
            for flag, text in zip(
                passages.get("is_selected") or [], passages.get("passage_text") or []
            ):
                if flag == 1:
                    yield row.get("query") or "", text or ""
        return
    column_pairs = spec.get("columns") or [[spec["query"], spec["positive"]]]
    for row in iter_rows(files):
        for left, right in column_pairs:
            if left in row and right in row:
                yield row[left] or "", row[right] or ""
                break


def _source_files(raw_dir: Path) -> List[Path]:
    return sorted(p for p in raw_dir.rglob("*.parquet") if p.is_file())


def _components(spec: Dict[str, Any], files: List[Path], max_chars: int) -> Dict[int, int]:
    """Union-find over the texts that share a pair; the root of a component is its smallest digest."""
    parent: Dict[int, int] = {}

    def find(x: int) -> int:
        root = x
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for first, second in _group_pairs(spec, files):
        a = normalise(first.strip()[:max_chars])
        b = normalise(second.strip()[:max_chars])
        if not a or not b:
            continue
        ra, rb = find(text_digest(a)), find(text_digest(b))
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {x: find(x) for x in list(parent)}


def partition_retrieval_source(
    spec: Dict[str, Any],
    raw_dir: Path,
    out_dir: Path,
    config: Dict[str, Any],
    blocklist: Blocklist,
    seen_pairs: Set[int],
    max_pairs: Optional[int] = None,
) -> Tuple[PhysicalSplitResult, Dict[str, Any]]:
    """Streams one source into train/val/test; ``seen_pairs`` is shared across sources (deduplication)."""
    ratios = _ratios(config["retrieval_ratios"])
    max_chars = int(config["retrieval_max_chars"])
    files = _source_files(raw_dir)
    if not files:
        raise FileNotFoundError(f"no parquet files for {spec['id']} in {raw_dir}")
    roots = _components(spec, files, max_chars) if spec.get("symmetric") else None
    writers = _SplitWriters(out_dir, RETRIEVAL_SCHEMA)
    stats: Dict[str, Any] = {
        "input": 0,
        "empty": 0,
        "duplicate": 0,
        "kept": 0,
        "leaked": {},
    }
    for index, (first, second) in enumerate(_group_pairs(spec, files)):
        if max_pairs is not None and index >= max_pairs:
            break
        stats["input"] += 1
        query, positive = first.strip()[:max_chars], second.strip()[:max_chars]
        nq, npos = normalise(query), normalise(positive)
        if not nq or not npos:
            stats["empty"] += 1
            continue
        reason = (
            blocklist.exact_hit(nq)
            or blocklist.exact_hit(npos)
            or blocklist.overlap_hit(npos)
            or (blocklist.overlap_hit(nq) if spec.get("symmetric") else None)
        )
        if reason:
            stats["leaked"][reason] = stats["leaked"].get(reason, 0) + 1
            continue
        pair_key = text_digest(f"{nq}\x1f{npos}")
        if spec.get("symmetric"):
            pair_key = text_digest("\x1f".join(sorted((nq, npos))))
        if pair_key in seen_pairs:
            stats["duplicate"] += 1
            continue
        seen_pairs.add(pair_key)
        group = text_digest(nq)
        if roots is not None:
            group = roots[group]
        split = bucket_split(f"retrieval::{group}", config["seed"], ratios)
        writers.add(split, {"query": query, "positive": positive, "source": spec["id"]})
        stats["kept"] += 1
    stats["leaked_total"] = sum(stats["leaked"].values())
    return writers.close(spec["id"]), stats


def scan_split_isolation(paths: Dict[str, Iterable[Path]]) -> Dict[str, Any]:
    """Counts normalised queries that appear in more than one split, within and across sources.

    ``paths`` maps a source id to its split files; the first split a query is seen in owns it.
    """
    owner: Dict[int, Tuple[str, str]] = {}
    within = 0
    across = 0
    for source, files in paths.items():
        for path in files:
            split = path.stem
            for batch in pq.ParquetFile(path).iter_batches(batch_size=20000, columns=["query"]):
                for query in batch.column(0).to_pylist():
                    key = text_digest(normalise(query))
                    seen_source, seen_split = owner.setdefault(key, (source, split))
                    if seen_split != split:
                        if seen_source == source:
                            within += 1
                        else:
                            across += 1
    return {"queries_in_two_splits_within_source": within, "queries_in_two_splits_across_sources": across}

