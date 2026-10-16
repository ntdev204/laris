"""Adversarial and schema validation tests for specialist contracts and VerifierGate.

Covers Issue #98 (Subtask M7-ORCH-002-SUB-02):
- Adversarial coordinate integrity tests (corrupted SHA-256, tampered offsets, NaN/inf confidence)
- Adversarial claim manipulation and unanchored hallucination detection
- Strict provenance violation triggering under diverse adversarial conditions
- Payload schema boundary tests (empty strings, non-finite floats, negative counts)
- Agent role mismatch enforcement and bounded retry failure containment
"""

from __future__ import annotations

import pytest

from laris.core.errors import ModuleContractViolationError, ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.orchestration import (
    AgentRole,
    GenericSpecialistAgent,
    SpecialistInputPayload,
    SpecialistOutputPayload,
    TaskNodeStatus,
    VerifierGate,
)


@pytest.fixture
def canonical_coordinate() -> EvidenceCoordinate:
    """Fixture returning a canonical valid EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id="coord-valid-001",
        document_id="doc-supercond-2024",
        document_sha256="a" * 64,
        page_number=1,
        section_identifier="abstract",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=42,
        verbatim_snippet="Critical temperature measured at 260 K.",
        extraction_confidence=0.98,
    )


# ---------------------------------------------------------------------------
# 1. Adversarial Coordinate Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corrupt_sha",
    [
        "a" * 63,  # Too short
        "a" * 65,  # Too long
        "g" * 64,  # Non-hex characters
        " " * 64,  # Spaces
        "a" * 32 + "!" * 32,  # Punctuation
        "A" * 63 + "Z",  # Invalid hex char 'Z'
        "",  # Empty string
    ],
)
def test_adversarial_sha256_detection(
    canonical_coordinate: EvidenceCoordinate,
    corrupt_sha: str,
) -> None:
    """Tests that any malformed or tampered SHA-256 digest is rejected."""
    verifier = VerifierGate(strict_provenance=False)
    coord = EvidenceCoordinate(
        coordinate_id="c-sha",
        document_id="doc1",
        document_sha256="0" * 64,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=10,
        verbatim_snippet="snippet",
        extraction_confidence=0.9,
    )
    object.__setattr__(coord, "document_sha256", corrupt_sha)
    errors = verifier.verify_coordinate_integrity(coord)
    assert any("not a valid 64-character hexadecimal" in e for e in errors)


@pytest.mark.parametrize(
    ("start", "end", "expected_substr"),
    [
        (-1, 10, "cannot be negative"),
        (-100, 5, "cannot be negative"),
        (10, 10, "strictly greater than char_start"),
        (25, 20, "strictly greater than char_start"),
        (100, 0, "strictly greater than char_start"),
    ],
)
def test_adversarial_character_offsets(
    canonical_coordinate: EvidenceCoordinate,
    start: int,
    end: int,
    expected_substr: str,
) -> None:
    """Tests that inverted, negative, or zero-length character offsets are rejected."""
    verifier = VerifierGate(strict_provenance=False)
    coord = EvidenceCoordinate(
        coordinate_id="c-span",
        document_id="doc1",
        document_sha256=canonical_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=10,
        verbatim_snippet="snippet",
        extraction_confidence=0.9,
    )
    object.__setattr__(coord, "char_start", start)
    object.__setattr__(coord, "char_end", end)
    errors = verifier.verify_coordinate_integrity(coord)
    assert any(expected_substr in e for e in errors)


@pytest.mark.parametrize(
    "corrupt_confidence",
    [-0.01, 1.01, -10.0, 100.0, float("nan"), float("inf"), float("-inf")],
)
def test_adversarial_extraction_confidence(
    canonical_coordinate: EvidenceCoordinate,
    corrupt_confidence: float,
) -> None:
    """Tests that out-of-range, NaN, or infinite confidence values are rejected."""
    verifier = VerifierGate(strict_provenance=False)
    coord = EvidenceCoordinate(
        coordinate_id="c-conf",
        document_id="doc1",
        document_sha256=canonical_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=10,
        verbatim_snippet="snippet",
        extraction_confidence=0.5,
    )
    object.__setattr__(coord, "extraction_confidence", corrupt_confidence)
    errors = verifier.verify_coordinate_integrity(coord)
    assert any("must be within [0.0, 1.0]" in e for e in errors)


@pytest.mark.parametrize(
    "corrupt_snippet",
    ["", " ", "   ", "\t", "\n", " \t \n "],
)
def test_adversarial_empty_or_whitespace_snippet(
    canonical_coordinate: EvidenceCoordinate,
    corrupt_snippet: str,
) -> None:
    """Tests that empty or whitespace-only verbatim snippets are rejected."""
    verifier = VerifierGate(strict_provenance=False)
    coord = EvidenceCoordinate(
        coordinate_id="c-snip",
        document_id="doc1",
        document_sha256=canonical_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=10,
        verbatim_snippet="valid snippet",
        extraction_confidence=0.9,
    )
    object.__setattr__(coord, "verbatim_snippet", corrupt_snippet)
    errors = verifier.verify_coordinate_integrity(coord)
    assert any("verbatim_snippet must not be empty" in e for e in errors)


# ---------------------------------------------------------------------------
# 2. Adversarial Evidence Citation Lists and Claim Anchoring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_citation_item",
    [
        "not-a-coordinate-string",
        {"document_id": "doc1", "char_start": 0},
        12345,
        None,
        ["nested_list"],
    ],
)
def test_adversarial_citation_type_injection(bad_citation_item: object) -> None:
    """Tests that non-EvidenceCoordinate items injected in citations are rejected."""
    verifier = VerifierGate(strict_provenance=False)
    output = SpecialistOutputPayload(
        task_id="t-inj",
        role=AgentRole.EVIDENCE_RETRIEVAL,
        status=TaskNodeStatus.COMPLETED,
        evidence_citations=[bad_citation_item],  # type: ignore[list-item]
    )
    res = verifier.verify_output(output)
    assert res.is_valid is False
    assert any("is not an EvidenceCoordinate" in v for v in res.violations)


def test_adversarial_unanchored_hallucinations_strict(
    canonical_coordinate: EvidenceCoordinate,
) -> None:
    """Tests that unanchored claims trigger ProvenanceViolationError under strict mode."""
    verifier_strict = VerifierGate(strict_provenance=True)

    # Claim with completely missing coordinate anchor
    output_unanchored = SpecialistOutputPayload(
        task_id="t-claim-unanchored",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={
            "claims": [
                {
                    "claim_text": "Room temperature superconductivity observed at 300 K.",
                    "coordinate_id": "",
                }
            ]
        },
        evidence_citations=[canonical_coordinate],
    )
    with pytest.raises(ProvenanceViolationError) as exc_info:
        verifier_strict.verify_output(output_unanchored, require_evidence=True)
    assert "t-claim-unanchored" in str(exc_info.value)
    assert "lacks citation anchor" in str(exc_info.value)

    # Claim with hallucinated phantom coordinate anchor
    output_phantom = SpecialistOutputPayload(
        task_id="t-claim-phantom",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={
            "claims": [
                {
                    "claim_text": "Zero electrical resistance detected.",
                    "coordinate_id": "phantom-coordinate-999",
                }
            ]
        },
        evidence_citations=[canonical_coordinate],
    )
    with pytest.raises(ProvenanceViolationError) as exc_phantom:
        verifier_strict.verify_output(output_phantom, require_evidence=True)
    assert "phantom-coordinate-999" in str(exc_phantom.value)


def test_adversarial_evidence_coordinate_id_alias(
    canonical_coordinate: EvidenceCoordinate,
) -> None:
    """Tests that evidence_coordinate_id alias is recognized when anchoring claims."""
    verifier = VerifierGate(strict_provenance=True)
    output_alias = SpecialistOutputPayload(
        task_id="t-claim-alias",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={
            "claims": [
                {
                    "claim_text": "Resistance drop at critical Tc.",
                    "evidence_coordinate_id": canonical_coordinate.coordinate_id,
                }
            ]
        },
        evidence_citations=[canonical_coordinate],
    )
    res = verifier.verify_output(output_alias, require_evidence=True)
    assert res.is_valid is True
    assert res.checked_claims_count == 1
    assert res.verified_coordinates_count == 1


# ---------------------------------------------------------------------------
# 3. Payload Schema Boundary & Contract Invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task_id", "goal_statement", "timeout_seconds"),
    [
        ("", "Valid goal", 30.0),
        ("   ", "Valid goal", 30.0),
        ("task-1", "", 30.0),
        ("task-1", "   ", 30.0),
        ("task-1", "Valid goal", 0.0),
        ("task-1", "Valid goal", -5.0),
        ("task-1", "Valid goal", float("nan")),
        ("task-1", "Valid goal", float("inf")),
    ],
)
def test_adversarial_specialist_input_payload(
    task_id: str,
    goal_statement: str,
    timeout_seconds: float,
) -> None:
    """Tests input payload contract rejection on malformed fields."""
    with pytest.raises(ModuleContractViolationError):
        SpecialistInputPayload(
            task_id=task_id,
            role=AgentRole.LANGUAGE_ANALYSIS,
            goal_statement=goal_statement,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize(
    ("task_id", "tokens_used", "duration_ms", "retry_count"),
    [
        ("", 100, 50.0, 0),
        ("   ", 100, 50.0, 0),
        ("t1", -1, 50.0, 0),
        ("t1", 100, -1.0, 0),
        ("t1", 100, float("nan"), 0),
        ("t1", 100, float("inf"), 0),
        ("t1", 100, 50.0, -1),
    ],
)
def test_adversarial_specialist_output_payload(
    task_id: str,
    tokens_used: int,
    duration_ms: float,
    retry_count: int,
) -> None:
    """Tests output payload contract rejection on invalid numerical metrics."""
    with pytest.raises(ModuleContractViolationError):
        SpecialistOutputPayload(
            task_id=task_id,
            role=AgentRole.DOCUMENT_ANALYSIS,
            status=TaskNodeStatus.COMPLETED,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )


@pytest.mark.parametrize(
    ("max_retries", "timeout_seconds"),
    [
        (-1, 30.0),
        (4, 30.0),
        (10, 30.0),
        (2, 0.0),
        (2, -10.0),
        (2, float("nan")),
        (2, float("inf")),
    ],
)
def test_adversarial_agent_configuration_bounds(
    max_retries: int,
    timeout_seconds: float,
) -> None:
    """Tests that specialist agent bounded retries [0, 3] and timeout invariants hold."""
    with pytest.raises(ModuleContractViolationError):
        GenericSpecialistAgent(
            role=AgentRole.CROSS_PAPER_SYNTHESIS,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )


def test_adversarial_agent_role_mismatch() -> None:
    """Tests that dispatching payload with mismatched role raises error."""
    agent = GenericSpecialistAgent(role=AgentRole.GAP_DISCOVERY)
    mismatched_payload = SpecialistInputPayload(
        task_id="t-mismatch",
        role=AgentRole.REPORT_COMPOSER,
        goal_statement="Draft report",
    )
    with pytest.raises(ModuleContractViolationError) as exc_info:
        agent.execute_with_retry(mismatched_payload)
    assert "does not match specialist role" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Adversarial Retry Behavior & Failure Containment
# ---------------------------------------------------------------------------


def test_adversarial_repeated_runtime_crashes_containment() -> None:
    """Tests that unhandled exceptions during execution do not crash the caller."""
    call_count = 0

    def crash_handler(inp: SpecialistInputPayload) -> SpecialistOutputPayload:
        nonlocal call_count
        call_count += 1
        raise ZeroDivisionError(f"Simulated crash on call {call_count}")

    agent = GenericSpecialistAgent(
        role=AgentRole.CRITICAL_REVIEWER,
        handler=crash_handler,
        max_retries=2,
    )
    payload = SpecialistInputPayload(
        task_id="t-crash-containment",
        role=AgentRole.CRITICAL_REVIEWER,
        goal_statement="Adversarial audit",
    )

    result = agent.execute_with_retry(payload)
    assert result.status == TaskNodeStatus.FAILED
    assert call_count == 3  # Initial attempt + 2 retries
    assert result.retry_count == 2
    assert "Specialist execution exception: Simulated crash on call 3" in (
        result.error_message or ""
    )


def test_adversarial_intermittent_failure_recovery() -> None:
    """Tests that an intermittent failure recovers on the final allowed retry attempt."""
    attempts = 0

    def intermittent_handler(inp: SpecialistInputPayload) -> SpecialistOutputPayload:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return SpecialistOutputPayload(
                task_id=inp.task_id,
                role=inp.role,
                status=TaskNodeStatus.FAILED,
                error_message=f"Transient failure #{attempts}",
            )
        return SpecialistOutputPayload(
            task_id=inp.task_id,
            role=inp.role,
            status=TaskNodeStatus.COMPLETED,
            data={"recovered": True},
        )

    agent = GenericSpecialistAgent(
        role=AgentRole.QUERY_PLANNER,
        handler=intermittent_handler,
        max_retries=2,
    )
    payload = SpecialistInputPayload(
        task_id="t-intermittent",
        role=AgentRole.QUERY_PLANNER,
        goal_statement="Generate retrieval plan",
    )

    result = agent.execute_with_retry(payload)
    assert result.status == TaskNodeStatus.COMPLETED
    assert result.retry_count == 2
    assert result.data["recovered"] is True
    assert attempts == 3
