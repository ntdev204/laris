"""Evidence coordinate verification, provenance auditing, and fail-closed validation.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010:
- Bitwise coordinate integrity verification against source document spans
- Provenance checksum auditing matching document SHA-256 hashes
- Strict fail-closed semantics (ProvenanceViolationError) on missing/tampered coordinates
- Verification of page, paragraph, sentence, and character offsets
- Document revision identity checking and structured audit trail generation
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer6_retrieval.schemas import RetrievalCandidate

_SHA256_HEX_PATTERN = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class DocumentProvenanceRecord:
    """Canonical registration record for a source document in the provenance registry."""

    document_id: str
    document_sha256: str
    text: str
    revision_id: str = "1.0.0"
    total_pages: Optional[int] = None


@dataclass(frozen=True)
class ProvenanceViolationDetail:
    """Structured detail of a single coordinate or candidate provenance violation."""

    candidate_id: str
    coordinate_id: Optional[str]
    violation_type: str
    message: str


@dataclass(frozen=True)
class ProvenanceAuditReport:
    """Comprehensive audit trail report for evaluated retrieval candidates."""

    total_candidates: int
    verified_candidates: int
    failed_candidates: int
    violations: List[ProvenanceViolationDetail]

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0


class EvidenceCoordinateValidator:
    """Validator auditing evidence coordinates and enforcing fail-closed provenance."""

    def __init__(
        self,
        corpus: Optional[Dict[str, str]] = None,
        document_checksums: Optional[Dict[str, str]] = None,
        document_revisions: Optional[Dict[str, str]] = None,
        document_page_counts: Optional[Dict[str, int]] = None,
    ) -> None:
        self.corpus: Dict[str, str] = dict(corpus or {})
        self.document_checksums: Dict[str, str] = dict(document_checksums or {})
        self.document_revisions: Dict[str, str] = dict(document_revisions or {})
        self.document_page_counts: Dict[str, int] = dict(document_page_counts or {})

    def register_document(
        self,
        document_id: str,
        text: str,
        document_sha256: str,
        revision_id: str = "1.0.0",
        total_pages: Optional[int] = None,
    ) -> None:
        """Registers a verified source document text, canonical SHA-256, and metadata."""
        self.corpus[document_id] = text
        self.document_checksums[document_id] = document_sha256
        self.document_revisions[document_id] = revision_id
        if total_pages is not None:
            self.document_page_counts[document_id] = total_pages

    def validate_coordinate(
        self,
        coordinate: EvidenceCoordinate,
        document_text: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        expected_revision: Optional[str] = None,
    ) -> bool:
        """Audits an individual EvidenceCoordinate for bitwise and structural integrity."""
        cid = coordinate.coordinate_id
        if not cid or not cid.strip():
            raise ProvenanceViolationError("EvidenceCoordinate coordinate_id must not be empty.")

        doc_id = coordinate.document_id
        if not doc_id or not doc_id.strip():
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' document_id must not be empty."
            )

        if coordinate.page_number < 1:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' page_number must be >= 1, got {coordinate.page_number}."
            )

        max_pages = self.document_page_counts.get(doc_id)
        if max_pages is not None and coordinate.page_number > max_pages:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' page_number ({coordinate.page_number}) exceeds "
                f"document max_pages ({max_pages})."
            )

        if coordinate.paragraph_index < 0:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' paragraph_index must be >= 0, "
                f"got {coordinate.paragraph_index}."
            )

        if coordinate.sentence_index < 0:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' sentence_index must be >= 0, "
                f"got {coordinate.sentence_index}."
            )

        if coordinate.char_start < 0 or coordinate.char_end < coordinate.char_start:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' invalid character range: "
                f"[{coordinate.char_start}:{coordinate.char_end}]."
            )

        if not coordinate.verbatim_snippet or not coordinate.verbatim_snippet.strip():
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' verbatim_snippet must not be empty."
            )

        if not coordinate.section_identifier or not coordinate.section_identifier.strip():
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' section_identifier must not be empty."
            )

        if not (0.0 <= coordinate.extraction_confidence <= 1.0):
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' extraction_confidence must be between 0.0 and 1.0, "
                f"got {coordinate.extraction_confidence}."
            )

        sha = coordinate.document_sha256
        if not sha or len(sha) != 64 or not _SHA256_HEX_PATTERN.fullmatch(sha):
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' invalid document_sha256 format: '{sha}' "
                "(must be 64-char lowercase hex)."
            )

        target_rev = self.document_revisions.get(doc_id)
        if (
            expected_revision is not None
            and target_rev is not None
            and target_rev != expected_revision
        ):
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' document revision mismatch: expected '{expected_revision}', "
                f"got '{target_rev}'."
            )
        elif expected_revision is not None and target_rev is None:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' document '{doc_id}' has no registered revision; "
                f"expected '{expected_revision}'."
            )

        target_sha = expected_sha256 or self.document_checksums.get(doc_id)
        if target_sha is not None and coordinate.document_sha256 != target_sha:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' document_sha256 mismatch: expected '{target_sha}', "
                f"got '{coordinate.document_sha256}'."
            )

        target_text = document_text or self.corpus.get(doc_id)
        if target_text is not None:
            if coordinate.char_end > len(target_text):
                raise ProvenanceViolationError(
                    f"Coordinate '{cid}' char_end ({coordinate.char_end}) exceeds "
                    f"document length ({len(target_text)})."
                )
            extracted_span = target_text[coordinate.char_start : coordinate.char_end]
            if extracted_span != coordinate.verbatim_snippet:
                raise ProvenanceViolationError(
                    f"Coordinate '{cid}' verbatim snippet mismatch at "
                    f"[{coordinate.char_start}:{coordinate.char_end}]: expected "
                    f"'{extracted_span}', got '{coordinate.verbatim_snippet}'."
                )

        return True

    def validate_candidate(
        self,
        candidate: RetrievalCandidate,
        require_coordinates: bool = True,
    ) -> bool:
        """Validates that a retrieval candidate possesses verified source provenance."""
        if require_coordinates and not candidate.coordinates:
            raise ProvenanceViolationError(
                f"RetrievalCandidate '{candidate.candidate_id}' lacks verified "
                "EvidenceCoordinate records (fail closed under ADR-004)."
            )

        for coord in candidate.coordinates:
            self.validate_coordinate(coord)

        return True

    def validate_candidates(
        self,
        candidates: List[RetrievalCandidate],
        require_coordinates: bool = True,
        fail_closed: bool = True,
    ) -> List[RetrievalCandidate]:
        """Audits candidate list, failing closed or filtering invalid candidates."""
        valid_candidates: List[RetrievalCandidate] = []
        for cand in candidates:
            try:
                self.validate_candidate(cand, require_coordinates=require_coordinates)
                valid_candidates.append(cand)
            except ProvenanceViolationError:
                if fail_closed:
                    raise

        return valid_candidates

    def audit_candidates(
        self,
        candidates: List[RetrievalCandidate],
        require_coordinates: bool = True,
    ) -> ProvenanceAuditReport:
        """Performs non-fatal provenance audit on candidates, returning structured report."""
        violations: List[ProvenanceViolationDetail] = []
        verified_count = 0
        failed_count = 0

        for cand in candidates:
            cand_id = cand.candidate_id
            if require_coordinates and not cand.coordinates:
                violations.append(
                    ProvenanceViolationDetail(
                        candidate_id=cand_id,
                        coordinate_id=None,
                        violation_type="MISSING_COORDINATES",
                        message=f"Candidate '{cand_id}' has no EvidenceCoordinate records.",
                    )
                )
                failed_count += 1
                continue

            cand_failed = False
            for coord in cand.coordinates:
                try:
                    self.validate_coordinate(coord)
                except ProvenanceViolationError as exc:
                    violations.append(
                        ProvenanceViolationDetail(
                            candidate_id=cand_id,
                            coordinate_id=coord.coordinate_id,
                            violation_type="CORRUPTED_COORDINATE",
                            message=str(exc),
                        )
                    )
                    cand_failed = True

            if cand_failed:
                failed_count += 1
            else:
                verified_count += 1

        return ProvenanceAuditReport(
            total_candidates=len(candidates),
            verified_candidates=verified_count,
            failed_candidates=failed_count,
            violations=violations,
        )
