"""Core primitives, schemas, and error hierarchies for LARIS."""

from laris.core.schemas import (
    EpistemicStatus,
    EvidenceCoordinate,
    ScientificClaim,
    ResearchGapClass,
    CalibratedScores,
    ValidationPlan,
    ResearchGap,
    TelemetrySnapshot,
)
from laris.core.errors import (
    LarisError,
    ProvenanceViolationError,
    EpistemicOverreachError,
    HardwareBudgetExceededError,
    ModuleContractViolationError,
    CyclicExecutionError,
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
