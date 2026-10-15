"""Layer 7 Research Reasoning and Gap Discovery Engine.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, and ADR-004.
"""

from laris.layers.layer7_reasoning.benchmark import (
    ConflictBenchmarkReport,
    ConflictEvaluationBenchmark,
    ContradictionBenchmarkCase,
)
from laris.layers.layer7_reasoning.conflict_detector import ConditionAwareConflictDetector
from laris.layers.layer7_reasoning.gap_classifier import RuleBasedGapClassifier
from laris.layers.layer7_reasoning.gap_evaluation import (
    GapEvaluationReport,
    GapTypologyEvaluationSuite,
    GapTypologyGoldCase,
)
from laris.layers.layer7_reasoning.gap_scorer import CalibratedGapScoringEngine
from laris.layers.layer7_reasoning.matrix_engine import ComparativeMatrixEngine
from laris.layers.layer7_reasoning.schemas import (
    CalibratedGapScores,
    CaveatSeverity,
    ComparabilityCaveat,
    ComparativeCell,
    ComparativeMatrix,
    ConflictRecord,
    ConflictType,
    CorpusScope,
    GapClass,
    MetricDirection,
    ResearchGap,
    StudyFinding,
    ValidationPlan,
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
    "ContradictionBenchmarkCase",
    "ConflictBenchmarkReport",
    "ConflictEvaluationBenchmark",
    "GapClass",
    "CalibratedGapScores",
    "ValidationPlan",
    "CorpusScope",
    "ResearchGap",
    "CalibratedGapScoringEngine",
    "RuleBasedGapClassifier",
    "GapTypologyGoldCase",
    "GapEvaluationReport",
    "GapTypologyEvaluationSuite",
]
