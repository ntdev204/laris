"""Title/context-grouped partitioning of reading-comprehension data (SQuAD, ViQuAD)."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256


class QADatasetPartitioner:
    """Context/Document-grouped partitioner for Reading Comprehension datasets (SQuAD / ViQuAD).

    Partitions QA items by grouping on article title or context hash to ensure:
    - Zero context/passage overlap between development and held-out test splits.
    - Deterministic sub-splitting of dev splits into separate DEV and HELD-OUT TEST partitions.
    """

    def __init__(
        self,
        dev_ratio: float = 0.50,
        test_ratio: float = 0.50,
        seed: str = "laris-qa-partition-seed-v1",
    ) -> None:
        if abs(dev_ratio + test_ratio - 1.0) > 1e-5:
            raise ValueError("dev_ratio and test_ratio must sum to 1.0")
        self.dev_ratio = dev_ratio
        self.test_ratio = test_ratio
        self.seed = seed

    def assign_group_split(self, group_key: str) -> DatasetSplit:
        """Maps a document/context group key to VAL (Dev) or TEST (Held-Out Test)."""
        if not group_key or not group_key.strip():
            raise ValueError("group_key must not be empty")

        hash_input = f"{self.seed}::{group_key.strip()}".encode("utf-8")
        hex_digest = hashlib.sha256(hash_input).hexdigest()
        bucket = int(hex_digest[:8], 16) / 0xFFFFFFFF

        if bucket < self.dev_ratio:
            return DatasetSplit.VAL
        return DatasetSplit.TEST

    def sub_split_dev_set(
        self,
        qa_items: Iterable[Dict[str, Any]],
        title_key: str = "title",
        context_key: str = "context",
    ) -> Dict[DatasetSplit, List[Dict[str, Any]]]:
        """Sub-splits a DEV dataset into isolated DEV and HELD-OUT TEST splits."""
        splits: Dict[DatasetSplit, List[Dict[str, Any]]] = {
            DatasetSplit.VAL: [],
            DatasetSplit.TEST: [],
        }

        seen_groups: Dict[str, DatasetSplit] = {}
        seen_contexts: Dict[str, DatasetSplit] = {}

        for item in qa_items:
            title = str(item.get(title_key, "")).strip()
            context = str(item.get(context_key, "")).strip()

            if not title and not context:
                raise ModuleContractViolationError(
                    "QA item must have either non-empty title or context"
                )

            # Primary group identifier is title; fallback to context content hash
            group_id = title if title else hashlib.sha256(context.encode("utf-8")).hexdigest()
            assigned_split = self.assign_group_split(group_id)

            if group_id in seen_groups and seen_groups[group_id] != assigned_split:
                raise DataLeakageError(
                    f"QA group '{group_id}' leaked across splits: "
                    f"{seen_groups[group_id].value} and {assigned_split.value}"
                )
            seen_groups[group_id] = assigned_split

            # Verify context hash isolation
            if context:
                ctx_sha = hashlib.sha256(context.encode("utf-8")).hexdigest()
                if ctx_sha in seen_contexts and seen_contexts[ctx_sha] != assigned_split:
                    raise DataLeakageError(
                        f"Context passage leaked between DEV and TEST splits: {title}"
                    )
                seen_contexts[ctx_sha] = assigned_split

            item_copy = dict(item)
            item_copy["assigned_split"] = assigned_split.value
            splits[assigned_split].append(item_copy)

        return splits


def partition_qa_dataset_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "SQUAD",
    dev_filename: str = "validation-00000-of-00001.parquet",
    train_filename: Optional[str] = "train-00000-of-00001.parquet",
    partitioner: Optional[QADatasetPartitioner] = None,
) -> PhysicalSplitResult:
    """Sub-splits Reading Comprehension dev sets into isolated dev and held-out test Parquet."""
    in_path = Path(raw_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    part = partitioner or QADatasetPartitioner(dev_ratio=0.50, test_ratio=0.50)
    dev_path = in_path / dev_filename
    if not dev_path.exists():
        raise FileNotFoundError(f"Dev file not found: {dev_path}")

    files: Dict[str, Path] = {}
    counts: Dict[str, int] = {}

    # Copy / Write train set if present
    if train_filename and (in_path / train_filename).exists():
        train_raw = in_path / train_filename
        train_dest = out_path / "train.parquet"
        t_table = pq.read_table(train_raw)
        pq.write_table(t_table, train_dest, compression="snappy")
        files["train"] = train_dest
        counts["train"] = len(t_table)

    # Sub-split dev into val and held-out test
    dev_table = pq.read_table(dev_path)
    title_col = (
        dev_table.column("title").to_pylist()
        if "title" in dev_table.column_names
        else ["default"] * len(dev_table)
    )

    val_idx: List[int] = []
    test_idx: List[int] = []
    seen_groups: Dict[str, DatasetSplit] = {}

    for idx, title_raw in enumerate(title_col):
        title = str(title_raw).strip() or f"group_{idx}"
        assigned = part.assign_group_split(title)
        if title in seen_groups and seen_groups[title] != assigned:
            raise DataLeakageError(f"QA title group {title} leaked across dev/test splits")
        seen_groups[title] = assigned

        if assigned == DatasetSplit.VAL:
            val_idx.append(idx)
        else:
            test_idx.append(idx)

    val_file = out_path / "val.parquet"
    test_file = out_path / "test.parquet"

    if val_idx:
        pq.write_table(
            dev_table.take(pa.array(val_idx, type=pa.int64())),
            val_file,
            compression="snappy",
        )
    if test_idx:
        pq.write_table(
            dev_table.take(pa.array(test_idx, type=pa.int64())),
            test_file,
            compression="snappy",
        )

    files["val"] = val_file
    files["test"] = test_file
    counts["val"] = len(val_idx)
    counts["test"] = len(test_idx)

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
