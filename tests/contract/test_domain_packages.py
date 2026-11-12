"""Contract tests for domain-based packages (ADR-011, ADR-012)."""

import importlib
from pathlib import Path

import pytest

DOMAINS = [
    "laris.shared.core",
    "laris.research.corpus",
    "laris.shared.language",
    "laris.shared.scientific",
    "laris.shared.graph",
    "laris.shared.retrieval",
    "laris.research.reasoning",
    "laris.research.orchestration",
    "laris.model.execution",
    "laris.research.evaluation",
    "laris.research.reporting",
]


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_package_importable(domain: str) -> None:
    """Verifies that every domain package can be directly imported."""
    mod = importlib.import_module(domain)
    assert mod is not None


def test_no_numbered_layer_directories_exist() -> None:
    """Verifies no legacy 'layers' or numbered packages exist in src (ADR-012)."""
    src_laris = Path(__file__).resolve().parent.parent.parent / "src"
    numbered_dirs = [
        p.name
        for p in src_laris.iterdir()
        if p.is_dir() and (p.name == "layers" or p.name.startswith("layer"))
    ]
    assert numbered_dirs == [], f"Found forbidden numbered layer directories: {numbered_dirs}"




def test_core_domain_exports():
    """Verifies core contracts."""
    from laris.shared.core import EvidenceCoordinate, LarisError, ModuleContractViolationError
    assert EvidenceCoordinate is not None
    assert LarisError is not None
    assert ModuleContractViolationError is not None


def test_corpus_domain_exports():
    """Verifies corpus contracts."""
    from laris.research.corpus import (
        CorpusIngestionPipeline,
        CorpusManifest,
        DatasetPartitionEngine,
        DeduplicationEngine,
        normalize_scientific_text,
    )
    assert CorpusIngestionPipeline is not None
    assert normalize_scientific_text is not None
    assert DeduplicationEngine is not None
    assert DatasetPartitionEngine is not None
    assert CorpusManifest is not None


def test_language_domain_exports():
    """Verifies language contracts."""
    from laris.shared.language import (
        CompactSentenceEncoder,
        STEMSubwordTokenizer,
    )
    from laris.shared.retrieval.bm25 import BM25RetrievalBaseline

    assert STEMSubwordTokenizer is not None
    assert CompactSentenceEncoder is not None
    assert BM25RetrievalBaseline is not None


@pytest.mark.parametrize(
    "module",
    [
        "laris.shared.language.tokenization.tokenizer",
        "laris.shared.language.tokenization.trainer",
        "laris.shared.language.encoder.transformer",
        "laris.shared.language.encoder.sentence_encoder",
        "laris.shared.language.encoder.config_handoff",
        "laris.shared.language.loading.dataloader",
        "laris.research.language.training.trainer",
        "laris.research.language.training.profiling",
        "laris.research.language.training.artifacts",
        "laris.shared.language.tokenization.stem_benchmark",
        "laris.shared.retrieval.bm25",
        "laris.shared.retrieval.baseline_comparison",
    ],
)
def test_language_functional_subpackages_importable(module: str) -> None:
    """Functional sub-packages (ADR-013) expose their modules at the new paths."""
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize(
    "legacy",
    ["tokenizer", "tokenizer_trainer", "neural", "encoder", "dataloader", "trainer", "bm25"],
)
def test_legacy_flat_language_modules_are_gone(legacy: str) -> None:
    """Flat modules moved into sub-packages must not linger beside them."""
    language_dir = Path(__file__).resolve().parents[2] / "src" / "laris" / "shared" / "language"
    assert not (language_dir / f"{legacy}.py").exists()


def test_scientific_domain_exports():
    """Verifies scientific contracts."""
    from laris.shared.scientific import (
        HeadingIndependentLimitationDetector,
        ScientificDiscourseExtractor,
        STEMUnitNormalizer,
    )
    assert ScientificDiscourseExtractor is not None
    assert HeadingIndependentLimitationDetector is not None
    assert STEMUnitNormalizer is not None


def test_graph_domain_exports():
    """Verifies graph contracts."""
    from laris.shared.graph import (
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
    """Verifies retrieval contracts."""
    from laris.shared.retrieval import (
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
    """Verifies reasoning contracts covering both NLI and gap reasoning."""
    from laris.research.reasoning import (
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
    """Verifies orchestration contracts."""
    from laris.research.orchestration import (
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
    """Verifies execution contracts."""
    from laris.model.execution import (
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
    """Verifies evaluation contracts."""
    from laris.research.evaluation import (
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
    """Verifies reporting contracts."""
    from laris.research.reporting import (
        EvidenceInspector,
        ManuscriptComposer,
        StructuredReportGenerator,
        StructuredResearchReport,
    )
    assert StructuredReportGenerator is not None
    assert EvidenceInspector is not None
    assert ManuscriptComposer is not None
    assert StructuredResearchReport is not None
