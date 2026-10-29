"""Connected-component partitioning of paraphrase pairs (Quora)."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.corpus.partition import _DisjointSetUnion
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256
from laris.corpus.splits.ratios import PartitionRatios


class QuestionPairGraphPartitioner:
    """Connected-component graph partitioner for pairwise semantic equivalence (Quora/PAWS).

    Constructs a graph where questions are nodes and evaluated pairs are edges.
    Assigns connected components to splits using Disjoint Set Union (DSU) to guarantee
    that no question in a TRAIN pair ever appears in VAL or TEST pairs (leakage prevention).
    """

    def __init__(
        self,
        ratios: Optional[PartitionRatios] = None,
        seed: str = "laris-question-pair-graph-seed-v1",
    ) -> None:
        self.ratios = ratios or PartitionRatios(train=0.80, val=0.10, test=0.10)
        if not seed:
            raise ValueError("Partition seed must not be empty")
        self.seed = seed

    def _assign_component_split(self, component_root: str) -> DatasetSplit:
        """Deterministically maps a component root to a DatasetSplit via hash bucketing."""
        hash_input = f"{self.seed}::{component_root}".encode("utf-8")
        hex_digest = hashlib.sha256(hash_input).hexdigest()
        bucket = int(hex_digest[:8], 16) / 0xFFFFFFFF

        if bucket < self.ratios.train:
            return DatasetSplit.TRAIN
        if bucket < self.ratios.train + self.ratios.val:
            return DatasetSplit.VAL
        return DatasetSplit.TEST

    def partition_pairs(
        self,
        pairs: Iterable[Dict[str, Any]],
        q1_key: str = "question1",
        q2_key: str = "question2",
        id_key: Optional[str] = "id",
    ) -> Dict[DatasetSplit, List[Dict[str, Any]]]:
        """Partitions question pairs by connected component to isolate questions across splits."""
        pair_list = list(pairs)
        if not pair_list:
            return {
                DatasetSplit.TRAIN: [],
                DatasetSplit.VAL: [],
                DatasetSplit.TEST: [],
            }

        # 1. Build connected components using DSU
        dsu = _DisjointSetUnion()
        for pair in pair_list:
            q1 = str(pair.get(q1_key, "")).strip().lower()
            q2 = str(pair.get(q2_key, "")).strip().lower()
            if not q1 or not q2:
                raise ModuleContractViolationError(f"Pair missing questions: {pair}")
            dsu.find(q1)
            dsu.find(q2)
            dsu.union(q1, q2)

        # 2. Assign split per component root
        root_to_split: Dict[str, DatasetSplit] = {}
        splits: Dict[DatasetSplit, List[Dict[str, Any]]] = {
            DatasetSplit.TRAIN: [],
            DatasetSplit.VAL: [],
            DatasetSplit.TEST: [],
        }

        seen_questions: Dict[str, DatasetSplit] = {}

        for pair in pair_list:
            q1 = str(pair.get(q1_key, "")).strip().lower()
            root = dsu.find(q1)

            if root not in root_to_split:
                root_to_split[root] = self._assign_component_split(root)

            assigned_split = root_to_split[root]

            # Verify no question crosses split boundaries
            for q in (q1, str(pair.get(q2_key, "")).strip().lower()):
                if q in seen_questions and seen_questions[q] != assigned_split:
                    raise DataLeakageError(
                        f"Question '{q}' leaked across splits: "
                        f"{seen_questions[q].value} and {assigned_split.value}"
                    )
                seen_questions[q] = assigned_split

            pair_copy = dict(pair)
            pair_copy["assigned_split"] = assigned_split.value
            splits[assigned_split].append(pair_copy)

        return splits


def partition_quora_dataset_physical(
    raw_file_path: Union[str, Path],
    output_dir: Union[str, Path],
    partitioner: Optional[QuestionPairGraphPartitioner] = None,
    batch_size: int = 50000,
    max_records: Optional[int] = None,
    q1_key: str = "sentence1",
    q2_key: str = "sentence2",
) -> PhysicalSplitResult:
    """Partitions Quora Question Pairs into physical train/val/test Parquet files via DSU."""
    raw_file = Path(raw_file_path)
    if not raw_file.is_file():
        raise FileNotFoundError(f"Quora raw file not found: {raw_file}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    part = partitioner or QuestionPairGraphPartitioner(
        ratios=PartitionRatios(train=0.80, val=0.10, test=0.10)
    )

    # 1. Build connected components graph across question pairs
    table_strings = pq.read_table(raw_file, columns=[q1_key, q2_key])
    q1_list = table_strings.column(q1_key).to_pylist()
    q2_list = table_strings.column(q2_key).to_pylist()

    dsu = _DisjointSetUnion()
    for q1_raw, q2_raw in zip(q1_list, q2_list):
        q1 = str(q1_raw).strip().lower()
        q2 = str(q2_raw).strip().lower()
        if q1 and q2:
            dsu.find(q1)
            dsu.find(q2)
            dsu.union(q1, q2)

    root_to_split: Dict[str, DatasetSplit] = {}
    for elem in list(dsu.parent.keys()):
        root = dsu.find(elem)
        if root not in root_to_split:
            root_to_split[root] = part._assign_component_split(root)

    # 2. Stream and write physical Parquet splits
    pq_file = pq.ParquetFile(raw_file)
    schema = pq_file.schema_arrow

    train_file = out_path / "train.parquet"
    val_file = out_path / "val.parquet"
    test_file = out_path / "test.parquet"

    train_writer = pq.ParquetWriter(train_file, schema=schema, compression="snappy")
    val_writer = pq.ParquetWriter(val_file, schema=schema, compression="snappy")
    test_writer = pq.ParquetWriter(test_file, schema=schema, compression="snappy")

    counts: Dict[str, int] = {"train": 0, "val": 0, "test": 0}
    seen_q: Dict[str, DatasetSplit] = {}
    total_processed = 0

    try:
        for batch in pq_file.iter_batches(batch_size=batch_size):
            q1_batch = batch.column(q1_key).to_pylist()
            q2_batch = batch.column(q2_key).to_pylist()

            train_idx: List[int] = []
            val_idx: List[int] = []
            test_idx: List[int] = []

            for idx, (q1_raw, q2_raw) in enumerate(zip(q1_batch, q2_batch)):
                q1 = str(q1_raw).strip().lower()
                q2 = str(q2_raw).strip().lower()
                if not q1 or not q2:
                    continue  # a pair with an empty question is not a real example
                root = dsu.find(q1)
                assigned_split = root_to_split.get(root, DatasetSplit.TRAIN)

                for q in (q1, q2):
                    if q:
                        if q in seen_q and seen_q[q] != assigned_split:
                            raise DataLeakageError(
                                f"Question '{q}' leaked across splits in Quora partitioning"
                            )
                        seen_q[q] = assigned_split

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
    finally:
        train_writer.close()
        val_writer.close()
        test_writer.close()

    files = {"train": train_file, "val": val_file, "test": test_file}
    bytes_dict = {k: v.stat().st_size for k, v in files.items()}
    sha256_dict = {k: _compute_file_sha256(v) for k, v in files.items()}

    return PhysicalSplitResult(
        dataset_id="QUORA-DUPLICATES",
        files=files,
        counts=counts,
        bytes=bytes_dict,
        sha256=sha256_dict,
        leakage_verified=True,
    )
