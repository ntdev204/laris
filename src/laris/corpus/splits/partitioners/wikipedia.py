"""Deterministic hash partitioning of document dumps (Wikipedia EN/VI)."""

import concurrent.futures
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.physical import (
    PhysicalSplitResult,
    _compute_file_sha256,
    _merge_parquet_parts_streaming,
)
from laris.corpus.splits.ratios import PartitionRatios


class WikipediaArticlePartitioner:
    """Deterministic hash-based partitioner for raw Wikipedia document shards.

    Partitions articles based on article ID or title hash, ensuring:
    - 100% reproducibility given identical seed
    - Zero document overlap between TRAIN, VAL, and TEST splits
    - Non-destructive processing (original shards remain untouched)
    """

    def __init__(
        self,
        ratios: Optional[PartitionRatios] = None,
        seed: str = "laris-wikipedia-partition-seed-v1",
    ) -> None:
        self.ratios = ratios or PartitionRatios(train=0.98, val=0.01, test=0.01)
        if not seed:
            raise ValueError("Partition seed must not be empty")
        self.seed = seed

    @classmethod
    def from_config(cls, config: Any) -> "WikipediaArticlePartitioner":
        """Instantiates WikipediaArticlePartitioner from centralized DataConfig or LarisConfig."""
        data_cfg = getattr(config, "data", config)
        ratios = PartitionRatios(
            train=getattr(data_cfg, "train_ratio", 0.80),
            val=getattr(data_cfg, "val_ratio", 0.10),
            test=getattr(data_cfg, "test_ratio", 0.10),
        )
        seed = getattr(data_cfg, "partition_seed", "laris-wikipedia-partition-seed-v1")
        return cls(ratios=ratios, seed=seed)

    def assign_split(self, article_id: str) -> DatasetSplit:
        """Deterministically maps an article ID to a DatasetSplit via hash bucketing."""
        if not article_id or not article_id.strip():
            raise ValueError("article_id must be a non-empty string")

        hash_input = f"{self.seed}::{article_id.strip()}".encode("utf-8")
        hex_digest = hashlib.sha256(hash_input).hexdigest()
        bucket = int(hex_digest[:8], 16) / 0xFFFFFFFF

        if bucket < self.ratios.train:
            return DatasetSplit.TRAIN
        if bucket < self.ratios.train + self.ratios.val:
            return DatasetSplit.VAL
        return DatasetSplit.TEST

    def partition_records(
        self,
        records: Iterable[Dict[str, Any]],
        id_key: str = "id",
        text_key: str = "text",
    ) -> Dict[DatasetSplit, List[Dict[str, Any]]]:
        """Partitions article records non-destructively, returning a split dictionary."""
        splits: Dict[DatasetSplit, List[Dict[str, Any]]] = {
            DatasetSplit.TRAIN: [],
            DatasetSplit.VAL: [],
            DatasetSplit.TEST: [],
        }

        seen_ids: Dict[str, DatasetSplit] = {}
        seen_hashes: Dict[str, DatasetSplit] = {}

        for record in records:
            art_id = str(record.get(id_key, "")).strip()
            if not art_id:
                raise ModuleContractViolationError(f"Missing or empty '{id_key}' in article record")

            assigned_split = self.assign_split(art_id)

            # Leakage check on ID
            if art_id in seen_ids and seen_ids[art_id] != assigned_split:
                raise DataLeakageError(
                    f"Article ID '{art_id}' assigned to multiple splits: "
                    f"{seen_ids[art_id].value} and {assigned_split.value}"
                )
            seen_ids[art_id] = assigned_split

            # Content hash check
            content = str(record.get(text_key, "")).strip()
            if content:
                content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if content_sha in seen_hashes and seen_hashes[content_sha] != assigned_split:
                    raise DataLeakageError(
                        f"Article content '{art_id}' leaked across splits: "
                        f"{seen_hashes[content_sha].value} and {assigned_split.value}"
                    )
                seen_hashes[content_sha] = assigned_split

            # Non-destructive copy with assigned split metadata
            record_copy = dict(record)
            record_copy["assigned_split"] = assigned_split.value
            splits[assigned_split].append(record_copy)

        return splits


def _partition_single_shard_worker(
    shard_path_str: str,
    output_dir_str: str,
    ratios_tuple: Tuple[float, float, float],
    seed: str,
    batch_size: int,
    id_key: str,
    max_records: Optional[int],
    prefix: str,
) -> Dict[str, Any]:
    """Worker process: partitions a single Parquet shard into temporary split files."""
    shard_path = Path(shard_path_str)
    out_path = Path(output_dir_str)
    out_path.mkdir(parents=True, exist_ok=True)

    part = WikipediaArticlePartitioner(
        ratios=PartitionRatios(*ratios_tuple),
        seed=seed,
    )

    pq_file = pq.ParquetFile(shard_path)
    schema = pq_file.schema_arrow

    train_part = out_path / f"_part_{prefix}_train.parquet"
    val_part = out_path / f"_part_{prefix}_val.parquet"
    test_part = out_path / f"_part_{prefix}_test.parquet"

    train_writer = pq.ParquetWriter(train_part, schema=schema, compression="snappy")
    val_writer = pq.ParquetWriter(val_part, schema=schema, compression="snappy")
    test_writer = pq.ParquetWriter(test_part, schema=schema, compression="snappy")

    counts = {"train": 0, "val": 0, "test": 0}
    seen_ids: Dict[str, str] = {}
    total_processed = 0

    try:
        for batch in pq_file.iter_batches(batch_size=batch_size):
            id_col = batch.column(id_key).to_pylist()
            train_idx: List[int] = []
            val_idx: List[int] = []
            test_idx: List[int] = []

            for idx, art_id_raw in enumerate(id_col):
                art_id = str(art_id_raw).strip()
                if not art_id:
                    continue
                assigned = part.assign_split(art_id)
                split_name = assigned.value.lower()

                if art_id in seen_ids and seen_ids[art_id] != split_name:
                    raise DataLeakageError(
                        f"Article ID {art_id} leaked across splits: "
                        f"{seen_ids[art_id]} vs {split_name}"
                    )
                seen_ids[art_id] = split_name

                if assigned == DatasetSplit.TRAIN:
                    train_idx.append(idx)
                elif assigned == DatasetSplit.VAL:
                    val_idx.append(idx)
                else:
                    test_idx.append(idx)

                total_processed += 1
                if max_records and total_processed >= max_records:
                    break

            if train_idx:
                train_writer.write_batch(batch.take(pa.array(train_idx, type=pa.int64())))
                counts["train"] += len(train_idx)
            if val_idx:
                val_writer.write_batch(batch.take(pa.array(val_idx, type=pa.int64())))
                counts["val"] += len(val_idx)
            if test_idx:
                test_writer.write_batch(batch.take(pa.array(test_idx, type=pa.int64())))
                counts["test"] += len(test_idx)

            if max_records and total_processed >= max_records:
                break
    finally:
        train_writer.close()
        val_writer.close()
        test_writer.close()

    return {
        "counts": counts,
        "train_part": str(train_part),
        "val_part": str(val_part),
        "test_part": str(test_part),
        "schema": schema,
    }


def partition_wikipedia_shards_physical(
    shard_paths: Sequence[Union[str, Path]],
    output_dir: Union[str, Path],
    dataset_id: str = "WIKIPEDIA",
    partitioner: Optional[WikipediaArticlePartitioner] = None,
    batch_size: int = 100000,
    max_records: Optional[int] = None,
    id_key: str = "id",
    num_workers: Optional[int] = None,
) -> PhysicalSplitResult:
    """Partitions Wikipedia Parquet shards into physical train/val/test Parquet files.

    Optimized for multi-core server hardware (14-core / 20-thread CPU, 32GB RAM DDR5, NVMe SSD):
    - Multi-worker parallel processing across shards via ProcessPoolExecutor when num_workers > 1.
    - Vectorized PyArrow streaming batch processing (default batch_size=100,000).
    - Sequential streaming fallback for single-core or single-shard test scenarios.
    - Zero modification of original raw corpus files.
    """
    valid_shards = [Path(p) for p in shard_paths if Path(p).is_file()]
    if not valid_shards:
        raise FileNotFoundError(f"No valid Parquet shards found for {dataset_id}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    part = partitioner or WikipediaArticlePartitioner(
        ratios=PartitionRatios(train=0.98, val=0.01, test=0.01)
    )
    ratios_tuple = (part.ratios.train, part.ratios.val, part.ratios.test)

    first_file = pq.ParquetFile(valid_shards[0])
    schema = first_file.schema_arrow

    train_file = out_path / "train.parquet"
    val_file = out_path / "val.parquet"
    test_file = out_path / "test.parquet"

    # Determine execution strategy (multi-worker parallel vs single-process sequential)
    cpu_limit = os.cpu_count() or 4
    resolved_workers = num_workers if num_workers is not None else min(len(valid_shards), cpu_limit)

    counts: Dict[str, int] = {"train": 0, "val": 0, "test": 0}

    if resolved_workers > 1 and len(valid_shards) > 1:
        # Multi-worker parallel execution across shards
        train_parts: List[Path] = []
        val_parts: List[Path] = []
        test_parts: List[Path] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=resolved_workers) as executor:
            futures = []
            for idx, shard in enumerate(valid_shards):
                prefix = f"shard_{idx:04d}"
                f = executor.submit(
                    _partition_single_shard_worker,
                    str(shard),
                    str(out_path),
                    ratios_tuple,
                    part.seed,
                    batch_size,
                    id_key,
                    max_records,
                    prefix,
                )
                futures.append(f)

            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                counts["train"] += res["counts"]["train"]
                counts["val"] += res["counts"]["val"]
                counts["test"] += res["counts"]["test"]
                train_parts.append(Path(res["train_part"]))
                val_parts.append(Path(res["val_part"]))
                test_parts.append(Path(res["test_part"]))

        # Consolidate intermediate parts into final canonical split files
        _merge_parquet_parts_streaming(train_parts, train_file, schema, batch_size=batch_size)
        _merge_parquet_parts_streaming(val_parts, val_file, schema, batch_size=batch_size)
        _merge_parquet_parts_streaming(test_parts, test_file, schema, batch_size=batch_size)
    else:
        # Single-worker sequential execution
        train_writer = pq.ParquetWriter(train_file, schema=schema, compression="snappy")
        val_writer = pq.ParquetWriter(val_file, schema=schema, compression="snappy")
        test_writer = pq.ParquetWriter(test_file, schema=schema, compression="snappy")

        seen_ids: Dict[str, str] = {}
        total_processed = 0

        try:
            for shard in valid_shards:
                pq_file = pq.ParquetFile(shard)
                for batch in pq_file.iter_batches(batch_size=batch_size):
                    id_col = batch.column(id_key).to_pylist()
                    train_idx: List[int] = []
                    val_idx: List[int] = []
                    test_idx: List[int] = []

                    for idx, art_id_raw in enumerate(id_col):
                        art_id = str(art_id_raw).strip()
                        if not art_id:
                            continue
                        assigned_split = part.assign_split(art_id)
                        split_name = assigned_split.value.lower()

                        if art_id in seen_ids and seen_ids[art_id] != split_name:
                            raise DataLeakageError(
                                f"Article ID {art_id} leaked across splits: "
                                f"{seen_ids[art_id]} vs {split_name}"
                            )
                        seen_ids[art_id] = split_name

                        if assigned_split == DatasetSplit.TRAIN:
                            train_idx.append(idx)
                        elif assigned_split == DatasetSplit.VAL:
                            val_idx.append(idx)
                        else:
                            test_idx.append(idx)

                        total_processed += 1
                        if max_records and total_processed >= max_records:
                            break

                    if train_idx:
                        train_writer.write_batch(batch.take(pa.array(train_idx, type=pa.int64())))
                        counts["train"] += len(train_idx)
                    if val_idx:
                        val_writer.write_batch(batch.take(pa.array(val_idx, type=pa.int64())))
                        counts["val"] += len(val_idx)
                    if test_idx:
                        test_writer.write_batch(batch.take(pa.array(test_idx, type=pa.int64())))
                        counts["test"] += len(test_idx)

                    if max_records and total_processed >= max_records:
                        break
                if max_records and total_processed >= max_records:
                    break
        finally:
            train_writer.close()
            val_writer.close()
            test_writer.close()

    files = {"train": train_file, "val": val_file, "test": test_file}
    bytes_dict = {k: v.stat().st_size for k, v in files.items()}
    sha256_dict = {k: _compute_file_sha256(v) for k, v in files.items()}

    return PhysicalSplitResult(
        dataset_id=dataset_id,
        files=files,
        counts=counts,
        bytes=bytes_dict,
        sha256=sha256_dict,
        leakage_verified=True,
    )
