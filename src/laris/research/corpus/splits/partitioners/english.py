"""Leakage-safe partitioning of the English stage-1 sources (T177, D46 / ADR-022).

Config-driven (``configs/data/english_partition.yaml``). Documents are split by a hash of their id
(or text), long documents are cut into passages that stay in their document's split, exact
duplicates are dropped across sources, and QA rows that share an article or context with the SQuAD
v1 validation or test partition are removed. Reads raw files and writes processed files; nothing
trains.
"""

import gzip
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from laris.research.corpus.splits.partitioners.common import (
    SPLIT_FILE_NAMES,
    bucket_split,
    normalized_text_digest,
    write_split_tables,
)
from laris.research.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256
from laris.research.corpus.splits.ratios import PartitionRatios
from laris.shared.corpus.schemas import DatasetSplit

REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "data" / "english_partition.yaml"
FLUSH_ROWS = 2000
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

MLM_SCHEMA = pa.schema([("id", pa.string()), ("text", pa.string()), ("source", pa.string())])
NLI_SCHEMA = pa.schema(
    [("premise", pa.string()), ("hypothesis", pa.string()), ("label", pa.string())]
)
PARA_SCHEMA = pa.schema(
    [("sentence1", pa.string()), ("sentence2", pa.string()), ("label", pa.int64())]
)


def load_partition_config(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or DEFAULT_CONFIG, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)  # type: ignore[no-any-return]


def _ratios(block: Dict[str, float]) -> PartitionRatios:
    return PartitionRatios(train=block["train"], val=block["val"], test=block["test"])


def iter_rows(files: List[Path], columns: Optional[List[str]] = None) -> Iterator[Dict[str, Any]]:
    """Streams rows of parquet, JSONL or JSON.GZ files with bounded memory."""
    for path in files:
        name = path.name
        if name.endswith(".parquet"):
            for batch in pq.ParquetFile(path).iter_batches(batch_size=2000, columns=columns):
                yield from batch.to_pylist()
        else:
            opener = gzip.open if name.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
                for line in handle:
                    if line.strip():
                        yield json.loads(line)


def chunk_text(text: str, chunk_chars: int, min_chars: int) -> List[str]:
    """Cuts text into passages of at most ``chunk_chars`` at paragraph, then sentence, ends."""
    pieces: List[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_chars:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE.split(paragraph):
            while len(sentence) > chunk_chars:  # unbroken text: hard cut
                pieces.append(sentence[:chunk_chars])
                sentence = sentence[chunk_chars:]
            if sentence:
                pieces.append(sentence)
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > chunk_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= min_chars]


def _digest_int(text: str) -> int:
    return int.from_bytes(normalized_text_digest(text)[:8], "big")


def wikipedia_digest_set(processed_root: Path, name: str) -> Set[int]:
    """Digests of every document of an already partitioned corpus (all splits)."""
    digests: Set[int] = set()
    for split in SPLIT_FILE_NAMES.values():
        path = processed_root / name / f"{split}.parquet"
        if path.is_file():
            for row in iter_rows([path], ["text"]):
                digests.add(_digest_int(row["text"] or ""))
    return digests


class _SplitWriters:
    """Three streaming parquet writers (train/val/test) with a small row buffer."""

    def __init__(self, out_dir: Path, schema: pa.Schema) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir, self.schema = out_dir, schema
        self.writers = {
            s: pq.ParquetWriter(out_dir / f"{n}.parquet", schema, compression="snappy")
            for s, n in SPLIT_FILE_NAMES.items()
        }
        self.buffers: Dict[DatasetSplit, List[Dict[str, Any]]] = {s: [] for s in SPLIT_FILE_NAMES}
        self.counts = {s: 0 for s in SPLIT_FILE_NAMES}

    def add(self, split: DatasetSplit, row: Dict[str, Any]) -> None:
        self.buffers[split].append(row)
        self.counts[split] += 1
        if len(self.buffers[split]) >= FLUSH_ROWS:
            self._flush(split)

    def _flush(self, split: DatasetSplit) -> None:
        if self.buffers[split]:
            self.writers[split].write_table(
                pa.Table.from_pylist(self.buffers[split], schema=self.schema)
            )
            self.buffers[split] = []

    def close(self, dataset_id: str) -> PhysicalSplitResult:
        result = PhysicalSplitResult(dataset_id=dataset_id)
        for split, name in SPLIT_FILE_NAMES.items():
            self._flush(split)
            self.writers[split].close()
            path = self.out_dir / f"{name}.parquet"
            if self.counts[split] == 0:
                path.unlink()
                continue
            result.files[name] = path
            result.counts[name] = self.counts[split]
            result.bytes[name] = path.stat().st_size
            result.sha256[name] = _compute_file_sha256(path)
        return result


def partition_mlm_source(
    spec: Dict[str, Any],
    raw_dir: Path,
    out_dir: Path,
    config: Dict[str, Any],
    seen: Set[int],
    max_docs: Optional[int] = None,
) -> Tuple[PhysicalSplitResult, Dict[str, int]]:
    """Splits documents by id hash, chunks them and drops exact duplicates (``seen`` is shared).

    An optional ``min_date: {field, value}`` in the spec drops rows whose ISO date field sorts below
    ``value``.
    """
    ratios = _ratios(config["mlm_ratios"])
    files = sorted(p for p in raw_dir.iterdir() if p.suffix in {".parquet", ".gz", ".jsonl"})
    writers = _SplitWriters(out_dir, MLM_SCHEMA)
    stats = {"documents": 0, "duplicates": 0, "short": 0, "filtered": 0}
    gate = spec.get("min_date")
    for index, row in enumerate(iter_rows(files, None)):
        if max_docs is not None and index >= max_docs:
            break
        if gate and str(row.get(gate["field"]) or "") < gate["value"]:
            # e.g. patents granted before the digital full-text era are OCR output with heavy noise
            stats["filtered"] += 1
            continue
        text = row.get(spec["text"]) or ""
        chunks = chunk_text(text, config["mlm_chunk_chars"], config["mlm_min_chunk_chars"])
        if not chunks:
            stats["short"] += 1
            continue
        digest = _digest_int(text)
        if digest in seen:
            stats["duplicates"] += 1
            continue
        seen.add(digest)
        doc_key = str(row.get(spec.get("doc_id", "")) or digest)
        split = bucket_split(f"{spec['id']}::{doc_key}", config["seed"], ratios)
        stats["documents"] += 1
        for number, chunk in enumerate(chunks):
            writers.add(split, {"id": f"{doc_key}#{number}", "text": chunk, "source": spec["id"]})
    return writers.close(spec["id"]), stats


def _pair_key(a: str, b: str) -> str:
    x, y = sorted((a.strip().casefold(), b.strip().casefold()))
    return f"{x}\x1f{y}"


def partition_pairs(
    spec: Dict[str, Any], kind: str, raw_dir: Path, out_dir: Path, config: Dict[str, Any]
) -> PhysicalSplitResult:
    """NLI or paraphrase pairs: pooled from every raw split, deduplicated, split by pair hash."""
    ratios = _ratios(config["supervised_ratios"])
    files = sorted(p for p in raw_dir.iterdir() if p.suffix in {".parquet", ".jsonl"})
    rows: Dict[DatasetSplit, List[Dict[str, Any]]] = {s: [] for s in SPLIT_FILE_NAMES}
    seen: Set[str] = set()
    for row in iter_rows(files):
        if kind == "nli":
            first, second = row.get(spec["premise"]) or "", row.get(spec["hypothesis"]) or ""
            label = spec.get("label_map", {}).get(row.get(spec["label"]), row.get(spec["label"]))
            if label not in {"entailment", "neutral", "contradiction"}:
                continue  # '-' (no gold consensus) and unknown labels are dropped, never guessed
            record = {"premise": first, "hypothesis": second, "label": label}
        else:
            first, second = row.get(spec["sentence1"]) or "", row.get(spec["sentence2"]) or ""
            if row.get(spec["label"]) not in (0, 1):
                continue
            record = {"sentence1": first, "sentence2": second, "label": int(row[spec["label"]])}
        if not first.strip() or not second.strip():
            continue
        key = _pair_key(first, second)
        if key in seen:
            continue
        seen.add(key)
        rows[bucket_split(key, config["seed"], ratios)].append(record)
    schema = NLI_SCHEMA if kind == "nli" else PARA_SCHEMA
    return write_split_tables(
        spec["id"], out_dir, {s: pa.Table.from_pylist(r, schema=schema) for s, r in rows.items()}
    )


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").replace("_", " ")).strip().casefold()


def squad_v1_heldout_keys(processed_root: Path) -> Tuple[Set[str], Set[int]]:
    """Titles and context digests of the SQuAD v1 validation and test partitions."""
    titles: Set[str] = set()
    contexts: Set[int] = set()
    for split in ("val", "test"):
        path = processed_root / "squad" / f"{split}.parquet"
        for row in iter_rows([path], ["title", "context"]):
            titles.add(_norm_title(row["title"]))
            contexts.add(_digest_int(row["context"] or ""))
    return titles, contexts


def partition_qa_source(
    spec: Dict[str, Any],
    raw_dir: Path,
    out_dir: Path,
    config: Dict[str, Any],
    blocked_titles: Set[str],
    blocked_contexts: Set[int],
) -> Tuple[PhysicalSplitResult, Dict[str, int]]:
    """Extractive QA rows grouped by article title; SQuAD v1 held-out articles are removed."""
    ratios = _ratios(config["supervised_ratios"])
    files = sorted(p for p in raw_dir.iterdir() if p.suffix == ".parquet")
    schema = pa.schema(
        [
            ("id", pa.string()),
            ("title", pa.string()),
            ("context", pa.string()),
            ("question", pa.string()),
            (
                "answers",
                pa.struct(
                    [("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]
                ),
            ),
        ]
    )
    rows: Dict[DatasetSplit, List[Dict[str, Any]]] = {s: [] for s in SPLIT_FILE_NAMES}
    stats = {"dropped_squad_v1_heldout": 0, "kept": 0}
    seen: Set[str] = set()
    for row in iter_rows(files, ["id", "title", "context", "question", "answers"]):
        title = _norm_title(row["title"])
        if title in blocked_titles or _digest_int(row["context"] or "") in blocked_contexts:
            stats["dropped_squad_v1_heldout"] += 1
            continue
        key = f"{spec['id']}::{row['id']}"
        if key in seen:
            continue
        seen.add(key)
        answers = row["answers"] or {"text": [], "answer_start": []}
        record = {**{k: row[k] for k in ("id", "title", "context", "question")}, "answers": answers}
        rows[bucket_split(f"{spec['id']}::{title}", config["seed"], ratios)].append(record)
        stats["kept"] += 1
    tables = {s: pa.Table.from_pylist(r, schema=schema) for s, r in rows.items()}
    return write_split_tables(spec["id"], out_dir, tables), stats
