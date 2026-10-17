"""Local-first evidence source span inspection and coordinate resolution.

Adheres to DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-001, and ADR-004:
- Local-first inspection of evidence source spans and exact character offsets
- Coordinate resolution against report citation indices and registered corpus texts
- Contextual snippet extraction with surrounding before/after context windows
- Bitwise checksum and integrity auditing of source documents
- Structured rendering of human-inspectable evidence cards
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    CoordinateResolutionError,
    ReportSchemaValidationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reporting.report_schema import (
    ReportAssertion,
    ReportSectionType,
    StructuredResearchReport,
)


@dataclass(frozen=True)
class EvidenceSourceCard:
    """Detailed inspection card for an evidence coordinate in document context."""

    coordinate_id: str
    document_id: str
    document_sha256: str
    page_number: int
    section_identifier: str
    paragraph_index: int
    sentence_index: int
    char_start: int
    char_end: int
    verbatim_snippet: str
    extraction_confidence: float
    context_before: str = ""
    context_after: str = ""
    resolved_against_document: bool = False
    document_checksum_valid: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert evidence source card to dictionary."""
        return {
            "coordinate_id": self.coordinate_id,
            "document_id": self.document_id,
            "document_sha256": self.document_sha256,
            "page_number": self.page_number,
            "section_identifier": self.section_identifier,
            "paragraph_index": self.paragraph_index,
            "sentence_index": self.sentence_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "verbatim_snippet": self.verbatim_snippet,
            "extraction_confidence": self.extraction_confidence,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "resolved_against_document": self.resolved_against_document,
            "document_checksum_valid": self.document_checksum_valid,
            "metadata": dict(self.metadata),
        }

    def render_markdown(self) -> str:
        """Render card as human-readable GitHub-flavored markdown."""
        integrity_status = (
            "Verified Match" if self.document_checksum_valid else "Checksum Unverified"
        )
        resolution_status = (
            "Source Text Resolved" if self.resolved_against_document else "Citation Index Only"
        )
        lines = [
            f"#### Evidence Source Coordinate: `{self.coordinate_id}`",
            f"- **Document ID:** `{self.document_id}` (p. {self.page_number}, "
            f"sec: `{self.section_identifier}`, para: {self.paragraph_index})",
            f"- **SHA-256:** `{self.document_sha256[:16]}...` ({integrity_status})",
            f"- **Span Offsets:** `[{self.char_start}:{self.char_end}]` ({resolution_status})",
            f"- **Extraction Confidence:** {self.extraction_confidence:.2f}",
            "",
            "> [!NOTE]",
            f"> **Source Snippet:** \"{self.verbatim_snippet}\"",
        ]
        if self.resolved_against_document and (self.context_before or self.context_after):
            lines.append(">")
            lines.append(
                f"> **Context:** ...{self.context_before}"
                f"**[{self.verbatim_snippet}]**"
                f"{self.context_after}..."
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class InspectionSummary:
    """Summary of coordinate resolution and inspection across a report."""

    total_citations: int
    resolved_citations: int
    unresolved_citations: List[str]
    document_verified_citations: int
    coverage_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert inspection summary to dictionary."""
        return {
            "total_citations": self.total_citations,
            "resolved_citations": self.resolved_citations,
            "unresolved_citations": list(self.unresolved_citations),
            "document_verified_citations": self.document_verified_citations,
            "coverage_ratio": self.coverage_ratio,
        }


class EvidenceInspector:
    """Local-first inspector resolving evidence coordinates and verifying spans."""

    def __init__(
        self,
        citation_index: Optional[Dict[str, EvidenceCoordinate]] = None,
        document_texts: Optional[Dict[str, str]] = None,
    ) -> None:
        self.citation_index: Dict[str, EvidenceCoordinate] = dict(citation_index or {})
        self.document_texts: Dict[str, str] = dict(document_texts or {})

    def register_coordinate(self, coordinate: EvidenceCoordinate) -> None:
        """Register an EvidenceCoordinate in the inspector index."""
        if not coordinate.coordinate_id.strip():
            raise ReportSchemaValidationError("coordinate_id cannot be empty.")
        self.citation_index[coordinate.coordinate_id] = coordinate

    def register_document(self, document_id: str, text: str) -> None:
        """Register a source document's plain text in local storage."""
        if not document_id.strip():
            raise ReportSchemaValidationError("document_id cannot be empty.")
        self.document_texts[document_id] = text

    def resolve_coordinate(self, coordinate_id: str) -> EvidenceCoordinate:
        """Resolve a coordinate ID to its canonical EvidenceCoordinate record."""
        coord = self.citation_index.get(coordinate_id)
        if coord is None:
            raise CoordinateResolutionError(
                f"Evidence coordinate '{coordinate_id}' could not be resolved in citation index."
            )
        return coord

    def inspect_coordinate(
        self, coordinate_id: str, context_window: int = 80
    ) -> EvidenceSourceCard:
        """Inspect coordinate, resolving exact source span and surrounding context."""
        coord = self.resolve_coordinate(coordinate_id)
        doc_text = self.document_texts.get(coord.document_id)

        if doc_text is None:
            return EvidenceSourceCard(
                coordinate_id=coord.coordinate_id,
                document_id=coord.document_id,
                document_sha256=coord.document_sha256,
                page_number=coord.page_number,
                section_identifier=coord.section_identifier,
                paragraph_index=coord.paragraph_index,
                sentence_index=coord.sentence_index,
                char_start=coord.char_start,
                char_end=coord.char_end,
                verbatim_snippet=coord.verbatim_snippet,
                extraction_confidence=coord.extraction_confidence,
                context_before="",
                context_after="",
                resolved_against_document=False,
                document_checksum_valid=False,
            )

        # Audit document checksum
        computed_hash = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
        checksum_valid = computed_hash == coord.document_sha256

        # Extract surrounding context
        start = max(0, coord.char_start - context_window)
        end = min(len(doc_text), coord.char_end + context_window)
        context_before = doc_text[start:coord.char_start]
        context_after = doc_text[coord.char_end:end]

        return EvidenceSourceCard(
            coordinate_id=coord.coordinate_id,
            document_id=coord.document_id,
            document_sha256=coord.document_sha256,
            page_number=coord.page_number,
            section_identifier=coord.section_identifier,
            paragraph_index=coord.paragraph_index,
            sentence_index=coord.sentence_index,
            char_start=coord.char_start,
            char_end=coord.char_end,
            verbatim_snippet=coord.verbatim_snippet,
            extraction_confidence=coord.extraction_confidence,
            context_before=context_before,
            context_after=context_after,
            resolved_against_document=True,
            document_checksum_valid=checksum_valid,
        )

    def inspect_assertion(
        self, assertion: ReportAssertion, context_window: int = 80
    ) -> List[EvidenceSourceCard]:
        """Inspect all coordinates cited by a specific report assertion."""
        cards: List[EvidenceSourceCard] = []
        for cid in assertion.coordinate_ids:
            cards.append(self.inspect_coordinate(cid, context_window=context_window))
        return cards

    def inspect_section_assertions(
        self, report: StructuredResearchReport, section_type: ReportSectionType
    ) -> Dict[str, List[EvidenceSourceCard]]:
        """Inspect all assertions within a specified report section."""
        section = report.sections.get(section_type)
        if not section:
            return {}
        result: Dict[str, List[EvidenceSourceCard]] = {}
        for assertion in section.assertions:
            result[assertion.assertion_id] = self.inspect_assertion(assertion)
        return result

    def generate_inspection_summary(
        self, report: StructuredResearchReport
    ) -> InspectionSummary:
        """Generate a complete inspection summary across all report citations."""
        all_cited_ids: set[str] = set()
        for assertion in report.all_assertions():
            all_cited_ids.update(assertion.coordinate_ids)

        total = len(all_cited_ids)
        if total == 0:
            return InspectionSummary(
                total_citations=0,
                resolved_citations=0,
                unresolved_citations=[],
                document_verified_citations=0,
                coverage_ratio=1.0,
            )

        resolved = 0
        doc_verified = 0
        unresolved: List[str] = []

        for cid in sorted(all_cited_ids):
            coord = self.citation_index.get(cid) or report.citation_index.get(cid)
            if coord is not None:
                resolved += 1
                doc_text = self.document_texts.get(coord.document_id)
                if doc_text is not None:
                    h = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
                    if h == coord.document_sha256:
                        doc_verified += 1
            else:
                unresolved.append(cid)

        return InspectionSummary(
            total_citations=total,
            resolved_citations=resolved,
            unresolved_citations=unresolved,
            document_verified_citations=doc_verified,
            coverage_ratio=resolved / total if total > 0 else 1.0,
        )
