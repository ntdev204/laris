"""Unit tests for Layer 0 split manifest integrity and leakage prevention.

Addresses Issue #80 (M1-DATA-004-SUB-02, Refs #15).
Validates:
- SplitManifest generation and cryptographic fingerprint immutability
- Large author group policy enforcement (FORCE_TO_TRAIN, REJECT, ALLOW)
- Stress testing of complex co-authorship networks with 0% leakage
- Deterministic seed reproducibility across multi-split partitions
"""

import unittest

from laris.core.errors import DataLeakageError
from laris.layers.layer0_corpus.partition import (
    DEFAULT_PARTITION_SEED,
    DatasetPartitionEngine,
    LargeGroupPolicy,
    SplitManifest,
    SplitRatios,
    compute_split_fingerprint,
    verify_split_leakage,
)
from laris.layers.layer0_corpus.schemas import (
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


class TestSplitManifestIntegrity(unittest.TestCase):
    """Test suite for split manifest generation, cryptographic hashing, and integrity."""

    def setUp(self) -> None:
        self.sample_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2401.00001",
            verified_by="test-agent",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )
        self.engine = DatasetPartitionEngine(
            ratios=SplitRatios(train=0.80, val=0.10, test=0.10),
            seed=DEFAULT_PARTITION_SEED,
        )

    def _make_item(self, corpus_id: str, text: str) -> ValidatedCorpusItem:
        return ValidatedCorpusItem(
            corpus_id=corpus_id,
            clean_text=text,
            sha256=f"{abs(hash(corpus_id + text)):064x}"[:64],
            split=DatasetSplit.TRAIN,
            license_provenance=self.sample_provenance,
            byte_length=len(text.encode("utf-8")),
        )

    def test_compute_split_fingerprint_deterministic_and_tamper_evident(self) -> None:
        """compute_split_fingerprint must be order-invariant but sensitive to any content change."""
        item1 = self._make_item("doc-1", "Text 1")
        item2 = self._make_item("doc-2", "Text 2")

        # Order invariance
        fp_12 = compute_split_fingerprint([item1, item2])
        fp_21 = compute_split_fingerprint([item2, item1])
        self.assertEqual(fp_12, fp_21)
        self.assertEqual(len(fp_12), 64)

        # Content tampering detection
        tampered_item2 = self._make_item("doc-2", "Text 2 tampered")
        fp_tampered = compute_split_fingerprint([item1, tampered_item2])
        self.assertNotEqual(fp_12, fp_tampered)

    def test_generate_manifest_fields_and_invariants(self) -> None:
        """generate_manifest must accurately summarize split distributions and fingerprints."""
        item_train = self._make_item("train-1", "Train content")
        item_val = self._make_item("val-1", "Validation content")
        item_test = self._make_item("test-1", "Test content")

        partitioned = {
            DatasetSplit.TRAIN: [item_train],
            DatasetSplit.VAL: [item_val],
            DatasetSplit.TEST: [item_test],
        }

        manifest = self.engine.generate_manifest(
            partitioned,
            author_group_count=3,
            manifest_id="split-manifest-test-01",
            created_at="2026-10-15T12:00:00Z",
        )

        self.assertIsInstance(manifest, SplitManifest)
        self.assertEqual(manifest.manifest_id, "split-manifest-test-01")
        self.assertEqual(manifest.seed, DEFAULT_PARTITION_SEED)
        self.assertEqual(manifest.total_items, 3)
        self.assertEqual(manifest.split_counts["TRAIN"], 1)
        self.assertEqual(manifest.split_counts["VAL"], 1)
        self.assertEqual(manifest.split_counts["TEST"], 1)
        self.assertEqual(manifest.author_group_count, 3)
        self.assertEqual(
            manifest.total_bytes,
            item_train.byte_length + item_val.byte_length + item_test.byte_length,
        )

        # Check cryptographic fingerprints are present for all three splits
        for split_key in ("TRAIN", "VAL", "TEST"):
            self.assertEqual(len(manifest.split_sha256_digests[split_key]), 64)

    def test_large_group_force_to_train(self) -> None:
        """Large groups exceeding max_group_fraction must be routed to TRAIN
        under FORCE_TO_TRAIN.
        """
        engine = DatasetPartitionEngine(
            ratios=SplitRatios(train=0.50, val=0.25, test=0.25),
            large_group_policy=LargeGroupPolicy.FORCE_TO_TRAIN,
            max_group_fraction=0.30,
        )

        # 4 items belonging to BigLab (40% of 10 items > 30% threshold)
        items = [self._make_item(f"doc-biglab-{i}", f"BigLab Paper {i}") for i in range(4)]
        # 6 items belonging to individual authors
        items.extend([self._make_item(f"doc-solo-{i}", f"Solo Paper {i}") for i in range(6)])

        author_map = {f"doc-biglab-{i}": ["BigLab Lead"] for i in range(4)}
        for i in range(6):
            author_map[f"doc-solo-{i}"] = [f"Solo Author {i}"]

        partitioned = engine.partition_items(items, author_map=author_map)

        # All BigLab items must be safely in TRAIN
        train_ids = [item.corpus_id for item in partitioned[DatasetSplit.TRAIN]]
        for i in range(4):
            self.assertIn(f"doc-biglab-{i}", train_ids)

        self.assertTrue(verify_split_leakage(partitioned, author_map=author_map))

    def test_large_group_reject_raises_leakage_error(self) -> None:
        """Large groups exceeding max_group_fraction must raise DataLeakageError under REJECT."""
        engine = DatasetPartitionEngine(
            large_group_policy=LargeGroupPolicy.REJECT,
            max_group_fraction=0.30,
        )
        items = [self._make_item(f"doc-{i}", f"Paper {i}") for i in range(5)]
        # All 5 items belong to one author (100% > 30%)
        author_map = {f"doc-{i}": ["Monopoly Author"] for i in range(5)}

        with self.assertRaises(DataLeakageError) as ctx:
            engine.partition_items(items, author_map=author_map)
        self.assertIn("Monopoly Author", str(ctx.exception))
        self.assertIn("exceeding max allowable fraction", str(ctx.exception))

    def test_complex_coauthorship_stress_leakage_test(self) -> None:
        """A network of 100 documents across 20 distinct author clusters must have 0% leakage."""
        items = []
        author_map = {}

        # 20 clusters of 5 papers each
        for cluster_id in range(20):
            author_a = f"Cluster{cluster_id}_AuthorA"
            author_b = f"Cluster{cluster_id}_AuthorB"
            for doc_idx in range(5):
                cid = f"doc-c{cluster_id}-d{doc_idx}"
                items.append(self._make_item(cid, f"Content for {cid}"))
                author_map[cid] = [author_a, author_b]

        partitioned = self.engine.partition_items(items, author_map=author_map)

        # Total item integrity
        total_partitioned = sum(len(split_items) for split_items in partitioned.values())
        self.assertEqual(total_partitioned, 100)

        # Strict leakage verification
        self.assertTrue(verify_split_leakage(partitioned, author_map=author_map))

        # Check every cluster landed entirely within a single split
        for cluster_id in range(20):
            cluster_cids = {f"doc-c{cluster_id}-d{doc_idx}" for doc_idx in range(5)}
            splits_for_cluster = set()
            for split, split_items in partitioned.items():
                if any(i.corpus_id in cluster_cids for i in split_items):
                    splits_for_cluster.add(split)
            self.assertEqual(
                len(splits_for_cluster),
                1,
                f"Cluster {cluster_id} leaked across splits: {splits_for_cluster}",
            )

    def test_reproducible_seed_behavior(self) -> None:
        """Identical inputs with identical seed must yield identical split manifests."""
        items = [self._make_item(f"doc-{i}", f"Content {i}") for i in range(15)]
        author_map = {f"doc-{i}": [f"Author {i}"] for i in range(15)}

        engine1 = DatasetPartitionEngine(seed="seed-alpha-123")
        engine2 = DatasetPartitionEngine(seed="seed-alpha-123")
        engine_diff = DatasetPartitionEngine(seed="seed-beta-456")

        part1 = engine1.partition_items(items, author_map=author_map)
        part2 = engine2.partition_items(items, author_map=author_map)
        part_diff = engine_diff.partition_items(items, author_map=author_map)

        # Manifests from engine1 and engine2 must be byte-for-byte identical
        m1 = engine1.generate_manifest(part1)
        m2 = engine2.generate_manifest(part2)
        self.assertEqual(m1, m2)

        # Different seed must yield distinct split distributions
        m_diff = engine_diff.generate_manifest(part_diff)
        self.assertNotEqual(m1.seed, m_diff.seed)


if __name__ == "__main__":
    unittest.main()
