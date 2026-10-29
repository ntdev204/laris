"""Helpers shared by the per-dataset partitioners."""

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256
from laris.corpus.splits.ratios import PartitionRatios

SPLIT_FILE_NAMES = {
    DatasetSplit.TRAIN: "train",
    DatasetSplit.VAL: "val",
    DatasetSplit.TEST: "test",
}
_WHITESPACE = re.compile(r"\s+")


def bucket_split(
    group_key: str, seed: str, ratios: Optional[PartitionRatios] = None
) -> DatasetSplit:
    """Deterministically maps a group key to TRAIN/VAL/TEST via SHA-256 bucketing."""
    if not group_key or not group_key.strip():
        raise ValueError("group_key must be a non-empty string")
    ratios = ratios or PartitionRatios()
    digest = hashlib.sha256(f"{seed}::{group_key.strip()}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    if bucket < ratios.train:
        return DatasetSplit.TRAIN
    if bucket < ratios.train + ratios.val:
        return DatasetSplit.VAL
    return DatasetSplit.TEST


def bucket_dev_split(group_key: str, seed: str) -> DatasetSplit:
    """Splits a held-out (dev) pool 50/50 into VAL and TEST by group."""
    if not group_key or not group_key.strip():
        raise ValueError("group_key must be a non-empty string")
    digest = hashlib.sha256(f"{seed}::{group_key.strip()}".encode("utf-8")).hexdigest()
    return DatasetSplit.VAL if int(digest[:8], 16) / 0xFFFFFFFF < 0.5 else DatasetSplit.TEST


def normalized_text_digest(text: str) -> bytes:
    """16-byte digest of NFC-normalized, case-folded, whitespace-collapsed text."""
    canon = _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip().casefold()
    return hashlib.sha256(canon.encode("utf-8")).digest()[:16]


def write_split_tables(
    dataset_id: str,
    output_dir: Path,
    tables: Dict[DatasetSplit, pa.Table],
) -> PhysicalSplitResult:
    """Writes one parquet per non-empty split and returns the authoritative result."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = PhysicalSplitResult(dataset_id=dataset_id)
    for split, table in tables.items():
        if len(table) == 0:
            continue
        name = SPLIT_FILE_NAMES[split]
        path = output_dir / f"{name}.parquet"
        pq.write_table(table, path, compression="snappy")
        result.files[name] = path
        result.counts[name] = len(table)
        result.bytes[name] = path.stat().st_size
        result.sha256[name] = _compute_file_sha256(path)
    return result


def rows_to_table(rows: List[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)
