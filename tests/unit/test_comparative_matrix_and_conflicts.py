"""Unit tests for comparable experimental matrix and conflict detection (Layer 7).

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, ADR-004, and Issue #62:
- Comparable experimental matrix records with condition and metric alignment
- Accurate identification of genuine contradictions vs incomparable study conditions
- Epistemic evidence coordinate anchoring for 100% of conflict records
"""

from __future__ import annotations

import pytest

from laris.core.errors import ModuleContractViolationError, ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.reasoning import (
    CaveatSeverity,
    ComparabilityCaveat,
    ComparativeCell,
    ComparativeMatrix,
    ComparativeMatrixEngine,
    ConditionAwareConflictDetector,
    ConflictRecord,
    ConflictType,
    MetricDirection,
    StudyFinding,
)


@pytest.fixture
def sample_coordinate() -> EvidenceCoordinate:
    """Fixture providing a verified EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id="coord-l7-001",
        document_id="doc-reasoning-2024",
        document_sha256="a" * 64,
        page_number=1,
        section_identifier="sec-experiments",
        paragraph_index=1,
        sentence_index=2,
        char_start=100,
        char_end=150,
        verbatim_snippet="Method X achieves 85.4% accuracy on Benchmark Y.",
        extraction_confidence=0.95,
    )


@pytest.fixture
def sample_finding_a(sample_coordinate: EvidenceCoordinate) -> StudyFinding:
    """Fixture providing finding A."""
    return StudyFinding(
        finding_id="finding-001",
        document_id="doc-reasoning-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.78,
        metric_direction=MetricDirection.HIGHER_IS_BETTER,
        condition_parameters={"batch_size": 32, "precision": "FP16"},
        evidence_coordinates=[sample_coordinate],
    )


# ==============================================================================
# 1. Schema Validation and Invariants
# ==============================================================================


def test_study_finding_validation(sample_coordinate: EvidenceCoordinate) -> None:
    """StudyFinding validates required non-empty fields and finite float values."""
    # Empty finding_id
    with pytest.raises(ModuleContractViolationError, match="finding_id must not be empty"):
        StudyFinding(
            finding_id="",
            document_id="doc-1",
            method_name="M",
            dataset_name="D",
            metric_name="acc",
            metric_value=0.9,
            evidence_coordinates=[sample_coordinate],
        )

    # Empty document_id
    with pytest.raises(ModuleContractViolationError, match="document_id must not be empty"):
        StudyFinding(
            finding_id="f1",
            document_id="",
            method_name="M",
            dataset_name="D",
            metric_name="acc",
            metric_value=0.9,
            evidence_coordinates=[sample_coordinate],
        )

    # Empty method_name
    with pytest.raises(ModuleContractViolationError, match="method_name must not be empty"):
        StudyFinding(
            finding_id="f1",
            document_id="doc-1",
            method_name="",
            dataset_name="D",
            metric_name="acc",
            metric_value=0.9,
            evidence_coordinates=[sample_coordinate],
        )

    # Empty dataset_name
    with pytest.raises(ModuleContractViolationError, match="dataset_name must not be empty"):
        StudyFinding(
            finding_id="f1",
            document_id="doc-1",
            method_name="M",
            dataset_name="",
            metric_name="acc",
            metric_value=0.9,
            evidence_coordinates=[sample_coordinate],
        )

    # Empty metric_name
    with pytest.raises(ModuleContractViolationError, match="metric_name must not be empty"):
        StudyFinding(
            finding_id="f1",
            document_id="doc-1",
            method_name="M",
            dataset_name="D",
            metric_name="",
            metric_value=0.9,
            evidence_coordinates=[sample_coordinate],
        )

    # NaN metric_value
    with pytest.raises(ModuleContractViolationError, match="metric_value must be a finite float"):
        StudyFinding(
            finding_id="f1",
            document_id="doc-1",
            method_name="M",
            dataset_name="D",
            metric_name="acc",
            metric_value=float("nan"),
            evidence_coordinates=[sample_coordinate],
        )

    # Empty evidence coordinates fails closed under ADR-004
    with pytest.raises(ProvenanceViolationError, match="lacks verified EvidenceCoordinate"):
        StudyFinding(
            finding_id="f1",
            document_id="doc-1",
            method_name="M",
            dataset_name="D",
            metric_name="acc",
            metric_value=0.9,
            evidence_coordinates=[],
        )


def test_conflict_record_validation(sample_coordinate: EvidenceCoordinate) -> None:
    """ConflictRecord enforces non-empty fields and mandatory evidence coordinates."""
    with pytest.raises(ProvenanceViolationError, match="lacks verified EvidenceCoordinate"):
        ConflictRecord(
            conflict_id="conf-001",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="f1",
            finding_b_id="f2",
            description="Contradiction",
            is_genuine_contradiction=True,
            evidence_coordinates=[],
        )


# ==============================================================================
# 2. Pairwise Comparison and Condition Alignment
# ==============================================================================


def test_compare_pair_identical_setup(sample_finding_a: StudyFinding) -> None:
    """Findings with identical metrics, datasets, and conditions are fully comparable."""
    engine = ComparativeMatrixEngine()
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-independent-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.76,
        metric_direction=MetricDirection.HIGHER_IS_BETTER,
        condition_parameters={"batch_size": 32, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is True
    assert len(cell.caveats) == 0
    assert cell.delta == pytest.approx(0.02, rel=1e-3)
    assert cell.ratio == pytest.approx(0.78 / 0.76, rel=1e-3)


def test_compare_pair_metric_mismatch(sample_finding_a: StudyFinding) -> None:
    """Different metrics result in is_comparable=False with METRIC_MISMATCH caveat."""
    engine = ComparativeMatrixEngine()
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="MRR",
        metric_value=0.75,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is False
    assert any(c.caveat_type == "METRIC_MISMATCH" for c in cell.caveats)


def test_compare_pair_dataset_mismatch(sample_finding_a: StudyFinding) -> None:
    """Different datasets result in is_comparable=False with DATASET_MISMATCH caveat."""
    engine = ComparativeMatrixEngine()
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="TREC-COVID",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.65,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is False
    assert any(c.caveat_type == "DATASET_MISMATCH" for c in cell.caveats)


def test_compare_pair_split_mismatch(sample_finding_a: StudyFinding) -> None:
    """Different dataset splits trigger DATASET_SPLIT_MISMATCH caveat."""
    engine = ComparativeMatrixEngine(strict_split_matching=True)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="validation",
        metric_name="NDCG@10",
        metric_value=0.82,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is False
    assert any(c.caveat_type == "DATASET_SPLIT_MISMATCH" for c in cell.caveats)


def test_compare_pair_condition_disparity(sample_finding_a: StudyFinding) -> None:
    """Different parameter conditions trigger CONDITION_DISPARITY caveat."""
    engine = ComparativeMatrixEngine(strict_condition_matching=False)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.74,
        condition_parameters={"batch_size": 128, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    # Under default strict_condition_matching=False, remains comparable with CAUTION caveat
    assert cell.is_comparable is True
    assert any(c.caveat_type == "CONDITION_DISPARITY" for c in cell.caveats)


def test_build_matrix_all_pairs(sample_finding_a: StudyFinding) -> None:
    """build_matrix generates all-pairs comparative cells across findings."""
    engine = ComparativeMatrixEngine()
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-2",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.75,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )
    finding_c = StudyFinding(
        finding_id="finding-003",
        document_id="doc-3",
        method_name="BM25Baseline",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.62,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    matrix = engine.build_matrix(
        "Scientific Information Retrieval",
        [sample_finding_a, finding_b, finding_c],
    )
    assert matrix.target_task_or_domain == "Scientific Information Retrieval"
    assert len(matrix.findings) == 3
    # 3 findings -> 3 * 2 / 2 = 3 cells
    assert len(matrix.cells) == 3


# ==============================================================================
# 3. Conflict and Contradiction Detection
# ==============================================================================


def test_detect_direct_empirical_contradiction(sample_finding_a: StudyFinding) -> None:
    """Direct contradiction detected when identical method scores differ significantly."""
    engine = ComparativeMatrixEngine()
    detector = ConditionAwareConflictDetector(discrepancy_threshold=0.05)

    # Finding B reports 0.60 vs Finding A's 0.78 (delta=0.18 >= 0.05)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-independent-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.60,
        condition_parameters={"batch_size": 32, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    matrix = engine.build_matrix("SciFact Retrieval", [sample_finding_a, finding_b])
    conflicts = detector.detect_conflicts(matrix)

    assert len(conflicts) == 1
    conf = conflicts[0]
    assert conf.conflict_type == ConflictType.DIRECT_EMPIRICAL_CONTRADICTION
    assert conf.is_genuine_contradiction is True
    assert len(conf.evidence_coordinates) >= 2


def test_detect_apparent_conflict_incomparable(sample_finding_a: StudyFinding) -> None:
    """Discrepancies arising from disparate splits/datasets flag as APPARENT_CONFLICT."""
    engine = ComparativeMatrixEngine()
    detector = ConditionAwareConflictDetector(discrepancy_threshold=0.05)

    # Finding B reports much lower score on validation split (incomparable)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="validation",
        metric_name="NDCG@10",
        metric_value=0.55,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    matrix = engine.build_matrix("SciFact Retrieval", [sample_finding_a, finding_b])
    conflicts = detector.detect_conflicts(matrix)

    assert len(conflicts) == 1
    conf = conflicts[0]
    assert conf.conflict_type == ConflictType.APPARENT_CONFLICT_INCOMPARABLE
    assert conf.is_genuine_contradiction is False
    assert any(c.caveat_type == "DATASET_SPLIT_MISMATCH" for c in conf.comparability_caveats)


def test_detect_cross_method_superiority_conflict(sample_coordinate: EvidenceCoordinate) -> None:
    """Conflicting claims regarding method superiority across papers trigger conflict."""
    # Paper 1: Method X (0.80) > Method Y (0.70)
    p1_mx = StudyFinding(
        finding_id="p1-mx",
        document_id="paper-alpha",
        method_name="MethodAlpha",
        dataset_name="SciRep",
        dataset_split="test",
        metric_name="F1",
        metric_value=0.80,
        evidence_coordinates=[sample_coordinate],
    )
    p1_my = StudyFinding(
        finding_id="p1-my",
        document_id="paper-alpha",
        method_name="MethodBeta",
        dataset_name="SciRep",
        dataset_split="test",
        metric_name="F1",
        metric_value=0.70,
        evidence_coordinates=[sample_coordinate],
    )

    # Paper 2: Method Y (0.85) > Method X (0.65)
    p2_mx = StudyFinding(
        finding_id="p2-mx",
        document_id="paper-beta",
        method_name="MethodAlpha",
        dataset_name="SciRep",
        dataset_split="test",
        metric_name="F1",
        metric_value=0.65,
        evidence_coordinates=[sample_coordinate],
    )
    p2_my = StudyFinding(
        finding_id="p2-my",
        document_id="paper-beta",
        method_name="MethodBeta",
        dataset_name="SciRep",
        dataset_split="test",
        metric_name="F1",
        metric_value=0.85,
        evidence_coordinates=[sample_coordinate],
    )

    engine = ComparativeMatrixEngine()
    detector = ConditionAwareConflictDetector(discrepancy_threshold=0.05)

    matrix = engine.build_matrix("SciRep Benchmarking", [p1_mx, p1_my, p2_mx, p2_my])
    conflicts = detector.detect_conflicts(matrix)

    superiority_conflicts = [
        c
        for c in conflicts
        if c.conflict_type == ConflictType.CROSS_METHOD_SUPERIORITY_CONTRADICTION
    ]
    assert len(superiority_conflicts) >= 1
    sup = superiority_conflicts[0]
    assert sup.is_genuine_contradiction is True
    assert "superior" in sup.description.lower()


def test_boundary_condition_discrepancy(sample_finding_a: StudyFinding) -> None:
    """Discrepancy across differing parameters flags as BOUNDARY_CONDITION_DISCREPANCY."""
    engine = ComparativeMatrixEngine(strict_condition_matching=False)
    detector = ConditionAwareConflictDetector(discrepancy_threshold=0.05)

    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.68,
        condition_parameters={"batch_size": 128, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )

    cell = engine.compare_pair(sample_finding_a, finding_b)
    conflict = detector.evaluate_cell(cell, sample_finding_a, finding_b)
    assert conflict is not None
    assert conflict.conflict_type == ConflictType.BOUNDARY_CONDITION_DISCREPANCY
    assert conflict.is_genuine_contradiction is True


def test_schema_contracts_and_empty_guards(sample_coordinate: EvidenceCoordinate) -> None:
    """Verifies all schema post_init empty field validations."""
    # ComparabilityCaveat
    with pytest.raises(ModuleContractViolationError, match="caveat_type must not be empty"):
        ComparabilityCaveat(caveat_type="", description="desc")
    with pytest.raises(ModuleContractViolationError, match="description must not be empty"):
        ComparabilityCaveat(caveat_type="TYPE", description="")

    # ComparativeCell
    with pytest.raises(ModuleContractViolationError, match="cell_id must not be empty"):
        ComparativeCell(cell_id="", finding_a_id="f1", finding_b_id="f2", is_comparable=True)
    with pytest.raises(ModuleContractViolationError, match="finding_a_id must not be empty"):
        ComparativeCell(cell_id="c1", finding_a_id="", finding_b_id="f2", is_comparable=True)
    with pytest.raises(ModuleContractViolationError, match="finding_b_id must not be empty"):
        ComparativeCell(cell_id="c1", finding_a_id="f1", finding_b_id="", is_comparable=True)

    # ComparativeMatrix
    with pytest.raises(ModuleContractViolationError, match="matrix_id must not be empty"):
        ComparativeMatrix(matrix_id="", target_task_or_domain="domain", findings=[], cells=[])
    with pytest.raises(
        ModuleContractViolationError, match="target_task_or_domain must not be empty"
    ):
        ComparativeMatrix(matrix_id="m1", target_task_or_domain="", findings=[], cells=[])

    # ConflictRecord
    with pytest.raises(ModuleContractViolationError, match="conflict_id must not be empty"):
        ConflictRecord(
            conflict_id="",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="f1",
            finding_b_id="f2",
            description="desc",
            is_genuine_contradiction=True,
            evidence_coordinates=[sample_coordinate],
        )
    with pytest.raises(ModuleContractViolationError, match="finding_a_id must not be empty"):
        ConflictRecord(
            conflict_id="c1",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="",
            finding_b_id="f2",
            description="desc",
            is_genuine_contradiction=True,
            evidence_coordinates=[sample_coordinate],
        )
    with pytest.raises(ModuleContractViolationError, match="finding_b_id must not be empty"):
        ConflictRecord(
            conflict_id="c1",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="f1",
            finding_b_id="",
            description="desc",
            is_genuine_contradiction=True,
            evidence_coordinates=[sample_coordinate],
        )
    with pytest.raises(ModuleContractViolationError, match="description must not be empty"):
        ConflictRecord(
            conflict_id="c1",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="f1",
            finding_b_id="f2",
            description="",
            is_genuine_contradiction=True,
            evidence_coordinates=[sample_coordinate],
        )


def test_matrix_engine_edge_cases(sample_finding_a: StudyFinding) -> None:
    """Verifies matrix engine strict condition matching and build_matrix validation."""
    engine_strict = ComparativeMatrixEngine(strict_condition_matching=True)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.74,
        condition_parameters={"batch_size": 128, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )
    cell = engine_strict.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is False

    # Metric direction mismatch
    finding_lower = StudyFinding(
        finding_id="finding-003",
        document_id="doc-other-2024",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.74,
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )
    cell_dir = engine_strict.compare_pair(sample_finding_a, finding_lower)
    assert cell_dir.is_comparable is False
    assert any(c.caveat_type == "METRIC_DIRECTION_MISMATCH" for c in cell_dir.caveats)

    # Empty target_task_or_domain in build_matrix
    with pytest.raises(
        ModuleContractViolationError, match="target_task_or_domain must not be empty"
    ):
        engine_strict.build_matrix("", [sample_finding_a])


def test_superiority_conflict_lower_is_better(sample_coordinate: EvidenceCoordinate) -> None:
    """Cross-method superiority conflict correctly handles LOWER_IS_BETTER metrics."""
    # Paper 1: Method Alpha (10.0 ms) < Method Beta (20.0 ms) -> Alpha is better
    p1_a = StudyFinding(
        finding_id="p1-a",
        document_id="p1",
        method_name="Alpha",
        dataset_name="LatencyBench",
        dataset_split="test",
        metric_name="latency_ms",
        metric_value=10.0,
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        evidence_coordinates=[sample_coordinate],
    )
    p1_b = StudyFinding(
        finding_id="p1-b",
        document_id="p1",
        method_name="Beta",
        dataset_name="LatencyBench",
        dataset_split="test",
        metric_name="latency_ms",
        metric_value=20.0,
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        evidence_coordinates=[sample_coordinate],
    )

    # Paper 2: Method Beta (8.0 ms) < Method Alpha (25.0 ms) -> Beta is better
    p2_a = StudyFinding(
        finding_id="p2-a",
        document_id="p2",
        method_name="Alpha",
        dataset_name="LatencyBench",
        dataset_split="test",
        metric_name="latency_ms",
        metric_value=25.0,
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        evidence_coordinates=[sample_coordinate],
    )
    p2_b = StudyFinding(
        finding_id="p2-b",
        document_id="p2",
        method_name="Beta",
        dataset_name="LatencyBench",
        dataset_split="test",
        metric_name="latency_ms",
        metric_value=8.0,
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        evidence_coordinates=[sample_coordinate],
    )

    engine = ComparativeMatrixEngine()
    detector = ConditionAwareConflictDetector()
    matrix = engine.build_matrix("Latency Testing", [p1_a, p1_b, p2_a, p2_b])
    conflicts = detector.detect_conflicts(matrix)

    sup = [
        c
        for c in conflicts
        if c.conflict_type == ConflictType.CROSS_METHOD_SUPERIORITY_CONTRADICTION
    ]
    assert len(sup) >= 1


def test_evaluate_cell_incomparable_small_delta(sample_finding_a: StudyFinding) -> None:
    """Incomparable cell with delta below threshold does not generate apparent conflict."""
    engine = ComparativeMatrixEngine()
    detector = ConditionAwareConflictDetector(discrepancy_threshold=0.05)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="validation",
        metric_name="NDCG@10",
        metric_value=0.781,
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )
    cell = engine.compare_pair(sample_finding_a, finding_b)
    conflict = detector.evaluate_cell(cell, sample_finding_a, finding_b)
    assert conflict is None


def test_strict_condition_matching_disparity(sample_finding_a: StudyFinding) -> None:
    """Disparity under strict_condition_matching sets severity to INCOMPARABLE."""
    engine = ComparativeMatrixEngine(strict_condition_matching=True)
    finding_b = StudyFinding(
        finding_id="finding-002",
        document_id="doc-other",
        method_name="DenseRetrieverV2",
        dataset_name="SciFact",
        dataset_split="test",
        metric_name="NDCG@10",
        metric_value=0.74,
        condition_parameters={"batch_size": 64, "precision": "FP16"},
        evidence_coordinates=sample_finding_a.evidence_coordinates,
    )
    cell = engine.compare_pair(sample_finding_a, finding_b)
    assert cell.is_comparable is False
    assert any(c.severity == CaveatSeverity.INCOMPARABLE for c in cell.caveats)


