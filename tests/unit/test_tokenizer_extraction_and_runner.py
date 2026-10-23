"""Unit tests for tokenizer extraction and runner readiness (Issue #232).

Adheres to DOC-SPEC-MOD-001 (Boundary B), ADR-002, and ADR-008.
Verifies:
- Clean Wikipedia extraction strictly from TRAIN partition
- DataLeakageError rejection when validation/test partition is passed
- Tokenizer execution authorization gate
- SentencePiece training workflow on dummy corpus
"""

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from laris.core.authorization import (
    assert_tokenizer_training_authorized,
    assert_training_authorized,
    is_tokenizer_training_authorized,
    is_training_authorized,
    temporary_training_authorization,
)
from laris.core.errors import DataLeakageError, TrainingExecutionProhibitedError
from laris.language.tokenizer_trainer import (
    TokenizerReadinessState,
    TokenizerTrainerConfig,
    TokenizerTrainingPipeline,
    extract_clean_wikipedia_corpus,
)


class TestTokenizerExtractionAndRunner(unittest.TestCase):
    """Test suite for tokenizer corpus extraction and training pipeline."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _create_dummy_train_parquet(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        texts = [
            "Hệ thống LARIS xử lý dữ liệu tiếng Việt có dấu: sắc, huyền, hỏi, ngã, nặng.",
            "Nghiên cứu khoa học tự nhiên và trí tuệ nhân tạo cục bộ.",
            "Công thức toán học: $\\int_0^\\infty e^{-x} dx = 1$ và biến số $x \\in \\mathbb{R}$.",
            "English sentences for bilingual training and natural language foundation.",
        ] * 10
        table = pa.Table.from_arrays([pa.array(texts)], names=["text"])
        pq.write_table(table, path, compression="snappy")

    def test_extract_clean_wikipedia_corpus_success(self) -> None:
        """Extracts clean lines from train Parquet shard."""
        train_pq = self.root / "train.parquet"
        self._create_dummy_train_parquet(train_pq)

        text_out = self.root / "extracted_train.txt"
        count = extract_clean_wikipedia_corpus(
            parquet_paths=[train_pq],
            output_text_path=text_out,
            batch_size=10,
        )

        self.assertEqual(count, 40)
        self.assertTrue(text_out.is_file())
        with open(text_out, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 40)
        # Verify Vietnamese diacritics preserved
        self.assertIn("tiếng Việt", lines[0])

    def test_extract_clean_wikipedia_corpus_leakage_rejection(self) -> None:
        """Must reject files with 'val' or 'test' in the filename."""
        val_pq = self.root / "val.parquet"
        self._create_dummy_train_parquet(val_pq)

        text_out = self.root / "extracted.txt"
        with self.assertRaises(DataLeakageError):
            extract_clean_wikipedia_corpus(
                parquet_paths=[val_pq],
                output_text_path=text_out,
            )

    def test_authorization_gate_defaults_to_false(self) -> None:
        """Training gates must default to False in absence of authorization."""
        self.assertFalse(is_training_authorized())
        self.assertFalse(is_tokenizer_training_authorized())

        with self.assertRaises(TrainingExecutionProhibitedError):
            assert_training_authorized("test context")

        with self.assertRaises(TrainingExecutionProhibitedError):
            assert_tokenizer_training_authorized("test tokenizer")

    def test_temporary_training_authorization_context(self) -> None:
        """Context manager safely toggles authorization state and resets afterwards."""
        self.assertFalse(is_tokenizer_training_authorized())
        with temporary_training_authorization(enable=True, tokenizer_only=True):
            self.assertTrue(is_tokenizer_training_authorized())
            self.assertFalse(is_training_authorized())
        self.assertFalse(is_tokenizer_training_authorized())

    def test_tokenizer_training_pipeline_authorized_run(self) -> None:
        """When authorized and sentencepiece available, pipeline fits tokenizer."""
        train_pq = self.root / "train.parquet"
        self._create_dummy_train_parquet(train_pq)

        text_out = self.root / "corpus.txt"
        extract_clean_wikipedia_corpus([train_pq], text_out)

        out_dir = self.root / "artifacts" / "tokenizer"
        cfg = TokenizerTrainerConfig(
            vocab_size=200,
            model_type="bpe",
            character_coverage=0.9995,
            input_corpus_paths=[text_out],
            output_dir=out_dir,
        )
        pipeline = TokenizerTrainingPipeline(cfg)

        # Unauthorized attempt raises error
        with self.assertRaises(TrainingExecutionProhibitedError):
            pipeline.execute_training(force_authorized=False)

        # Authorized run creates model and contract
        model_file = pipeline.execute_training(force_authorized=True, model_prefix="test_spm")
        self.assertTrue(model_file.is_file())
        self.assertTrue((out_dir / "test_spm.vocab").is_file())
        self.assertTrue((out_dir / "test_spm_contract.json").is_file())

        report = pipeline.get_readiness_report()
        self.assertEqual(report["readiness_state"], TokenizerReadinessState.TRAINED.value)
        self.assertTrue(report["tokenizer_trained"])


if __name__ == "__main__":
    unittest.main()
