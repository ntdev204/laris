"""Canonical configuration package for LARIS.

Adheres to DOC-SPEC-TRAIN-001, ADR-001, ADR-002, ADR-005, and Issue #215.
Provides centralized schemas, multi-tier precedence loading, hashing, and redaction.
"""

from laris.config.loader import (
    compute_config_hash,
    inspect_config,
    load_config,
)
from laris.config.schemas import (
    DataConfig,
    HardwareConfig,
    LarisConfig,
    ModelConfig,
    TrainingConfig,
)

__all__ = [
    "DataConfig",
    "HardwareConfig",
    "LarisConfig",
    "ModelConfig",
    "TrainingConfig",
    "compute_config_hash",
    "inspect_config",
    "load_config",
]
