"""Layer 3: Scientific NLP & Discourse Intelligence.

Implements Boundary D (MOD-SCINLP-001) providing heading-agnostic scientific discourse entity
extraction (claims, methods, datasets, metrics, results, limitations, assumptions, formulas)
anchored to immutable physical evidence coordinates.
"""

from laris.layers.layer3_scinlp.benchmark import (
    StrippedHeadingBenchmark,
    StrippedHeadingBenchmarkMetrics,
    StrippedHeadingBenchmarkReport,
    StrippedHeadingBenchmarkSample,
    get_default_synthetic_benchmark_corpus,
)
from laris.layers.layer3_scinlp.extractor import ScientificDiscourseExtractor
from laris.layers.layer3_scinlp.limitations import (
    HeadingIndependentLimitationDetector,
    LimitationDetectionResult,
    compute_uncertainty_score,
    strip_headings,
)
from laris.layers.layer3_scinlp.schemas import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MIN_EXTRACTION_CONFIDENCE,
    AssumptionRecord,
    ClaimRecord,
    DatasetRecord,
    DiscourseEntityType,
    DiscourseExtractionSet,
    DiscourseExtractorContract,
    FormulaRecord,
    LimitationCategory,
    LimitationRecord,
    MethodRecord,
    MetricRecord,
    NegativeFindingRecord,
    ResultRecord,
)
from laris.layers.layer3_scinlp.units import (
    BaseDimension,
    DimensionalVector,
    EpistemicAssertion,
    EpistemicAssertionType,
    NormalizedQuantity,
    STEMUnitNormalizer,
    UnitSpec,
)

__all__ = [
    "DiscourseEntityType",
    "ClaimRecord",
    "MethodRecord",
    "DatasetRecord",
    "MetricRecord",
    "ResultRecord",
    "LimitationCategory",
    "LimitationRecord",
    "AssumptionRecord",
    "NegativeFindingRecord",
    "FormulaRecord",
    "DiscourseExtractionSet",
    "DiscourseExtractorContract",
    "ScientificDiscourseExtractor",
    "HeadingIndependentLimitationDetector",
    "LimitationDetectionResult",
    "compute_uncertainty_score",
    "strip_headings",
    "StrippedHeadingBenchmark",
    "StrippedHeadingBenchmarkMetrics",
    "StrippedHeadingBenchmarkReport",
    "StrippedHeadingBenchmarkSample",
    "get_default_synthetic_benchmark_corpus",
    "BaseDimension",
    "DimensionalVector",
    "UnitSpec",
    "NormalizedQuantity",
    "EpistemicAssertionType",
    "EpistemicAssertion",
    "STEMUnitNormalizer",
    "MIN_EXTRACTION_CONFIDENCE",
    "DEFAULT_CONFIDENCE_THRESHOLD",
]
