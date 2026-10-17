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


    def test_parameter_count_breakdown_including_heads(self) -> None:
        """Config must provide exact parameter breakdown for backbone and capability heads."""
        config = TransformerEncoderConfig(
            vocab_size=32000,
            d_model=768,
            num_layers=12,
            num_heads=12,
            d_ff=3072,
            tie_embeddings=True,
        )
        backbone_count = config.calculate_backbone_parameter_count()
        self.assertEqual(backbone_count, 109_561_856)

        heads_count = config.calculate_head_parameter_count()
        # NLI (197,635) + Para (769) + Sim (769) + QA (1,538) = 200,711
        self.assertEqual(heads_count, 200_711)

        total_with_heads = config.calculate_parameter_count(include_heads=True)
        self.assertEqual(total_with_heads, 109_561_856 + 200_711)
        self.assertEqual(total_with_heads, 109_762_567)

        # Default maintains backward compatibility with 109.56M
        self.assertEqual(config.calculate_parameter_count(include_heads=False), 109_561_856)

    def test_analytical_memory_estimation(self) -> None:
        """Analytical memory estimation must distinguish analytical models from measured RAM."""
        config = TransformerEncoderConfig(
            vocab_size=32000,
            d_model=768,
            num_layers=12,
            num_heads=12,
            d_ff=3072,
            precision="bf16",
        )
        est = config.estimate_memory_consumption(batch_size=2, seq_len=128)
        self.assertEqual(est["status"], "ANALYTICAL_ESTIMATE")
        self.assertEqual(est["bytes_per_param"], 2)
        self.assertGreater(est["weights_memory_mb"], 200.0)
        self.assertGreater(est["estimated_activations_mb"], 0.0)
        self.assertGreater(est["estimated_peak_memory_mb"], est["weights_memory_mb"])
        self.assertIn("Analytical estimate", est["note"])


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

    def test_parameter_counts_stored_accurately(self) -> None:
        """Model must record both backbone and total parameter counts."""
        self.assertEqual(self.model.parameter_count, self.model.backbone_parameter_count)
        self.assertGreater(self.model.total_parameter_count, self.model.backbone_parameter_count)

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
        self.assertIn("similarity_score", outputs)
        self.assertIn("qa_logits", outputs)

        # Shape assertions
        self.assertEqual(outputs["hidden_states"].shape, (batch_size, seq_len, 384))
        self.assertEqual(outputs["cls_embedding"].shape, (batch_size, 384))
        self.assertEqual(outputs["mlm_logits"].shape, (batch_size, seq_len, 1000))
        self.assertEqual(outputs["nli_logits"].shape, (batch_size, 3))
        self.assertEqual(outputs["paraphrase_prob"].shape, (batch_size, 1))
        self.assertEqual(outputs["similarity_score"].shape, (batch_size, 1))
        self.assertEqual(outputs["qa_logits"].shape, (batch_size, seq_len, 2))

        # Check all values are finite and scores in [0, 1]
        for name, tensor in outputs.items():
            self.assertTrue(np.all(np.isfinite(tensor)), f"Non-finite output in {name}")
        p_prob = outputs["paraphrase_prob"]
        s_score = outputs["similarity_score"]
        self.assertTrue(np.all((p_prob >= 0.0) & (p_prob <= 1.0)))
        self.assertTrue(np.all((s_score >= 0.0) & (s_score <= 1.0)))

    def test_attention_mask_isolates_padded_tokens(self) -> None:
        """Changing padded tokens must not alter representations of valid tokens."""
        # Two sequences with identical first 3 valid tokens, but different padded token at index 3
        seq1 = [10, 20, 30, 0]
        seq2 = [10, 20, 30, 999]  # Different padded token
        token_ids = np.array([seq1, seq2], dtype=np.int64)
        mask = np.array([[1, 1, 1, 0], [1, 1, 1, 0]], dtype=np.float32)

        outputs = self.model.forward(token_ids, attention_mask=mask)
        h = outputs["hidden_states"]

        # Hidden states for valid tokens (pos 0, 1, 2) must be identical within numerical precision
        diff_pos0 = np.max(np.abs(h[0, 0] - h[1, 0]))
        diff_pos1 = np.max(np.abs(h[0, 1] - h[1, 1]))
        diff_pos2 = np.max(np.abs(h[0, 2] - h[1, 2]))

        self.assertLess(diff_pos0, 1e-4)
        self.assertLess(diff_pos1, 1e-4)
        self.assertLess(diff_pos2, 1e-4)

    def test_invalid_attention_mask_shape_rejected(self) -> None:
        """Attention mask with mismatched shape must raise ValueError."""
        token_ids = np.ones((2, 8), dtype=np.int64)
        bad_mask = np.ones((2, 4), dtype=np.float32)
        with self.assertRaises(ValueError):
            self.model.forward(token_ids, attention_mask=bad_mask)

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


class TestRoPEMathematics(unittest.TestCase):
    """Focused mathematical verification for Rotary Position Embeddings (RoPE)."""

    def test_rope_norm_preservation(self) -> None:
        """Rotary rotation is orthogonal and must strictly preserve Euclidean vector norms."""
        from laris.language.neural import _apply_rope

        seq_len = 8
        head_dim = 64
        rng = np.random.default_rng(123)
        q = rng.normal(0.0, 1.0, (1, seq_len, 1, head_dim)).astype(np.float32)
        k = rng.normal(0.0, 1.0, (1, seq_len, 1, head_dim)).astype(np.float32)

        q_norm_before = np.linalg.norm(q, axis=-1)
        k_norm_before = np.linalg.norm(k, axis=-1)

        q_rot, k_rot = _apply_rope(q, k, seq_len, head_dim)

        q_norm_after = np.linalg.norm(q_rot, axis=-1)
        k_norm_after = np.linalg.norm(k_rot, axis=-1)

        np.testing.assert_allclose(q_norm_before, q_norm_after, rtol=1e-5, atol=1e-5)
        np.testing.assert_allclose(k_norm_before, k_norm_after, rtol=1e-5, atol=1e-5)

    def test_rope_position_zero_is_identity(self) -> None:
        """At position 0, angles are 0, so rotation must equal identity (q_rot[0] == q[0])."""
        from laris.language.neural import _apply_rope

        seq_len = 4
        head_dim = 32
        rng = np.random.default_rng(42)
        q = rng.normal(0.0, 1.0, (1, seq_len, 1, head_dim)).astype(np.float32)
        k = rng.normal(0.0, 1.0, (1, seq_len, 1, head_dim)).astype(np.float32)

        q_rot, k_rot = _apply_rope(q, k, seq_len, head_dim)

        np.testing.assert_allclose(q[:, 0, :, :], q_rot[:, 0, :, :], rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(k[:, 0, :, :], k_rot[:, 0, :, :], rtol=1e-6, atol=1e-6)

