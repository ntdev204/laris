"""Leakage-proof dataset partition engine for Layer 0.

Adheres to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
Provides 100% deterministic, leakage-free dataset partitioning across
TRAIN, VAL, and TEST splits grouped strictly by author and document boundaries.
"""

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Iterable, List, Optional

from laris.core.errors import DataLeakageError
from laris.layers.layer0_corpus.schemas import DatasetSplit, ValidatedCorpusItem

# Explicit algorithm and contract specifications
PARTITION_ALGORITHM = "HASH-BUCKET-GROUPED"
PARTITION_SPEC_VERSION = "1.0"
DEFAULT_PARTITION_SEED = "laris-partition-seed-v1"


class MissingAuthorPolicy(str, Enum):
    """Policy for handling documents lacking explicit author attribution."""

    DOCUMENT_AS_GROUP = "DOCUMENT_AS_GROUP"  # Treat document ID as unique group
    ISOLATE_TO_TRAIN = "ISOLATE_TO_TRAIN"    # Force unassigned items to TRAIN only
    REJECT = "REJECT"                        # Raise DataLeakageError on missing authors


@dataclass(frozen=True)
class SplitRatios:
    """Configurable target distribution ratios for dataset splits."""

    train: float = 0.80
    val: float = 0.10
    test: float = 0.10

    def __post_init__(self) -> None:
        if self.train <= 0.0 or self.val <= 0.0 or self.test <= 0.0:
            raise ValueError("All split ratios must be strictly positive")
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-5:
            raise ValueError(f"Split ratios must sum to 1.0, got {total:.6f}")


class _DisjointSetUnion:
    """Internal disjoint-set union (Union-Find) with path compression."""

    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        if self.parent.setdefault(x, x) != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            # Deterministic union: smaller string becomes root
            if root_x < root_y:
                self.parent[root_y] = root_x
            else:
                self.parent[root_x] = root_y


def verify_split_leakage(
    partitioned_items: Dict[DatasetSplit, List[ValidatedCorpusItem]],
    author_map: Optional[Dict[str, List[str]]] = None,
) -> bool:
    """Verifies that zero document or author overlap exists between any two splits.

    Raises:
        DataLeakageError: if any document ID, content SHA-256, or author is found
        in more than one dataset split.
    """
    seen_corpus_ids: Dict[str, DatasetSplit] = {}
    seen_sha256s: Dict[str, DatasetSplit] = {}
    seen_authors: Dict[str, DatasetSplit] = {}

    for split, items in partitioned_items.items():
        for item in items:
            # 1. Document ID uniqueness across splits
            if item.corpus_id in seen_corpus_ids:
                prior_split = seen_corpus_ids[item.corpus_id]
                if prior_split != split:
                    raise DataLeakageError(
                        f"Corpus ID '{item.corpus_id}' leaked across splits: "
                        f"{prior_split.value} and {split.value}"
                    )
            seen_corpus_ids[item.corpus_id] = split

            # 2. Content SHA-256 uniqueness across splits
            if item.sha256 in seen_sha256s:
                prior_split = seen_sha256s[item.sha256]
                if prior_split != split:
                    raise DataLeakageError(
                        f"Document content SHA-256 '{item.sha256}' leaked across splits: "
                        f"{prior_split.value} and {split.value}"
                    )
            seen_sha256s[item.sha256] = split

            # 3. Author overlap across splits
            if author_map and item.corpus_id in author_map:
                authors = author_map[item.corpus_id]
                for author in authors:
                    clean_author = author.strip()
                    if not clean_author:
                        continue
                    if clean_author in seen_authors:
                        prior_split = seen_authors[clean_author]
                        if prior_split != split:
                            raise DataLeakageError(
                                f"Author '{clean_author}' leaked across splits: "
                                f"{prior_split.value} and {split.value}"
                            )
                    seen_authors[clean_author] = split

    return True


class DatasetPartitionEngine:
    """Deterministic, leakage-proof dataset partition engine.

    Guarantees:
    - 100% reproducible split assignment given identical seed and group IDs.
    - Zero author or document leakage between TRAIN, VAL, and TEST splits.
    - Explicit missing-author handling via `MissingAuthorPolicy`.
    """

    def __init__(
        self,
        ratios: Optional[SplitRatios] = None,
        seed: str = DEFAULT_PARTITION_SEED,
        missing_author_policy: MissingAuthorPolicy = MissingAuthorPolicy.DOCUMENT_AS_GROUP,
    ) -> None:
        self.ratios = ratios or SplitRatios()
        if not seed:
            raise ValueError("Partition seed MUST NOT be empty")
        self.seed = seed
        self.missing_author_policy = missing_author_policy

    def assign_split(self, group_id: str) -> DatasetSplit:
        """Deterministically maps a group identifier to a DatasetSplit via hash bucketing."""
        if not group_id:
            raise ValueError("group_id MUST NOT be empty")

        hash_input = f"{self.seed}::{group_id}".encode("utf-8")
        hex_digest = hashlib.sha256(hash_input).hexdigest()
        # Uniform bucket in [0.0, 1.0) derived from leading 8 hex characters
        bucket = int(hex_digest[:8], 16) / 0xFFFFFFFF

        if bucket < self.ratios.train:
            return DatasetSplit.TRAIN
        if bucket < self.ratios.train + self.ratios.val:
            return DatasetSplit.VAL
        return DatasetSplit.TEST

    def partition_items(
        self,
        items: Iterable[ValidatedCorpusItem],
        author_map: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[DatasetSplit, List[ValidatedCorpusItem]]:
        """Partitions an iterable of ValidatedCorpusItems into leakage-isolated splits."""
        author_map = author_map or {}
        item_list = list(items)

        partitioned: Dict[DatasetSplit, List[ValidatedCorpusItem]] = {
            DatasetSplit.TRAIN: [],
            DatasetSplit.VAL: [],
            DatasetSplit.TEST: [],
        }

        if not item_list:
            return partitioned

        # 1. Build connected components of co-authors using DSU
        dsu = _DisjointSetUnion()
        item_group_keys: Dict[str, str] = {}

        for item in item_list:
            authors = [a.strip() for a in author_map.get(item.corpus_id, []) if a.strip()]

            if authors:
                primary = authors[0]
                dsu.find(primary)
                for co_author in authors[1:]:
                    dsu.union(primary, co_author)
                item_group_keys[item.corpus_id] = primary
            else:
                if self.missing_author_policy == MissingAuthorPolicy.DOCUMENT_AS_GROUP:
                    group_key = f"doc_group::{item.corpus_id}"
                    dsu.find(group_key)
                    item_group_keys[item.corpus_id] = group_key
                elif self.missing_author_policy == MissingAuthorPolicy.ISOLATE_TO_TRAIN:
                    item_group_keys[item.corpus_id] = "__ISOLATE_TO_TRAIN__"
                elif self.missing_author_policy == MissingAuthorPolicy.REJECT:
                    raise DataLeakageError(
                        f"Missing author metadata for corpus item '{item.corpus_id}' "
                        f"under policy REJECT"
                    )

        # 2. Assign each component to a split and populate partitioned items
        # Cache split assignment per canonical group root
        group_split_cache: Dict[str, DatasetSplit] = {}

        for item in item_list:
            group_key = item_group_keys[item.corpus_id]

            if group_key == "__ISOLATE_TO_TRAIN__":
                split = DatasetSplit.TRAIN
            else:
                canonical_root = dsu.find(group_key)
                if canonical_root not in group_split_cache:
                    group_split_cache[canonical_root] = self.assign_split(canonical_root)
                split = group_split_cache[canonical_root]

            updated_item = replace(item, split=split)
            partitioned[split].append(updated_item)

        # 3. Postcondition verification: assert zero leakage
        verify_split_leakage(partitioned, author_map=author_map)

        return partitioned
