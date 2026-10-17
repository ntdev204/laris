"""Task-specific leakage-proof dataset partitioning and validation engine.

Adheres to DOC-SPEC-MOD-001, ADR-001, ADR-003, and Issue #217 (WP2).
Provides:
- Deterministic hash-partitioning for unpartitioned document dumps (Wikipedia EN/VI)
- Connected-component graph partitioning for pairwise semantic equivalence (Quora)
- Title/context-grouped isolation for reading comprehension (SQuAD / ViQuAD)
- Zero-leakage cross-split verification and data quality validation
- Strict non-destructive transformations preserving original raw corpus artifacts
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.corpus.partition import _DisjointSetUnion
from laris.corpus.schemas import DatasetSplit


@dataclass(frozen=True)
class PartitionRatios:
    """Configurable target distribution ratios for dataset splits."""

    train: float = 0.80
    val: float = 0.10
    test: float = 0.10

    def __post_init__(self) -> None:
        if self.train <= 0.0 or self.val <= 0.0 or self.test <= 0.0:
            raise ValueError("All partition ratios must be strictly positive")
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-5:
            raise ValueError(f"Partition ratios must sum to 1.0, got {total:.6f}")


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


def validate_split_isolation(
    splits: Dict[DatasetSplit, List[Dict[str, Any]]],
    item_id_key: str = "id",
    content_hash_key: Optional[str] = None,
) -> bool:
    """Verifies that zero items or content digests overlap between any two splits."""
    seen_ids: Dict[str, DatasetSplit] = {}
    seen_hashes: Dict[str, DatasetSplit] = {}

    for split, items in splits.items():
        for item in items:
            item_id = str(item.get(item_id_key, "")).strip()
            if item_id:
                if item_id in seen_ids and seen_ids[item_id] != split:
                    raise DataLeakageError(
                        f"Item ID '{item_id}' leaked across splits: "
                        f"{seen_ids[item_id].value} and {split.value}"
                    )
                seen_ids[item_id] = split

            if content_hash_key and content_hash_key in item:
                h = str(item[content_hash_key]).strip()
                if h:
                    if h in seen_hashes and seen_hashes[h] != split:
                        raise DataLeakageError(
                            f"Content hash '{h}' leaked across splits: "
                            f"{seen_hashes[h].value} and {split.value}"
                        )
                    seen_hashes[h] = split

    return True


def validate_record_quality(record: Dict[str, Any], required_fields: List[str]) -> bool:
    """Validates that a dataset record is non-empty, well-formed, and contains required fields."""
    for field_name in required_fields:
        if field_name not in record:
            raise ModuleContractViolationError(f"Missing required field: '{field_name}'")
        val = record[field_name]
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ModuleContractViolationError(
                f"Field '{field_name}' has empty or whitespace-only value"
            )
    return True
