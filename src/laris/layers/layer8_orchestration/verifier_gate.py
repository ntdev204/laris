"""Verifier gate enforcing evidence coordinate and citation integrity for specialist outputs.

Adheres to DOC-SPEC-MOD-001 (Boundary H), ADR-006, and Issue #66:
- Rigorous validation of specialist agent outputs and state transitions
- Evidence coordinate provenance integrity checks (offsets, SHA-256 hashes, snippets)
- Enforcement of evidence anchoring on scientific claims preventing hallucinated assertions
- Raises ProvenanceViolationError on unanchored assertions when strict mode is active
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer8_orchestration.schemas import TaskNodeStatus
from laris.layers.layer8_orchestration.specialists import SpecialistOutputPayload

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class VerificationResult:
    """Detailed audit report produced by VerifierGate."""

    is_valid: bool
    violations: List[str] = field(default_factory=list)
    verified_coordinates_count: int = 0
    checked_claims_count: int = 0


class VerifierGate:
    """Verification gate auditing specialist agent outputs against provenance and schema rules."""

    def __init__(self, strict_provenance: bool = True) -> None:
        self.strict_provenance = strict_provenance

    def verify_coordinate_integrity(self, coord: EvidenceCoordinate) -> List[str]:
        """Validates internal integrity of an EvidenceCoordinate record."""
        errors: List[str] = []

        if not coord.coordinate_id or not coord.coordinate_id.strip():
            errors.append("EvidenceCoordinate coordinate_id must not be empty.")
        if not coord.document_id or not coord.document_id.strip():
            errors.append("EvidenceCoordinate document_id must not be empty.")
        if not SHA256_HEX_REGEX.match(coord.document_sha256):
            errors.append(
                f"EvidenceCoordinate document_sha256 '{coord.document_sha256}' is not a valid "
                "64-character hexadecimal SHA-256 digest."
            )
        if coord.char_start < 0:
            errors.append(f"EvidenceCoordinate char_start ({coord.char_start}) cannot be negative.")
        if coord.char_end <= coord.char_start:
            errors.append(
                f"EvidenceCoordinate char_end ({coord.char_end}) must be strictly greater than "
                f"char_start ({coord.char_start})."
            )
        if not coord.verbatim_snippet or not coord.verbatim_snippet.strip():
            errors.append("EvidenceCoordinate verbatim_snippet must not be empty.")
        if not (0.0 <= coord.extraction_confidence <= 1.0):
            errors.append(
                f"EvidenceCoordinate extraction_confidence ({coord.extraction_confidence}) must "
                "be within [0.0, 1.0]."
            )

        return errors

    def verify_output(
        self,
        output: SpecialistOutputPayload,
        require_evidence: bool = False,
    ) -> VerificationResult:
        """Audits specialist output for status consistency, coordinate validity, and anchoring."""
        violations: List[str] = []
        verified_coords = 0
        checked_claims = 0

        # Failed tasks do not need evidence citations
        if output.status == TaskNodeStatus.FAILED:
            if not output.error_message or not output.error_message.strip():
                violations.append("Failed specialist output must specify an error_message.")
            return VerificationResult(
                is_valid=len(violations) == 0,
                violations=violations,
                verified_coordinates_count=0,
                checked_claims_count=0,
            )

        # Evidence requirement
        if require_evidence and not output.evidence_citations:
            violations.append(
                f"Specialist '{output.role.value}' output requires evidence citations, but "
                "evidence_citations list is empty."
            )

        # Coordinate verification
        known_coord_ids = set()
        for coord in output.evidence_citations:
            if not isinstance(coord, EvidenceCoordinate):
                violations.append(
                    f"Found item in evidence_citations that is not an EvidenceCoordinate: {coord}"
                )
                continue
            coord_errors = self.verify_coordinate_integrity(coord)
            if coord_errors:
                violations.extend(coord_errors)
            else:
                verified_coords += 1
                known_coord_ids.add(coord.coordinate_id)

        # Check claims data if present in output data
        claims = output.data.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                checked_claims += 1
                if isinstance(claim, dict):
                    # Check anchoring
                    anchor = claim.get("coordinate_id") or claim.get("evidence_coordinate_id")
                    if not anchor:
                        claim_text = claim.get("claim_text", "")
                        violations.append(
                            f"Scientific claim '{claim_text}' lacks citation anchor."
                        )
                    elif anchor not in known_coord_ids:
                        violations.append(
                            f"Scientific claim references coordinate '{anchor}' not found in "
                            "evidence_citations."
                        )

        is_valid = len(violations) == 0

        if not is_valid and self.strict_provenance and require_evidence:
            raise ProvenanceViolationError(
                f"VerifierGate detected provenance violations for task '{output.task_id}': "
                f"{'; '.join(violations)}."
            )

        return VerificationResult(
            is_valid=is_valid,
            violations=violations,
            verified_coordinates_count=verified_coords,
            checked_claims_count=checked_claims,
        )
