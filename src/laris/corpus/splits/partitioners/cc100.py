"""CC-100 Vietnamese: hash split by document with exact-duplicate removal against Wikipedia-VI."""

from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import (
    SPLIT_FILE_NAMES,
    bucket_split,
    normalized_text_digest,
)
from laris.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256

SCHEMA = pa.schema([("id", pa.string()), ("text", pa.string()), ("source", pa.string())])


def wikipedia_digests(shard_paths: Iterable[Path], batch_size: int = 20000) -> Set[bytes]:
    """Digests of every Wikipedia article body, streamed so memory stays bounded."""
    digests: Set[bytes] = set()
    for shard in shard_paths:
        for batch in pq.ParquetFile(shard).iter_batches(batch_size=batch_size, columns=["text"]):
            digests.update(normalized_text_digest(t) for t in batch.column(0).to_pylist() if t)
    return digests


def partition_cc100_physical(
    shard_paths: Iterable[Path],
    output_dir: Union[str, Path],
    dataset_id: str = "CC100-VI-CLEAN",
    exclude_digests: Optional[Set[bytes]] = None,
    max_records: Optional[int] = None,
    batch_size: int = 20000,
    seed: str = "laris-cc100-partition-seed-v1",
) -> PhysicalSplitResult:
    """Single streaming pass; a document goes to exactly one split and never to two."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    blocked = exclude_digests or set()
    writers: Dict[DatasetSplit, pq.ParquetWriter] = {
        split: pq.ParquetWriter(out_dir / f"{name}.parquet", SCHEMA, compression="snappy")
        for split, name in SPLIT_FILE_NAMES.items()
    }
    counts = {name: 0 for name in SPLIT_FILE_NAMES.values()}
    seen: Set[bytes] = set()
    total = 0
    try:
        for shard in shard_paths:
            for batch in pq.ParquetFile(shard).iter_batches(batch_size=batch_size):
                buckets: Dict[DatasetSplit, Dict[str, list]] = {
                    s: {"id": [], "text": [], "source": []} for s in SPLIT_FILE_NAMES
                }
                for rec in batch.to_pylist():
                    if max_records is not None and total >= max_records:
                        break
                    digest = normalized_text_digest(rec["text"])
                    if digest in blocked or digest in seen:
                        continue
                    seen.add(digest)
                    split = bucket_split(rec["doc_id"], seed)
                    bucket = buckets[split]
                    bucket["id"].append(rec["doc_id"])
                    bucket["text"].append(rec["text"])
                    bucket["source"].append(rec.get("source") or "cc100-vi")
                    total += 1
                for split, cols in buckets.items():
                    if cols["id"]:
                        writers[split].write_table(pa.table(cols, schema=SCHEMA))
                        counts[SPLIT_FILE_NAMES[split]] += len(cols["id"])
            if max_records is not None and total >= max_records:
                break
    finally:
        for writer in writers.values():
            writer.close()

    result = PhysicalSplitResult(dataset_id=dataset_id)
    for name, count in counts.items():
        path = out_dir / f"{name}.parquet"
        result.files[name] = path
        result.counts[name] = count
        result.bytes[name] = path.stat().st_size
        result.sha256[name] = _compute_file_sha256(path)
    return result
