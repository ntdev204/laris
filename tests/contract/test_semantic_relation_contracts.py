"""Contract validation tests for semantic equivalence, coreference, and discourse relations.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-004, ADR-008
"""

import pytest

from laris.core.errors import (
    EpistemicOverreachError,
    InvalidNLIInputError,
    ModuleContractViolationError,
    UncertaintyCeilingExceededError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reasoning import (
    CoreferenceCluster,
    CoreferenceOutput,
    CoreferenceResolutionStatus,
    DiscourseRelationOutput,
    DiscourseRelationType,
    EquivalenceStatus,
    MentionSpan,
    SemanticEquivalenceOutput,
)


class TestSemanticEquivalenceContract:
    """Verifies interface invariants for SemanticEquivalenceOutput."""

    def test_valid_equivalence_output(self) -> None:
        eq = SemanticEquivalenceOutput(
            text_a="The reaction is exothermic.",
            text_b="Heat is released during the chemical reaction.",
            status=EquivalenceStatus.EQUIVALENT,
            confidence=0.95,
            topical_similarity=0.89,
            evidence_notes="Direct paraphrase in physical chemistry.",
        )
        assert eq.status == EquivalenceStatus.EQUIVALENT
        assert eq.confidence == 0.95
        assert eq.topical_similarity == 0.89
        assert eq.schema_version == "0.1.0"

    def test_ambiguous_equivalence_status(self) -> None:
        eq = SemanticEquivalenceOutput(
            text_a="The enzyme was active at pH 7.4.",
            text_b="Optimal enzymatic velocity occurs near physiological pH.",
            status=EquivalenceStatus.AMBIGUOUS,
            confidence=0.55,
            topical_similarity=0.62,
        )
        assert eq.status == EquivalenceStatus.AMBIGUOUS

    def test_string_status_coercion(self) -> None:
        eq = SemanticEquivalenceOutput(
            text_a="Statement A",
            text_b="Statement B",
            status="PARTIALLY_EQUIVALENT",  # type: ignore[arg-type]
            confidence=0.7,
            topical_similarity=0.7,
        )
        assert eq.status == EquivalenceStatus.PARTIALLY_EQUIVALENT

    def test_invalid_text_raises(self) -> None:
        with pytest.raises(InvalidNLIInputError, match="text_a must be a non-empty string"):
            SemanticEquivalenceOutput(
                text_a="",
                text_b="Valid text",
                status=EquivalenceStatus.EQUIVALENT,
                confidence=0.9,
                topical_similarity=0.8,
            )

        with pytest.raises(InvalidNLIInputError, match="text_b must be a non-empty string"):
            SemanticEquivalenceOutput(
                text_a="Valid text",
                text_b="   \t",
                status=EquivalenceStatus.EQUIVALENT,
                confidence=0.9,
                topical_similarity=0.8,
            )

    def test_confidence_bounds_raises(self) -> None:
        with pytest.raises(ModuleContractViolationError, match="confidence must be in"):
            SemanticEquivalenceOutput(
                text_a="Text A",
                text_b="Text B",
                status=EquivalenceStatus.EQUIVALENT,
                confidence=1.05,
                topical_similarity=0.8,
            )

    def test_topical_similarity_bounds_raises(self) -> None:
        with pytest.raises(ModuleContractViolationError, match="topical_similarity must be in"):
            SemanticEquivalenceOutput(
                text_a="Text A",
                text_b="Text B",
                status=EquivalenceStatus.EQUIVALENT,
                confidence=0.9,
                topical_similarity=-0.01,
            )

    def test_equivalence_serialization_round_trip(self) -> None:
        eq = SemanticEquivalenceOutput(
            text_a="Quantum entanglement is non-local.",
            text_b="Entangled particle states exhibit non-local correlations.",
            status=EquivalenceStatus.EQUIVALENT,
            confidence=0.98,
            topical_similarity=0.91,
            metadata={"source": "physics_benchmark"},
        )
        d = eq.to_dict()
        restored = SemanticEquivalenceOutput.from_dict(d)
        assert restored == eq

        json_str = eq.to_json()
        from_json = SemanticEquivalenceOutput.from_json(json_str)
        assert from_json == eq


class TestScientificCoreferenceContract:
    """Verifies contracts for MentionSpan, CoreferenceCluster, and CoreferenceOutput."""

    def test_valid_coreference_hierarchy(self) -> None:
        coord = EvidenceCoordinate(
            coordinate_id="COORD-001",
            document_id="DOC-PHYS-001",
            document_sha256="a" * 64,
            page_number=1,
            section_identifier="sec-1",
            paragraph_index=2,
            sentence_index=3,
            char_start=45,
            char_end=85,
            verbatim_snippet="the high-temperature cuprate superconductor",
        )
        m1 = MentionSpan(
            mention_id="M-001",
            text="the high-temperature cuprate superconductor",
            start_char=45,
            end_char=88,
            sentence_index=3,
            evidence_coordinate=coord,
        )
        m2 = MentionSpan(
            mention_id="M-002",
            text="this material",
            start_char=105,
            end_char=118,
            sentence_index=4,
        )

        cluster = CoreferenceCluster(
            cluster_id="CLUST-001",
            canonical_mention="high-temperature cuprate superconductor",
            mentions=[m1, m2],
            confidence=0.94,
            status=CoreferenceResolutionStatus.RESOLVED,
        )
        output = CoreferenceOutput(clusters=[cluster], document_id="DOC-PHYS-001")

        assert len(output.clusters) == 1
        assert len(output.clusters[0].mentions) == 2
        assert output.clusters[0].mentions[0].evidence_coordinate == coord

        # Serialization round trip
        d = output.to_dict()
        restored = CoreferenceOutput.from_dict(d)
        assert restored.clusters[0].cluster_id == "CLUST-001"
        assert restored.clusters[0].mentions[0].start_char == 45

    def test_invalid_mention_span_boundaries(self) -> None:
        with pytest.raises(ModuleContractViolationError, match="start_char must be non-negative"):
            MentionSpan(mention_id="M-ERR", text="sample", start_char=-1, end_char=5)

        with pytest.raises(ModuleContractViolationError, match="strictly greater than start_char"):
            MentionSpan(mention_id="M-ERR", text="sample", start_char=10, end_char=10)

    def test_ambiguous_antecedent_status(self) -> None:
        cluster = CoreferenceCluster(
            cluster_id="CLUST-AMBIG",
            canonical_mention="the algorithm",
            mentions=[
                MentionSpan(mention_id="M-1", text="the algorithm", start_char=0, end_char=13),
                MentionSpan(mention_id="M-2", text="it", start_char=40, end_char=42),
            ],
            confidence=0.45,
            status=CoreferenceResolutionStatus.AMBIGUOUS_ANTECEDENT,
        )
        assert cluster.status == CoreferenceResolutionStatus.AMBIGUOUS_ANTECEDENT


class TestDiscourseRelationContract:
    """Verifies contracts and epistemic guardrails for DiscourseRelationOutput."""

    def test_valid_correlational_discourse_relation(self) -> None:
        rel = DiscourseRelationOutput(
            relation_id="REL-001",
            relation_type=DiscourseRelationType.CORRELATIONAL,
            arg1="Serum biomarker levels were elevated in affected cohorts.",
            arg2="Disease progression was accompanied by cognitive decline.",
            connective_cue="correlated with",
            confidence=0.91,
            uncertainty_score=0.12,
            causal_verified=False,
        )
        assert rel.relation_type == DiscourseRelationType.CORRELATIONAL
        assert rel.causal_verified is False

    def test_epistemic_guardrail_prevents_correlational_cue_claimed_as_causal(self) -> None:
        """ADR-008 & Boundary C Guardrail:

        Assertion of correlation cannot be classified as CAUSAL without causal verification.
        """
        with pytest.raises(EpistemicOverreachError, match="Epistemic Overreach"):
            DiscourseRelationOutput(
                relation_id="REL-INVALID-CAUSAL",
                relation_type=DiscourseRelationType.CAUSAL,
                arg1="Increased dietary sodium was associated with hypertension.",
                arg2="Hypertension incidence rose across the observed group.",
                connective_cue="associated with",
                confidence=0.88,
                causal_verified=False,  # Unverified!
            )

    def test_verified_causal_relation_passes(self) -> None:
        """When causal_verified is True (e.g. randomized controlled trial or knockout validation),

        causal classification is permitted.
        """
        rel = DiscourseRelationOutput(
            relation_id="REL-VALID-CAUSAL",
            relation_type=DiscourseRelationType.CAUSAL,
            arg1="CRISPR knockout of Gene X was conducted in vivo.",
            arg2="Tumor cell proliferation ceased completely.",
            connective_cue="led to",
            confidence=0.96,
            causal_verified=True,
        )
        assert rel.relation_type == DiscourseRelationType.CAUSAL
        assert rel.causal_verified is True

    def test_discourse_relation_serialization_round_trip(self) -> None:
        rel = DiscourseRelationOutput(
            relation_id="REL-CONTRAST-001",
            relation_type=DiscourseRelationType.CONTRAST,
            arg1="Model A achieved 94% precision.",
            arg2="Model B suffered degradation on out-of-distribution inputs.",
            connective_cue="In contrast",
            confidence=0.92,
            uncertainty_score=0.15,
        )
        d = rel.to_dict()
        restored = DiscourseRelationOutput.from_dict(d)
        assert restored == rel

        json_str = rel.to_json()
        from_json = DiscourseRelationOutput.from_json(json_str)
        assert from_json == rel

    def test_uncertainty_score_bounds_raises(self) -> None:
        with pytest.raises(UncertaintyCeilingExceededError, match="uncertainty_score must be in"):
            DiscourseRelationOutput(
                relation_id="REL-BOUNDS",
                relation_type=DiscourseRelationType.TEMPORAL,
                arg1="Event 1",
                arg2="Event 2",
                uncertainty_score=1.2,
            )
