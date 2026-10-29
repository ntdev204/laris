"""Unit tests for from-scratch bilingual tokenizer training pipeline.

Addresses Issue #217 (WP3).
Validates:
- TokenizerTrainerConfig invariants and split leakage prevention
- Rejection of non-TRAIN splits for tokenizer induction
- Vietnamese diacritic preservation coverage verification
- Deterministic SentencePiece command-line argument construction
- Strict enforcement of TrainingExecutionProhibitedError on training execution
- VocabularyContract generation and cryptographic validation
"""

import unittest

from laris.core.errors import (
    DataLeakageError,
    ModuleContractViolationError,
    TrainingExecutionProhibitedError,
)
from laris.corpus.schemas import DatasetSplit
from laris.language.tokenization.trainer import (
    TokenizerTrainerConfig,
    TokenizerTrainingPipeline,
)


class TestTokenizerTrainingPipeline(unittest.TestCase):
    """Test suite for tokenizer training pipeline contracts and guards."""

    def setUp(self) -> None:
        self.config = TokenizerTrainerConfig(
            vocab_size=32000,
            model_type="bpe",
            character_coverage=0.9995,
            input_split=DatasetSplit.TRAIN,
        )
        self.pipeline = TokenizerTrainingPipeline(self.config)

    def test_config_non_train_split_rejected(self) -> None:
        """Tokenizer training configuration must reject non-TRAIN splits to prevent leakage."""
        with self.assertRaises(DataLeakageError):
            TokenizerTrainerConfig(input_split=DatasetSplit.VAL)
        with self.assertRaises(DataLeakageError):
            TokenizerTrainerConfig(input_split=DatasetSplit.TEST)

    def test_config_invalid_vocab_size_rejected(self) -> None:
        """Vocab size outside [100, 128000] must be rejected."""
        with self.assertRaises(ValueError):
            TokenizerTrainerConfig(vocab_size=50)
        with self.assertRaises(ValueError):
            TokenizerTrainerConfig(vocab_size=200000)

    def test_vietnamese_diacritic_coverage_validation(self) -> None:
        """High coverage threshold (>= 0.9995) must be enforced for Vietnamese text."""
        self.assertTrue(self.pipeline.validate_vietnamese_diacritics_coverage())

        # Low coverage must be rejected
        low_cov_config = TokenizerTrainerConfig(character_coverage=0.95)
        low_cov_pipeline = TokenizerTrainingPipeline(low_cov_config)
        with self.assertRaises(ModuleContractViolationError):
            low_cov_pipeline.validate_vietnamese_diacritics_coverage()

    def test_build_sentencepiece_args(self) -> None:
        """SentencePiece CLI args must include special tokens and required parameters."""
        args = self.pipeline.build_sentencepiece_args("corpus_train.txt", model_prefix="bpe32k")

        arg_str = " ".join(args)
        self.assertIn("--vocab_size=32000", arg_str)
        self.assertIn("--model_type=bpe", arg_str)
        self.assertIn("--character_coverage=0.9995", arg_str)
        self.assertIn("--bos_piece=[CLS]", arg_str)
        self.assertIn("--eos_piece=[SEP]", arg_str)
        self.assertIn("--pad_piece=[PAD]", arg_str)
        self.assertIn("--unk_piece=[UNK]", arg_str)
        self.assertIn("--user_defined_symbols=[MASK],[MATH],[GREEK],[UNIT]", arg_str)

    def test_execute_training_raises_prohibition_error(self) -> None:
        """Mandatory stop: calling execute_training() MUST raise prohibited error."""
        with self.assertRaises(TrainingExecutionProhibitedError):
            self.pipeline.execute_training()

    def test_validate_vocabulary_contract(self) -> None:
        """Pipeline can construct and validate an immutable VocabularyContract."""
        sample_tokens = {
            "[PAD]": 0,
            "[UNK]": 1,
            "[CLS]": 2,
            "[SEP]": 3,
            "[MASK]": 4,
            "[MATH]": 5,
            "[GREEK]": 6,
            "[UNIT]": 7,
            "khoa": 8,
            "học": 9,
            "science": 10,
        }
        for i in range(11, 100):
            sample_tokens[f"token_{i}"] = i

        vocab_contract = self.pipeline.validate_vocabulary_contract(sample_tokens)
        self.assertEqual(vocab_contract.vocab_size, 100)
        self.assertEqual(vocab_contract.token_to_id["khoa"], 8)
        self.assertEqual(vocab_contract.id_to_token[8], "khoa")
        self.assertEqual(len(vocab_contract.vocab_sha256), 64)

    def test_tokenizer_readiness_state_and_report(self) -> None:
        """Pipeline must explicitly report PIPELINE_IMPLEMENTED and zero training."""
        from laris.language.tokenization.trainer import TokenizerReadinessState

        self.assertEqual(
            self.pipeline.readiness_state, TokenizerReadinessState.PIPELINE_IMPLEMENTED
        )
        report = self.pipeline.get_readiness_report()
        self.assertEqual(report["status"], "PIPELINE_IMPLEMENTED")
        self.assertEqual(report["readiness_state"], "PIPELINE_IMPLEMENTED")
        self.assertFalse(report["tokenizer_artifact_generated"])
        self.assertFalse(report["tokenizer_trained"])
        self.assertTrue(report["training_execution_barrier_active"])
        self.assertIn("sentencepiece", report["dependency_declared_in_project"])

    def test_unicode_and_vietnamese_diacritic_preservation(self) -> None:
        """Unicode NFC normalization and Vietnamese diacritics must be verified intact."""
        result = self.pipeline.validate_unicode_preservation()
        self.assertTrue(result["vietnamese_diacritics_intact"])
        self.assertTrue(result["scientific_symbols_intact"])
        self.assertTrue(result["nfc_normalized"])
        self.assertGreaterEqual(result["preservation_rate"], 1.0)

        # Complex sentence test
        custom_sample = [
            "Trường Đại học Bách khoa Hà Nội và Viện Hàn lâm Khoa học và Công nghệ Việt Nam.",
            "Phương trình vi phân: ∂u/∂t = α ∇²u + β ∫ f(x) dx.",
            "Vần ươu, oang, uế: con hươu, hoa hoang dã, vương miện.",
        ]
        res_custom = self.pipeline.validate_unicode_preservation(custom_sample)
        self.assertTrue(res_custom["vietnamese_diacritics_intact"])
        self.assertEqual(res_custom["preservation_rate"], 1.0)

    def test_config_serialization_round_trip(self) -> None:
        """TokenizerTrainerConfig must serialize and deserialize deterministically."""
        import tempfile
        from pathlib import Path

        config_dict = self.config.to_dict()
        self.assertEqual(config_dict["vocab_size"], 32000)
        self.assertEqual(config_dict["model_type"], "bpe")
        self.assertEqual(config_dict["input_split"], "TRAIN")

        reconstructed = TokenizerTrainerConfig.from_dict(config_dict)
        self.assertEqual(reconstructed.vocab_size, self.config.vocab_size)
        self.assertEqual(reconstructed.character_coverage, self.config.character_coverage)

        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "tokenizer_cfg.json"
            self.config.save_json(json_path)
            loaded_cfg = TokenizerTrainerConfig.from_json(json_path)
            self.assertEqual(loaded_cfg.vocab_size, self.config.vocab_size)
            self.assertEqual(loaded_cfg.model_type, self.config.model_type)

    def test_pipeline_metadata_save(self) -> None:
        """Pipeline metadata report must save valid JSON without claiming trained weights."""
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            meta_path = Path(tmp_dir) / "pipeline_metadata.json"
            self.pipeline.save_pipeline_metadata(
                meta_path, extra_metadata={"audit_stage": "M2-LANG-006"}
            )
            self.assertTrue(meta_path.exists())

            with open(meta_path, "r", encoding="utf-8") as f:
                saved_meta = json.load(f)
            self.assertEqual(saved_meta["status"], "PIPELINE_IMPLEMENTED")
            self.assertFalse(saved_meta["tokenizer_trained"])
            self.assertEqual(saved_meta["extra_metadata"]["audit_stage"], "M2-LANG-006")

    def test_pyproject_toml_declares_sentencepiece(self) -> None:
        """SentencePiece must be declared as an approved optional dependency in pyproject.toml."""
        from pathlib import Path
        pyproject_path = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        content = pyproject_path.read_text(encoding="utf-8")
        self.assertIn("sentencepiece", content)
        self.assertIn("[project.optional-dependencies]", content)
