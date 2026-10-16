"""Unit tests for semantic equivalence, coreference, and discourse relation schemas.

Task ID: M3-SEM-002-SUB-01 (Issue #54)
"""

import pytest

from laris.core.errors import (
    EpistemicOverreachError,
    InvalidNLIInputError,
    ModuleContractViolationError,
    UncertaintyCeilingExceededError,
)
from laris.reasoning import (
    CoreferenceCluster,
    DiscourseRelationOutput,
    DiscourseRelationType,
    EquivalenceStatus,
    MentionSpan,
)


def test_equivalence_status_from_str() -> None:
    assert EquivalenceStatus.from_str("equivalent") == EquivalenceStatus.EQUIVALENT
    assert EquivalenceStatus.from_str("NOT_EQUIVALENT") == EquivalenceStatus.NOT_EQUIVALENT
    part_eq = EquivalenceStatus.from_str("partially_equivalent")
    assert part_eq == EquivalenceStatus.PARTIALLY_EQUIVALENT
    assert EquivalenceStatus.from_str("ambiguous") == EquivalenceStatus.AMBIGUOUS

    with pytest.raises(ModuleContractViolationError):
        EquivalenceStatus.from_str("INVALID_STATUS")


def test_discourse_relation_type_from_str() -> None:
    assert DiscourseRelationType.from_str("causal") == DiscourseRelationType.CAUSAL
    assert DiscourseRelationType.from_str("correlational") == DiscourseRelationType.CORRELATIONAL
    assert DiscourseRelationType.from_str("contrast") == DiscourseRelationType.CONTRAST
    assert DiscourseRelationType.from_str("concessive") == DiscourseRelationType.CONCESSIVE
    assert DiscourseRelationType.from_str("temporal") == DiscourseRelationType.TEMPORAL
    assert DiscourseRelationType.from_str("elaboration") == DiscourseRelationType.ELABORATION
    assert DiscourseRelationType.from_str("ambiguous") == DiscourseRelationType.AMBIGUOUS
    unknown = DiscourseRelationType.from_str("unknown_relation")
    assert unknown == DiscourseRelationType.UNKNOWN_RELATION

    with pytest.raises(ModuleContractViolationError):
        DiscourseRelationType.from_str("NOT_A_RELATION")


def test_mention_span_validation() -> None:
    with pytest.raises(ModuleContractViolationError, match="mention_id must be a non-empty string"):
        MentionSpan(mention_id="", text="token", start_char=0, end_char=5)

    with pytest.raises(ModuleContractViolationError, match="text must be a non-empty string"):
        MentionSpan(mention_id="M-1", text="   ", start_char=0, end_char=5)

    span = MentionSpan(mention_id="M-OK", text="nanotube", start_char=10, end_char=18)
    d = span.to_dict()
    restored = MentionSpan.from_dict(d)
    assert restored == span


def test_coreference_cluster_validation() -> None:
    with pytest.raises(ModuleContractViolationError, match="cluster_id must be a non-empty string"):
        CoreferenceCluster(cluster_id="", canonical_mention="protein", mentions=[], confidence=0.8)

    with pytest.raises(ModuleContractViolationError, match="canonical_mention must be"):
        CoreferenceCluster(cluster_id="C-1", canonical_mention="", mentions=[], confidence=0.8)

    with pytest.raises(ModuleContractViolationError, match="confidence must be in"):
        CoreferenceCluster(
            cluster_id="C-1", canonical_mention="protein", mentions=[], confidence=-0.1
        )


def test_discourse_relation_empty_arguments() -> None:
    with pytest.raises(ModuleContractViolationError, match="relation_id must be"):
        DiscourseRelationOutput(
            relation_id="",
            relation_type=DiscourseRelationType.TEMPORAL,
            arg1="Arg 1",
            arg2="Arg 2",
        )

    with pytest.raises(InvalidNLIInputError, match="arg1 must be a non-empty string"):
        DiscourseRelationOutput(
            relation_id="REL-1",
            relation_type=DiscourseRelationType.TEMPORAL,
            arg1="",
            arg2="Arg 2",
        )

    with pytest.raises(InvalidNLIInputError, match="arg2 must be a non-empty string"):
        DiscourseRelationOutput(
            relation_id="REL-1",
            relation_type=DiscourseRelationType.TEMPORAL,
            arg1="Arg 1",
            arg2="   ",
        )


def test_discourse_relation_negative_uncertainty_raises() -> None:
    with pytest.raises(UncertaintyCeilingExceededError):
        DiscourseRelationOutput(
            relation_id="REL-NEG-U",
            relation_type=DiscourseRelationType.CONCESSIVE,
            arg1="Premise",
            arg2="Hypothesis",
            uncertainty_score=-0.05,
        )


def test_epistemic_overreach_all_correlational_cues() -> None:
    cues = [
        "correlated with",
        "associated with",
        "co-occurs with",
        "linked to",
        "accompanied by",
    ]
    for cue in cues:
        with pytest.raises(EpistemicOverreachError):
            DiscourseRelationOutput(
                relation_id=f"REL-OVERREACH-{cue[:4]}",
                relation_type=DiscourseRelationType.CAUSAL,
                arg1=f"Exposure was {cue} clinical pathology.",
                arg2="Outcome observed in subjects.",
                connective_cue=cue,
                causal_verified=False,
            )


def test_semantic_equivalence_invalid_status_type() -> None:
    from laris.reasoning import SemanticEquivalenceOutput

    with pytest.raises(ModuleContractViolationError, match="status must be an EquivalenceStatus"):
        SemanticEquivalenceOutput(
            text_a="A",
            text_b="B",
            status=12345,  # type: ignore[arg-type]
            confidence=0.5,
            topical_similarity=0.5,
        )


def test_coreference_output_json_and_cluster_status_invalid() -> None:
    from laris.reasoning import CoreferenceOutput

    cluster = CoreferenceCluster(
        cluster_id="C-JSON",
        canonical_mention="graphene",
        mentions=[],
        confidence=0.9,
        status="RESOLVED",  # string coercion
    )
    out = CoreferenceOutput(clusters=[cluster], document_id="DOC-01")
    s = out.to_json()
    restored = CoreferenceOutput.from_json(s)
    assert restored.clusters[0].cluster_id == "C-JSON"

    with pytest.raises(ModuleContractViolationError, match="Invalid CoreferenceResolutionStatus"):
        CoreferenceCluster(
            cluster_id="C-ERR",
            canonical_mention="graphene",
            mentions=[],
            confidence=0.9,
            status=12345,  # type: ignore[arg-type]
        )


def test_discourse_relation_invalid_relation_type_and_confidence() -> None:
    # String coercion test
    rel_coerced = DiscourseRelationOutput(
        relation_id="REL-STR",
        relation_type="CONTRAST",  # type: ignore[arg-type]
        arg1="A",
        arg2="B",
    )
    assert rel_coerced.relation_type == DiscourseRelationType.CONTRAST

    with pytest.raises(ModuleContractViolationError, match="Invalid DiscourseRelationType"):
        DiscourseRelationOutput(
            relation_id="REL-ERR",
            relation_type=12345,  # type: ignore[arg-type]
            arg1="A",
            arg2="B",
        )

    with pytest.raises(ModuleContractViolationError, match="confidence must be in"):
        DiscourseRelationOutput(
            relation_id="REL-ERR-CONF",
            relation_type=DiscourseRelationType.CONTRAST,
            arg1="A",
            arg2="B",
            confidence=1.5,
        )

    with pytest.raises(ModuleContractViolationError, match="confidence must be in"):
        DiscourseRelationOutput(
            relation_id="REL-ERR-CONF-NEG",
            relation_type=DiscourseRelationType.CONTRAST,
            arg1="A",
            arg2="B",
            confidence=-0.1,
        )


def test_discourse_relation_with_evidence_coordinate_roundtrip() -> None:
    from laris.core.schemas import EvidenceCoordinate

    coord = EvidenceCoordinate(
        coordinate_id="COORD-REL-1",
        document_id="DOC-REL-01",
        document_sha256="b" * 64,
        page_number=2,
        section_identifier="sec-res",
        paragraph_index=1,
        sentence_index=4,
        char_start=10,
        char_end=50,
        verbatim_snippet="A led to B under high pressure",
    )
    rel = DiscourseRelationOutput(
        relation_id="REL-COORD",
        relation_type=DiscourseRelationType.CAUSAL,
        arg1="A occurred",
        arg2="B followed",
        causal_verified=True,
        evidence_coordinate=coord,
    )
    s = rel.to_json()
    restored = DiscourseRelationOutput.from_json(s)
    assert restored.evidence_coordinate is not None
    assert restored.evidence_coordinate.coordinate_id == "COORD-REL-1"
