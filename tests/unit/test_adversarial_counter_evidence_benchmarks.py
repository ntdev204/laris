"""Unit and integration tests for adversarial counter-evidence benchmark suite.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, ADR-004, and Issue #96:
- Verifies synthetic benchmark cases covering decisive refutation, unresolved disputes, and gaps
- Validates rejection of refuted gap candidates and preservation of evidence coordinate provenance
- Verifies uncertainty calibration when empirical disputes are detected
- Verifies validation plans are concrete, falsifiable, and measurable
"""

from __future__ import annotations

import pytest

from laris.core.schemas import EvidenceCoordinate
from laris.reasoning import (
    AdversarialBenchmarkCase,
    AdversarialBenchmarkSuite,
    CandidateGapStatus,
    ResearchGap,
    ValidationPlan,
    ValidationPlanGenerator,
)


@pytest.fixture
def benchmark_suite() -> AdversarialBenchmarkSuite:
    """Provides a fresh AdversarialBenchmarkSuite instance."""
    return AdversarialBenchmarkSuite()


def test_benchmark_cases_generation(benchmark_suite: AdversarialBenchmarkSuite) -> None:
    """Verifies that synthetic benchmark cases cover all required evaluation statuses."""
    cases = benchmark_suite.generate_benchmark_cases()
    assert len(cases) >= 12

    statuses = {case.expected_status for case in cases}
    assert CandidateGapStatus.REFUTED in statuses
    assert CandidateGapStatus.UNRESOLVED_DISPUTE in statuses
    assert CandidateGapStatus.CONFIRMED_GAP in statuses

    # Verify domains diversity
    domains = {case.scenario_domain for case in cases}
    assert len(domains) >= 8

    # Verify all refuted cases expect is_refuted=True
    for c in cases:
        if c.expected_status == CandidateGapStatus.REFUTED:
            assert c.expected_is_refuted is True
        else:
            assert c.expected_is_refuted is False


def test_adversarial_benchmark_evaluation_passes(
    benchmark_suite: AdversarialBenchmarkSuite,
) -> None:
    """Runs full benchmark suite and verifies 100% pass rates on all metrics."""
    report = benchmark_suite.run_evaluation()

    assert report.total_cases >= 12
    assert report.status_accuracy == 1.0
    assert report.plan_measurability_adherence == 1.0
    assert report.uncertainty_calibration_adherence == 1.0
    assert report.refuted_count >= 3
    assert report.disputed_count >= 3
    assert report.confirmed_count >= 4
    assert report.passed is True
    assert len(report.failures) == 0


def test_adversarial_benchmark_detects_status_mismatch(
    benchmark_suite: AdversarialBenchmarkSuite,
) -> None:
    """Verifies that unexpected status transitions are flagged as evaluation failures."""
    cases = benchmark_suite.generate_benchmark_cases()
    first_case = cases[0]

    # Invert expected status from REFUTED to CONFIRMED_GAP
    mismatched_case = AdversarialBenchmarkCase(
        case_id="adv-corrupted-status",
        candidate_gap=first_case.candidate_gap,
        counter_evidence=first_case.counter_evidence,
        expected_status=CandidateGapStatus.CONFIRMED_GAP,  # Deliberate mismatch
        expected_is_refuted=False,
        scenario_domain=first_case.scenario_domain,
    )

    report = benchmark_suite.run_evaluation([mismatched_case])
    assert report.passed is False
    assert report.status_accuracy == 0.0
    assert len(report.failures) == 1
    assert "Status mismatch" in report.failures[0]


def test_adversarial_benchmark_detects_uncertainty_violation(
    benchmark_suite: AdversarialBenchmarkSuite,
) -> None:
    """Verifies that failure to elevate uncertainty under dispute is flagged."""
    cases = benchmark_suite.generate_benchmark_cases()
    # Find an ambiguous/dispute case
    dispute_case = next(
        c for c in cases if c.expected_status == CandidateGapStatus.UNRESOLVED_DISPUTE
    )

    # Set an impossible minimum uncertainty floor of 0.99
    uncalibrated_case = AdversarialBenchmarkCase(
        case_id="adv-uncalibrated-uncertainty",
        candidate_gap=dispute_case.candidate_gap,
        counter_evidence=dispute_case.counter_evidence,
        expected_status=dispute_case.expected_status,
        expected_is_refuted=dispute_case.expected_is_refuted,
        scenario_domain=dispute_case.scenario_domain,
        expected_min_uncertainty=0.99,  # Engine sets 0.50, violating this floor
    )

    report = benchmark_suite.run_evaluation([uncalibrated_case])
    assert report.passed is False
    assert report.uncertainty_calibration_adherence == 0.0
    assert len(report.failures) == 1
    assert "below expected minimum" in report.failures[0]

    # Test ceiling violation as well
    ceiling_violation_case = AdversarialBenchmarkCase(
        case_id="adv-ceiling-violation",
        candidate_gap=dispute_case.candidate_gap,
        counter_evidence=dispute_case.counter_evidence,
        expected_status=dispute_case.expected_status,
        expected_is_refuted=dispute_case.expected_is_refuted,
        scenario_domain=dispute_case.scenario_domain,
        expected_max_uncertainty=0.40,  # Engine produces 0.50, violating maximum 0.40
    )
    rep_ceiling = benchmark_suite.run_evaluation([ceiling_violation_case])
    assert rep_ceiling.passed is False
    assert len(rep_ceiling.failures) == 1
    assert "exceeds expected maximum" in rep_ceiling.failures[0]


def test_adversarial_benchmark_detects_unmeasurable_validation_plan() -> None:
    """Verifies that unmeasurable or missing validation protocols are detected."""
    # Mock generator returning plan with insufficiently descriptive methodology (< 20 chars)
    class IncompletePlanGenerator(ValidationPlanGenerator):
        def generate_plan(self, gap: ResearchGap) -> ValidationPlan:
            return ValidationPlan(
                proposed_methodology="Too brief.",  # Valid per schema, but fails >= 20 char check
                required_datasets=["TestDataset"],
                expected_baselines=["TestBaseline"],
                evaluation_metrics=["TestMetric"],
            )

    suite = AdversarialBenchmarkSuite(plan_generator=IncompletePlanGenerator())
    cases = suite.generate_benchmark_cases()[:1]

    report = suite.run_evaluation(cases)
    assert report.passed is False
    assert report.plan_measurability_adherence == 0.0
    assert len(report.failures) == 1
    assert "measurability check" in report.failures[0]


def test_plan_measurability_criteria_edges(benchmark_suite: AdversarialBenchmarkSuite) -> None:
    """Verifies edge criteria in plan measurability verification."""
    case = benchmark_suite.generate_benchmark_cases()[0]

    # Too short methodology (< 20 chars)
    plan_short_meth = ValidationPlan(
        proposed_methodology="Methodology < 20",
        required_datasets=["Dataset"],
        expected_baselines=["Baseline"],
        evaluation_metrics=["Metric"],
    )
    assert benchmark_suite.verify_plan_measurability(plan_short_meth, case) is False

    # Missing expected metric
    case_with_exp_metric = AdversarialBenchmarkCase(
        case_id="case-exp-metric",
        candidate_gap=case.candidate_gap,
        counter_evidence=[],
        expected_status=CandidateGapStatus.CONFIRMED_GAP,
        expected_is_refuted=False,
        scenario_domain="Domain",
        expected_metrics=["SpecificUnachievedMetric"],
    )
    plan_valid = ValidationPlan(
        proposed_methodology="Adequate length description for proposed methodology experiment.",
        required_datasets=["Dataset"],
        expected_baselines=["Baseline"],
        evaluation_metrics=["OtherMetric"],
    )
    assert benchmark_suite.verify_plan_measurability(plan_valid, case_with_exp_metric) is False

    # Missing expected baseline
    case_with_exp_base = AdversarialBenchmarkCase(
        case_id="case-exp-base",
        candidate_gap=case.candidate_gap,
        counter_evidence=[],
        expected_status=CandidateGapStatus.CONFIRMED_GAP,
        expected_is_refuted=False,
        scenario_domain="Domain",
        expected_baselines=["SpecificUnachievedBaseline"],
    )
    assert benchmark_suite.verify_plan_measurability(plan_valid, case_with_exp_base) is False

    # Defensive edge: empty dataset list
    plan_empty_data = ValidationPlan(
        proposed_methodology="Adequate length description for proposed methodology experiment.",
        required_datasets=["Initial"],
        expected_baselines=["Baseline"],
        evaluation_metrics=["Metric"],
    )
    object.__setattr__(plan_empty_data, "required_datasets", [])
    assert benchmark_suite.verify_plan_measurability(plan_empty_data, case) is False

    # Defensive edge: empty baseline list
    plan_empty_base = ValidationPlan(
        proposed_methodology="Adequate length description for proposed methodology experiment.",
        required_datasets=["Dataset"],
        expected_baselines=["Initial"],
        evaluation_metrics=["Metric"],
    )
    object.__setattr__(plan_empty_base, "expected_baselines", [])
    assert benchmark_suite.verify_plan_measurability(plan_empty_base, case) is False

    # Defensive edge: empty metrics list
    plan_empty_metrics = ValidationPlan(
        proposed_methodology="Adequate length description for proposed methodology experiment.",
        required_datasets=["Dataset"],
        expected_baselines=["Baseline"],
        evaluation_metrics=["Initial"],
    )
    object.__setattr__(plan_empty_metrics, "evaluation_metrics", [])
    assert benchmark_suite.verify_plan_measurability(plan_empty_metrics, case) is False


def test_empty_adversarial_benchmark_run(
    benchmark_suite: AdversarialBenchmarkSuite,
) -> None:
    """Verifies handling of empty case list."""
    report = benchmark_suite.run_evaluation([])
    assert report.total_cases == 0
    assert report.status_accuracy == 0.0
    assert report.passed is False


def test_coordinate_provenance_integrity_in_benchmarks(
    benchmark_suite: AdversarialBenchmarkSuite,
) -> None:
    """Verifies that all counter-evidence items possess valid coordinate provenance."""
    cases = benchmark_suite.generate_benchmark_cases()
    for case in cases:
        for item in case.counter_evidence:
            coord = item.coordinate
            assert isinstance(coord, EvidenceCoordinate)
            assert coord.document_id.startswith(("paper-", "doc-"))
            assert len(coord.document_sha256) == 64
            assert coord.char_start >= 0
            assert coord.char_end > coord.char_start
            assert len(coord.verbatim_snippet) > 0
            assert coord.extraction_confidence > 0.0
