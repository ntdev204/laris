"""Canonical typed configuration schemas for LARIS.

Adheres to DOC-SPEC-TRAIN-001, ADR-001, ADR-002, ADR-005, and Issue #215.
Enforces:
- Strict Pydantic V2 validation and immutable domain invariants
- Protection against bypassing the 14.5 GB VRAM hardware safety ceiling
- Structural model invariants (Pre-RMSNorm, RoPE, GELU, tied MLM projection)
- Bounded parameter ranges and data ratio sum-to-one validation
"""

from typing import Set

from pydantic import BaseModel, Field, field_validator, model_validator

from laris.core.errors import HardwareBudgetExceededError

ALLOWED_EMBEDDING_DIMENSIONS: Set[int] = {384, 768}


class ModelConfig(BaseModel):
    """Configuration for Model 1 Natural Language Foundation Transformer encoder."""

    vocab_size: int = Field(default=32000, ge=100, le=128000)
    max_sequence_length: int = Field(default=512, ge=16, le=4096)
    d_model: int = Field(default=768)
    num_layers: int = Field(default=12, ge=1, le=48)
    num_heads: int = Field(default=12, ge=1, le=32)
    d_ff: int = Field(default=3072, ge=128)
    dropout: float = Field(default=0.1, ge=0.0, lt=1.0)
    norm_type: str = Field(default="rmsnorm")
    pos_encoding: str = Field(default="rope")
    activation: str = Field(default="gelu")
    tie_embeddings: bool = Field(default=True)
    precision: str = Field(default="bf16")
    seed: int = Field(default=42)

    @field_validator("d_model")
    @classmethod
    def validate_d_model(cls, v: int) -> int:
        if v not in ALLOWED_EMBEDDING_DIMENSIONS:
            allowed = sorted(ALLOWED_EMBEDDING_DIMENSIONS)
            raise ValueError(f"d_model {v} must be in {allowed}")
        return v

    @field_validator("precision")
    @classmethod
    def validate_precision(cls, v: str) -> str:
        if v not in {"bf16", "fp16", "fp32"}:
            raise ValueError(f"Invalid precision: '{v}'. Allowed: 'bf16', 'fp16', 'fp32'")
        return v

    @field_validator("norm_type")
    @classmethod
    def validate_norm_type(cls, v: str) -> str:
        if v != "rmsnorm":
            raise ValueError(f"Invariant violation: norm_type must be 'rmsnorm', got '{v}'")
        return v

    @field_validator("pos_encoding")
    @classmethod
    def validate_pos_encoding(cls, v: str) -> str:
        if v != "rope":
            raise ValueError(f"Invariant violation: pos_encoding must be 'rope', got '{v}'")
        return v

    @field_validator("activation")
    @classmethod
    def validate_activation(cls, v: str) -> str:
        if v != "gelu":
            raise ValueError(f"Invariant violation: activation must be 'gelu', got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_structural_harmony(self) -> "ModelConfig":
        if self.d_model % self.num_heads != 0:
            raise ValueError(
                f"d_model ({self.d_model}) must be divisible by num_heads ({self.num_heads})"
            )
        return self


class TrainingConfig(BaseModel):
    """Hyperparameters for model pretraining and multi-task representation learning."""

    batch_size: int = Field(default=32, ge=1)
    micro_batch_size: int = Field(default=4, ge=1)
    gradient_accumulation_steps: int = Field(default=8, ge=1)
    learning_rate: float = Field(default=1e-4, gt=0.0)
    warmup_steps: int = Field(default=2000, ge=0)
    max_steps: int = Field(default=100000, ge=1)
    loss_lambda_mlm: float = Field(default=0.35, gt=0.0)
    loss_lambda_nli: float = Field(default=0.25, gt=0.0)
    loss_lambda_para: float = Field(default=0.15, gt=0.0)
    loss_lambda_sim: float = Field(default=0.10, gt=0.0)
    loss_lambda_qa: float = Field(default=0.15, gt=0.0)

    @model_validator(mode="after")
    def validate_batch_hierarchy(self) -> "TrainingConfig":
        if self.micro_batch_size > self.batch_size:
            raise ValueError(
                f"micro_batch_size ({self.micro_batch_size}) cannot exceed "
                f"batch_size ({self.batch_size})"
            )
        return self


class DataConfig(BaseModel):
    """Configuration for dataset partitioning, leakage isolation, and coverage."""

    train_ratio: float = Field(default=0.80, gt=0.0, lt=1.0)
    val_ratio: float = Field(default=0.10, gt=0.0, lt=1.0)
    test_ratio: float = Field(default=0.10, gt=0.0, lt=1.0)
    partition_seed: str = Field(default="laris-partition-seed-v1")
    character_coverage: float = Field(default=0.9995, ge=0.90, le=1.0)

    @model_validator(mode="after")
    def validate_ratios_sum(self) -> "DataConfig":
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-5:
            raise ValueError(f"Split ratios must sum to 1.0, got {total:.6f}")
        return self


class HardwareConfig(BaseModel):
    """Hardware resource budgets and device allocations."""

    max_vram_gb: float = Field(default=14.5, gt=0.0)
    target_device: str = Field(default="cuda")

    @field_validator("max_vram_gb")
    @classmethod
    def enforce_safety_governor(cls, v: float) -> float:
        if v > 14.5:
            raise HardwareBudgetExceededError(
                f"Configured max_vram_gb ({v:.2f} GB) exceeds safe hardware envelope (14.5 GB) "
                "for RTX 5070 Ti under ADR-005."
            )
        return v


class LarisConfig(BaseModel):
    """Root configuration object uniting all system subsystems."""

    config_version: str = Field(default="1.0.0")
    environment: str = Field(default="development")
    model: ModelConfig = Field(default_factory=ModelConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
