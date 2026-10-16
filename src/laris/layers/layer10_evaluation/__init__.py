"""Layer 10 Evaluation, Feedback & Learning.

Adheres to DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #71:
- Versioned capability benchmark execution on frozen immutable evaluation sets
- Automated scientific error taxonomy (provenance, epistemic, extraction, reasoning, system)
- Regression threshold gates and historical release baseline comparison
- Offline evaluation isolation preventing training set contamination
"""

from laris.core.errors import (
    BenchmarkContaminationError,
    BenchmarkRegressionError,
)
from laris.layers.layer10_evaluation.benchmark_runner import (
    BenchmarkRunner,
)
from laris.layers.layer10_evaluation.error_taxonomy import (
    ScientificErrorTaxonomy,
)
from laris.layers.layer10_evaluation.feedback_mining import (
    ExpertFeedbackRecord,
    FeedbackMiningRepository,
    FeedbackSource,
    HardNegativeSample,
    HardNegativeStrategy,
    ReviewerDecision,
)
from laris.layers.layer10_evaluation.schemas import (
    BenchmarkBaseline,
    BenchmarkItem,
    BenchmarkRunReport,
    BenchmarkSuiteType,
    ErrorSeverity,
    EvaluationRunRequest,
    FrozenBenchmarkManifest,
    RegressionThreshold,
    ScientificErrorCategory,
    ScientificErrorRecord,
)

__all__ = [
    "BenchmarkContaminationError",
    "BenchmarkRegressionError",
    "ScientificErrorCategory",
    "ErrorSeverity",
    "BenchmarkSuiteType",
    "ScientificErrorRecord",
    "BenchmarkItem",
    "FrozenBenchmarkManifest",
    "RegressionThreshold",
    "BenchmarkBaseline",
    "EvaluationRunRequest",
    "BenchmarkRunReport",
    "ScientificErrorTaxonomy",
    "BenchmarkRunner",
    "ReviewerDecision",
    "FeedbackSource",
    "HardNegativeStrategy",
    "ExpertFeedbackRecord",
    "HardNegativeSample",
    "FeedbackMiningRepository",
]
