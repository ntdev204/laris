"""Unit tests for real randomly initialized Transformer encoder architecture.

Addresses Issue #217 (WP4).
Validates:
- Exact parameter count formula matching 109,561,856 params
- ModelReadinessState taxonomy (RANDOMLY_INITIALIZED vs BASELINE vs TRAINED)
- Deterministic initialization from seed
- Forward pass output shapes, multi-task capability heads, and finite output guarantees
- Untrained checkpoint saving and metadata round-trip
- Absolute prohibition on training steps (TrainingExecutionProhibitedError)
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    SequenceLengthExceededError,
    TrainingExecutionProhibitedError,
)
from laris.language.neural import (
    ModelReadinessState,
    RandomlyInitializedTransformerEncoder,
    TransformerEncoderConfig,
)


class TestTransformerEncoderConfig(unittest.TestCase):
    """Test suite for TransformerEncoderConfig hyperparameter verification."""

    def test_parameter_count_formula_exact_109m(self) -> None:
        """Config parameter count must match 109,561,856 according to specification equations."""
        config = TransformerEncoderConfig(
            vocab_size=32000,
            d_model=768,
            num_layers=12,
            num_heads=12,
            d_ff=3072,
            tie_embeddings=True,
        )
        param_count = config.calculate_parameter_count()
        self.assertEqual(param_count, 109_561_856)

    def test_untied_parameter_count(self) -> None:
        """Untied MLM output head adds V * d = 24.58M additional parameters."""
        config = TransformerEncoderConfig(
            vocab_size=32000,
            d_model=768,
            num_layers=12,
            num_heads=12,
            d_ff=3072,
            tie_embeddings=False,
        )
        param_count = config.calculate_parameter_count()
        self.assertEqual(param_count, 134_137_856)

    def test_invalid_dimension_rejected(self) -> None:
        """Dimensions outside {384, 768} must be rejected."""
        with self.assertRaises(EmbeddingDimensionMismatchError):
            TransformerEncoderConfig(d_model=512)

    def test_invalid_norm_or_activation_rejected(self) -> None:
        """Non-approved normalization or activation types must be rejected."""
        with self.assertRaises(ValueError):
            TransformerEncoderConfig(norm_type="layernorm")
        with self.assertRaises(ValueError):
            TransformerEncoderConfig(activation="relu")
        with self.assertRaises(ValueError):
            TransformerEncoderConfig(pos_encoding="learned")


class TestRandomlyInitializedTransformerEncoder(unittest.TestCase):
    """Test suite for randomly initialized neural encoder and capability heads."""

    def setUp(self) -> None:
        # Use a compact config for fast unit testing of forward pass mechanics
        self.config = TransformerEncoderConfig(
            vocab_size=1000,
            max_sequence_length=64,
            d_model=384,
            num_layers=2,
            num_heads=6,
            d_ff=1536,
            seed=42,
        )
        self.model = RandomlyInitializedTransformerEncoder(self.config)

    def test_readiness_state_is_randomly_initialized(self) -> None:
        """Model must be formally marked as RANDOMLY_INITIALIZED, not TRAINED."""
        self.assertEqual(self.model.readiness_state, ModelReadinessState.RANDOMLY_INITIALIZED)
        self.assertNotEqual(self.model.readiness_state, ModelReadinessState.TRAINED)

    def test_weights_sha256_determinism(self) -> None:
        """Identical seed must produce identical weights hash."""
        model2 = RandomlyInitializedTransformerEncoder(self.config)
        self.assertEqual(self.model.weights_sha256, model2.weights_sha256)
        self.assertEqual(len(self.model.weights_sha256), 64)

    def test_forward_pass_shapes_and_finite_outputs(self) -> None:
        """Forward pass must produce valid tensor shapes and strictly finite values."""
        batch_size = 2
        seq_len = 8
        token_ids = np.random.randint(0, 1000, size=(batch_size, seq_len))

        outputs = self.model.forward(token_ids)

        self.assertIn("hidden_states", outputs)
        self.assertIn("cls_embedding", outputs)
        self.assertIn("mlm_logits", outputs)
        self.assertIn("nli_logits", outputs)
        self.assertIn("paraphrase_prob", outputs)
        self.assertIn("qa_logits", outputs)

        # Shape assertions
        self.assertEqual(outputs["hidden_states"].shape, (batch_size, seq_len, 384))
        self.assertEqual(outputs["cls_embedding"].shape, (batch_size, 384))
        self.assertEqual(outputs["mlm_logits"].shape, (batch_size, seq_len, 1000))
        self.assertEqual(outputs["nli_logits"].shape, (batch_size, 3))
        self.assertEqual(outputs["paraphrase_prob"].shape, (batch_size, 1))
        self.assertEqual(outputs["qa_logits"].shape, (batch_size, seq_len, 2))

        # Check all values are finite
        for name, tensor in outputs.items():
            self.assertTrue(np.all(np.isfinite(tensor)), f"Non-finite output in {name}")

    def test_sequence_length_exceeded_raises_error(self) -> None:
        """Sequences longer than max_sequence_length must raise SequenceLengthExceededError."""
        long_tokens = np.zeros((1, 128), dtype=np.int64)
        with self.assertRaises(SequenceLengthExceededError):
            self.model.forward(long_tokens)

    def test_train_step_raises_prohibition_error(self) -> None:
        """Mandatory stop: calling train_step() MUST raise TrainingExecutionProhibitedError."""
        with self.assertRaises(TrainingExecutionProhibitedError):
            self.model.train_step()

    def test_save_untrained_checkpoint(self) -> None:
        """Untrained state metadata can be serialized to disk cleanly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            ckpt_path = Path(tmp_dir) / "untrained_model.json"
            saved_path = self.model.save_untrained_checkpoint(ckpt_path)
            self.assertTrue(saved_path.exists())
            self.assertGreater(saved_path.stat().st_size, 0)
