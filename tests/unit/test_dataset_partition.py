"""Unit tests for Layer 0 grouped deterministic dataset partition engine.

Addresses Issue #48 (M1-DATA-004-SUB-01, Refs #15).
Validates:
- SplitRatios validation (positive values, summing to 1.0)
- Deterministic group-to-split hash bucketing
- Author co-authorship connected component clustering
- Strict zero-leakage invariant verification across splits
- Missing author policies (DOCUMENT_AS_GROUP, ISOLATE_TO_TRAIN, REJECT)
- Empty, singleton, and chained co-authorship edge cases
"""

import unittest

from laris.core.errors import DataLeakageError
from laris.layers.layer0_corpus.partition import (
    DEFAULT_PARTITION_SEED,
    PARTITION_ALGORITHM,
    PARTITION_SPEC_VERSION,
    DatasetPartitionEngine,
    MissingAuthorPolicy,
    SplitRatios,
    verify_split_leakage,
)
from laris.layers.layer0_corpus.schemas import (
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


class TestSplitRatiosAndConstants(unittest.TestCase):
    """Test suite for SplitRatios configuration and algorithm metadata."""

    def test_partition_constants(self) -> None:
        """Explicit algorithm and contract version constants must be defined."""
        self.assertEqual(PARTITION_ALGORITHM, "HASH-BUCKET-GROUPED")
        self.assertEqual(PARTITION_SPEC_VERSION, "1.0")
        self.assertEqual(DEFAULT_PARTITION_SEED, "laris-partition-seed-v1")

    def test_valid_split_ratios(self) -> None:
        """Valid ratios summing to 1.0 must instantiate cleanly."""
        ratios = SplitRatios(train=0.8, val=0.1, test=0.1)
        self.assertEqual(ratios.train, 0.8)
        self.assertEqual(ratios.val, 0.1)
        self.assertEqual(ratios.test, 0.1)

    def test_invalid_split_ratios(self) -> None:
        """Ratios with non-positive values or not summing to 1.0 must be rejected."""
        with self.assertRaises(ValueError):
            SplitRatios(train=0.0, val=0.5, test=0.5)
        with self.assertRaises(ValueError):
            SplitRatios(train=-0.1, val=0.6, test=0.5)
        with self.assertRaises(ValueError):
            SplitRatios(train=0.7, val=0.1, test=0.1)  # Sums to 0.9


class TestDatasetPartitionEngine(unittest.TestCase):
    """Test suite for DatasetPartitionEngine assignment, grouping, and leakage prevention."""

    def setUp(self) -> None:
        self.engine = DatasetPartitionEngine(
            ratios=SplitRatios(train=0.70, val=0.15, test=0.15),
            seed="test-seed-42",
        )
        self.sample_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2401.00001",
            verified_by="test-agent",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )

    def _make_item(self, corpus_id: str, content: str) -> ValidatedCorpusItem:
        return ValidatedCorpusItem(
            corpus_id=corpus_id,
            clean_text=content,
            sha256=f"{abs(hash(corpus_id)):064x}"[:64],
            split=DatasetSplit.TRAIN,
            license_provenance=self.sample_provenance,
            byte_length=len(content.encode("utf-8")),
        )

    def test_assign_split_determinism(self) -> None:
        """assign_split must deterministically map a group ID to a split."""
        split1 = self.engine.assign_split("author::Alice")
        split2 = self.engine.assign_split("author::Alice")
        self.assertEqual(split1, split2)
        self.assertIn(split1, (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST))

        with self.assertRaises(ValueError):
            self.engine.assign_split("")

    def test_coauthor_chain_clustered_to_same_split(self) -> None:
        """Papers linked via co-authorship chains must be assigned to the exact same split."""
        # Paper 1: Alice, Bob
        # Paper 2: Bob, Charlie
        # Paper 3: Charlie, David
        item1 = self._make_item("p1", "Article 1 on quantum error correction.")
        item2 = self._make_item("p2", "Article 2 on topological surface codes.")
        item3 = self._make_item("p3", "Article 3 on syndrome measurement protocols.")

        author_map = {
            "p1": ["Alice Smith", "Bob Jones"],
            "p2": ["Bob Jones", "Charlie Brown"],
            "p3": ["Charlie Brown", "David Lee"],
        }

        partitioned = self.engine.partition_items([item1, item2, item3], author_map=author_map)

        # Locate which split p1 landed in
        target_split = None
        for split, items in partitioned.items():
            if any(i.corpus_id == "p1" for i in items):
                target_split = split
                break

        self.assertIsNotNone(target_split)
        assigned_ids = [i.corpus_id for i in partitioned[target_split]]  # type: ignore[index]
        self.assertIn("p1", assigned_ids)
        self.assertIn("p2", assigned_ids)
        self.assertIn("p3", assigned_ids)

        # Verify zero leakage
        self.assertTrue(verify_split_leakage(partitioned, author_map=author_map))

    def test_missing_author_policy_document_as_group(self) -> None:
        """DOCUMENT_AS_GROUP treats papers lacking author metadata as unique singleton groups."""
        engine = DatasetPartitionEngine(
            missing_author_policy=MissingAuthorPolicy.DOCUMENT_AS_GROUP
        )
        item1 = self._make_item("doc-anon-1", "Anonymous report on laboratory protocols.")
        item2 = self._make_item("doc-anon-2", "Corporate preprint on hardware benchmark.")

        partitioned = engine.partition_items([item1, item2], author_map={})
        total_items = sum(len(items) for items in partitioned.values())
        self.assertEqual(total_items, 2)
        self.assertTrue(verify_split_leakage(partitioned, author_map={}))

    def test_missing_author_policy_isolate_to_train(self) -> None:
        """ISOLATE_TO_TRAIN places documents without authors strictly into TRAIN split."""
        engine = DatasetPartitionEngine(
            missing_author_policy=MissingAuthorPolicy.ISOLATE_TO_TRAIN
        )
        item = self._make_item("doc-anon", "Document without explicit authors.")
        partitioned = engine.partition_items([item], author_map={})

        self.assertEqual(len(partitioned[DatasetSplit.TRAIN]), 1)
        self.assertEqual(partitioned[DatasetSplit.TRAIN][0].corpus_id, "doc-anon")
        self.assertEqual(len(partitioned[DatasetSplit.VAL]), 0)
        self.assertEqual(len(partitioned[DatasetSplit.TEST]), 0)

    def test_missing_author_policy_reject(self) -> None:
        """REJECT policy raises DataLeakageError when any document lacks author attribution."""
        engine = DatasetPartitionEngine(
            missing_author_policy=MissingAuthorPolicy.REJECT
        )
        item = self._make_item("doc-anon", "Document without authors.")

        with self.assertRaises(DataLeakageError):
            engine.partition_items([item], author_map={})

    def test_verify_split_leakage_detects_author_overlap(self) -> None:
        """verify_split_leakage must raise DataLeakageError if an author overlaps splits."""
        item1 = self._make_item("p1", "Text 1")
        item2 = self._make_item("p2", "Text 2")

        # Manually create leakage: p1 in TRAIN, p2 in TEST with shared author
        partitioned = {
            DatasetSplit.TRAIN: [item1],
            DatasetSplit.VAL: [],
            DatasetSplit.TEST: [item2],
        }
        author_map = {
            "p1": ["Shared Author"],
            "p2": ["Shared Author"],
        }

        with self.assertRaises(DataLeakageError) as ctx:
            verify_split_leakage(partitioned, author_map=author_map)
        self.assertIn("Shared Author", str(ctx.exception))
        self.assertIn("leaked across splits", str(ctx.exception))

    def test_verify_split_leakage_detects_corpus_id_overlap(self) -> None:
        """verify_split_leakage must raise DataLeakageError if a corpus_id overlaps splits."""
        item = self._make_item("dup-id", "Duplicate content")
        partitioned = {
            DatasetSplit.TRAIN: [item],
            DatasetSplit.VAL: [item],
            DatasetSplit.TEST: [],
        }

        with self.assertRaises(DataLeakageError) as ctx:
            verify_split_leakage(partitioned)
        self.assertIn("Corpus ID 'dup-id' leaked", str(ctx.exception))

    def test_empty_partition(self) -> None:
        """Empty input must produce empty splits without error."""
        partitioned = self.engine.partition_items([])
        self.assertEqual(len(partitioned[DatasetSplit.TRAIN]), 0)
        self.assertEqual(len(partitioned[DatasetSplit.VAL]), 0)
        self.assertEqual(len(partitioned[DatasetSplit.TEST]), 0)


if __name__ == "__main__":
    unittest.main()
