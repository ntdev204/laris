"""Contract tests for domain-based packages (ADR-011, ADR-012)."""

import importlib
from pathlib import Path

import pytest

DOMAINS = [
    "core",
    "corpus",
    "language",
    "scientific",
    "graph",
    "retrieval",
    "reasoning",
    "orchestration",
    "execution",
    "evaluation",
    "reporting",
]


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_package_importable(domain: str) -> None:
    """Verifies that every domain package can be directly imported."""
    mod = importlib.import_module(f"laris.{domain}")
    assert mod is not None


def test_no_numbered_layer_directories_exist() -> None:
    """Verifies no legacy 'layers' or numbered packages exist in src/laris (ADR-012)."""
    src_laris = Path(__file__).resolve().parent.parent.parent / "src" / "laris"
    numbered_dirs = [
        p.name
        for p in src_laris.iterdir()
        if p.is_dir() and (p.name == "layers" or p.name.startswith("layer"))
    ]
    assert numbered_dirs == [], f"Found forbidden numbered layer directories: {numbered_dirs}"




def test_core_domain_exports():
    """Verifies laris.core contracts."""
    from laris.core import EvidenceCoordinate, LarisError, ModuleContractViolationError
    assert EvidenceCoordinate is not None
    assert LarisError is not None
    assert ModuleContractViolationError is not None


def test_corpus_domain_exports():
    """Verifies laris.corpus contracts."""
    from laris.corpus import (
        CorpusManifest,
        DatasetPartitionEngine,
        DeduplicationEngine,
        Layer0Pipeline,
        normalize_scientific_text,
    )
    assert Layer0Pipeline is not None
    assert normalize_scientific_text is not None
    assert DeduplicationEngine is not None
    assert DatasetPartitionEngine is not None
    assert CorpusManifest is not None


def test_language_domain_exports():
    """Verifies laris.language contracts."""
    from laris.language import (
        BM25RetrievalBaseline,
        CompactSentenceEncoder,
        STEMSubwordTokenizer,
    )
    assert STEMSubwordTokenizer is not None
    assert CompactSentenceEncoder is not None
    assert BM25RetrievalBaseline is not None


def test_scientific_domain_exports():
    """Verifies laris.scientific contracts."""
    from laris.scientific import (
        HeadingIndependentLimitationDetector,
        ScientificDiscourseExtractor,
        STEMUnitNormalizer,
    )
    assert ScientificDiscourseExtractor is not None
    assert HeadingIndependentLimitationDetector is not None
    assert STEMUnitNormalizer is not None


def test_graph_domain_exports():
    """Verifies laris.graph contracts."""
    from laris.graph import (
        BaseGraphPersistenceAdapter,
        EvidenceEdge,
        EvidenceGraph,
        EvidenceNode,
        SQLiteGraphPersistenceAdapter,
    )
    assert SQLiteGraphPersistenceAdapter is not None
    assert BaseGraphPersistenceAdapter is not None
    assert EvidenceGraph is not None
    assert EvidenceNode is not None
    assert EvidenceEdge is not None


def test_retrieval_domain_exports():
    """Verifies laris.retrieval contracts."""
    from laris.retrieval import (
        DenseVectorAdapter,
        GraphRetrievalAdapter,
        HybridRetrievalEngine,
        LexicalBM25Adapter,
        ReciprocalRankFusion,
    )
    assert HybridRetrievalEngine is not None
    assert ReciprocalRankFusion is not None
    assert LexicalBM25Adapter is not None
    assert DenseVectorAdapter is not None
    assert GraphRetrievalAdapter is not None


def test_reasoning_domain_exports():
    """Verifies laris.reasoning contracts covering both NLI and gap reasoning."""
    from laris.reasoning import (
        AdversarialCounterEvidenceEngine,
        CalibratedGapScoringEngine,
        ComparativeMatrixEngine,
        ConditionAwareConflictDetector,
        DeterministicScientificNLIEngine,
        NLILabel,
        RuleBasedGapClassifier,
        ScientificNLIEngine,
    )
    assert DeterministicScientificNLIEngine is not None
    assert ScientificNLIEngine is not None
    assert NLILabel is not None
    assert ComparativeMatrixEngine is not None
    assert ConditionAwareConflictDetector is not None
    assert RuleBasedGapClassifier is not None
    assert CalibratedGapScoringEngine is not None
    assert AdversarialCounterEvidenceEngine is not None


def test_orchestration_domain_exports():
    """Verifies laris.orchestration contracts."""
    from laris.orchestration import (
        BudgetGovernor,
        CycleDetector,
        DAGScheduler,
        DAGValidator,
        VerifierGate,
    )
    assert DAGScheduler is not None
    assert BudgetGovernor is not None
    assert CycleDetector is not None
    assert DAGValidator is not None
    assert VerifierGate is not None


def test_execution_domain_exports():
    """Verifies laris.execution contracts."""
    from laris.execution import (
        HardwareTelemetryEngine,
        HeadroomBudgetGovernor,
        SpecialistLRUCache,
        TaskRouter,
    )
    assert TaskRouter is not None
    assert HardwareTelemetryEngine is not None
    assert HeadroomBudgetGovernor is not None
    assert SpecialistLRUCache is not None


def test_evaluation_domain_exports():
    """Verifies laris.evaluation contracts."""
    from laris.evaluation import (
        BenchmarkRunner,
        DeterministicBaselineRouter,
        FeedbackMiningRepository,
        ScientificErrorTaxonomy,
    )
    assert BenchmarkRunner is not None
    assert ScientificErrorTaxonomy is not None
    assert FeedbackMiningRepository is not None
    assert DeterministicBaselineRouter is not None


def test_reporting_domain_exports():
    """Verifies laris.reporting contracts."""
    from laris.reporting import (
        EvidenceInspector,
        ManuscriptComposer,
        StructuredReportGenerator,
        StructuredResearchReport,
    )
    assert StructuredReportGenerator is not None
    assert EvidenceInspector is not None
    assert ManuscriptComposer is not None
    assert StructuredResearchReport is not None
