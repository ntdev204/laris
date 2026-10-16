"""Structured research report generator and end-to-end evidence gate pipeline.

Adheres to DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-004, and Issue #106:
- Compiles synthesis inputs into the seven mandatory canonical sections
- Integrates EvidenceGate verification preventing unanchored factual assertions
- Supports strict gating (raising UnanchoredAssertionError) and annotated fallback
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from laris.core.errors import ReportSchemaValidationError
from laris.core.schemas import EvidenceCoordinate
from laris.reporting.report_schema import (
    CorpusManifestEntry,
    EvidenceGate,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    ReportVerificationSummary,
    StructuredResearchReport,
)

_CANONICAL_SECTION_TITLES: Dict[ReportSectionType, str] = {
    ReportSectionType.EXECUTIVE_SUMMARY: "Executive Summary & Inquiry Scope",
    ReportSectionType.CORPUS_PROVENANCE_MANIFEST: "Corpus Evidence & Provenance Manifest",
    ReportSectionType.COMPARATIVE_SYNTHESIS: "Comparative Synthesis & Methodological Analysis",
    ReportSectionType.CONTRADICTION_ANALYSIS: "Conflicting Evidence & Contradiction Analysis",
    ReportSectionType.RESEARCH_GAPS: "Ranked Research Gaps & Validation Protocols",
    ReportSectionType.LIMITATIONS_AND_BOUNDARIES: "Limitations & Boundary Conditions",
    ReportSectionType.AUDITABLE_CITATION_INDEX: "Auditable Evidence Citation Index",
}


class StructuredReportGenerator:
    """Generator compiling verified research findings into canonical structured reports."""

    def __init__(
        self,
        evidence_gate: Optional[EvidenceGate] = None,
        default_strict_gate: bool = True,
    ) -> None:
        self._gate = evidence_gate or EvidenceGate(minimum_coverage_ratio=1.0)
        self._default_strict_gate = default_strict_gate

    @property
    def evidence_gate(self) -> EvidenceGate:
        """Return the configured EvidenceGate."""
        return self._gate

    def generate_report(
        self,
        report_id: str,
        query_statement: str,
        corpus_manifest: List[CorpusManifestEntry],
        sections_content: Dict[ReportSectionType, str],
        assertions: List[ReportAssertion],
        citation_index: Dict[str, EvidenceCoordinate],
        metadata: Optional[Dict[str, Any]] = None,
        strict_gate: Optional[bool] = None,
    ) -> tuple[StructuredResearchReport, ReportVerificationSummary]:
        """Compile and verify a complete structured research report."""
        if not report_id.strip():
            raise ReportSchemaValidationError("report_id cannot be empty.")
        if not query_statement.strip():
            raise ReportSchemaValidationError("query_statement cannot be empty.")

        # Check all seven mandatory sections
        missing = [st for st in ReportSectionType if st not in sections_content]
        if missing:
            raise ReportSchemaValidationError(
                f"Cannot generate report: missing content for mandatory sections: "
                f"{[s.value for s in missing]}."
            )

        # Partition assertions by section
        section_assertions: Dict[ReportSectionType, List[ReportAssertion]] = {
            st: [] for st in ReportSectionType
        }
        for a in assertions:
            if a.section in section_assertions:
                section_assertions[a.section].append(a)
            else:
                section_assertions[ReportSectionType.EXECUTIVE_SUMMARY].append(a)

        # Assemble report sections
        report_sections: Dict[ReportSectionType, ReportSection] = {}
        for st in ReportSectionType:
            report_sections[st] = ReportSection(
                section_type=st,
                title=_CANONICAL_SECTION_TITLES[st],
                content_markdown=sections_content[st],
                assertions=section_assertions[st],
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report = StructuredResearchReport(
            report_id=report_id,
            query_statement=query_statement,
            created_at_iso=now_iso,
            corpus_manifest=list(corpus_manifest),
            sections=report_sections,
            citation_index=dict(citation_index),
            metadata=dict(metadata or {}),
        )

        strict = self._default_strict_gate if strict_gate is None else strict_gate
        summary = self._gate.verify_report(report, strict=strict)

        return report, summary
