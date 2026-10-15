"""Layer 2: Semantic Intelligence & Relational Logic.

Provides Natural Language Inference (NLI), semantic equivalence, coreference resolution,
and discourse parsing conforming to Boundary C (MOD-SEM-001).
"""

from laris.layers.layer2_semantic.calibration import (
    BENCHMARK_VERSION,
    EXIT_GATE_MACRO_F1_THRESHOLD,
    SCIENTIFIC_NLI_BENCHMARK_FIXTURES,
    BenchmarkNLIPair,
    NLICalibrationMetrics,
    NLICalibrationReport,
    evaluate_nli_calibration,
)
from laris.layers.layer2_semantic.discourse import (
    CAUSAL_CUES,
    CONCESSIVE_CUES,
    CONTRAST_CUES,
    ELABORATION_CUES,
    TEMPORAL_CUES,
    DiscourseGraph,
    DiscourseGraphEdge,
    ScientificDiscourseParser,
)
from laris.layers.layer2_semantic.engine import (
    DIRECT_NEGATIONS,
    SCIENTIFIC_OPPOSITES,
    DeterministicScientificNLIEngine,
)
from laris.layers.layer2_semantic.relations import (
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
from laris.layers.layer2_semantic.schemas import (
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

__all__ = [
    "NLILabel",
    "SentencePairInput",
    "NLIProbabilities",
    "NLIOutput",
    "NLIPairBatch",
    "NLIOutputBatch",
    "NLIEngineContract",
    "DeterministicScientificNLIEngine",
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
    "SCIENTIFIC_NLI_BENCHMARK_FIXTURES",
    "NLICalibrationMetrics",
    "NLICalibrationReport",
    "evaluate_nli_calibration",
]
