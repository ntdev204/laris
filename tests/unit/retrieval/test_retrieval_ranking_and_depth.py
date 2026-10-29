"""Unit tests and benchmarks for retrieval ranking, metadata filtering, and depth bounds.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, ADR-008, and ADR-010 (Issue #92):
- Deterministic ranking where promised across repeated evaluations
- 100% precision on metadata filters without predicate leakage
- Traversal depth bounds ($N <= 5$) and graceful rejection of runaway depths
- Graceful degradation and fallback behavior when dense backend is missing
- Multi-channel hybrid retrieval comparative benchmark
"""

import pytest

from laris.core.errors import RetrievalDepthExceededError
from laris.retrieval import (
    MAX_RETRIEVAL_DEPTH,
    MetadataFilter,
    RetrievalChannel,
    RetrievalEvaluationBenchmark,
    RetrievalQuery,
)


@pytest.fixture
def benchmark_runner() -> RetrievalEvaluationBenchmark:
    """Fixture providing initialized RetrievalEvaluationBenchmark."""
    return RetrievalEvaluationBenchmark()


def test_retrieval_benchmark_suite_overall(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Executes the full RetrievalEvaluationBenchmark and verifies all gates pass."""
    report = benchmark_runner.run_all()
    assert report.overall_status is True
    assert report.determinism_result.passed is True
    assert report.depth_bound_result.passed is True
    assert report.filter_result.passed is True
    assert report.fallback_result.passed is True

    # Verify every modality achieved valid MRR
    for mod_name, res in report.modality_results.items():
        assert res.passed is True
        assert res.mrr >= 0.5
        assert res.avg_latency_ms < 500.0


def test_multi_channel_vs_single_modality_ranking(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Compares multi-channel hybrid retrieval against single-modality channels."""
    engine = benchmark_runner.setup_engine()
    results = benchmark_runner.benchmark_modalities(engine)

    assert "lexical" in results
    assert "dense" in results
    assert "graph" in results
    assert "hybrid" in results

    hybrid_res = results["hybrid"]
    assert hybrid_res.passed is True
    assert hybrid_res.mrr >= 0.70
    assert hybrid_res.precision_at_1 >= 0.60


def test_ranking_determinism(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Verifies that retrieval rankings are 100% deterministic across repeated trials."""
    engine = benchmark_runner.setup_engine()
    det_res = benchmark_runner.benchmark_ranking_determinism(engine, trials=20)

    assert det_res.passed is True
    assert det_res.total_trials == 20
    assert det_res.identical_order_trials == 20
    assert det_res.determinism_rate == 1.0


def test_depth_bounds_and_escalation_enforcement(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Tests traversal depth bounds and ensures runaway depths are strictly rejected."""
    engine = benchmark_runner.setup_engine()
    depth_res = benchmark_runner.benchmark_depth_bounds(engine)

    assert depth_res.passed is True
    assert depth_res.violations_detected == 0
    assert depth_res.graceful_rejections == 2

    # Direct query test: depth ceiling violated
    with pytest.raises(RetrievalDepthExceededError, match="exceeds ceiling"):
        RetrievalQuery(text="test query", max_depth=MAX_RETRIEVAL_DEPTH + 1)


def test_metadata_filtering_precision(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Verifies 100% metadata filter compliance with zero leakage."""
    engine = benchmark_runner.setup_engine()
    filter_res = benchmark_runner.benchmark_filter_accuracy(engine)

    assert filter_res.passed is True
    assert filter_res.filter_leakage_count == 0
    assert filter_res.filter_precision == 1.0

    # Specific year window filter
    query_year = RetrievalQuery(
        text="quantum optomechanics",
        top_k=5,
        filter=MetadataFilter(min_year=2021, max_year=2023),
    )
    candidates = engine.retrieve(query_year)
    for c in candidates:
        year = c.metadata.get("year")
        if year is not None:
            assert 2021 <= year <= 2023


def test_dense_backend_missing_and_fallback(
    benchmark_runner: RetrievalEvaluationBenchmark,
) -> None:
    """Tests graceful fallback when dense encoder backend is absent or fails."""
    fallback_res = benchmark_runner.benchmark_fallback_robustness()
    assert fallback_res.passed is True
    assert fallback_res.dense_backend_missing_handled is True
    assert fallback_res.unregistered_channel_handled is True

    # Build engine without dense adapter
    lex_docs, _, graph, _ = benchmark_runner.build_synthetic_corpus()
    lex_adapter = benchmark_runner.setup_engine().get_adapter(RetrievalChannel.LEXICAL)
    graph_adapter = benchmark_runner.setup_engine().get_adapter(RetrievalChannel.GRAPH)

    assert lex_adapter is not None
    assert graph_adapter is not None

    partial_engine = benchmark_runner.setup_engine()
    partial_engine.unregister_adapter(RetrievalChannel.DENSE)

    assert not partial_engine.has_adapter(RetrievalChannel.DENSE)
    query = RetrievalQuery(text="quantum cavity optomechanics", top_k=5)

    # Retrieval succeeds using surviving channels
    candidates = partial_engine.retrieve(query)
    assert len(candidates) > 0
    for cand in candidates:
        assert cand.channel == RetrievalChannel.HYBRID
        assert "dense" not in cand.source_scores
        assert "lexical" in cand.source_scores or "graph" in cand.source_scores
