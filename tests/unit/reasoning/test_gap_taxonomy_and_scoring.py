"""Unit and contract tests for 12-class research gap taxonomy and calibrated scoring.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, ADR-004, and Issue #63:
- Tests 12-class GapClass taxonomy contracts and string representations
- Validates CalibratedGapScores domain limits [0.0, 1.0] and composite formula
- Enforces prohibition of global novelty claims under bounded corpus coverage
- Tests ValidationPlan, CorpusScope, and ResearchGap provenance and contracts
- Evaluates RuleBasedGapClassifier across all 12 classes and conflict records
"""

from __future__ import annotations

import math

import pytest

from laris.core.errors import (
    EpistemicOverreachError,
    ModuleContractViolationError,
    ProvenanceViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reasoning import (
    CalibratedGapScores,
    CalibratedGapScoringEngine,
    CaveatSeverity,
    ComparabilityCaveat,
    ConflictRecord,
    ConflictType,
    CorpusScope,
    GapClass,
    ResearchGap,
    RuleBasedGapClassifier,
    ValidationPlan,
)


@pytest.fixture
def sample_coordinate() -> EvidenceCoordinate:
    """Provides a valid synthetic EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id="coord-gap-001",
        document_id="paper-synth-2024",
        document_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        page_number=3,
        section_identifier="sec-eval",
        paragraph_index=2,
        sentence_index=1,
        char_start=10,
        char_end=60,
        verbatim_snippet="Model fails under high thermal noise conditions.",
        extraction_confidence=0.98,
    )


def test_gap_class_twelve_classes() -> None:
    """Verifies that GapClass contains exactly the canonical 12 gap classes."""
    expected_classes = {
        "KNOWLEDGE_GAP",
        "METHODOLOGICAL_GAP",
        "MEASUREMENT_EVALUATION_GAP",
        "DATASET_DOMAIN_GAP",
        "GENERALIZATION_GAP",
        "REPRODUCIBILITY_GAP",
        "CONFLICTING_EVIDENCE_GAP",
        "ASSUMPTION_BOUNDARY_GAP",
        "INTEGRATION_INTERDISCIPLINARY_GAP",
        "DEPLOYMENT_RESOURCE_GAP",
        "TEMPORAL_GAP",
        "UNDEREXPLORED_RESEARCH_QUESTION",
    }
    actual_classes = {c.value for c in GapClass}
    assert actual_classes == expected_classes
    assert len(GapClass) == 12


def test_calibrated_gap_scores_valid() -> None:
    """Tests valid creation of CalibratedGapScores."""
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
    assert scores.novelty == 0.85
    assert scores.composite_score == 0.82
    assert scores.corpus_bounded is True
    assert scores.is_global_claim is False


def test_calibrated_gap_scores_invalid_range() -> None:
    """Verifies scores outside [0.0, 1.0] or non-finite floats raise error."""
    with pytest.raises(ModuleContractViolationError, match="must be within"):
        CalibratedGapScores(
            novelty=1.2,
            grounding=0.5,
            feasibility=0.5,
            significance=0.5,
            uncertainty=0.5,
            composite_score=0.5,
        )

    with pytest.raises(ModuleContractViolationError, match="must be a finite float"):
        CalibratedGapScores(
            novelty=float("nan"),
            grounding=0.5,
            feasibility=0.5,
            significance=0.5,
            uncertainty=0.5,
            composite_score=0.5,
        )


def test_calibrated_gap_scores_prohibits_global_novelty_when_bounded() -> None:
    """Verifies global novelty claims raise EpistemicOverreachError when bounded."""
    with pytest.raises(
        EpistemicOverreachError,
        match="Global novelty claims are strictly prohibited",
    ):
        CalibratedGapScores(
            novelty=0.95,
            grounding=0.80,
            feasibility=0.70,
            significance=0.85,
            uncertainty=0.10,
            composite_score=0.85,
            corpus_bounded=True,
            is_global_claim=True,
        )


def test_calibrated_gap_scores_allows_global_claim_if_unbounded() -> None:
    """Verifies global claims are permitted when corpus is explicitly unbounded."""
    scores = CalibratedGapScores(
        novelty=0.95,
        grounding=0.80,
        feasibility=0.70,
        significance=0.85,
        uncertainty=0.10,
        composite_score=0.85,
        corpus_bounded=False,
        is_global_claim=True,
    )
    assert scores.is_global_claim is True
    assert scores.corpus_bounded is False


def test_validation_plan_contracts() -> None:
    """Verifies ValidationPlan field contracts and validation logic."""
    plan = ValidationPlan(
        proposed_methodology="Implement cryogenic cross-validation benchmark.",
        required_datasets=["CryoBenchV1"],
        expected_baselines=["StandardQubitBaseline"],
        evaluation_metrics=["T1_relaxation_us", "Fidelity"],
    )
    assert len(plan.required_datasets) == 1
    assert len(plan.evaluation_metrics) == 2

    # Empty proposed methodology
    with pytest.raises(ModuleContractViolationError, match="proposed_methodology"):
        ValidationPlan(
            proposed_methodology="   ",
            required_datasets=["CryoBenchV1"],
            expected_baselines=["StandardQubitBaseline"],
            evaluation_metrics=["Fidelity"],
        )

    # Empty datasets
    with pytest.raises(ModuleContractViolationError, match="required_datasets"):
        ValidationPlan(
            proposed_methodology="Valid methodology",
            required_datasets=[],
            expected_baselines=["StandardQubitBaseline"],
            evaluation_metrics=["Fidelity"],
        )

    # Empty baselines
    with pytest.raises(ModuleContractViolationError, match="expected_baselines"):
        ValidationPlan(
            proposed_methodology="Valid methodology",
            required_datasets=["CryoBenchV1"],
            expected_baselines=[],
            evaluation_metrics=["Fidelity"],
        )

    # Empty metrics
    with pytest.raises(ModuleContractViolationError, match="evaluation_metrics"):
        ValidationPlan(
            proposed_methodology="Valid methodology",
            required_datasets=["CryoBenchV1"],
            expected_baselines=["StandardQubitBaseline"],
            evaluation_metrics=[],
        )


def test_corpus_scope_contracts() -> None:
    """Tests CorpusScope invariants."""
    scope = CorpusScope(
        scope_id="scope-quantum-2024",
        document_count=42,
        is_bounded=True,
        inclusion_criteria=["Quantum computing peer-reviewed preprints 2023-2024"],
        exclusion_criteria=["Editorials", "Non-English"],
        coverage_notes="Bounded to cryo-qubit research.",
    )
    assert scope.scope_id == "scope-quantum-2024"
    assert scope.document_count == 42

    with pytest.raises(ModuleContractViolationError, match="scope_id"):
        CorpusScope(scope_id="", document_count=10)

    with pytest.raises(ModuleContractViolationError, match="document_count"):
        CorpusScope(scope_id="valid-id", document_count=-5)


def test_research_gap_instantiation_and_provenance(sample_coordinate: EvidenceCoordinate) -> None:
    """Verifies valid ResearchGap instantiation and provenance requirements."""
    scores = CalibratedGapScores(
        novelty=0.8,
        grounding=0.9,
        feasibility=0.7,
        significance=0.8,
        uncertainty=0.1,
        composite_score=0.82,
    )
    plan = ValidationPlan(
        proposed_methodology="Cross-platform test",
        required_datasets=["DS1"],
        expected_baselines=["B1"],
        evaluation_metrics=["Acc"],
    )
    scope = CorpusScope(scope_id="scope-main", document_count=100)

    gap = ResearchGap(
        gap_id="gap-001",
        gap_class=GapClass.CONFLICTING_EVIDENCE_GAP,
        title="Contradictory Qubit T1 Coherence Measurements",
        description="Independent labs report contradictory T1 relaxation rates.",
        epistemic_rationale="Identical dilution temperature yields incompatible results.",
        supporting_evidence=[sample_coordinate],
        calibrated_scores=scores,
        validation_plan=plan,
        corpus_scope=scope,
    )
    assert gap.gap_id == "gap-001"
    assert gap.gap_class == GapClass.CONFLICTING_EVIDENCE_GAP
    assert len(gap.supporting_evidence) == 1

    # Empty string validation
    with pytest.raises(ModuleContractViolationError, match="gap_id"):
        ResearchGap(
            gap_id="",
            gap_class=GapClass.KNOWLEDGE_GAP,
            title="Title",
            description="Desc",
            epistemic_rationale="Rat",
            supporting_evidence=[sample_coordinate],
            calibrated_scores=scores,
            validation_plan=plan,
        )

    with pytest.raises(ModuleContractViolationError, match="title"):
        ResearchGap(
            gap_id="gap-01",
            gap_class=GapClass.KNOWLEDGE_GAP,
            title="",
            description="Desc",
            epistemic_rationale="Rat",
            supporting_evidence=[sample_coordinate],
            calibrated_scores=scores,
            validation_plan=plan,
        )

    with pytest.raises(ModuleContractViolationError, match="description"):
        ResearchGap(
            gap_id="gap-01",
            gap_class=GapClass.KNOWLEDGE_GAP,
            title="Title",
            description="   ",
            epistemic_rationale="Rat",
            supporting_evidence=[sample_coordinate],
            calibrated_scores=scores,
            validation_plan=plan,
        )

    with pytest.raises(ModuleContractViolationError, match="epistemic_rationale"):
        ResearchGap(
            gap_id="gap-01",
            gap_class=GapClass.KNOWLEDGE_GAP,
            title="Title",
            description="Desc",
            epistemic_rationale="",
            supporting_evidence=[sample_coordinate],
            calibrated_scores=scores,
            validation_plan=plan,
        )

    # Empty provenance raises ProvenanceViolationError
    with pytest.raises(ProvenanceViolationError):
        ResearchGap(
            gap_id="gap-002",
            gap_class=GapClass.KNOWLEDGE_GAP,
            title="Title",
            description="Desc",
            epistemic_rationale="Rat",
            supporting_evidence=[],
            calibrated_scores=scores,
            validation_plan=plan,
        )


def test_research_gap_epistemic_overreach_on_global_claim(
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that asserting a global claim within a bounded corpus scope raises error."""
    unbounded_scores_with_global = CalibratedGapScores(
        novelty=0.95,
        grounding=0.9,
        feasibility=0.8,
        significance=0.9,
        uncertainty=0.05,
        composite_score=0.92,
        corpus_bounded=False,
        is_global_claim=True,
    )
    plan = ValidationPlan(
        proposed_methodology="Test",
        required_datasets=["DS1"],
        expected_baselines=["B1"],
        evaluation_metrics=["Acc"],
    )
    bounded_scope = CorpusScope(scope_id="scope-bounded-01", document_count=15, is_bounded=True)

    with pytest.raises(EpistemicOverreachError, match="asserts global novelty but corpus scope"):
        ResearchGap(
            gap_id="gap-global-violator",
            gap_class=GapClass.METHODOLOGICAL_GAP,
            title="Global Claim Violation",
            description="Asserting global novelty over bounded local corpus.",
            epistemic_rationale="Unauthorized overreach.",
            supporting_evidence=[sample_coordinate],
            calibrated_scores=unbounded_scores_with_global,
            validation_plan=plan,
            corpus_scope=bounded_scope,
        )


def test_calibrated_gap_scoring_engine() -> None:
    """Tests CalibratedGapScoringEngine calculation, weights, and bounded enforcement."""
    engine = CalibratedGapScoringEngine()

    # Valid scoring with default weights
    scores = engine.score_gap(
        novelty=0.80,
        grounding=0.80,
        feasibility=0.60,
        significance=0.70,
        uncertainty=0.10,
    )
    # Expected: 0.25*0.8 + 0.25*0.8 + 0.20*0.6 + 0.20*0.7 + 0.10*0.9
    # = 0.2 + 0.2 + 0.12 + 0.14 + 0.09 = 0.75
    assert math.isclose(scores.composite_score, 0.75, abs_tol=1e-3)
    assert scores.corpus_bounded is True
    assert scores.is_global_claim is False

    # Illegal global novelty claim
    with pytest.raises(
        EpistemicOverreachError,
        match="Global novelty claims are strictly prohibited",
    ):
        engine.score_gap(
            novelty=0.9,
            grounding=0.9,
            feasibility=0.9,
            significance=0.9,
            uncertainty=0.1,
            assert_global_novelty=True,
        )

    # Sparse corpus (< 5 docs) elevates minimum uncertainty to 0.20
    sparse_scope = CorpusScope(scope_id="scope-sparse", document_count=3, is_bounded=True)
    scores_sparse = engine.score_gap(
        novelty=0.8,
        grounding=0.8,
        feasibility=0.6,
        significance=0.7,
        uncertainty=0.05,  # Lower than floor 0.20
        corpus_scope=sparse_scope,
    )
    assert scores_sparse.uncertainty == 0.20

    # Invalid weights sum
    with pytest.raises(ModuleContractViolationError, match="must sum to 1.0"):
        CalibratedGapScoringEngine(weight_novelty=0.5, weight_grounding=0.8)

    # Negative weight
    with pytest.raises(ModuleContractViolationError, match="non-negative"):
        CalibratedGapScoringEngine(
            weight_novelty=-0.1,
            weight_grounding=0.4,
            weight_feasibility=0.3,
            weight_significance=0.2,
            weight_certainty=0.2,
        )

    # Non-finite score input
    with pytest.raises(ModuleContractViolationError, match="must be a finite float"):
        engine.score_gap(
            novelty=float("nan"),
            grounding=0.8,
            feasibility=0.6,
            significance=0.7,
            uncertainty=0.1,
        )

    # Out of bounds score input
    with pytest.raises(ModuleContractViolationError, match="must be within"):
        engine.score_gap(
            novelty=1.5,
            grounding=0.8,
            feasibility=0.6,
            significance=0.7,
            uncertainty=0.1,
        )


def test_rule_based_gap_classifier_text_classes() -> None:
    """Verifies RuleBasedGapClassifier correctly identifies all 12 classes from indicator text."""
    classifier = RuleBasedGapClassifier()

    cases = [
        (
            "Deployment on edge devices fails due to excessive VRAM footprint and latency.",
            GapClass.DEPLOYMENT_RESOURCE_GAP,
        ),
        (
            "Attempts to replicate original experiments failed; code and missing artifacts.",
            GapClass.REPRODUCIBILITY_GAP,
        ),
        (
            "Evaluation metric suffers from benchmark leakage and flawed measurement protocol.",
            GapClass.MEASUREMENT_EVALUATION_GAP,
        ),
        (
            "Dataset scarcity in low-resource specialized domain impedes training.",
            GapClass.DATASET_DOMAIN_GAP,
        ),
        (
            "Accuracy degrades sharply under distribution shift and out-of-distribution OOD data.",
            GapClass.GENERALIZATION_GAP,
        ),
        (
            "Model breakdown observed at thermal boundary condition and high operating limit.",
            GapClass.ASSUMPTION_BOUNDARY_GAP,
        ),
        (
            "Siloed disciplines lack an interdisciplinary cross-domain bridging framework.",
            GapClass.INTEGRATION_INTERDISCIPLINARY_GAP,
        ),
        (
            "Temporal concept drift renders historical outdated baselines obsolete.",
            GapClass.TEMPORAL_GAP,
        ),
        (
            "Opposing empirical findings show severe contradiction between studies.",
            GapClass.CONFLICTING_EVIDENCE_GAP,
        ),
        (
            "Current algorithmic limitation in modeling methodology prevents scaling.",
            GapClass.METHODOLOGICAL_GAP,
        ),
        (
            "The underlying theoretical mechanism and fundamental principle remain unknown.",
            GapClass.KNOWLEDGE_GAP,
        ),
        (
            "An underexplored open question with scarce literature and uncharted scope.",
            GapClass.UNDEREXPLORED_RESEARCH_QUESTION,
        ),
    ]

    for text, expected_class in cases:
        detected = classifier.classify_text(text)
        assert detected == expected_class, f"Failed on text: '{text}', expected {expected_class}"


def test_rule_based_gap_classifier_conflict_mapping(sample_coordinate: EvidenceCoordinate) -> None:
    """Verifies that ConflictRecord instances map to appropriate GapClass."""
    classifier = RuleBasedGapClassifier()

    # Direct empirical contradiction -> CONFLICTING_EVIDENCE_GAP
    rec_direct = ConflictRecord(
        conflict_id="c-direct",
        conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Direct empirical contradiction between two papers.",
        is_genuine_contradiction=True,
        evidence_coordinates=[sample_coordinate],
    )
    assert classifier.classify_from_conflict(rec_direct) == GapClass.CONFLICTING_EVIDENCE_GAP

    # Boundary condition discrepancy -> ASSUMPTION_BOUNDARY_GAP
    rec_bound = ConflictRecord(
        conflict_id="c-bound",
        conflict_type=ConflictType.BOUNDARY_CONDITION_DISCREPANCY,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Boundary condition discrepancy across temperatures.",
        is_genuine_contradiction=True,
        evidence_coordinates=[sample_coordinate],
    )
    assert classifier.classify_from_conflict(rec_bound) == GapClass.ASSUMPTION_BOUNDARY_GAP

    # Apparent conflict due to metric mismatch -> MEASUREMENT_EVALUATION_GAP
    caveat_metric = ComparabilityCaveat(
        caveat_type="METRIC_DISPARITY",
        description="Metric mismatch: WER vs Accuracy.",
        severity=CaveatSeverity.INCOMPARABLE,
    )
    rec_metric = ConflictRecord(
        conflict_id="c-metric",
        conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Disparate metrics explain difference.",
        is_genuine_contradiction=False,
        evidence_coordinates=[sample_coordinate],
        comparability_caveats=[caveat_metric],
    )
    assert classifier.classify_from_conflict(rec_metric) == GapClass.MEASUREMENT_EVALUATION_GAP

    # Apparent conflict due to split mismatch -> DATASET_DOMAIN_GAP
    caveat_split = ComparabilityCaveat(
        caveat_type="SPLIT_DISPARITY",
        description="In-domain vs OOD test split.",
        severity=CaveatSeverity.INCOMPARABLE,
    )
    rec_split = ConflictRecord(
        conflict_id="c-split",
        conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Disparate test splits.",
        is_genuine_contradiction=False,
        evidence_coordinates=[sample_coordinate],
        comparability_caveats=[caveat_split],
    )
    assert classifier.classify_from_conflict(rec_split) == GapClass.DATASET_DOMAIN_GAP

    # Cross method superiority -> CONFLICTING_EVIDENCE_GAP
    rec_sup = ConflictRecord(
        conflict_id="c-sup",
        conflict_type=ConflictType.CROSS_METHOD_SUPERIORITY_CONTRADICTION,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Cross-method superiority contradiction.",
        is_genuine_contradiction=True,
        evidence_coordinates=[sample_coordinate],
    )
    assert classifier.classify_from_conflict(rec_sup) == GapClass.CONFLICTING_EVIDENCE_GAP

    # Apparent conflict without metric/split caveats -> GENERALIZATION_GAP
    caveat_other = ComparabilityCaveat(
        caveat_type="PREPROCESSING_DIFFERENCE",
        description="Different tokenizers used.",
        severity=CaveatSeverity.INCOMPARABLE,
    )
    rec_gen = ConflictRecord(
        conflict_id="c-gen",
        conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
        finding_a_id="fa",
        finding_b_id="fb",
        description="General comparability discrepancy.",
        is_genuine_contradiction=False,
        evidence_coordinates=[sample_coordinate],
        comparability_caveats=[caveat_other],
    )
    assert classifier.classify_from_conflict(rec_gen) == GapClass.GENERALIZATION_GAP


def test_rule_based_gap_classifier_candidate_dispatch(
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies classify_candidate dispatch logic."""
    classifier = RuleBasedGapClassifier()
    rec_direct = ConflictRecord(
        conflict_id="c-direct",
        conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
        finding_a_id="fa",
        finding_b_id="fb",
        description="Direct conflict.",
        is_genuine_contradiction=True,
        evidence_coordinates=[sample_coordinate],
    )
    # With conflict record passed, priority is conflict mapping
    res = classifier.classify_candidate(
        "VRAM Footprint Issue",
        "High memory usage",
        conflict=rec_direct,
    )
    assert res == GapClass.CONFLICTING_EVIDENCE_GAP

    # Without conflict, uses text
    res_text = classifier.classify_candidate(
        "High Latency",
        "Model latency exceeds real-time budget.",
    )
    assert res_text == GapClass.DEPLOYMENT_RESOURCE_GAP

    # Empty text raises error
    with pytest.raises(ModuleContractViolationError):
        classifier.classify_text("   ")
