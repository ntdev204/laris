"""Structured research report schema and evidence verification gate.

Adheres to DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-004, and Issue #74:
- Seven mandatory report sections: Executive Summary, Corpus Provenance Manifest,
  Comparative Synthesis, Contradiction Analysis, Ranked Research Gaps, Limitations, Citation Index
- Assertion-to-evidence coordinate anchoring with status tracking
- Evidence gate rejecting or explicitly marking unanchored claims without verified coordinates
- Complete serialization, deserialization, and deterministic Markdown generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    ReportSchemaValidationError,
    UnanchoredAssertionError,
)
from laris.core.schemas import EvidenceCoordinate


class ReportSectionType(str, Enum):
    """The seven mandatory canonical sections of a LARIS Structured Research Report."""

    EXECUTIVE_SUMMARY = "executive_summary"
    CORPUS_PROVENANCE_MANIFEST = "corpus_provenance_manifest"
    COMPARATIVE_SYNTHESIS = "comparative_synthesis"
    CONTRADICTION_ANALYSIS = "contradiction_analysis"
    RESEARCH_GAPS = "research_gaps"
    LIMITATIONS_AND_BOUNDARIES = "limitations_and_boundaries"
    AUDITABLE_CITATION_INDEX = "auditable_citation_index"


class AssertionStatus(str, Enum):
    """Evidence anchoring status of a report assertion."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FLAGGED_MISSING_EVIDENCE = "flagged_missing_evidence"
    REJECTED = "rejected"


@dataclass
class ReportAssertion:
    """Discrete factual claim within a report section anchored to evidence coordinates."""

    assertion_id: str
    section: ReportSectionType
    statement: str
    coordinate_ids: List[str]
    status: AssertionStatus = AssertionStatus.UNVERIFIED
    confidence_score: float = 1.0
    caveat: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.assertion_id.strip():
            raise ReportSchemaValidationError("assertion_id cannot be empty.")
        if not self.statement.strip():
            raise ReportSchemaValidationError("statement cannot be empty.")
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ReportSchemaValidationError("confidence_score must be between 0.0 and 1.0.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize assertion to dictionary."""
        return {
            "assertion_id": self.assertion_id,
            "section": self.section.value,
            "statement": self.statement,
            "coordinate_ids": list(self.coordinate_ids),
            "status": self.status.value,
            "confidence_score": self.confidence_score,
            "caveat": self.caveat,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReportAssertion:
        """Construct assertion from dictionary."""
        return cls(
            assertion_id=data["assertion_id"],
            section=ReportSectionType(data["section"]),
            statement=data["statement"],
            coordinate_ids=list(data.get("coordinate_ids", [])),
            status=AssertionStatus(data.get("status", AssertionStatus.UNVERIFIED.value)),
            confidence_score=float(data.get("confidence_score", 1.0)),
            caveat=data.get("caveat"),
        )


@dataclass(frozen=True)
class CorpusManifestEntry:
    """Record of an ingested document forming the empirical corpus boundary."""

    document_id: str
    title: str
    sha256_hash: str
    publication_year: int
    venue: str
    peer_reviewed: bool = True
    ocr_quality_score: float = 1.0

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ReportSchemaValidationError("document_id cannot be empty.")
        if len(self.sha256_hash) != 64:
            raise ReportSchemaValidationError("sha256_hash must be a 64-character hexadecimal.")
        if not (0.0 <= self.ocr_quality_score <= 1.0):
            raise ReportSchemaValidationError("ocr_quality_score must be between 0.0 and 1.0.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize corpus manifest entry to dictionary."""
        return {
            "document_id": self.document_id,
            "title": self.title,
            "sha256_hash": self.sha256_hash,
            "publication_year": self.publication_year,
            "venue": self.venue,
            "peer_reviewed": self.peer_reviewed,
            "ocr_quality_score": self.ocr_quality_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CorpusManifestEntry:
        """Construct corpus manifest entry from dictionary."""
        return cls(
            document_id=data["document_id"],
            title=data["title"],
            sha256_hash=data["sha256_hash"],
            publication_year=int(data["publication_year"]),
            venue=data["venue"],
            peer_reviewed=bool(data.get("peer_reviewed", True)),
            ocr_quality_score=float(data.get("ocr_quality_score", 1.0)),
        )


@dataclass
class ReportSection:
    """A single canonical section of a structured research report."""

    section_type: ReportSectionType
    title: str
    content_markdown: str
    assertions: List[ReportAssertion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize section to dictionary."""
        return {
            "section_type": self.section_type.value,
            "title": self.title,
            "content_markdown": self.content_markdown,
            "assertions": [a.to_dict() for a in self.assertions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReportSection:
        """Construct section from dictionary."""
        return cls(
            section_type=ReportSectionType(data["section_type"]),
            title=data["title"],
            content_markdown=data["content_markdown"],
            assertions=[ReportAssertion.from_dict(a) for a in data.get("assertions", [])],
        )


@dataclass(frozen=True)
class ReportVerificationSummary:
    """Summary of assertion evidence anchoring and verification coverage."""

    is_valid: bool
    total_assertions: int
    verified_assertions: int
    unanchored_assertions: int
    missing_evidence_ids: List[str]
    coverage_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary."""
        return {
            "is_valid": self.is_valid,
            "total_assertions": self.total_assertions,
            "verified_assertions": self.verified_assertions,
            "unanchored_assertions": self.unanchored_assertions,
            "missing_evidence_ids": list(self.missing_evidence_ids),
            "coverage_ratio": self.coverage_ratio,
        }


@dataclass
class StructuredResearchReport:
    """Canonical research report deliverable strictly partitioned into seven mandatory sections."""

    report_id: str
    query_statement: str
    created_at_iso: str
    corpus_manifest: List[CorpusManifestEntry]
    sections: Dict[ReportSectionType, ReportSection]
    citation_index: Dict[str, EvidenceCoordinate]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.report_id.strip():
            raise ReportSchemaValidationError("report_id cannot be empty.")
        if not self.query_statement.strip():
            raise ReportSchemaValidationError("query_statement cannot be empty.")

    def verify_all_sections_present(self) -> bool:
        """Verify that all seven canonical sections are present."""
        return all(st in self.sections for st in ReportSectionType)

    def all_assertions(self) -> List[ReportAssertion]:
        """Return a flat list of all assertions across all sections."""
        assertions: List[ReportAssertion] = []
        for section in self.sections.values():
            assertions.extend(section.assertions)
        return assertions

    def render_markdown(self) -> str:
        """Render complete structured report as human-readable GitHub-flavored markdown."""
        lines: List[str] = [
            f"# LARIS Structured Research Report: {self.report_id}",
            f"**Inquiry:** {self.query_statement}",
            f"**Generated:** {self.created_at_iso}",
            "",
            "---",
            "",
        ]

        # Render sections in canonical enum order
        section_order = list(ReportSectionType)
        for st in section_order:
            sec = self.sections.get(st)
            if not sec:
                continue
            lines.append(f"## {sec.title}")
            lines.append("")
            lines.append(sec.content_markdown)
            lines.append("")

            # Render assertion anchoring status if present
            if sec.assertions:
                lines.append("### Factual Assertions & Grounding Status")
                for a in sec.assertions:
                    cites = ", ".join(f"`{cid}`" for cid in a.coordinate_ids) or "NONE"
                    status_badge = f"**[{a.status.value.upper()}]**"
                    caveat_str = f" *(Note: {a.caveat})*" if a.caveat else ""
                    lines.append(
                        f"- {status_badge} {a.statement} "
                        f"(Evidence: {cites}, Confidence: {a.confidence_score:.2f}){caveat_str}"
                    )
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete structured report to dictionary."""
        serialized_citations = {
            cid: {
                "coordinate_id": coord.coordinate_id,
                "document_id": coord.document_id,
                "document_sha256": coord.document_sha256,
                "page_number": coord.page_number,
                "section_identifier": coord.section_identifier,
                "paragraph_index": coord.paragraph_index,
                "sentence_index": coord.sentence_index,
                "char_start": coord.char_start,
                "char_end": coord.char_end,
                "verbatim_snippet": coord.verbatim_snippet,
                "extraction_confidence": coord.extraction_confidence,
            }
            for cid, coord in self.citation_index.items()
        }

        return {
            "report_id": self.report_id,
            "query_statement": self.query_statement,
            "created_at_iso": self.created_at_iso,
            "corpus_manifest": [entry.to_dict() for entry in self.corpus_manifest],
            "sections": {st.value: sec.to_dict() for st, sec in self.sections.items()},
            "citation_index": serialized_citations,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StructuredResearchReport:
        """Construct structured report from dictionary."""
        manifest = [CorpusManifestEntry.from_dict(e) for e in data.get("corpus_manifest", [])]
        sections = {
            ReportSectionType(k): ReportSection.from_dict(v)
            for k, v in data.get("sections", {}).items()
        }

        citations: Dict[str, EvidenceCoordinate] = {}
        for cid, cdata in data.get("citation_index", {}).items():
            citations[cid] = EvidenceCoordinate(
                coordinate_id=cdata["coordinate_id"],
                document_id=cdata["document_id"],
                document_sha256=cdata["document_sha256"],
                page_number=int(cdata["page_number"]),
                section_identifier=cdata["section_identifier"],
                paragraph_index=int(cdata["paragraph_index"]),
                sentence_index=int(cdata["sentence_index"]),
                char_start=int(cdata["char_start"]),
                char_end=int(cdata["char_end"]),
                verbatim_snippet=cdata["verbatim_snippet"],
                extraction_confidence=float(cdata.get("extraction_confidence", 1.0)),
            )

        return cls(
            report_id=data["report_id"],
            query_statement=data["query_statement"],
            created_at_iso=data["created_at_iso"],
            corpus_manifest=manifest,
            sections=sections,
            citation_index=citations,
            metadata=dict(data.get("metadata", {})),
        )


class EvidenceGate:
    """Gatekeeper enforcing Boundary K invariant: all factual claims must be evidence-anchored."""

    def __init__(self, minimum_coverage_ratio: float = 1.0) -> None:
        self._minimum_coverage_ratio = minimum_coverage_ratio

    def validate_assertion(
        self,
        assertion: ReportAssertion,
        available_coordinates: Dict[str, EvidenceCoordinate],
        strict: bool = True,
    ) -> ReportAssertion:
        """Validate single assertion against available physical evidence coordinates."""
        if not assertion.coordinate_ids:
            if strict:
                raise UnanchoredAssertionError(
                    f"Assertion '{assertion.assertion_id}' in section '{assertion.section.value}' "
                    "has no evidence coordinates cited."
                )
            assertion.status = AssertionStatus.FLAGGED_MISSING_EVIDENCE
            assertion.caveat = "Missing empirical evidence coordinates; unverified assertion."
            return assertion

        missing = [cid for cid in assertion.coordinate_ids if cid not in available_coordinates]
        if missing:
            if strict:
                raise UnanchoredAssertionError(
                    f"Assertion '{assertion.assertion_id}' cites missing evidence coordinates: "
                    f"{missing}."
                )
            assertion.status = AssertionStatus.FLAGGED_MISSING_EVIDENCE
            assertion.caveat = f"Evidence coordinates {missing} not found in verified index."
            return assertion

        assertion.status = AssertionStatus.VERIFIED
        assertion.caveat = None
        return assertion

    def verify_report(
        self,
        report: StructuredResearchReport,
        strict: bool = True,
    ) -> ReportVerificationSummary:
        """Audit all assertions in report and verify compliance with coverage thresholds."""
        if not report.verify_all_sections_present():
            missing_secs = [st.value for st in ReportSectionType if st not in report.sections]
            raise ReportSchemaValidationError(
                f"Report '{report.report_id}' missing mandatory sections: {missing_secs}."
            )

        total_assertions = 0
        verified_assertions = 0
        unanchored_assertions = 0
        missing_ids: List[str] = []

        for section in report.sections.values():
            for assertion in section.assertions:
                total_assertions += 1
                try:
                    self.validate_assertion(assertion, report.citation_index, strict=strict)
                    if assertion.status == AssertionStatus.VERIFIED:
                        verified_assertions += 1
                    else:
                        unanchored_assertions += 1
                        missing_ids.append(assertion.assertion_id)
                except UnanchoredAssertionError:
                    unanchored_assertions += 1
                    missing_ids.append(assertion.assertion_id)
                    if strict:
                        raise

        coverage = (
            (verified_assertions / total_assertions) if total_assertions > 0 else 1.0
        )
        is_valid = (coverage >= self._minimum_coverage_ratio) and (unanchored_assertions == 0)

        return ReportVerificationSummary(
            is_valid=is_valid,
            total_assertions=total_assertions,
            verified_assertions=verified_assertions,
            unanchored_assertions=unanchored_assertions,
            missing_evidence_ids=missing_ids,
            coverage_ratio=round(coverage, 4),
        )

    def filter_or_annotate_unanchored_assertions(
        self,
        report: StructuredResearchReport,
        drop_unanchored: bool = False,
    ) -> StructuredResearchReport:
        """Sanitize report by dropping unanchored assertions or explicitly annotating them."""
        for section in report.sections.values():
            updated_assertions: List[ReportAssertion] = []
            for assertion in section.assertions:
                self.validate_assertion(assertion, report.citation_index, strict=False)
                if assertion.status == AssertionStatus.VERIFIED:
                    updated_assertions.append(assertion)
                elif not drop_unanchored:
                    updated_assertions.append(assertion)
            section.assertions = updated_assertions
        return report
