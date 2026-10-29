"""Shared helpers for physical (on-disk) Parquet partitioning."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq


def _compute_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 digest of a physical file in streaming chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PhysicalSplitResult:
    """Authoritative outcome of a physical dataset partitioning execution."""

    dataset_id: str
    files: Dict[str, Path] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    bytes: Dict[str, int] = field(default_factory=dict)
    sha256: Dict[str, str] = field(default_factory=dict)
    leakage_verified: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to JSON-serializable dictionary."""
        return {
            "dataset_id": self.dataset_id,
            "files": {k: str(v) for k, v in self.files.items()},
            "counts": dict(self.counts),
            "bytes": dict(self.bytes),
            "sha256": dict(self.sha256),
            "leakage_verified": self.leakage_verified,
        }


def _merge_parquet_parts_streaming(
    part_files: List[Path],
    output_file: Path,
    schema: pa.Schema,
    batch_size: int = 100000,
) -> int:
    """Streams and concatenates multiple Parquet parts into a final consolidated file."""
    writer = pq.ParquetWriter(output_file, schema=schema, compression="snappy")
    total_written = 0
    try:
        for p in part_files:
            if not p.is_file() or p.stat().st_size == 0:
                continue
            pq_f = pq.ParquetFile(p)
            for batch in pq_f.iter_batches(batch_size=batch_size):
                writer.write_batch(batch)
                total_written += len(batch)
    finally:
        writer.close()

    # Clean up intermediate part files
    for p in part_files:
        try:
            p.unlink()
        except OSError:
            pass

    return total_written
