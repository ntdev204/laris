"""Unit and contract tests for the On-Demand Academic Manuscript Composer.

Tests compliance with DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), and Issue #76:
- Strict opt-in enforcement preventing uncommanded manuscript generation
- Accurate mapping of 7 canonical report sections into academic IMRAD structure
- Full preservation of evidence coordinates and provenance citations
- Publication-quality Markdown and standard LaTeX article rendering
- Edge cases: missing mandatory sections, empty metadata, custom venues/authors
"""

from __future__ import annotations

import pytest

from laris.core.errors import (
    ModuleContractViolationError,
    ReportSchemaValidationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer11_reporting import (
    AcademicManuscript,
    AssertionStatus,
    CorpusManifestEntry,
    ManuscriptComposer,
    ManuscriptSection,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    StructuredResearchReport,
)


def _make_test_coordinate(cid: str = "COORD-TEST-01") -> EvidenceCoordinate:
    """Helper generating a valid EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id=cid,
        document_id="DOC-MED-2024",
        document_sha256="c" * 64,
        page_number=3,
        section_identifier="Results",
        paragraph_index=2,
        sentence_index=1,
        char_start=150,
        char_end=210,
        verbatim_snippet="Kinase domain mutant shows 10-fold reduced binding affinity.",
        extraction_confidence=0.97,
    )


def _make_complete_report(report_id: str = "REP-MANUSCRIPT-01") -> StructuredResearchReport:
    """Helper creating a valid 7-section structured research report."""
    coord = _make_test_coordinate()
    manifest = [
        CorpusManifestEntry(
            document_id="DOC-MED-2024",
            title="Structural Insights into Kinase Mutants",
            sha256_hash="c" * 64,
            publication_year=2024,
            venue="Structure",
            peer_reviewed=True,
            ocr_quality_score=0.99,
        )
    ]
    sections = {}
    titles = {
        ReportSectionType.EXECUTIVE_SUMMARY: "Executive Summary & Inquiry Scope",
        ReportSectionType.CORPUS_PROVENANCE_MANIFEST: "Corpus Evidence & Provenance Manifest",
        ReportSectionType.COMPARATIVE_SYNTHESIS: "Comparative Synthesis & Methodological Analysis",
        ReportSectionType.CONTRADICTION_ANALYSIS: "Conflicting Evidence & Contradiction Analysis",
        ReportSectionType.RESEARCH_GAPS: "Ranked Research Gaps & Validation Protocols",
        ReportSectionType.LIMITATIONS_AND_BOUNDARIES: "Limitations & Boundary Conditions",
        ReportSectionType.AUDITABLE_CITATION_INDEX: "Auditable Evidence Citation Index",
    }
    for st, title in titles.items():
        assertions = []
        if st == ReportSectionType.EXECUTIVE_SUMMARY:
            assertions.append(
                ReportAssertion(
                    assertion_id="ASRT-MS-01",
                    section=st,
                    statement="Kinase domain mutation significantly destabilizes binding.",
                    coordinate_ids=[coord.coordinate_id],
                    status=AssertionStatus.VERIFIED,
                    confidence_score=0.95,
                )
            )
        sections[st] = ReportSection(
            section_type=st,
            title=title,
            content_markdown=f"Body narrative for {title}.",
            assertions=assertions,
        )

    return StructuredResearchReport(
        report_id=report_id,
        query_statement="Investigating kinase domain structural variants.",
        created_at_iso="2026-10-16T08:00:00Z",
        corpus_manifest=manifest,
        sections=sections,
        citation_index={coord.coordinate_id: coord},
    )


class TestManuscriptSectionAndDataContracts:
    """Contract tests for ManuscriptSection and AcademicManuscript data structures."""

    def test_manuscript_section_serialization(self) -> None:
        """Verify serialization and deserialization of ManuscriptSection."""
        sec = ManuscriptSection(
            section_id="sec-intro",
            heading="Introduction",
            body="Introduction narrative.",
            citations=["COORD-1", "COORD-2"],
        )
        d = sec.to_dict()
        assert d["section_id"] == "sec-intro"
        assert d["citations"] == ["COORD-1", "COORD-2"]

        reconstructed = ManuscriptSection.from_dict(d)
        assert reconstructed.heading == "Introduction"
        assert reconstructed.body == "Introduction narrative."
        assert reconstructed.citations == ["COORD-1", "COORD-2"]

    def test_academic_manuscript_validation_failures(self) -> None:
        """AcademicManuscript raises ReportSchemaValidationError on empty required fields."""
        coord = _make_test_coordinate()
        with pytest.raises(ReportSchemaValidationError, match="manuscript_id cannot be empty"):
            AcademicManuscript(
                manuscript_id="",
                report_id="R1",
                title="Title",
                abstract="Abstract",
                authors=["Author"],
                sections={},
                citation_index={coord.coordinate_id: coord},
                created_at_iso="now",
            )

        with pytest.raises(ReportSchemaValidationError, match="title cannot be empty"):
            AcademicManuscript(
                manuscript_id="MS1",
                report_id="R1",
                title="   ",
                abstract="Abstract",
                authors=["Author"],
                sections={},
                citation_index={coord.coordinate_id: coord},
                created_at_iso="now",
            )

        with pytest.raises(ReportSchemaValidationError, match="abstract cannot be empty"):
            AcademicManuscript(
                manuscript_id="MS1",
                report_id="R1",
                title="Title",
                abstract="",
                authors=["Author"],
                sections={},
                citation_index={coord.coordinate_id: coord},
                created_at_iso="now",
            )


class TestManuscriptComposerOptInAndStructure:
    """Contract tests for ManuscriptComposer enforcing opt-in and IMRAD mapping."""

    def test_composer_rejects_unprompted_generation(self) -> None:
        """Default call with explicit_command=False raises ModuleContractViolationError."""
        report = _make_complete_report()
        composer = ManuscriptComposer()

        with pytest.raises(
            ModuleContractViolationError, match="requires explicit user opt-in"
        ):
            composer.compose_from_report(report, explicit_command=False)

    def test_composer_rejects_incomplete_report(self) -> None:
        """Attempting to compose from report missing canonical sections raises validation error."""
        report = _make_complete_report()
        del report.sections[ReportSectionType.RESEARCH_GAPS]

        composer = ManuscriptComposer()
        with pytest.raises(
            ReportSchemaValidationError, match="missing mandatory canonical sections"
        ):
            composer.compose_from_report(report, explicit_command=True)

    def test_compose_manuscript_success_and_imrad_mapping(self) -> None:
        """Compose academic manuscript with explicit opt-in and verify IMRAD sections."""
        report = _make_complete_report("REP-EXP-99")
        composer = ManuscriptComposer()

        manuscript = composer.compose_from_report(
            report,
            explicit_command=True,
            authors=["Dr. Alice Researcher", "Dr. Bob Scientist"],
            target_venue="Journal of Molecular Biology",
            custom_title="Structural Instability in Kinase Mutants",
        )

        assert isinstance(manuscript, AcademicManuscript)
        assert manuscript.manuscript_id == "MS-REP-EXP-99"
        assert manuscript.title == "Structural Instability in Kinase Mutants"
        assert manuscript.target_venue == "Journal of Molecular Biology"
        assert manuscript.authors == ["Dr. Alice Researcher", "Dr. Bob Scientist"]
        assert len(manuscript.abstract) > 0

        # Verify five standard IMRAD body sections exist
        expected_sections = [
            "introduction",
            "related_work",
            "contradictions",
            "research_gaps",
            "discussion",
        ]
        for sec_key in expected_sections:
            assert sec_key in manuscript.sections
            sec = manuscript.sections[sec_key]
            assert len(sec.body) > 0
            assert len(sec.heading) > 0

        # Verify citations preservation
        intro_sec = manuscript.sections["introduction"]
        assert "COORD-TEST-01" in intro_sec.citations

        # Check serialization
        d = manuscript.to_dict()
        assert d["manuscript_id"] == "MS-REP-EXP-99"
        assert "introduction" in d["sections"]

    def test_render_markdown_and_latex(self) -> None:
        """Verify complete Markdown and LaTeX rendering outputs."""
        report = _make_complete_report("REP-RENDER-01")
        composer = ManuscriptComposer()

        manuscript = composer.compose_from_report(
            report,
            explicit_command=True,
            authors=["Alice & Bob"],
            target_venue="Conference on Scientific AI",
            custom_title="Study_on_Kinases & Receptors",
        )

        # Markdown render
        md = manuscript.render_markdown()
        assert "# Study_on_Kinases & Receptors" in md
        assert "Alice & Bob" in md
        assert "Conference on Scientific AI" in md
        assert "## Abstract" in md
        assert "## Introduction & Problem Formulation" in md
        assert "## References & Evidence Coordinate Index" in md
        assert "COORD-TEST-01" in md

        # LaTeX render
        latex = manuscript.render_latex()
        assert "\\documentclass[11pt,a4paper]{article}" in latex
        assert "\\title{Study\\_on\\_Kinases \\& Receptors}" in latex
        assert "Alice \\& Bob" in latex
        assert "\\begin{abstract}" in latex
        assert "\\section{Introduction \\& Problem Formulation}" in latex
        assert "\\section*{References \\& Evidence Provenance Index}" in latex
        assert "\\texttt{COORD-TEST-01}" in latex
        assert "\\end{document}" in latex
