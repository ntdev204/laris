"""Unit and contract tests for specialist agent interfaces and verifier gate.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #66:
- Tests SpecialistInputPayload and SpecialistOutputPayload interface contracts
- Tests bounded retry ceilings (0 <= max_retries <= 3) and timeout parameters
- Tests VerifierGate evidence coordinate integrity and citation provenance checks
- Tests detection of unanchored assertions and ProvenanceViolationError enforcement
"""

from __future__ import annotations

import pytest

from laris.core.errors import ModuleContractViolationError, ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.orchestration import (
    AgentRole,
    BaseSpecialistAgent,
    GenericSpecialistAgent,
    SpecialistInputPayload,
    SpecialistOutputPayload,
    TaskNodeStatus,
    VerifierGate,
)


@pytest.fixture
def sample_valid_coordinate() -> EvidenceCoordinate:
    """Provides a valid synthetic EvidenceCoordinate instance."""
    return EvidenceCoordinate(
        coordinate_id="coord-spec-001",
        document_id="paper-supercond-2024",
        document_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        page_number=3,
        section_identifier="sec-results",
        paragraph_index=2,
        sentence_index=1,
        char_start=12,
        char_end=68,
        verbatim_snippet="Critical temperature Tc measured at 260 K under 150 GPa.",
        extraction_confidence=0.97,
    )


def test_specialist_input_payload_contracts() -> None:
    """Tests SpecialistInputPayload validation rules."""
    payload = SpecialistInputPayload(
        task_id="task-01",
        role=AgentRole.SCIENTIFIC_CLAIM,
        goal_statement="Extract superconducting claims.",
        parameters={"metric": "Tc"},
        upstream_artifacts={"retrieval": ["doc-1"]},
        timeout_seconds=45.0,
    )
    assert payload.task_id == "task-01"
    assert payload.role == AgentRole.SCIENTIFIC_CLAIM
    assert payload.timeout_seconds == 45.0

    with pytest.raises(ModuleContractViolationError, match="task_id must not be empty"):
        SpecialistInputPayload(task_id="", role=AgentRole.SUPERVISOR, goal_statement="Goal")

    with pytest.raises(ModuleContractViolationError, match="goal_statement must not be empty"):
        SpecialistInputPayload(task_id="t1", role=AgentRole.SUPERVISOR, goal_statement="   ")

    with pytest.raises(ModuleContractViolationError, match="timeout_seconds must be a positive"):
        SpecialistInputPayload(
            task_id="t1", role=AgentRole.SUPERVISOR, goal_statement="Goal", timeout_seconds=0.0
        )


def test_specialist_output_payload_contracts(
    sample_valid_coordinate: EvidenceCoordinate,
) -> None:
    """Tests SpecialistOutputPayload validation rules."""
    output = SpecialistOutputPayload(
        task_id="task-01",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={"claims": [{"claim_text": "High Tc", "coordinate_id": "coord-spec-001"}]},
        evidence_citations=[sample_valid_coordinate],
        tokens_used=250,
        duration_ms=45.2,
    )
    assert output.task_id == "task-01"
    assert output.tokens_used == 250
    assert len(output.evidence_citations) == 1

    with pytest.raises(ModuleContractViolationError, match="task_id must not be empty"):
        SpecialistOutputPayload(
            task_id="",
            role=AgentRole.SUPERVISOR,
            status=TaskNodeStatus.COMPLETED,
        )

    with pytest.raises(ModuleContractViolationError, match="tokens_used must be non-negative"):
        SpecialistOutputPayload(
            task_id="t1",
            role=AgentRole.SUPERVISOR,
            status=TaskNodeStatus.COMPLETED,
            tokens_used=-10,
        )

    with pytest.raises(ModuleContractViolationError, match="duration_ms must be a non-negative"):
        SpecialistOutputPayload(
            task_id="t1",
            role=AgentRole.SUPERVISOR,
            status=TaskNodeStatus.COMPLETED,
            duration_ms=-1.0,
        )

    with pytest.raises(ModuleContractViolationError, match="retry_count must be non-negative"):
        SpecialistOutputPayload(
            task_id="t1",
            role=AgentRole.SUPERVISOR,
            status=TaskNodeStatus.COMPLETED,
            retry_count=-1,
        )


def test_base_specialist_agent_bounds() -> None:
    """Verifies that specialist agent retries are strictly bounded [0, 3]."""
    # Valid agent initialization
    agent = GenericSpecialistAgent(role=AgentRole.LANGUAGE_ANALYSIS, max_retries=2)
    assert agent.max_retries == 2

    # Exceed retry ceiling (> 3)
    with pytest.raises(ModuleContractViolationError, match="bounded within"):
        GenericSpecialistAgent(role=AgentRole.LANGUAGE_ANALYSIS, max_retries=4)

    # Negative retries (< 0)
    with pytest.raises(ModuleContractViolationError, match="bounded within"):
        GenericSpecialistAgent(role=AgentRole.LANGUAGE_ANALYSIS, max_retries=-1)

    # Invalid timeout
    with pytest.raises(ModuleContractViolationError, match="timeout_seconds must be a positive"):
        GenericSpecialistAgent(
            role=AgentRole.LANGUAGE_ANALYSIS, max_retries=2, timeout_seconds=0.0
        )


def test_specialist_agent_execution_and_retry_lifecycle() -> None:
    """Tests execution and bounded retry behavior under transient and persistent failures."""
    # 1. Normal success
    agent_ok = GenericSpecialistAgent(role=AgentRole.DOCUMENT_ANALYSIS)
    payload_ok = SpecialistInputPayload("t1", AgentRole.DOCUMENT_ANALYSIS, "Analyze doc")
    out_ok = agent_ok.execute_with_retry(payload_ok)
    assert out_ok.status == TaskNodeStatus.COMPLETED
    assert out_ok.retry_count == 0

    # 2. Role mismatch failure
    payload_mismatch = SpecialistInputPayload("t2", AgentRole.QUERY_PLANNER, "Plan")
    with pytest.raises(ModuleContractViolationError, match="does not match specialist role"):
        agent_ok.execute_with_retry(payload_mismatch)

    # 3. Flaky agent: fails once, succeeds on retry 1
    call_count = 0

    def flaky_handler(payload: SpecialistInputPayload) -> SpecialistOutputPayload:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return SpecialistOutputPayload(
                task_id=payload.task_id,
                role=payload.role,
                status=TaskNodeStatus.FAILED,
                error_message="Transient network glitch.",
            )
        return SpecialistOutputPayload(
            task_id=payload.task_id,
            role=payload.role,
            status=TaskNodeStatus.COMPLETED,
            data={"recovered": True},
        )

    agent_flaky = GenericSpecialistAgent(
        role=AgentRole.EVIDENCE_RETRIEVAL,
        handler=flaky_handler,
        max_retries=2,
    )
    payload_flaky = SpecialistInputPayload("t3", AgentRole.EVIDENCE_RETRIEVAL, "Retrieve")
    out_recovered = agent_flaky.execute_with_retry(payload_flaky)
    assert out_recovered.status == TaskNodeStatus.COMPLETED
    assert out_recovered.retry_count == 1
    assert call_count == 2

    # 4. Persistent failure: reaches max_retries and returns FAILED
    agent_failing = GenericSpecialistAgent(
        role=AgentRole.CRITICAL_REVIEWER,
        handler=lambda p: SpecialistOutputPayload(
            p.task_id, p.role, TaskNodeStatus.FAILED, error_message="Fatal unrecoverable error"
        ),
        max_retries=2,
    )
    payload_fatal = SpecialistInputPayload("t4", AgentRole.CRITICAL_REVIEWER, "Review")
    out_fatal = agent_failing.execute_with_retry(payload_fatal)
    assert out_fatal.status == TaskNodeStatus.FAILED
    assert out_fatal.retry_count == 2


def test_verifier_gate_coordinate_integrity(
    sample_valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies VerifierGate audit of individual evidence coordinates."""
    verifier = VerifierGate(strict_provenance=False)

    # Valid coordinate
    errors = verifier.verify_coordinate_integrity(sample_valid_coordinate)
    assert len(errors) == 0

    # Broken SHA-256 (not 64 hex characters)
    coord_bad_hash = EvidenceCoordinate(
        coordinate_id="c1",
        document_id="doc1",
        document_sha256="invalid_hash_string",
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=10,
        verbatim_snippet="snippet text",
        extraction_confidence=0.9,
    )
    errors_hash = verifier.verify_coordinate_integrity(coord_bad_hash)
    assert len(errors_hash) == 1
    assert "not a valid 64-character hexadecimal" in errors_hash[0]

    # Equal character offsets (zero-width range, allowed by dataclass but rejected by VerifierGate)
    coord_zero_range = EvidenceCoordinate(
        coordinate_id="c2",
        document_id="doc1",
        document_sha256=sample_valid_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=10,
        char_end=10,
        verbatim_snippet="snippet",
        extraction_confidence=0.9,
    )
    errors_offsets = verifier.verify_coordinate_integrity(coord_zero_range)
    assert any("strictly greater than char_start" in e for e in errors_offsets)

    # Empty snippet
    coord_empty_snip = EvidenceCoordinate(
        coordinate_id="c3",
        document_id="doc1",
        document_sha256=sample_valid_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=5,
        verbatim_snippet="   ",
        extraction_confidence=0.9,
    )
    assert any(
        "verbatim_snippet must not be empty" in e
        for e in verifier.verify_coordinate_integrity(coord_empty_snip)
    )

    # Empty coordinate_id and document_id
    coord_empty_ids = EvidenceCoordinate(
        coordinate_id="   ",
        document_id="",
        document_sha256=sample_valid_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=5,
        verbatim_snippet="snippet",
        extraction_confidence=0.9,
    )
    errors_empty_ids = verifier.verify_coordinate_integrity(coord_empty_ids)
    assert any("coordinate_id must not be empty" in e for e in errors_empty_ids)
    assert any("document_id must not be empty" in e for e in errors_empty_ids)

    # Out of bounds confidence via setattr (simulating corrupted state)
    coord_oob = EvidenceCoordinate(
        coordinate_id="c4",
        document_id="doc1",
        document_sha256=sample_valid_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=5,
        verbatim_snippet="snippet",
        extraction_confidence=0.5,
    )
    object.__setattr__(coord_oob, "extraction_confidence", 1.5)
    assert any(
        "must be within [0.0, 1.0]" in e
        for e in verifier.verify_coordinate_integrity(coord_oob)
    )


def test_verifier_gate_strict_provenance_enforcement(
    sample_valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that strict provenance mode raises ProvenanceViolationError."""
    verifier_strict = VerifierGate(strict_provenance=True)
    verifier_lenient = VerifierGate(strict_provenance=False)

    # Missing evidence citations when required
    output_no_evidence = SpecialistOutputPayload(
        task_id="t-claim",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={"claims": [{"claim_text": "Unanchored assertion"}]},
        evidence_citations=[],  # Empty!
    )

    # Strict mode raises ProvenanceViolationError
    with pytest.raises(ProvenanceViolationError, match="requires evidence citations"):
        verifier_strict.verify_output(output_no_evidence, require_evidence=True)

    # Lenient mode returns invalid result with violations
    result = verifier_lenient.verify_output(output_no_evidence, require_evidence=True)
    assert result.is_valid is False
    assert len(result.violations) >= 1
    assert "requires evidence citations" in result.violations[0]


def test_verifier_gate_anchored_claims_validation(
    sample_valid_coordinate: EvidenceCoordinate,
) -> None:
    """Tests claim anchoring against verified coordinate IDs."""
    verifier = VerifierGate(strict_provenance=False)

    # Properly anchored claim
    output_valid = SpecialistOutputPayload(
        task_id="t-claim-anchored",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={
            "claims": [
                {
                    "claim_text": "Superconductivity observed at 260 K",
                    "coordinate_id": sample_valid_coordinate.coordinate_id,
                }
            ]
        },
        evidence_citations=[sample_valid_coordinate],
    )
    res_valid = verifier.verify_output(output_valid, require_evidence=True)
    assert res_valid.is_valid is True
    assert res_valid.verified_coordinates_count == 1
    assert res_valid.checked_claims_count == 1
    assert len(res_valid.violations) == 0

    # Claim referencing non-existent coordinate ID
    output_orphan_claim = SpecialistOutputPayload(
        task_id="t-claim-orphan",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        data={
            "claims": [
                {
                    "claim_text": "Superconductivity observed",
                    "coordinate_id": "non_existent_coord_id",
                }
            ]
        },
        evidence_citations=[sample_valid_coordinate],
    )
    res_orphan = verifier.verify_output(output_orphan_claim, require_evidence=True)
    assert any(
        "references coordinate 'non_existent_coord_id' not found" in v
        for v in res_orphan.violations
    )


def test_verifier_gate_failed_task_audit() -> None:
    """Verifies that failed outputs must provide an error_message."""
    verifier = VerifierGate(strict_provenance=True)

    # Failed output with valid message
    failed_valid = SpecialistOutputPayload(
        task_id="t-fail-1",
        role=AgentRole.EVIDENCE_RETRIEVAL,
        status=TaskNodeStatus.FAILED,
        error_message="Index unavailable.",
    )
    res_fail = verifier.verify_output(failed_valid)
    assert res_fail.is_valid is True

    # Failed output missing error message
    failed_bad = SpecialistOutputPayload(
        task_id="t-fail-2",
        role=AgentRole.EVIDENCE_RETRIEVAL,
        status=TaskNodeStatus.FAILED,
        error_message="",
    )
    res_bad = verifier.verify_output(failed_bad)
    assert res_bad.is_valid is False
    assert any("must specify an error_message" in v for v in res_bad.violations)


def test_base_specialist_agent_not_implemented() -> None:
    """Verifies that BaseSpecialistAgent.execute raises NotImplementedError."""
    class DummyAgent(BaseSpecialistAgent):
        def execute(
            self, input_payload: SpecialistInputPayload
        ) -> SpecialistOutputPayload:
            return super().execute(input_payload)

    agent = DummyAgent(role=AgentRole.CRITICAL_REVIEWER)
    payload = SpecialistInputPayload(
        task_id="t1",
        role=AgentRole.CRITICAL_REVIEWER,
        goal_statement="Review scientific claim",
    )
    with pytest.raises(NotImplementedError):
        agent.execute(payload)


def test_specialist_agent_exception_handling_in_retry() -> None:
    """Verifies that unexpected exceptions during execution are caught and recorded."""
    def failing_handler(inp: SpecialistInputPayload) -> SpecialistOutputPayload:
        raise RuntimeError("Kernel crashed unexpectedly")

    agent = GenericSpecialistAgent(
        role=AgentRole.GAP_DISCOVERY,
        handler=failing_handler,
        max_retries=1,
    )
    payload = SpecialistInputPayload(
        task_id="t-crash",
        role=AgentRole.GAP_DISCOVERY,
        goal_statement="Discover research gaps",
    )
    output = agent.execute_with_retry(payload)
    assert output.status == TaskNodeStatus.FAILED
    assert "Specialist execution exception: Kernel crashed unexpectedly" in (
        output.error_message or ""
    )
    assert output.retry_count == 1


def test_verifier_gate_additional_integrity_and_type_checks(
    sample_valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies VerifierGate edge checks: negative start, non-coordinate item, corrupted coord."""
    verifier = VerifierGate(strict_provenance=False)

    # Negative char_start via setattr
    coord_neg = EvidenceCoordinate(
        coordinate_id="c-neg",
        document_id="doc1",
        document_sha256=sample_valid_coordinate.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=1,
        sentence_index=1,
        char_start=0,
        char_end=5,
        verbatim_snippet="snippet",
        extraction_confidence=0.5,
    )
    object.__setattr__(coord_neg, "char_start", -5)
    errors_neg = verifier.verify_coordinate_integrity(coord_neg)
    assert any("char_start (-5) cannot be negative" in e for e in errors_neg)

    # Non-EvidenceCoordinate in evidence_citations
    output_bad_type = SpecialistOutputPayload(
        task_id="t-bad-type",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        evidence_citations=["not_a_coordinate"],  # type: ignore[list-item]
    )
    res_type = verifier.verify_output(output_bad_type)
    assert res_type.is_valid is False
    assert any("is not an EvidenceCoordinate" in v for v in res_type.violations)

    # Corrupted EvidenceCoordinate in evidence_citations
    output_corrupted_coord = SpecialistOutputPayload(
        task_id="t-corrupt-coord",
        role=AgentRole.SCIENTIFIC_CLAIM,
        status=TaskNodeStatus.COMPLETED,
        evidence_citations=[coord_neg],
    )
    res_corrupt = verifier.verify_output(output_corrupted_coord)
    assert res_corrupt.is_valid is False
    assert any("char_start (-5) cannot be negative" in v for v in res_corrupt.violations)

