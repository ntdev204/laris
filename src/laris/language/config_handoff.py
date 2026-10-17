"""Centralized configuration handoff catalog for Issue #215 (M11-CONFIG-001).

Adheres to DOC-SPEC-TRAIN-001, ADR-002, and Issue #217 (WP6).
Classifies:
- Tunable hyperparameters to be controlled by YAML configs in #215
- Immutable domain invariants that must NEVER be overridden or bypassed
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class ParameterClassification:
    """Audit entry classifying a parameter as tunable vs invariant."""

    name: str
    category: str  # "TUNABLE" or "INVARIANT"
    default_value: Any
    unit: str
    rationale: str
    issue_handoff: str = "#215"


# Authoritative inventory for Issue #215 Centralized Configuration System
TUNABLE_PARAMETER_INVENTORY_FOR_CONFIG: List[ParameterClassification] = [
    # Model 1 Architecture Tunables
    ParameterClassification(
        "vocab_size", "TUNABLE", 32000, "tokens", "Balanced bilingual vocabulary capacity"
    ),
    ParameterClassification(
        "max_sequence_length", "TUNABLE", 512, "tokens", "Maximum positional sequence context"
    ),
    ParameterClassification(
        "d_model", "TUNABLE", 768, "dim", "Hidden representation dimension (384 or 768)"
    ),
    ParameterClassification(
        "num_layers", "TUNABLE", 12, "layers", "Transformer encoder layer depth"
    ),
    ParameterClassification(
        "num_heads", "TUNABLE", 12, "heads", "Multi-head attention projections"
    ),
    ParameterClassification(
        "d_ff", "TUNABLE", 3072, "dim", "Intermediate FFN dimension (4 * d_model)"
    ),
    ParameterClassification(
        "dropout", "TUNABLE", 0.1, "ratio", "Attention and hidden activation dropout rate"
    ),
    ParameterClassification(
        "precision", "TUNABLE", "bf16", "dtype", "Native mixed-precision format (bf16/fp16)"
    ),
    ParameterClassification(
        "seed", "TUNABLE", 42, "integer", "PRNG seed for reproducible initialization"
    ),

    # Training & Optimization Tunables (for future authorized run)
    ParameterClassification(
        "batch_size", "TUNABLE", 32, "samples", "Effective optimization batch size"
    ),
    ParameterClassification(
        "micro_batch_size", "TUNABLE", 4, "samples", "Per-device forward pass micro-batch"
    ),
    ParameterClassification(
        "gradient_accumulation_steps", "TUNABLE", 8, "steps", "Gradient accumulation multiplier"
    ),
    ParameterClassification(
        "learning_rate", "TUNABLE", 1e-4, "float", "Peak AdamW learning rate"
    ),
    ParameterClassification(
        "warmup_steps", "TUNABLE", 2000, "steps", "Linear learning rate warmup schedule"
    ),
    ParameterClassification(
        "max_steps", "TUNABLE", 100000, "steps", "Total optimization steps limit"
    ),
    ParameterClassification(
        "loss_lambda_mlm", "TUNABLE", 0.35, "weight", "Multi-task mixture weight for MLM"
    ),
    ParameterClassification(
        "loss_lambda_nli", "TUNABLE", 0.25, "weight", "Multi-task mixture weight for 3-way NLI"
    ),
    ParameterClassification(
        "loss_lambda_para", "TUNABLE", 0.15, "weight", "Multi-task mixture weight for Paraphrase"
    ),
    ParameterClassification(
        "loss_lambda_sim", "TUNABLE", 0.10, "weight", "Multi-task mixture weight for STS-B"
    ),
    ParameterClassification(
        "loss_lambda_qa", "TUNABLE", 0.15, "weight", "Multi-task mixture weight for Reading QA"
    ),

    # Immutable Architectural Invariants (MUST NOT be overridden by config)
    ParameterClassification(
        "norm_type", "INVARIANT", "rmsnorm", "type", "Pre-RMSNorm scale without bias"
    ),
    ParameterClassification(
        "pos_encoding", "INVARIANT", "rope", "type", "Rotary position embeddings on Q/K"
    ),
    ParameterClassification(
        "activation", "INVARIANT", "gelu", "type", "Gaussian Error Linear Unit FFN"
    ),
    ParameterClassification(
        "tie_embeddings", "INVARIANT", True, "bool", "MLM output tied to token embeddings"
    ),
    ParameterClassification(
        "max_vram_gb", "INVARIANT", 14.5, "GB", "RTX 5070 Ti 16 GB hardware safety ceiling"
    ),
    ParameterClassification(
        "zero_test_leakage", "INVARIANT", True, "bool", "Evaluation split isolation invariant"
    ),
    ParameterClassification(
        "mandatory_training_ban", "INVARIANT", True, "bool", "No autonomous training execution"
    ),
]


def get_tunable_parameters() -> Dict[str, Any]:
    """Returns dictionary of default values for all tunable parameters."""
    return {
        p.name: p.default_value
        for p in TUNABLE_PARAMETER_INVENTORY_FOR_CONFIG
        if p.category == "TUNABLE"
    }


def get_immutable_invariants() -> Dict[str, Any]:
    """Returns dictionary of immutable architectural invariants."""
    return {
        p.name: p.default_value
        for p in TUNABLE_PARAMETER_INVENTORY_FOR_CONFIG
        if p.category == "INVARIANT"
    }
