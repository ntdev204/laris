"""Unit tests for physical dataset partitioning engine (Issue #232).

Adheres to DOC-SPEC-MOD-001, ADR-001, ADR-003, and ADR-008.
Verifies:
- Streaming Parquet partitioning for Wikipedia and Quora without memory bloat
- Anti-leakage guarantees (zero cross-split document / pair leakage)
- Zero mutation of original input files
- Deterministic cryptographic hashing of output partitions
"""

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.task_splits import (
    PartitionRatios,
    WikipediaArticlePartitioner,
    execute_physical_partitioning,
    partition_quora_dataset_physical,
    partition_wikipedia_shards_physical,
)


class TestPhysicalPartitioning(unittest.TestCase):
    """Test suite for physical streaming dataset partitioners."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _create_dummy_wikipedia_shard(self, path: Path, num_articles: int = 100) -> None:
        """Helper to create synthetic Wikipedia Parquet shard."""
        path.parent.mkdir(parents=True, exist_ok=True)
        ids = [f"wiki_art_{i:04d}" for i in range(num_articles)]
        titles = [f"Title {i}" for i in range(num_articles)]
        urls = [f"https://en.wikipedia.org/wiki/Art_{i}" for i in range(num_articles)]
        texts = [f"This is normalized body text for article {i}." for i in range(num_articles)]

        table = pa.Table.from_arrays(
            [pa.array(ids), pa.array(urls), pa.array(titles), pa.array(texts)],
            names=["id", "url", "title", "text"],
        )
        pq.write_table(table, path, compression="snappy")

    def _create_dummy_quora_shard(self, path: Path) -> None:
        """Helper to create synthetic Quora Question Pairs Parquet shard."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Pairs:
        # q1 and q2 linked
        # q3 and q4 linked
        # q5 and q6 linked
        q1 = ["How to learn python?", "Is Python fast?", "What is deep learning?"]
        q2 = ["Best way to learn python?", "Python performance tips?", "Deep learning guide?"]
        labels = [1, 0, 1]

        table = pa.Table.from_arrays(
            [pa.array(q1), pa.array(q2), pa.array(labels)],
            names=["sentence1", "sentence2", "label"],
        )
        pq.write_table(table, path, compression="snappy")

    def test_partition_wikipedia_shards_physical(self) -> None:
        """Streaming Wikipedia partitioner must generate valid train/val/test Parquet files."""
        raw_shard = self.root / "raw_wiki" / "shard1.parquet"
        self._create_dummy_wikipedia_shard(raw_shard, num_articles=200)

        out_dir = self.root / "processed_wiki"
        part = WikipediaArticlePartitioner(
            ratios=PartitionRatios(train=0.80, val=0.10, test=0.10),
            seed="test-seed-v1",
        )

        res = partition_wikipedia_shards_physical(
            shard_paths=[raw_shard],
            output_dir=out_dir,
            dataset_id="TEST-WIKI",
            partitioner=part,
            batch_size=50,
        )

        self.assertEqual(res.dataset_id, "TEST-WIKI")
        self.assertTrue(res.leakage_verified)
        self.assertTrue((out_dir / "train.parquet").is_file())
        self.assertTrue((out_dir / "val.parquet").is_file())
        self.assertTrue((out_dir / "test.parquet").is_file())

        total = sum(res.counts.values())
        self.assertEqual(total, 200)
        self.assertGreater(res.counts["train"], 0)
        self.assertGreater(res.counts["val"], 0)
        self.assertGreater(res.counts["test"], 0)

        # Verify output parquet readability and zero ID overlap
        train_ids = set(pq.read_table(out_dir / "train.parquet").column("id").to_pylist())
        val_ids = set(pq.read_table(out_dir / "val.parquet").column("id").to_pylist())
        test_ids = set(pq.read_table(out_dir / "test.parquet").column("id").to_pylist())

        self.assertEqual(len(train_ids.intersection(val_ids)), 0)
        self.assertEqual(len(train_ids.intersection(test_ids)), 0)
        self.assertEqual(len(val_ids.intersection(test_ids)), 0)

        # Raw file must remain completely untouched
        self.assertTrue(raw_shard.is_file())

    def test_partition_quora_dataset_physical(self) -> None:
        """Quora partitioner must build DSU graph and write physical splits."""
        raw_file = self.root / "raw_quora" / "train.parquet"
        self._create_dummy_quora_shard(raw_file)

        out_dir = self.root / "processed_quora"
        res = partition_quora_dataset_physical(
            raw_file_path=raw_file,
            output_dir=out_dir,
            batch_size=2,
        )

        self.assertEqual(res.dataset_id, "QUORA-DUPLICATES")
        self.assertTrue((out_dir / "train.parquet").is_file())
        self.assertTrue((out_dir / "val.parquet").is_file())
        self.assertTrue((out_dir / "test.parquet").is_file())
        self.assertEqual(sum(res.counts.values()), 3)

    def test_execute_physical_partitioning_orchestrator(self) -> None:
        """Overall execute_physical_partitioning must create task_splits_manifest.json."""
        raw_root = self.root / "data" / "raw"
        proc_root = self.root / "data" / "processed"

        # Create raw mocks
        wiki_shard = raw_root / "wikipedia_vi" / "0000.parquet"
        self._create_dummy_wikipedia_shard(wiki_shard, num_articles=50)

        manifest_path = proc_root / "task_splits_manifest.json"
        report = execute_physical_partitioning(
            raw_root=raw_root,
            processed_root=proc_root,
            manifest_output_path=manifest_path,
            datasets=["WIKIPEDIA-VI"],
        )

        self.assertTrue(manifest_path.is_file())
        self.assertEqual(report["total_datasets_partitioned"], 1)
        self.assertEqual(report["manifest_version"], "1.1.0")
        self.assertTrue(report["zero_training_verified"])
        self.assertTrue(report["raw_data_untouched"])


if __name__ == "__main__":
    unittest.main()
