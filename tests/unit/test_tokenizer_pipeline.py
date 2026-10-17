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
from laris.language.tokenizer_trainer import (
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
        self.assertIn("--user_defined_symbols=[MATH],[GREEK],[UNIT]", arg_str)

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
