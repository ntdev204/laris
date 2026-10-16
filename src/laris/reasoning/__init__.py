"""Domain: Scientific Reasoning, Verification, and Gap Discovery.

Integrates:
1. Natural Language Inference (NLI) & Confidence Calibration (Conceptual Layer 2)
2. Discourse relations & Semantic Equivalence (Conceptual Layer 2)
3. Comparative Experimental Matrices & Condition-Aware Conflicts (Conceptual Layer 7)
4. 12-Class Research Gap Typology & Calibrated Gap Scoring (Conceptual Layer 7)
5. Adversarial Counter-Evidence Retrieval & Validation Planning (Conceptual Layer 7)

Adheres to DOC-SPEC-MOD-001 (Boundaries C & G), ADR-001, ADR-004, and ADR-011.
"""

from laris.reasoning.adversarial_engine import (
    AdversarialCounterEvidenceEngine,
    ValidationPlanGenerator,
)
from laris.reasoning.adversarial_evaluation import (
    AdversarialBenchmarkCase,
    AdversarialBenchmarkSuite,
    AdversarialEvaluationReport,
)
from laris.reasoning.benchmark import (
    ConflictBenchmarkReport,
    ConflictEvaluationBenchmark,
    ContradictionBenchmarkCase,
)
from laris.reasoning.calibration import (
    BENCHMARK_VERSION,
    EXIT_GATE_MACRO_F1_THRESHOLD,
    SCIENTIFIC_NLI_BENCHMARK_FIXTURES,
    SCIENTIFIC_NLI_TEST_FIXTURES,
    SCIENTIFIC_NLI_TRAIN_FIXTURES,
    SCIENTIFIC_NLI_VAL_FIXTURES,
    BenchmarkNLIPair,
    BenchmarkSplit,
    NLICalibrationMetrics,
    NLICalibrationReport,
    NLIFailureDiagnostic,
    NLIFailureType,
    SplitIsolationReport,
    classify_failure_type,
    evaluate_nli_calibration,
    verify_nli_split_isolation,
)
from laris.reasoning.conflict_detector import ConditionAwareConflictDetector
from laris.reasoning.discourse import (
    CAUSAL_CUES,
    CONCESSIVE_CUES,
    CONTRAST_CUES,
    ELABORATION_CUES,
    TEMPORAL_CUES,
    DiscourseGraph,
    DiscourseGraphEdge,
    ScientificDiscourseParser,
)
from laris.reasoning.gap_classifier import RuleBasedGapClassifier
from laris.reasoning.gap_evaluation import (
    GapEvaluationReport,
    GapTypologyEvaluationSuite,
    GapTypologyGoldCase,
)
from laris.reasoning.gap_scorer import CalibratedGapScoringEngine
from laris.reasoning.matrix_engine import ComparativeMatrixEngine
from laris.reasoning.nli_engine import (
    DIRECT_NEGATIONS,
    SCIENTIFIC_OPPOSITES,
    DeterministicScientificNLIEngine,
)
from laris.reasoning.nli_schemas import (
    LN_3,
    PROBABILITY_SUM_TOLERANCE,
    NLIEngineContract,
    NLILabel,
    NLIOutput,
    NLIOutputBatch,
    NLIPairBatch,
    NLIProbabilities,
    SentencePairInput,
)
from laris.reasoning.relations import (
    CORRELATIONAL_CUES,
    CoreferenceCluster,
    CoreferenceOutput,
    CoreferenceResolutionStatus,
    DiscourseRelationOutput,
    DiscourseRelationType,
    EquivalenceStatus,
    MentionSpan,
    SemanticEquivalenceOutput,
)
from laris.reasoning.schemas import (
    AdversarialRefutationResult,
    CalibratedGapScores,
    CandidateGapStatus,
    CaveatSeverity,
    ComparabilityCaveat,
    ComparativeCell,
    ComparativeMatrix,
    ConflictRecord,
    ConflictType,
    CorpusScope,
    CounterEvidenceItem,
    GapClass,
    MetricDirection,
    ResearchGap,
    StudyFinding,
    ValidationPlan,
)

# Canonical aliases
ScientificNLIEngine = DeterministicScientificNLIEngine

__all__ = [
    # Gap & Matrix Reasoning
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
    "CandidateGapStatus",
    "CounterEvidenceItem",
    "AdversarialRefutationResult",
    "AdversarialCounterEvidenceEngine",
    "ValidationPlanGenerator",
    "AdversarialBenchmarkCase",
    "AdversarialEvaluationReport",
    "AdversarialBenchmarkSuite",
    # NLI & Semantic Reasoning
    "NLILabel",
    "SentencePairInput",
    "NLIProbabilities",
    "NLIOutput",
    "NLIPairBatch",
    "NLIOutputBatch",
    "NLIEngineContract",
    "DeterministicScientificNLIEngine",
    "ScientificNLIEngine",
    "SCIENTIFIC_OPPOSITES",
    "DIRECT_NEGATIONS",
    "PROBABILITY_SUM_TOLERANCE",
    "LN_3",
    "EquivalenceStatus",
    "SemanticEquivalenceOutput",
    "CoreferenceResolutionStatus",
    "MentionSpan",
    "CoreferenceCluster",
    "CoreferenceOutput",
    "DiscourseRelationType",
    "DiscourseRelationOutput",
    "CORRELATIONAL_CUES",
    "CAUSAL_CUES",
    "CONTRAST_CUES",
    "CONCESSIVE_CUES",
    "TEMPORAL_CUES",
    "ELABORATION_CUES",
    "DiscourseGraphEdge",
    "DiscourseGraph",
    "ScientificDiscourseParser",
    "BENCHMARK_VERSION",
    "EXIT_GATE_MACRO_F1_THRESHOLD",
    "BenchmarkNLIPair",
    "BenchmarkSplit",
    "SCIENTIFIC_NLI_BENCHMARK_FIXTURES",
    "SCIENTIFIC_NLI_TEST_FIXTURES",
    "SCIENTIFIC_NLI_TRAIN_FIXTURES",
    "SCIENTIFIC_NLI_VAL_FIXTURES",
    "NLICalibrationMetrics",
    "NLICalibrationReport",
    "NLIFailureDiagnostic",
    "NLIFailureType",
    "SplitIsolationReport",
    "classify_failure_type",
    "evaluate_nli_calibration",
    "verify_nli_split_isolation",
]
