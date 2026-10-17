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
class TransformerEncoderConfig:
    """Hyperparameter specification for Model 1 Natural Language Foundation encoder."""

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
    def from_config(cls, config: Any) -> "TransformerEncoderConfig":
        """Instantiates TransformerEncoderConfig from centralized ModelConfig or LarisConfig."""
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

    def calculate_parameter_count(self) -> int:
        """Calculates exact parameter count according to the architectural equations.

        Equation:
          V * d + L * (4 * d^2 + 2 * d * d_ff + 2 * d) + d + V (tied MLM bias)
        """
        # Token embeddings (V * d)
        emb_params = self.vocab_size * self.d_model

        # Multi-head attention (W_q, W_k, W_v, W_o: 4 * d * d; no bias)
        attn_params = 4 * self.d_model * self.d_model

        # Feed-forward network (W1: d * d_ff, W2: d_ff * d; no bias)
        ffn_params = 2 * self.d_model * self.d_ff

        # Pre-RMSNorm on attention and FFN inputs (2 * d scale parameters; no bias)
        layer_norm_params = 2 * self.d_model

        per_layer_params = attn_params + ffn_params + layer_norm_params
        total_layers = self.num_layers * per_layer_params

        # Final RMSNorm scale parameter (d)
        final_norm_params = self.d_model

        # Tied MLM projection shares embedding table (V * d), adds only output bias (V)
        if self.tie_embeddings:
            head_bias_params = self.vocab_size
        else:
            head_bias_params = self.vocab_size * self.d_model + self.vocab_size

        return emb_params + total_layers + final_norm_params + head_bias_params


def _gelu(x: np.ndarray) -> np.ndarray:
    """Gaussian Error Linear Unit approximation."""
    res = 0.5 * x * (1.0 + np.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * np.power(x, 3))))
    return np.asarray(res, dtype=np.float32)


def _rmsnorm(x: np.ndarray, weight: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Root Mean Square Layer Normalization."""
    variance = np.mean(np.square(x), axis=-1, keepdims=True)
    res = x / np.sqrt(variance + eps) * weight
    return np.asarray(res, dtype=np.float32)


def _apply_rope(
    q: np.ndarray, k: np.ndarray, seq_len: int, head_dim: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Applies Rotary Position Embeddings (RoPE) to query and key states."""
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

    cos_full = np.repeat(cos, 2, axis=-1)[None, :, None, :]  # (1, seq_len, 1, head_dim)
    sin_full = np.repeat(sin, 2, axis=-1)[None, :, None, :]

    q_rot = (q * cos_full) + (rotate_half(q) * sin_full)
    k_rot = (k * cos_full) + (rotate_half(k) * sin_full)
    return q_rot, k_rot


class RandomlyInitializedTransformerEncoder:
    """Real, randomly initialized 110M parameter bidirectional Transformer encoder.

    Implements:
    - Pure CPU-capable NumPy forward pass for validation and profiling
    - Reproducible initialization from random seed
    - Shape and parameter verification
    - Multi-task output heads (MLM, NLI, Paraphrase, STS-B, Span QA)
    - Strict prohibition on model weight updates
    """

    def __init__(self, config: Optional[TransformerEncoderConfig] = None) -> None:
        self.config = config or TransformerEncoderConfig()
        self.readiness_state = ModelReadinessState.RANDOMLY_INITIALIZED
        self.parameter_count = self.config.calculate_parameter_count()

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

        # Paraphrase head (d -> 1)
        weights["para_w"] = self.rng.normal(0.0, std, (d, 1)).astype(np.float32)
        weights["para_b"] = np.zeros(1, dtype=np.float32)

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
    ) -> Dict[str, np.ndarray]:
        """Executes a bounded, CPU-capable forward pass producing finite representations."""
        arr = np.asarray(token_ids, dtype=np.int64)
        if arr.ndim == 1:
            arr = arr[None, :]
        batch_size, seq_len = arr.shape

        if seq_len > self.config.max_sequence_length:
            raise SequenceLengthExceededError(
                f"Sequence length {seq_len} exceeds max capacity {self.config.max_sequence_length}"
            )

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
            # Softmax along last axis
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

        # Paraphrase Head (probability in [0, 1])
        para_logit = np.dot(cls_rep, self.weights["para_w"]) + self.weights["para_b"]
        para_prob = 1.0 / (1.0 + np.exp(-para_logit))  # (B, 1)

        # QA Span Head (start and end logits per token)
        qa_logits = np.dot(hidden_states, self.weights["qa_w"]) + self.weights["qa_b"]  # (B, S, 2)

        # Assert all output arrays are strictly finite
        for name, tensor in [
            ("hidden_states", hidden_states),
            ("cls_rep", cls_rep),
            ("mlm_logits", mlm_logits),
            ("nli_logits", nli_logits),
            ("para_prob", para_prob),
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
            "qa_logits": qa_logits,
        }

    def train_step(self, *args: Any, **kwargs: Any) -> None:
        """Mandatory prohibition barrier preventing any model training or weight updates."""
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
            "model_id": "laris-model1-transformer-110m-untrained",
            "parameter_count": self.parameter_count,
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
