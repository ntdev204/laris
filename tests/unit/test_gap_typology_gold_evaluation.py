"""Unit and integration tests for gap typology evaluation suite and gold set.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, ADR-004, and Issue #95:
- Verifies comprehensive synthetic gold set covering all 12 GapClass categories
- Evaluates classification accuracy against gold standard scientific scenarios
- Verifies bounded-corpus guard enforcing refusal of global novelty claims
- Tests uncertainty calibration under sparse literature sampling
"""

from __future__ import annotations

import pytest

from laris.layers.layer7_reasoning import (
    CalibratedGapScores,
    CalibratedGapScoringEngine,
    CorpusScope,
    GapClass,
    GapTypologyEvaluationSuite,
    GapTypologyGoldCase,
)


@pytest.fixture
def eval_suite() -> GapTypologyEvaluationSuite:
    """Provides a fresh GapTypologyEvaluationSuite instance."""
    return GapTypologyEvaluationSuite()


def test_gold_set_generation(eval_suite: GapTypologyEvaluationSuite) -> None:
    """Verifies that the synthetic gold set generates cases covering all 12 gap classes."""
    cases = eval_suite.generate_gold_set()
    assert len(cases) >= 14

    covered_classes = {c.expected_class for c in cases}
    assert len(covered_classes) == 12
    for gap_class in GapClass:
        assert gap_class in covered_classes

    # Verify at least one bounded guard test case and one uncertainty calibration case
    guard_cases = [c for c in cases if c.should_refuse_global]
    assert len(guard_cases) >= 1

    unc_cases = [c for c in cases if c.expected_uncertainty_floor is not None]
    assert len(unc_cases) >= 1


def test_gold_set_evaluation_passes(eval_suite: GapTypologyEvaluationSuite) -> None:
    """Runs the full gold set evaluation and verifies 100% accuracy and guard adherence."""
    report = eval_suite.run_evaluation()

    assert report.total_cases >= 14
    assert report.accuracy == 1.0
    assert report.bounded_guard_adherence == 1.0
    assert report.uncertainty_calibration_adherence == 1.0
    assert report.passed is True
    assert len(report.failures) == 0

    # Verify confusion breakdown contains all 12 classes along the diagonal
    for gap_class in GapClass:
        cls_name = gap_class.value
        assert cls_name in report.confusion_breakdown
        assert report.confusion_breakdown[cls_name].get(cls_name, 0) >= 1


def test_evaluation_detects_misclassification(
    eval_suite: GapTypologyEvaluationSuite,
) -> None:
    """Verifies that a misclassified case is detected and fails the report."""
    corrupted_case = GapTypologyGoldCase(
        case_id="case-corrupted-class",
        expected_class=GapClass.KNOWLEDGE_GAP,  # Expect knowledge gap
        title="High VRAM Latency Breakdown",
        description="VRAM footprint latency hardware memory limits prevent deployment.",  # Resource
        scenario_domain="Edge Robotics",
    )

    report = eval_suite.run_evaluation([corrupted_case])
    assert report.passed is False
    assert report.accuracy == 0.0
    assert len(report.failures) == 1
    assert "Expected KNOWLEDGE_GAP" in report.failures[0]


def test_evaluation_detects_uncalibrated_uncertainty() -> None:
    """Verifies that uncertainty below the expected floor is detected and flagged."""
    # Custom mock engine that ignores sparse scope
    class MockEngine(CalibratedGapScoringEngine):
        def score_gap(self, *args, **kwargs) -> CalibratedGapScores:  # type: ignore[no-untyped-def]
            return CalibratedGapScores(
                novelty=0.8,
                grounding=0.8,
                feasibility=0.8,
                significance=0.8,
                uncertainty=0.05,  # Violates expected floor 0.20
                composite_score=0.8,
                corpus_bounded=True,
                is_global_claim=False,
            )

    suite = GapTypologyEvaluationSuite(scoring_engine=MockEngine())
    sparse_case = GapTypologyGoldCase(
        case_id="case-sparse-floor-violation",
        expected_class=GapClass.UNDEREXPLORED_RESEARCH_QUESTION,
        title="Sparse Test Case",
        description="Underexplored open question with scarce literature.",
        scenario_domain="Domain",
        corpus_scope=CorpusScope(scope_id="scope-sparse", document_count=2, is_bounded=True),
        expected_uncertainty_floor=0.20,
    )

    report = suite.run_evaluation([sparse_case])
    assert report.passed is False
    assert report.uncertainty_calibration_adherence == 0.0
    assert len(report.failures) == 1
    assert "below expected floor" in report.failures[0]


def test_evaluation_detects_bounded_guard_failure() -> None:
    """Verifies that failing to refuse global claims on a bounded corpus is caught."""
    # Custom mock engine that permits global novelty despite bounded scope
    class PermissiveEngine(CalibratedGapScoringEngine):
        def score_gap(self, *args, **kwargs) -> CalibratedGapScores:  # type: ignore[no-untyped-def]
            return CalibratedGapScores(
                novelty=0.9,
                grounding=0.9,
                feasibility=0.8,
                significance=0.9,
                uncertainty=0.1,
                composite_score=0.9,
                corpus_bounded=False,
                is_global_claim=True,
            )

    suite = GapTypologyEvaluationSuite(scoring_engine=PermissiveEngine())
    guard_case = GapTypologyGoldCase(
        case_id="case-guard-failure",
        expected_class=GapClass.METHODOLOGICAL_GAP,
        title="Algorithmic Limitation in Methodology",
        description="Algorithmic limitation and modeling technique.",
        scenario_domain="Domain",
        corpus_scope=CorpusScope(scope_id="scope-bounded", document_count=10, is_bounded=True),
        should_refuse_global=True,
    )

    report = suite.run_evaluation([guard_case])
    assert report.passed is False
    assert report.bounded_guard_adherence == 0.0
    assert len(report.failures) == 1
    assert "Failed to refuse global novelty claim" in report.failures[0]


def test_empty_evaluation_run(eval_suite: GapTypologyEvaluationSuite) -> None:
    """Verifies handling of empty case list."""
    report = eval_suite.run_evaluation([])
    assert report.total_cases == 0
    assert report.accuracy == 0.0
    assert report.passed is False
