"""Unit and contract tests for adversarial counter-evidence search and validation plan generator.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, ADR-004, and Issue #64:
- Tests AdversarialCounterEvidenceEngine query synthesis and refutation lifecycle
- Validates rejection of refuted gap candidates and preservation of unresolved uncertainty
- Verifies ValidationPlanGenerator produces actionable, falsifiable validation protocols
"""

from __future__ import annotations

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer7_reasoning import (
    AdversarialCounterEvidenceEngine,
    AdversarialRefutationResult,
    CalibratedGapScores,
    CandidateGapStatus,
    CounterEvidenceItem,
    GapClass,
    ResearchGap,
    ValidationPlan,
    ValidationPlanGenerator,
)


@pytest.fixture
def sample_coordinate() -> EvidenceCoordinate:
    """Provides a valid synthetic EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id="coord-adv-001",
        document_id="paper-adv-2024",
        document_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        page_number=4,
        section_identifier="sec-experiments",
        paragraph_index=2,
        sentence_index=1,
        char_start=0,
        char_end=55,
        verbatim_snippet="Proposed method achieves 45 ms real-time inference.",
        extraction_confidence=0.99,
    )


@pytest.fixture
def sample_gap(sample_coordinate: EvidenceCoordinate) -> ResearchGap:
    """Provides a valid candidate ResearchGap instance."""
    scores = CalibratedGapScores(
        novelty=0.85,
        grounding=0.90,
        feasibility=0.75,
        significance=0.80,
        uncertainty=0.15,
        composite_score=0.82,
        corpus_bounded=True,
        is_global_claim=False,
    )
    plan = ValidationPlan(
        proposed_methodology="Test real-time inference latency.",
        required_datasets=["BenchmarkDataset"],
        expected_baselines=["StandardBaseline"],
        evaluation_metrics=["Latency_ms"],
    )
    return ResearchGap(
        gap_id="gap-adv-test-01",
        gap_class=GapClass.DEPLOYMENT_RESOURCE_GAP,
        title="Excessive Latency in Point Cloud Processing",
        description="Lidar segmentation requires over 100 ms, exceeding real-time requirements.",
        epistemic_rationale="No existing method operates under 50 ms.",
        supporting_evidence=[sample_coordinate],
        calibrated_scores=scores,
        validation_plan=plan,
    )


def test_candidate_gap_status_enum() -> None:
    """Verifies all values in CandidateGapStatus enum."""
    expected = {"CONFIRMED_GAP", "REFUTED", "PREVIOUSLY_ADDRESSED", "UNRESOLVED_DISPUTE"}
    actual = {s.value for s in CandidateGapStatus}
    assert actual == expected


def test_counter_evidence_item_contracts(sample_coordinate: EvidenceCoordinate) -> None:
    """Tests CounterEvidenceItem validation rules."""
    item = CounterEvidenceItem(
        coordinate=sample_coordinate,
        refutation_snippet="Method achieves 45 ms latency.",
        refutation_confidence=0.92,
        refuting_method_or_solution="FastPointNet",
    )
    assert item.refutation_confidence == 0.92
    assert item.refuting_method_or_solution == "FastPointNet"

    with pytest.raises(ModuleContractViolationError, match="refutation_snippet"):
        CounterEvidenceItem(
            coordinate=sample_coordinate,
            refutation_snippet="   ",
            refutation_confidence=0.90,
        )

    with pytest.raises(ModuleContractViolationError, match="must be within"):
        CounterEvidenceItem(
            coordinate=sample_coordinate,
            refutation_snippet="Snippet",
            refutation_confidence=1.5,
        )

    with pytest.raises(ModuleContractViolationError, match="must be a finite float"):
        CounterEvidenceItem(
            coordinate=sample_coordinate,
            refutation_snippet="Snippet",
            refutation_confidence=float("nan"),
        )


def test_adversarial_refutation_result_contracts() -> None:
    """Tests AdversarialRefutationResult validation rules."""
    res = AdversarialRefutationResult(
        gap_id="gap-01",
        status=CandidateGapStatus.CONFIRMED_GAP,
        generated_counter_queries=["query 1"],
        refutation_rationale="No counter evidence found.",
        updated_uncertainty=0.15,
        is_refuted=False,
    )
    assert res.status == CandidateGapStatus.CONFIRMED_GAP
    assert res.is_refuted is False

    with pytest.raises(ModuleContractViolationError, match="gap_id"):
        AdversarialRefutationResult(
            gap_id="",
            status=CandidateGapStatus.CONFIRMED_GAP,
            generated_counter_queries=["query 1"],
            refutation_rationale="Valid",
            updated_uncertainty=0.10,
        )

    with pytest.raises(ModuleContractViolationError, match="refutation_rationale"):
        AdversarialRefutationResult(
            gap_id="valid-id",
            status=CandidateGapStatus.CONFIRMED_GAP,
            generated_counter_queries=["query 1"],
            refutation_rationale="",
            updated_uncertainty=0.10,
        )

    with pytest.raises(ModuleContractViolationError, match="must be within"):
        AdversarialRefutationResult(
            gap_id="valid-id",
            status=CandidateGapStatus.CONFIRMED_GAP,
            generated_counter_queries=["query 1"],
            refutation_rationale="Rationale",
            updated_uncertainty=1.2,
        )

    with pytest.raises(ModuleContractViolationError, match="must be a finite float"):
        AdversarialRefutationResult(
            gap_id="valid-id",
            status=CandidateGapStatus.CONFIRMED_GAP,
            generated_counter_queries=["query 1"],
            refutation_rationale="Rationale",
            updated_uncertainty=float("nan"),
        )


def test_adversarial_counter_evidence_engine_thresholds() -> None:
    """Tests engine threshold initialization contracts."""
    engine = AdversarialCounterEvidenceEngine(
        refutation_threshold=0.80,
        ambiguity_threshold=0.30,
    )
    assert engine.refutation_threshold == 0.80
    assert engine.ambiguity_threshold == 0.30

    with pytest.raises(ModuleContractViolationError, match="strictly less than"):
        AdversarialCounterEvidenceEngine(
            refutation_threshold=0.50,
            ambiguity_threshold=0.50,
        )

    with pytest.raises(
        ModuleContractViolationError,
        match="refutation_threshold must be a valid float",
    ):
        AdversarialCounterEvidenceEngine(
            refutation_threshold=1.5,
            ambiguity_threshold=0.4,
        )

    with pytest.raises(
        ModuleContractViolationError,
        match="ambiguity_threshold must be a valid float",
    ):
        AdversarialCounterEvidenceEngine(
            refutation_threshold=0.8,
            ambiguity_threshold=-0.1,
        )


def test_adversarial_engine_query_generation(sample_gap: ResearchGap) -> None:
    """Verifies that query generation creates diverse adversarial search queries."""
    engine = AdversarialCounterEvidenceEngine()
    queries = engine.generate_counter_queries(sample_gap)

    assert len(queries) >= 4
    for q in queries:
        assert isinstance(q, str)
        assert len(q) > 10
    # Should include gap title and class
    assert any("Excessive Latency" in q for q in queries)
    assert any("DEPLOYMENT_RESOURCE_GAP" in q for q in queries)


def test_adversarial_engine_decisive_refutation(
    sample_gap: ResearchGap,
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that high-confidence counter-evidence refutes the candidate gap."""
    engine = AdversarialCounterEvidenceEngine()

    refuting_item = CounterEvidenceItem(
        coordinate=sample_coordinate,
        refutation_snippet="FastPointNet achieves 32 ms latency with 91% accuracy.",
        refutation_confidence=0.95,
        refuting_method_or_solution="FastPointNet",
    )

    result = engine.evaluate_counter_evidence(sample_gap, [refuting_item])

    assert result.status == CandidateGapStatus.REFUTED
    assert result.is_refuted is True
    assert "refuted via 'FastPointNet'" in result.refutation_rationale
    assert len(result.counter_evidence) == 1


def test_adversarial_engine_ambiguous_counter_evidence(
    sample_gap: ResearchGap,
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that ambiguous counter-evidence elevates epistemic uncertainty."""
    engine = AdversarialCounterEvidenceEngine()

    ambiguous_item = CounterEvidenceItem(
        coordinate=sample_coordinate,
        refutation_snippet="Preliminary tests report 48 ms latency on high-end server GPU.",
        refutation_confidence=0.60,
    )

    result = engine.evaluate_counter_evidence(sample_gap, [ambiguous_item])

    assert result.status == CandidateGapStatus.UNRESOLVED_DISPUTE
    assert result.is_refuted is False
    assert result.updated_uncertainty >= 0.50
    assert "unresolved empirical dispute" in result.refutation_rationale


def test_adversarial_engine_weak_or_empty_evidence(
    sample_gap: ResearchGap,
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that empty or weak counter-evidence confirms the candidate gap."""
    engine = AdversarialCounterEvidenceEngine()

    # Empty evidence
    res_empty = engine.evaluate_counter_evidence(sample_gap, [])
    assert res_empty.status == CandidateGapStatus.CONFIRMED_GAP
    assert res_empty.is_refuted is False
    assert res_empty.updated_uncertainty == sample_gap.calibrated_scores.uncertainty

    # Weak evidence below ambiguity threshold
    weak_item = CounterEvidenceItem(
        coordinate=sample_coordinate,
        refutation_snippet="General review of point cloud algorithms.",
        refutation_confidence=0.15,
    )
    res_weak = engine.evaluate_counter_evidence(sample_gap, [weak_item])
    assert res_weak.status == CandidateGapStatus.CONFIRMED_GAP
    assert res_weak.is_refuted is False
    assert "below ambiguity threshold" in res_weak.refutation_rationale


def test_validation_plan_generator(sample_gap: ResearchGap) -> None:
    """Verifies ValidationPlanGenerator tailors plans across diverse gap classes."""
    generator = ValidationPlanGenerator()

    # DEPLOYMENT_RESOURCE_GAP
    plan_resource = generator.generate_plan(sample_gap)
    assert "latency" in plan_resource.proposed_methodology.lower()
    assert "PeakVRAM_GB" in plan_resource.evaluation_metrics
    assert len(plan_resource.required_datasets) >= 1

    # REPRODUCIBILITY_GAP
    gap_repro = ResearchGap(
        gap_id="gap-repro",
        gap_class=GapClass.REPRODUCIBILITY_GAP,
        title="Unreproducible Fidelity Claims",
        description="Independent reproduction studies failed.",
        epistemic_rationale="Missing code and weights.",
        supporting_evidence=sample_gap.supporting_evidence,
        calibrated_scores=sample_gap.calibrated_scores,
        validation_plan=sample_gap.validation_plan,
    )
    plan_repro = generator.generate_plan(gap_repro)
    assert "reproduction" in plan_repro.proposed_methodology.lower()
    assert "ReplicationFidelity" in plan_repro.evaluation_metrics

    # CONFLICTING_EVIDENCE_GAP
    gap_conf = ResearchGap(
        gap_id="gap-conf",
        gap_class=GapClass.CONFLICTING_EVIDENCE_GAP,
        title="Empirical Contradiction in Superconductivity",
        description="Studies report conflicting critical temperatures.",
        epistemic_rationale="Disparate findings under identical nominal conditions.",
        supporting_evidence=sample_gap.supporting_evidence,
        calibrated_scores=sample_gap.calibrated_scores,
        validation_plan=sample_gap.validation_plan,
    )
    plan_conf = generator.generate_plan(gap_conf)
    assert "arbitration" in plan_conf.proposed_methodology.lower()
    assert "RelativeSuperiorityDelta" in plan_conf.evaluation_metrics

    # GENERALIZATION_GAP
    gap_gen = ResearchGap(
        gap_id="gap-gen",
        gap_class=GapClass.GENERALIZATION_GAP,
        title="OOD Degradation Under Domain Shift",
        description="Vision model fails out of distribution.",
        epistemic_rationale="Covariate shift causes catastrophic accuracy loss.",
        supporting_evidence=sample_gap.supporting_evidence,
        calibrated_scores=sample_gap.calibrated_scores,
        validation_plan=sample_gap.validation_plan,
    )
    plan_gen = generator.generate_plan(gap_gen)
    assert "distribution shifts" in plan_gen.proposed_methodology.lower()

    # ASSUMPTION_BOUNDARY_GAP
    gap_bound = ResearchGap(
        gap_id="gap-bound",
        gap_class=GapClass.ASSUMPTION_BOUNDARY_GAP,
        title="Thermal Operating Breakdown",
        description="Breakdown observed above 100 mK.",
        epistemic_rationale="Boundary assumption violated.",
        supporting_evidence=sample_gap.supporting_evidence,
        calibrated_scores=sample_gap.calibrated_scores,
        validation_plan=sample_gap.validation_plan,
    )
    plan_bound = generator.generate_plan(gap_bound)
    assert "parameter sweep" in plan_bound.proposed_methodology.lower()

    # Fallback (KNOWLEDGE_GAP)
    gap_know = ResearchGap(
        gap_id="gap-know",
        gap_class=GapClass.KNOWLEDGE_GAP,
        title="Theoretical Mechanism of Coherence",
        description="Mechanism remains uncharacterized.",
        epistemic_rationale="Fundamental theory missing.",
        supporting_evidence=sample_gap.supporting_evidence,
        calibrated_scores=sample_gap.calibrated_scores,
        validation_plan=sample_gap.validation_plan,
    )
    plan_know = generator.generate_plan(gap_know)
    assert "hypothesis validation" in plan_know.proposed_methodology.lower()
