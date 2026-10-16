"""Unit and regression tests for synthetic contradiction benchmarks and comparability fixtures.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, ADR-004, and Issue #94:
- Validates synthetic scientific contradiction benchmark cases
- Asserts 100% evidence citation rate on all detected conflicts
- Verifies zero false contradictions on incomparable experimental setups
"""

from __future__ import annotations

import pytest

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.reasoning import (
    ConflictBenchmarkReport,
    ConflictEvaluationBenchmark,
    ConflictType,
    ContradictionBenchmarkCase,
    StudyFinding,
)
from laris.reasoning.conflict_detector import ConditionAwareConflictDetector
from laris.reasoning.schemas import ComparativeCell, ComparativeMatrix


@pytest.fixture
def benchmark_harness() -> ConflictEvaluationBenchmark:
    """Provides a fresh ConflictEvaluationBenchmark instance."""
    return ConflictEvaluationBenchmark()


def test_synthetic_benchmark_suite_generation(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies generated benchmark suite integrity, non-empty findings, and coordinates."""
    suite = benchmark_harness.generate_benchmark_suite()
    assert len(suite) >= 5

    for case in suite:
        assert case.case_id.startswith("case-")
        assert len(case.scenario_description) > 0
        assert case.finding_a is not None
        assert case.finding_b is not None

        # Mandatory evidence coordinates
        assert len(case.finding_a.evidence_coordinates) >= 1
        assert len(case.finding_b.evidence_coordinates) >= 1

        for coord in case.finding_a.evidence_coordinates + case.finding_b.evidence_coordinates:
            assert isinstance(coord, EvidenceCoordinate)
            assert len(coord.document_sha256) == 64
            assert coord.page_number >= 1
            assert len(coord.verbatim_snippet) > 0


def test_benchmark_execution_and_accuracy(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies that the full synthetic benchmark achieves 100% accuracy and 0 false positives."""
    report: ConflictBenchmarkReport = benchmark_harness.run_benchmark()

    assert report.total_cases >= 5
    assert report.matched_cases == report.total_cases
    assert report.unmatched_cases == 0
    assert report.false_positives == 0
    assert report.accuracy == 1.0
    assert report.evidence_citation_rate == 1.0
    assert report.passed is True

    # Check detail lines
    assert all(detail.startswith("PASS:") for detail in report.details)


def test_benchmark_detects_false_positive_rejection(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies that injecting an unheralded discrepancy triggers failure detection."""
    coord = benchmark_harness._create_synthetic_coordinate("doc-synthetic", "Snippet text")
    f_a = StudyFinding(
        finding_id="fa-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.9,
        evidence_coordinates=[coord],
    )
    f_b = StudyFinding(
        finding_id="fb-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.5,  # Significant drop -> will yield DIRECT_EMPIRICAL_CONTRADICTION
        evidence_coordinates=[coord],
    )

    # We tell benchmark we expected NO conflict, but there IS one
    corrupted_case = ContradictionBenchmarkCase(
        case_id="case-fail-expected-none",
        scenario_description="Injected mismatch expecting no conflict",
        finding_a=f_a,
        finding_b=f_b,
        expected_conflict_type=None,
        expected_is_genuine=False,
    )

    report = benchmark_harness.run_benchmark([corrupted_case])
    assert report.total_cases == 1
    assert report.matched_cases == 0
    assert report.unmatched_cases == 1
    assert report.false_positives == 1
    assert report.passed is False
    assert any("FAIL:" in d for d in report.details)


def test_benchmark_detects_wrong_conflict_type(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies that detecting wrong conflict type fails the benchmark."""
    coord = benchmark_harness._create_synthetic_coordinate("doc-synthetic", "Snippet text")
    f_a = StudyFinding(
        finding_id="fa-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.9,
        evidence_coordinates=[coord],
    )
    f_b = StudyFinding(
        finding_id="fb-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.5,
        evidence_coordinates=[coord],
    )

    # Tells benchmark we expected APPARENT_CONFLICT_INCOMPARABLE, but it is DIRECT
    wrong_type_case = ContradictionBenchmarkCase(
        case_id="case-fail-wrong-type",
        scenario_description="Expecting wrong conflict type",
        finding_a=f_a,
        finding_b=f_b,
        expected_conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
        expected_is_genuine=False,
    )

    report = benchmark_harness.run_benchmark([wrong_type_case])
    assert report.passed is False
    assert report.unmatched_cases == 1


def test_benchmark_detects_missing_conflict(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies that expecting a conflict when none occurs fails the benchmark."""
    coord = benchmark_harness._create_synthetic_coordinate("doc-synthetic", "Snippet text")
    f_a = StudyFinding(
        finding_id="fa-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.90,
        evidence_coordinates=[coord],
    )
    f_b = StudyFinding(
        finding_id="fb-test",
        document_id="doc-synthetic",
        method_name="MethodA",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.901,  # Identical -> no conflict
        evidence_coordinates=[coord],
    )

    missing_case = ContradictionBenchmarkCase(
        case_id="case-fail-missing",
        scenario_description="Expecting conflict but findings are identical",
        finding_a=f_a,
        finding_b=f_b,
        expected_conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
        expected_is_genuine=True,
    )

    report = benchmark_harness.run_benchmark([missing_case])
    assert report.passed is False
    assert report.unmatched_cases == 1


def test_conflict_detector_provenance_violation_raises(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies that findings without EvidenceCoordinates trigger ProvenanceViolationError."""
    detector = ConditionAwareConflictDetector()
    coord = benchmark_harness._create_synthetic_coordinate("doc-1", "Snippet")
    f_a = StudyFinding(
        finding_id="f-coord-1",
        document_id="doc-1",
        method_name="MethodX",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.9,
        evidence_coordinates=[coord],
    )
    f_b = StudyFinding(
        finding_id="f-coord-2",
        document_id="doc-2",
        method_name="MethodX",
        dataset_name="DS",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.5,
        evidence_coordinates=[coord],
    )
    # Clear evidence coordinates dynamically to test detector defence-in-depth
    object.__setattr__(f_a, "evidence_coordinates", [])
    object.__setattr__(f_b, "evidence_coordinates", [])
    cell = ComparativeCell(
        cell_id="cell-test",
        finding_a_id="f-coord-1",
        finding_b_id="f-coord-2",
        delta=0.4,
        is_comparable=True,
    )
    with pytest.raises(ProvenanceViolationError):
        detector.evaluate_cell(cell, f_a, f_b)


def test_detect_conflicts_handles_missing_finding_ids(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies detect_conflicts skips cells referencing missing findings gracefully."""
    detector = ConditionAwareConflictDetector()
    cell = ComparativeCell(
        cell_id="cell-orphan",
        finding_a_id="nonexistent-a",
        finding_b_id="nonexistent-b",
        delta=0.4,
        is_comparable=True,
    )
    matrix = ComparativeMatrix(
        matrix_id="matrix-orphan",
        target_task_or_domain="benchmark",
        findings=[],
        cells=[cell],
    )
    conflicts = detector.detect_conflicts(matrix)
    assert len(conflicts) == 0


def test_cross_method_superiority_edge_cases(
    benchmark_harness: ConflictEvaluationBenchmark,
) -> None:
    """Verifies cross-method superiority checks ignore disparate datasets or missing methods."""
    coord = benchmark_harness._create_synthetic_coordinate("doc-x", "Snippet")
    f1 = StudyFinding(
        finding_id="f1",
        document_id="doc-1",
        method_name="MethodA",
        dataset_name="Dataset1",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.9,
        evidence_coordinates=[coord],
    )
    f2 = StudyFinding(
        finding_id="f2",
        document_id="doc-2",
        method_name="MethodA",
        dataset_name="Dataset2",  # Different dataset -> hits line 188
        dataset_split="test",
        metric_name="acc",
        metric_value=0.5,
        evidence_coordinates=[coord],
    )
    # Same doc with two findings for the same method -> hits line 200 (m_a == m_b)
    f3 = StudyFinding(
        finding_id="f3",
        document_id="doc-1",
        method_name="MethodA",
        dataset_name="Dataset1",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.95,
        evidence_coordinates=[coord],
    )
    # Doc 3 has Dataset1 and acc, but only MethodA (not MethodB) -> hits line 212
    f4 = StudyFinding(
        finding_id="f4",
        document_id="doc-3",
        method_name="MethodB",
        dataset_name="Dataset1",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.8,
        evidence_coordinates=[coord],
    )
    f5 = StudyFinding(
        finding_id="f5",
        document_id="doc-4",
        method_name="MethodA",
        dataset_name="Dataset1",
        dataset_split="test",
        metric_name="acc",
        metric_value=0.85,
        evidence_coordinates=[coord],
    )
    matrix = ComparativeMatrix(
        matrix_id="matrix-edge-cases",
        target_task_or_domain="benchmark",
        findings=[f1, f2, f3, f4, f5],
        cells=[],
    )
    detector = ConditionAwareConflictDetector()
    conflicts = detector.detect_conflicts(matrix)
    assert len(conflicts) == 0

