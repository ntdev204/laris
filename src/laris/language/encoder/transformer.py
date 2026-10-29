"""Real randomly initialized neural Transformer encoder architecture.

Adheres to DOC-SPEC-TRAIN-001, ADR-002, ADR-003, and Issue #217 (WP4).
Provides:
- 109.56M parameter bidirectional Transformer encoder matching specification equations
- Pre-RMSNorm, Rotary Position Embeddings (RoPE), GELU FFN (d_ff = 3072), and tied MLM projection
- Explicit capability heads: 3-way NLI, paraphrase detection, semantic similarity, and span QA
- CPU-capable NumPy forward pass without external cloud or foundation model dependencies
- Deterministic initialization from seed with finite-output verification
- Precise labeling: ModelReadinessState.RANDOMLY_INITIALIZED vs BASELINE vs TRAINED
- STRICT PROHIBITION: Any training step or gradient update raises TrainingExecutionProhibitedError
"""

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from laris.core.authorization import assert_training_authorized
from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    SequenceLengthExceededError,
    TrainingExecutionProhibitedError,
)
from laris.language.schemas import (
    ALLOWED_EMBEDDING_DIMENSIONS,
    DEFAULT_MAX_SEQUENCE_LENGTH,
    DEFAULT_TARGET_VOCAB_SIZE,
)


class ModelReadinessState(str, Enum):
    """Formal taxonomy of model implementation and training status."""

    # Heuristic baseline (e.g., CompactSentenceEncoder)
    BASELINE = "BASELINE"
    # Real neural architecture instantiated from seed, untrained
    RANDOMLY_INITIALIZED = "RANDOMLY_INITIALIZED"
    # Learned model weights (PROHIBITED in this phase)
    TRAINED = "TRAINED"
    # Formally benchmarked against exit gate metrics
    EVALUATED = "EVALUATED"


@dataclass(frozen=True)
class LanguageEncoderConfig:
    """Hyperparameter specification for the language encoder."""

    vocab_size: int = DEFAULT_TARGET_VOCAB_SIZE  # 32,000
    max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH  # 512
    d_model: int = 768
    num_layers: int = 12
    num_heads: int = 12
    d_ff: int = 3072
    dropout: float = 0.1
    norm_type: str = "rmsnorm"
    pos_encoding: str = "rope"
    activation: str = "gelu"
    tie_embeddings: bool = True
    precision: str = "bf16"
    seed: int = 42
    gradient_checkpointing: bool = False

    def __post_init__(self) -> None:
        if self.d_model not in ALLOWED_EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionMismatchError(
                f"d_model {self.d_model} must be in {sorted(ALLOWED_EMBEDDING_DIMENSIONS)}"
            )
        if self.num_layers <= 0:
            raise ValueError("num_layers must be positive")
        if self.num_heads <= 0 or self.d_model % self.num_heads != 0:
            raise ValueError(
                f"d_model ({self.d_model}) must be divisible by num_heads ({self.num_heads})"
            )
        if self.d_ff <= 0:
            raise ValueError("d_ff must be positive")
        if self.norm_type != "rmsnorm":
            raise ValueError(f"Only 'rmsnorm' is approved, got '{self.norm_type}'")
        if self.pos_encoding != "rope":
            raise ValueError(f"Only 'rope' is approved, got '{self.pos_encoding}'")
        if self.activation != "gelu":
            raise ValueError(f"Only 'gelu' is approved, got '{self.activation}'")

    @classmethod
    def from_config(cls, config: Any) -> "LanguageEncoderConfig":
        """Instantiates LanguageEncoderConfig from centralized ModelConfig or LarisConfig."""
        model_cfg = getattr(config, "model", config)
        return cls(
            vocab_size=getattr(model_cfg, "vocab_size", DEFAULT_TARGET_VOCAB_SIZE),
            max_sequence_length=getattr(
                model_cfg, "max_sequence_length", DEFAULT_MAX_SEQUENCE_LENGTH
            ),
            d_model=getattr(model_cfg, "d_model", 768),
            num_layers=getattr(model_cfg, "num_layers", 12),
            num_heads=getattr(model_cfg, "num_heads", 12),
            d_ff=getattr(model_cfg, "d_ff", 3072),
            dropout=getattr(model_cfg, "dropout", 0.1),
            norm_type=getattr(model_cfg, "norm_type", "rmsnorm"),
            pos_encoding=getattr(model_cfg, "pos_encoding", "rope"),
            activation=getattr(model_cfg, "activation", "gelu"),
            tie_embeddings=getattr(model_cfg, "tie_embeddings", True),
            precision=getattr(model_cfg, "precision", "bf16"),
            seed=getattr(model_cfg, "seed", 42),
        )

    def calculate_backbone_parameter_count(self) -> int:
        """Calculates exact parameter count of the Transformer encoder backbone.

        Backbone Equation:
          V * d + L * (4 * d^2 + 2 * d * d_ff + 2 * d) + d + (V if tie_embeddings else V * d + V)
        For canonical configuration: 32000*768 + 12*(4*768^2 + 2*768*3072 + 2*768) + 768 + 32000
          = 24,576,000 + 12*(2,359,296 + 4,718,592 + 1,536) + 768 + 32,000
          = 24,576,000 + 12*(7,079,424) + 768 + 32,000
          = 24,576,000 + 84,953,088 + 768 + 32,000
          = 109,561,856 parameters.
        """
        emb_params = self.vocab_size * self.d_model
        attn_params = 4 * self.d_model * self.d_model
        ffn_params = 2 * self.d_model * self.d_ff
        layer_norm_params = 2 * self.d_model
        per_layer_params = attn_params + ffn_params + layer_norm_params
        total_layers = self.num_layers * per_layer_params
        final_norm_params = self.d_model

        if self.tie_embeddings:
            head_bias_params = self.vocab_size
        else:
            head_bias_params = self.vocab_size * self.d_model + self.vocab_size

        return emb_params + total_layers + final_norm_params + head_bias_params

    def calculate_head_parameter_count(self) -> int:
        """Calculates parameters across all capability task heads (NLI, Paraphrase, Similarity, QA).

        Head Equations:
          - 3-Way NLI head: (d -> 256 -> 3): d*256 + 256 + 256*3 + 3 = 197,635 params (d=768)
          - Paraphrase head: (d -> 1): d*1 + 1 = 769 params (d=768)
          - Semantic similarity head: (d -> 1): d*1 + 1 = 769 params (d=768)
          - Span QA head: (d -> 2): d*2 + 2 = 1,538 params (d=768)
          Total capability head params = 200,711 params (d=768)
        """
        d = self.d_model
        nli_params = (d * 256 + 256) + (256 * 3 + 3)
        para_params = d * 1 + 1
        sim_params = d * 1 + 1
        qa_params = d * 2 + 2
        return nli_params + para_params + sim_params + qa_params

    def calculate_parameter_count(self, include_heads: bool = False) -> int:
        """Calculates parameter count according to architectural equations.

        Args:
            include_heads: If False (default), returns the exact backbone parameter count
                (109,561,856 for canonical 110M model). If True, includes all instantiated
                multi-task capability heads (109,762,567 for canonical 110M model).
        """
        backbone = self.calculate_backbone_parameter_count()
        if include_heads:
            return backbone + self.calculate_head_parameter_count()
        return backbone

    def estimate_memory_consumption(
        self,
        batch_size: int = 2,
        seq_len: int = 32,
    ) -> Dict[str, Any]:
        """Provides analytical memory estimates separated from physical measurements.

        Analytical model:
          - Weights memory: total_parameters * bytes_per_param
          - Forward activations per layer: attention scores + hidden states + FFN expansion
        """
        bytes_per_param = 2 if self.precision in ("bf16", "fp16") else 4
        backbone_params = self.calculate_backbone_parameter_count()
        total_params = self.calculate_parameter_count(include_heads=True)

        weights_mb = (total_params * bytes_per_param) / (1024 * 1024)
        per_layer_acts_bytes = (
            batch_size * self.num_heads * seq_len * seq_len * 4
            + batch_size * seq_len * self.d_model * bytes_per_param * 2
            + batch_size * seq_len * self.d_ff * bytes_per_param
        )
        activations_mb = (self.num_layers * per_layer_acts_bytes) / (1024 * 1024)
        estimated_peak_mb = weights_mb + activations_mb

        return {
            "status": "ANALYTICAL_ESTIMATE",
            "precision": self.precision,
            "bytes_per_param": bytes_per_param,
            "backbone_parameters": backbone_params,
            "total_parameters": total_params,
            "weights_memory_mb": round(weights_mb, 2),
            "estimated_activations_mb": round(activations_mb, 2),
            "estimated_peak_memory_mb": round(estimated_peak_mb, 2),
            "note": "Analytical estimate; distinct from measured OS RSS or CUDA VRAM.",
        }


@dataclass(frozen=True)
class LargeLanguageEncoderConfig(LanguageEncoderConfig):
    """Canonical configuration for large (512.9M parameter) language encoder.

    Backbone parameter breakdown (d_model=1280, num_layers=24, num_heads=20, d_ff=5120):
      Embeddings: 32,000 * 1,280 = 40,960,000
      Per Layer: 4*1280^2 + 2*1280*5120 + 2*1280 = 6,553,600 + 13,107,200 + 2,560 = 19,663,360
      24 Layers: 24 * 19,663,360 = 471,920,640
      Final Norm: 1,280
      Tied MLM Bias: 32,000
      Total Backbone = 512,913,920 parameters (~512.91M).
      With capability heads: 513,247,751 parameters (~513.25M).
    """

    d_model: int = 1280
    num_layers: int = 24
    num_heads: int = 20
    d_ff: int = 5120
    max_sequence_length: int = 1024
    vocab_size: int = DEFAULT_TARGET_VOCAB_SIZE
    dropout: float = 0.1
    norm_type: str = "rmsnorm"
    pos_encoding: str = "rope"
    activation: str = "gelu"
    tie_embeddings: bool = True
    precision: str = "bf16"
    seed: int = 42
    gradient_checkpointing: bool = True


def _gelu(x: np.ndarray) -> np.ndarray:
    """Gaussian Error Linear Unit approximation."""
    res = 0.5 * x * (1.0 + np.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * np.power(x, 3))))
    return np.asarray(res, dtype=np.float32)


def _rmsnorm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Root Mean Square Layer Normalization."""
    variance = np.mean(np.square(x), axis=-1, keepdims=True)
    res = x / np.sqrt(variance + eps) * weight
    return np.asarray(res, dtype=np.float32)


INIT_STD = 0.02  # GPT-2 / BERT initialisation scale


def _apply_rope(
    q: np.ndarray, k: np.ndarray, seq_len: int, head_dim: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Applies Rotary Position Embeddings (RoPE) to query and key states.

    Uses canonical split-half formulation:
      rotate_half(x) = [-x[..., d//2:], x[..., :d//2]]
      freqs = 1.0 / (10000.0 ** (2i / d)) for i in [0, d//2)
      cos_full = concat([cos, cos], axis=-1)
      sin_full = concat([sin, sin], axis=-1)
    ensuring each half is rotated with its matching frequency component.
    """
    pos = np.arange(seq_len)[:, None]
    dim_indices = np.arange(0, head_dim, 2)[None, :]
    freqs = 1.0 / (10000.0 ** (dim_indices / head_dim))
    angles = pos * freqs  # (seq_len, head_dim // 2)

    cos = np.cos(angles)  # (seq_len, head_dim // 2)
    sin = np.sin(angles)  # (seq_len, head_dim // 2)

    def rotate_half(x: np.ndarray) -> np.ndarray:
        x1 = x[..., :head_dim // 2]
        x2 = x[..., head_dim // 2:]
        return np.concatenate((-x2, x1), axis=-1)

    # Both halves share frequency component i in split-half rotation
    cos_full = np.concatenate([cos, cos], axis=-1)[None, :, None, :]  # (1, seq_len, 1, head_dim)
    sin_full = np.concatenate([sin, sin], axis=-1)[None, :, None, :]

    q_rot = (q * cos_full) + (rotate_half(q) * sin_full)
    k_rot = (k * cos_full) + (rotate_half(k) * sin_full)
    return q_rot, k_rot


class RandomlyInitializedTransformerEncoder:
    """Real, randomly initialized 110M parameter bidirectional Transformer encoder.

    Implements:
    - Pure CPU-capable NumPy forward pass for validation, smoke tests, and profiling
    - Reproducible initialization from random seed
    - Shape, parameter count, and finite output verification
    - Multi-task output heads (MLM, NLI, Paraphrase, Semantic Similarity, Span QA)
    - Attention mask support ensuring padded tokens cannot corrupt representations
    - Strict prohibition on model weight updates
    """

    def __init__(self, config: Optional[LanguageEncoderConfig] = None) -> None:
        self.config = config or LanguageEncoderConfig()
        self.readiness_state = ModelReadinessState.RANDOMLY_INITIALIZED
        self.backbone_parameter_count = self.config.calculate_backbone_parameter_count()
        self.total_parameter_count = self.config.calculate_parameter_count(include_heads=True)
        # Default parameter_count preserves existing contract (backbone parameter count 109.56M)
        self.parameter_count = self.backbone_parameter_count

        # Seeded PRNG for reproducible random initialization
        self.rng = np.random.default_rng(self.config.seed)
        self.weights: Dict[str, np.ndarray] = self._init_weights()
        self.weights_sha256 = self._compute_weights_hash()

    def _init_weights(self) -> Dict[str, np.ndarray]:
        """Initializes all model weights using standard scaled Gaussian distributions."""
        weights: Dict[str, np.ndarray] = {}
        d = self.config.d_model
        d_ff = self.config.d_ff
        std = 1.0 / math.sqrt(d)

        # 1. Input embedding matrix (V, d)
        weights["token_embeddings"] = self.rng.normal(
            0.0, std, (self.config.vocab_size, d)
        ).astype(np.float32)

        # 2. Transformer layers (12 layers)
        for layer_idx in range(self.config.num_layers):
            pfx = f"layer_{layer_idx}"
            # Attention projections (4 * d * d)
            weights[f"{pfx}.attn_q"] = self.rng.normal(0.0, std, (d, d)).astype(np.float32)
            weights[f"{pfx}.attn_k"] = self.rng.normal(0.0, std, (d, d)).astype(np.float32)
            weights[f"{pfx}.attn_v"] = self.rng.normal(0.0, std, (d, d)).astype(np.float32)
            weights[f"{pfx}.attn_o"] = self.rng.normal(0.0, std, (d, d)).astype(np.float32)

            # Pre-RMSNorm weights (initialized to 1.0)
            weights[f"{pfx}.attn_norm"] = np.ones(d, dtype=np.float32)
            weights[f"{pfx}.ffn_norm"] = np.ones(d, dtype=np.float32)

            # FFN projections (W1: d -> d_ff, W2: d_ff -> d)
            weights[f"{pfx}.ffn_w1"] = self.rng.normal(0.0, std, (d, d_ff)).astype(np.float32)
            weights[f"{pfx}.ffn_w2"] = self.rng.normal(
                0.0, 1.0 / math.sqrt(d_ff), (d_ff, d)
            ).astype(np.float32)

        # 3. Final RMSNorm
        weights["final_norm"] = np.ones(d, dtype=np.float32)

        # 4. Tied MLM head bias
        weights["mlm_bias"] = np.zeros(self.config.vocab_size, dtype=np.float32)

        # 5. Multi-task capability heads
        # 3-Way NLI head (d -> 256 -> 3)
        weights["nli_w1"] = self.rng.normal(0.0, std, (d, 256)).astype(np.float32)
        weights["nli_b1"] = np.zeros(256, dtype=np.float32)
        weights["nli_w2"] = self.rng.normal(0.0, 1.0 / math.sqrt(256), (256, 3)).astype(np.float32)
        weights["nli_b2"] = np.zeros(3, dtype=np.float32)

        # Paraphrase head (d -> 1: binary logit)
        weights["para_w"] = self.rng.normal(0.0, std, (d, 1)).astype(np.float32)
        weights["para_b"] = np.zeros(1, dtype=np.float32)

        # Distinct Semantic Similarity head (d -> 1: continuous similarity score)
        weights["sim_w"] = self.rng.normal(0.0, std, (d, 1)).astype(np.float32)
        weights["sim_b"] = np.zeros(1, dtype=np.float32)

        # QA span head (d -> 2: start logit, end logit)
        weights["qa_w"] = self.rng.normal(0.0, std, (d, 2)).astype(np.float32)
        weights["qa_b"] = np.zeros(2, dtype=np.float32)

        return weights

    def _compute_weights_hash(self) -> str:
        """Computes deterministic SHA-256 hash of all model weight arrays."""
        hasher = hashlib.sha256()
        for key in sorted(self.weights.keys()):
            hasher.update(key.encode("utf-8"))
            hasher.update(self.weights[key].tobytes())
        return hasher.hexdigest()

    def forward(
        self,
        token_ids: Union[List[List[int]], np.ndarray],
        attention_mask: Optional[Union[List[List[int]], np.ndarray]] = None,
    ) -> Dict[str, np.ndarray]:
        """Executes a bounded, CPU-capable forward pass producing finite representations.

        Args:
            token_ids: Array of shape (batch_size, seq_len) with integer token IDs.
            attention_mask: Optional binary array of shape (batch_size, seq_len),
                where 1 indicates a valid token and 0 indicates a padded token.
        """
        arr = np.asarray(token_ids, dtype=np.int64)
        if arr.ndim == 1:
            arr = arr[None, :]
        batch_size, seq_len = arr.shape

        if seq_len > self.config.max_sequence_length:
            raise SequenceLengthExceededError(
                f"Sequence length {seq_len} exceeds max capacity {self.config.max_sequence_length}"
            )

        # Validate and prepare additive attention mask: 0.0 for valid, -1e4 for pad
        mask_additive: Optional[np.ndarray] = None
        if attention_mask is not None:
            mask_arr = np.asarray(attention_mask, dtype=np.float32)
            if mask_arr.ndim == 1:
                mask_arr = mask_arr[None, :]
            if mask_arr.shape != (batch_size, seq_len):
                exp_shape = (batch_size, seq_len)
                raise ValueError(
                    f"attention_mask shape {mask_arr.shape} must match input shape {exp_shape}"
                )
            # (batch_size, 1, 1, seq_len) broadcasts across num_heads and queries
            mask_additive = (1.0 - mask_arr[:, None, None, :]) * -1e4

        d = self.config.d_model
        num_heads = self.config.num_heads
        head_dim = d // num_heads

        # 1. Embedding lookup (B, S, d)
        x = self.weights["token_embeddings"][arr]

        # 2. Forward through Transformer layers
        for layer_idx in range(self.config.num_layers):
            pfx = f"layer_{layer_idx}"

            # Pre-RMSNorm before attention
            normed_x = _rmsnorm(x, self.weights[f"{pfx}.attn_norm"])

            # Linear projections
            q = np.dot(normed_x, self.weights[f"{pfx}.attn_q"])
            k = np.dot(normed_x, self.weights[f"{pfx}.attn_k"])
            v = np.dot(normed_x, self.weights[f"{pfx}.attn_v"])

            # Reshape for multi-head attention: (B, S, H, D_h)
            q = q.reshape(batch_size, seq_len, num_heads, head_dim)
            k = k.reshape(batch_size, seq_len, num_heads, head_dim)
            v = v.reshape(batch_size, seq_len, num_heads, head_dim)

            # Apply RoPE positional rotation
            q_rot, k_rot = _apply_rope(q, k, seq_len, head_dim)

            # Transpose to (B, H, S, D_h)
            q_t = np.transpose(q_rot, (0, 2, 1, 3))
            k_t = np.transpose(k_rot, (0, 2, 1, 3))
            v_t = np.transpose(v, (0, 2, 1, 3))

            # Scaled dot-product attention
            scores = np.matmul(q_t, np.transpose(k_t, (0, 1, 3, 2))) / math.sqrt(head_dim)
            if mask_additive is not None:
                scores = scores + mask_additive

            # Softmax along last axis with numerical stability
            exp_scores = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
            attn_probs = exp_scores / (np.sum(exp_scores, axis=-1, keepdims=True) + 1e-9)

            attn_out = np.matmul(attn_probs, v_t)  # (B, H, S, D_h)
            attn_out = np.transpose(attn_out, (0, 2, 1, 3)).reshape(batch_size, seq_len, d)

            # Output projection and residual connection
            attn_proj = np.dot(attn_out, self.weights[f"{pfx}.attn_o"])
            x = x + attn_proj

            # Pre-RMSNorm before FFN
            normed_ffn = _rmsnorm(x, self.weights[f"{pfx}.ffn_norm"])
            ffn_hidden = _gelu(np.dot(normed_ffn, self.weights[f"{pfx}.ffn_w1"]))
            ffn_out = np.dot(ffn_hidden, self.weights[f"{pfx}.ffn_w2"])
            x = x + ffn_out

        # 3. Final normalization
        hidden_states = _rmsnorm(x, self.weights["final_norm"])  # (B, S, d)

        # 4. Pooled [CLS] representation (first token)
        cls_rep = hidden_states[:, 0, :]  # (B, d)

        # 5. Multi-task capability head forward passes
        # MLM Head: tied embedding weights + bias
        emb_t = self.weights["token_embeddings"].T
        mlm_logits = np.dot(hidden_states, emb_t) + self.weights["mlm_bias"]

        # 3-Way NLI Head
        nli_h = np.maximum(0.0, np.dot(cls_rep, self.weights["nli_w1"]) + self.weights["nli_b1"])
        nli_logits = np.dot(nli_h, self.weights["nli_w2"]) + self.weights["nli_b2"]  # (B, 3)

        # Paraphrase Head (binary probability in [0, 1])
        para_logit = np.dot(cls_rep, self.weights["para_w"]) + self.weights["para_b"]
        para_prob = 1.0 / (1.0 + np.exp(-para_logit))  # (B, 1)

        # Distinct Semantic Similarity Head (continuous similarity score in [0, 1])
        sim_logit = np.dot(cls_rep, self.weights["sim_w"]) + self.weights["sim_b"]
        similarity_score = 1.0 / (1.0 + np.exp(-sim_logit))  # (B, 1)

        # QA Span Head (start and end logits per token)
        qa_logits = np.dot(hidden_states, self.weights["qa_w"]) + self.weights["qa_b"]  # (B, S, 2)

        # Assert all output arrays are strictly finite
        for name, tensor in [
            ("hidden_states", hidden_states),
            ("cls_rep", cls_rep),
            ("mlm_logits", mlm_logits),
            ("nli_logits", nli_logits),
            ("para_prob", para_prob),
            ("similarity_score", similarity_score),
            ("qa_logits", qa_logits),
        ]:
            if not np.all(np.isfinite(tensor)):
                raise ValueError(f"Non-finite values detected in forward pass output: '{name}'")

        return {
            "hidden_states": hidden_states,
            "cls_embedding": cls_rep,
            "mlm_logits": mlm_logits,
            "nli_logits": nli_logits,
            "paraphrase_prob": para_prob,
            "similarity_score": similarity_score,
            "qa_logits": qa_logits,
        }

    def train_step(self, *args: Any, **kwargs: Any) -> None:
        """Mandatory prohibition barrier preventing any model training or weight updates."""
        assert_training_authorized("neural model backpropagation and weight updates")
        raise TrainingExecutionProhibitedError(
            "ABSOLUTE TRAINING PROHIBITION: The agent has no authority to execute training, "
            "perform backpropagation, or update model weights."
        )

    def save_untrained_checkpoint(self, target_path: Union[str, Path]) -> Path:
        """Saves randomly initialized architecture state and configuration to disk."""
        dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        meta = {
            "readiness_state": self.readiness_state.value,
            "model_id": "laris-language-encoder-compact-untrained",
            "parameter_count": self.parameter_count,
            "backbone_parameter_count": self.backbone_parameter_count,
            "total_parameter_count": self.total_parameter_count,
            "weights_sha256": self.weights_sha256,
            "config": {
                "vocab_size": self.config.vocab_size,
                "d_model": self.config.d_model,
                "num_layers": self.config.num_layers,
                "num_heads": self.config.num_heads,
                "d_ff": self.config.d_ff,
                "seed": self.config.seed,
            },
        }

        with open(dest, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return dest


# ---------------------------------------------------------------------------
# PyTorch Real Neural Model Backend (when torch is available)
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    TORCH_AVAILABLE = True

    class PyTorchTransformerEncoder(nn.Module):  # type: ignore[misc]
        """Real PyTorch Transformer encoder with autograd and GPU capability.

        Instantiated strictly from random initialization (no pretrained weights).
        Contains strict prohibition barrier on training steps.
        """

        def __init__(self, config: Optional[LanguageEncoderConfig] = None) -> None:
            super().__init__()
            self.config = config or LanguageEncoderConfig()
            self.readiness_state = ModelReadinessState.RANDOMLY_INITIALIZED

            d = self.config.d_model
            d_ff = self.config.d_ff
            v = self.config.vocab_size

            torch.manual_seed(self.config.seed)  # before any parameter exists

            # 1. Embeddings
            self.token_embeddings = nn.Embedding(v, d)

            # 2. Layers
            self.layers = nn.ModuleList([
                _PyTorchTransformerLayer(d, self.config.num_heads, d_ff)
                for _ in range(self.config.num_layers)
            ])

            # 3. Final RMSNorm
            self.final_norm = _PyTorchRMSNorm(d)

            # 4. MLM bias (tied embeddings)
            self.mlm_bias = nn.Parameter(torch.zeros(v))

            # 5. Multi-task heads
            self.nli_head = nn.Sequential(
                nn.Linear(d, 256),
                nn.ReLU(),
                nn.Linear(256, 3),
            )
            self.para_head = nn.Linear(d, 1)
            self.sim_head = nn.Linear(d, 1)
            self.qa_head = nn.Linear(d, 2)

            self._init_parameters()
            self.gradient_checkpointing = getattr(self.config, "gradient_checkpointing", False)
            self.eval()

        def _init_parameters(self) -> None:
            """GPT-2 style init: N(0, 0.02), zero biases, residual projections scaled.

            The embedding is also the tied MLM output matrix, so the PyTorch default N(0, 1)
            would give logits with a standard deviation near 28 and an initial loss of ~540
            instead of about ln(vocab_size).
            """
            std = INIT_STD
            residual_std = std / math.sqrt(2 * self.config.num_layers)
            nn.init.normal_(self.token_embeddings.weight, mean=0.0, std=std)
            for name, module in self.named_modules():
                if isinstance(module, nn.Linear):
                    residual = name.endswith(("o_proj", "ffn_w2"))
                    nn.init.normal_(module.weight, mean=0.0, std=residual_std if residual else std)
                    if module.bias is not None:
                        nn.init.zeros_(module.bias)

        def forward(
            self,
            token_ids: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
            training_pass: bool = False,
        ) -> Dict[str, torch.Tensor]:
            """Forward pass for inference/profiling or authorized training."""
            if training_pass:
                assert_training_authorized("PyTorch neural model forward pass with gradients")
                return self._forward_impl(token_ids, attention_mask=attention_mask)
            with torch.no_grad():
                return self._forward_impl(token_ids, attention_mask=attention_mask)

        def _forward_impl(
            self,
            token_ids: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
        ) -> Dict[str, torch.Tensor]:
            batch_size, seq_len = token_ids.shape
            x = self.token_embeddings(token_ids)

            for layer in self.layers:
                if (
                    self.gradient_checkpointing
                    and self.training
                    and hasattr(torch.utils, "checkpoint")
                ):
                    x = torch.utils.checkpoint.checkpoint(
                        layer, x, attention_mask, use_reentrant=False
                    )
                else:
                    x = layer(x, attention_mask=attention_mask)

            hidden_states = self.final_norm(x)
            cls_rep = hidden_states[:, 0, :]

            # Heads
            mlm_logits = F.linear(hidden_states, self.token_embeddings.weight, self.mlm_bias)
            nli_logits = self.nli_head(cls_rep)
            para_prob = torch.sigmoid(self.para_head(cls_rep))
            similarity_score = torch.sigmoid(self.sim_head(cls_rep))
            qa_logits = self.qa_head(hidden_states)

            return {
                "hidden_states": hidden_states,
                "cls_embedding": cls_rep,
                "mlm_logits": mlm_logits,
                "nli_logits": nli_logits,
                "paraphrase_prob": para_prob,
                "similarity_score": similarity_score,
                "qa_logits": qa_logits,
            }

        def train_step(self, *args: Any, **kwargs: Any) -> None:
            """Barrier preventing unauthorized model training or weight updates."""
            assert_training_authorized("PyTorch neural model backpropagation and weight updates")

    class _PyTorchRMSNorm(nn.Module):  # type: ignore[misc]
        def __init__(self, dim: int, eps: float = 1e-6) -> None:
            super().__init__()
            self.eps = eps
            self.weight = nn.Parameter(torch.ones(dim))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            var = x.pow(2).mean(dim=-1, keepdim=True)
            return x * torch.rsqrt(var + self.eps) * self.weight

    class _PyTorchTransformerLayer(nn.Module):  # type: ignore[misc]
        def __init__(self, d_model: int, num_heads: int, d_ff: int) -> None:
            super().__init__()
            self.d_model = d_model
            self.num_heads = num_heads
            self.head_dim = d_model // num_heads

            self.attn_norm = _PyTorchRMSNorm(d_model)
            self.q_proj = nn.Linear(d_model, d_model, bias=False)
            self.k_proj = nn.Linear(d_model, d_model, bias=False)
            self.v_proj = nn.Linear(d_model, d_model, bias=False)
            self.o_proj = nn.Linear(d_model, d_model, bias=False)

            self.ffn_norm = _PyTorchRMSNorm(d_model)
            self.ffn_w1 = nn.Linear(d_model, d_ff, bias=False)
            self.ffn_w2 = nn.Linear(d_ff, d_model, bias=False)

        def forward(
            self,
            x: torch.Tensor,
            attention_mask: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            b, s, _ = x.shape
            # Pre-RMSNorm
            norm_x = self.attn_norm(x)
            q = self.q_proj(norm_x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)
            k = self.k_proj(norm_x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)
            v = self.v_proj(norm_x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)

            if hasattr(F, "scaled_dot_product_attention"):
                if attention_mask is not None:
                    # attention_mask: (b, s), expand to (b, 1, 1, s) boolean mask
                    attn_mask = attention_mask[:, None, None, :] == 1
                    attn_out = F.scaled_dot_product_attention(q, k, v, attn_mask=attn_mask)
                else:
                    attn_out = F.scaled_dot_product_attention(q, k, v)
                attn_out = attn_out.transpose(1, 2).contiguous().view(b, s, self.d_model)
            else:
                scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
                if attention_mask is not None:
                    # (b, 1, 1, s)
                    mask = (1.0 - attention_mask[:, None, None, :].float()) * -1e4
                    scores = scores + mask
                attn = F.softmax(scores, dim=-1)
                attn_out = (
                    torch.matmul(attn, v).transpose(1, 2).contiguous().view(b, s, self.d_model)
                )
            x = x + self.o_proj(attn_out)

            # Pre-RMSNorm FFN
            norm_ffn = self.ffn_norm(x)
            ffn_out = self.ffn_w2(F.gelu(self.ffn_w1(norm_ffn)))
            x = x + ffn_out
            return x

except ImportError:
    TORCH_AVAILABLE = False

    class PyTorchTransformerEncoder:  # type: ignore[no-redef]
        """PyTorch neural model path for autograd/GPU execution."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "PyTorch is not installed in the current environment. "
                "Install PyTorch with GPU support to use PyTorchTransformerEncoder."
            )

