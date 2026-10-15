"""Evidence coordinate verification, provenance auditing, and fail-closed validation.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010:
- Bitwise coordinate integrity verification against source document spans
- Provenance checksum auditing matching document SHA-256 hashes
- Strict fail-closed semantics (ProvenanceViolationError) on missing/tampered coordinates
- Verification of page, paragraph, sentence, and character offsets
"""

from __future__ import annotations

from typing import Dict, List, Optional

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer6_retrieval.schemas import RetrievalCandidate


class EvidenceCoordinateValidator:
    """Validator auditing evidence coordinates and enforcing fail-closed provenance."""

    def __init__(
        self,
        corpus: Optional[Dict[str, str]] = None,
        document_checksums: Optional[Dict[str, str]] = None,
    ) -> None:
        self.corpus = dict(corpus or {})
        self.document_checksums = dict(document_checksums or {})

    def register_document(
        self,
        document_id: str,
        text: str,
        document_sha256: str,
    ) -> None:
        """Registers a verified source document text and its canonical SHA-256 checksum."""
        self.corpus[document_id] = text
        self.document_checksums[document_id] = document_sha256

    def validate_coordinate(
        self,
        coordinate: EvidenceCoordinate,
        document_text: Optional[str] = None,
        expected_sha256: Optional[str] = None,
    ) -> bool:
        """Audits an individual EvidenceCoordinate for bitwise and structural integrity."""
        cid = coordinate.coordinate_id
        if not cid or not cid.strip():
            raise ProvenanceViolationError("EvidenceCoordinate coordinate_id must not be empty.")

        if coordinate.page_number < 1:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' page_number must be >= 1, got {coordinate.page_number}."
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

        # Audit SHA-256 checksum
        target_sha = expected_sha256 or self.document_checksums.get(coordinate.document_id)
        if target_sha is not None and coordinate.document_sha256 != target_sha:
            raise ProvenanceViolationError(
                f"Coordinate '{cid}' document_sha256 mismatch: expected '{target_sha}', "
                f"got '{coordinate.document_sha256}'."
            )

        # Audit physical character offset span against source text
        target_text = document_text or self.corpus.get(coordinate.document_id)
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
