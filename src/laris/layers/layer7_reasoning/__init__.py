"""Layer 7 Research Reasoning and Gap Discovery Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, and ADR-004.
"""

from laris.layers.layer7_reasoning.conflict_detector import ConditionAwareConflictDetector
from laris.layers.layer7_reasoning.matrix_engine import ComparativeMatrixEngine
from laris.layers.layer7_reasoning.schemas import (
    CaveatSeverity,
    ComparabilityCaveat,
    ComparativeCell,
    ComparativeMatrix,
    ConflictRecord,
    ConflictType,
    MetricDirection,
    StudyFinding,
)

__all__ = [
    "MetricDirection",
    "CaveatSeverity",
    "ConflictType",
    "StudyFinding",
    "ComparabilityCaveat",
    "ComparativeCell",
    "ComparativeMatrix",
    "ConflictRecord",
    "ComparativeMatrixEngine",
    "ConditionAwareConflictDetector",
]
