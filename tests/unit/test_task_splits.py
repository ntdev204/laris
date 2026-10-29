"""Unit tests for task-specific dataset partitioning and leakage validation.

Addresses Issue #217 (WP2).
Validates:
- Wikipedia article hash partitioning determinism and zero-leakage
- Quora question-pair graph partitioning with connected component clustering
- Reading comprehension QA title/context-grouped dev/held-out test isolation
- Non-destructive processing preserving raw data artifacts
- Schema and data quality validation
"""

import json
import tempfile
import unittest
from pathlib import Path

from laris.core.errors import ModuleContractViolationError
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits import (
    PartitionRatios,
    QADatasetPartitioner,
    QuestionPairGraphPartitioner,
    WikipediaArticlePartitioner,
    audit_dataset_inventory,
    generate_leakage_safe_manifest,
    validate_record_quality,
    validate_split_isolation,
)


class TestWikipediaArticlePartitioner(unittest.TestCase):
    """Test suite for Wikipedia article hash partitioning."""

    def setUp(self) -> None:
        self.partitioner = WikipediaArticlePartitioner(
            ratios=PartitionRatios(train=0.8, val=0.1, test=0.1),
            seed="wiki-test-seed-1",
        )

    def test_determinism_and_split_assignment(self) -> None:
        """Same article ID must deterministically map to the same split."""
        split1 = self.partitioner.assign_split("art-1001")
        split2 = self.partitioner.assign_split("art-1001")
        self.assertEqual(split1, split2)
        self.assertIn(split1, (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST))

    def test_partition_records_non_destructive(self) -> None:
        """Original records must remain untouched while output gets assigned_split."""
        raw_records = [
            {"id": f"art-{i}", "text": f"This is encyclopedia article number {i}."}
            for i in range(50)
        ]
        original_first = dict(raw_records[0])

        splits = self.partitioner.partition_records(raw_records)

        # Original list unmodified
        self.assertEqual(raw_records[0], original_first)
        self.assertNotIn("assigned_split", raw_records[0])

        # All items partitioned
        total_items = sum(len(items) for items in splits.values())
        self.assertEqual(total_items, 50)

        # Verified zero leakage across splits
        self.assertTrue(validate_split_isolation(splits, item_id_key="id"))

    def test_empty_or_missing_id_raises_contract_error(self) -> None:
        """Missing or whitespace-only article IDs must be rejected."""
        with self.assertRaises(ModuleContractViolationError):
            self.partitioner.partition_records([{"id": "", "text": "sample text"}])
        with self.assertRaises(ModuleContractViolationError):
            self.partitioner.partition_records([{"text": "missing id"}])


class TestQuestionPairGraphPartitioner(unittest.TestCase):
    """Test suite for connected-component question pair partitioning."""

    def setUp(self) -> None:
        self.partitioner = QuestionPairGraphPartitioner(
            ratios=PartitionRatios(train=0.8, val=0.1, test=0.1),
            seed="graph-pair-seed-1",
        )

    def test_connected_questions_cluster_to_same_split(self) -> None:
        """Pairs sharing questions (Q1-Q2, Q2-Q3, Q3-Q4) must all reside in the same split."""
        pairs = [
            {
                "id": "p1",
                "question1": "What is machine learning?",
                "question2": "How does ML work?",
            },
            {
                "id": "p2",
                "question1": "How does ML work?",
                "question2": "Explain artificial intelligence.",
            },
            {
                "id": "p3",
                "question1": "Explain artificial intelligence.",
                "question2": "What are neural networks?",
            },
            {
                "id": "p4",
                "question1": "How to bake bread?",
                "question2": "Bread baking recipe.",
            },
        ]

        splits = self.partitioner.partition_pairs(pairs)

        # Check where p1, p2, p3 landed
        p1_split = None
        p2_split = None
        p3_split = None
        for s, p_list in splits.items():
            for p in p_list:
                if p["id"] == "p1":
                    p1_split = s
                elif p["id"] == "p2":
                    p2_split = s
                elif p["id"] == "p3":
                    p3_split = s

        self.assertIsNotNone(p1_split)
        self.assertEqual(p1_split, p2_split)
        self.assertEqual(p2_split, p3_split)

    def test_empty_question_raises_contract_error(self) -> None:
        """Malformed pair with empty questions must raise ModuleContractViolationError."""
        with self.assertRaises(ModuleContractViolationError):
            self.partitioner.partition_pairs([{"question1": "", "question2": "Valid question"}])


class TestQADatasetPartitioner(unittest.TestCase):
    """Test suite for reading comprehension title/context-grouped partitioning."""

    def setUp(self) -> None:
        self.partitioner = QADatasetPartitioner(
            dev_ratio=0.5,
            test_ratio=0.5,
            seed="qa-seed-42",
        )

    def test_qa_title_isolation_between_dev_and_test(self) -> None:
        """Questions sharing the same document title must not be split across DEV and TEST."""
        qa_items = [
            {
                "title": "Albert Einstein",
                "context": "Passage 1 on Einstein",
                "question": "Where was he born?",
            },
            {
                "title": "Albert Einstein",
                "context": "Passage 2 on relativity",
                "question": "What is E=mc^2?",
            },
            {
                "title": "Isaac Newton",
                "context": "Passage on gravity",
                "question": "What fell from the tree?",
            },
        ]

        splits = self.partitioner.sub_split_dev_set(qa_items)

        # Items with same title must be in the same split
        einstein_splits = {
            s for s, items in splits.items()
            if any(item["title"] == "Albert Einstein" for item in items)
        }
        self.assertEqual(len(einstein_splits), 1)

    def test_missing_title_and_context_raises_error(self) -> None:
        """QA items missing both title and context must raise ModuleContractViolationError."""
        with self.assertRaises(ModuleContractViolationError):
            self.partitioner.sub_split_dev_set([{"title": "", "context": "", "question": "Who?"}])


class TestValidationHelpers(unittest.TestCase):
    """Test suite for validation functions."""

    def test_validate_record_quality(self) -> None:
        """Record quality checker must reject missing or whitespace fields."""
        valid_rec = {"text": "Valid scientific text", "label": 1}
        self.assertTrue(validate_record_quality(valid_rec, ["text", "label"]))

        with self.assertRaises(ModuleContractViolationError):
            validate_record_quality({"text": "   ", "label": 1}, ["text"])

        with self.assertRaises(ModuleContractViolationError):
            validate_record_quality({"label": 1}, ["text"])


class TestDatasetInventoryAuditAndManifest(unittest.TestCase):
    """Test suite for dataset inventory audit and leakage-safe manifest generation."""

    def test_audit_dataset_inventory_from_manifest(self) -> None:
        """Inventory audit must accurately reflect disk holdings and explicit EN/VI gaps."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        manifest_path = repo_root / "data" / "acquisition_manifest.json"

        report = audit_dataset_inventory(manifest_path=manifest_path, base_dir=repo_root)
        self.assertEqual(report["status"], "VERIFIED_AUDIT")
        self.assertEqual(report["total_datasets_tracked"], 24)
        if report["physical_files_present"]:
            self.assertGreater(report["total_physical_files"], 40)
            self.assertGreater(report["total_physical_bytes"], 1_000_000_000)

        # Check disaggregated unit ledgers
        ledgers = report["disaggregated_unit_ledgers"]
        self.assertIn("Clean Wikipedia Article Document (English)", ledgers["english"])
        self.assertIn("Clean Wikipedia Article Document (Vietnamese)", ledgers["vietnamese"])
        self.assertIn(
            "Sentence Pair with 3-Way NLI Label (entailment/neutral/contradiction)",
            ledgers["english"],
        )
        self.assertNotIn(
            "Sentence Pair with 3-Way NLI Label (entailment/neutral/contradiction)",
            ledgers["vietnamese"],
        )

        # Check explicit coverage mapping
        cov = report["coverage_mapping"]
        self.assertEqual(cov["natural_language_inference"]["english"]["status"], "COVERED")
        self.assertEqual(
            cov["natural_language_inference"]["vietnamese"]["status"], "GAP_IDENTIFIED"
        )
        self.assertEqual(cov["paraphrase_and_duplicate"]["vietnamese"]["status"], "GAP_IDENTIFIED")
        self.assertEqual(
            cov["continuous_semantic_similarity"]["vietnamese"]["status"], "GAP_IDENTIFIED"
        )
        self.assertEqual(cov["ocr_image_transcription"]["english"]["status"], "GAP_IDENTIFIED")

        # Check dataset specific blockers
        datasets_by_id = {d["dataset_id"]: d for d in report["datasets"]}
        self.assertEqual(
            datasets_by_id["QUORA-DUPLICATES"]["split_usability"],
            "TRAIN_ONLY_NEEDS_GRAPH_PARTITION",
        )
        self.assertEqual(
            datasets_by_id["WIKIPEDIA-EN-BOUNDED"]["split_usability"],
            "UNPARTITIONED_RAW_DUMP",
        )
        self.assertEqual(
            datasets_by_id["SQUAD"]["split_usability"],
            "TEST_SET_PRIVATE_HELD_OUT",
        )

    def test_generate_leakage_safe_manifest_nondestructive(self) -> None:
        """Manifest generation must write valid JSON to target path without touching raw data."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        manifest_path = repo_root / "data" / "acquisition_manifest.json"

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "output_manifest.json"
            result_path = generate_leakage_safe_manifest(
                output_path=out_file,
                manifest_path=manifest_path,
                base_dir=repo_root,
            )
            self.assertTrue(result_path.exists())
            with open(result_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["manifest_version"], "1.0.0")
            self.assertTrue(data["zero_training_verified"])
            self.assertTrue(data["raw_data_untouched"])
            self.assertEqual(data["audit"]["status"], "VERIFIED_AUDIT")
            self.assertGreater(len(data["recommended_remediations"]), 0)
