"""Core primitives, schemas, and error hierarchies for LARIS."""

from laris.core.errors import (
    CyclicExecutionError,
    EpistemicOverreachError,
    HardwareBudgetExceededError,
    LarisError,
    ModuleContractViolationError,
    ProvenanceViolationError,
)
from laris.core.schemas import (
    CalibratedScores,
    EpistemicStatus,
    EvidenceCoordinate,
    ResearchGap,
    ResearchGapClass,
    ScientificClaim,
    TelemetrySnapshot,
    ValidationPlan,
)

__all__ = [
    "EpistemicStatus",
    "EvidenceCoordinate",
    "ScientificClaim",
    "ResearchGapClass",
    "CalibratedScores",
    "ValidationPlan",
    "ResearchGap",
    "TelemetrySnapshot",
    "LarisError",
    "ProvenanceViolationError",
    "EpistemicOverreachError",
    "HardwareBudgetExceededError",
    "ModuleContractViolationError",
    "CyclicExecutionError",
]
