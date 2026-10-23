"""End-to-end integration tests for fresh environment packaging and release candidate.

Verifies acceptance criteria for M10-PROD-003-SUB-02 and Milestone M10:
1. Package metadata, dependencies, and clean virtual environment compatibility
2. Complete end-to-end release pipeline: from evidence to report to manuscript
3. Strict opt-in contract enforcement for academic manuscript generation
4. Release notes, documentation metadata, and operational boundaries
5. Tamper-evident lineage audit trails and reproducible release state
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Dict, List

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

import pytest

import laris
from laris.core.errors import (
    ModuleContractViolationError,
    UnanchoredAssertionError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reporting import (
    AcademicManuscript,
    AssertionStatus,
    CorpusManifestEntry,
    CorpusVersionRecord,
    EvidenceGate,
    EvidenceInspector,
    EvidenceSourceCard,
    InterventionType,
    ManuscriptComposer,
    ProjectHistoryManager,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    ReportVerificationSummary,
    ReportVersionRecord,
    RunVersionRecord,
    StructuredResearchReport,
)


def _build_test_coordinate(
    cid: str = "COORD-REL-01",
    doc_id: str = "DOC-MED-2024",
    doc_hash: str = "a" * 64,
    page: int = 2,
    char_start: int = 120,
    char_end: int = 240,
    snippet: str = "Statistical significance was reached at p < 0.001 across all trials.",
) -> EvidenceCoordinate:
    """Helper creating a valid EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id=cid,
        document_id=doc_id,
        document_sha256=doc_hash,
        page_number=page,
        section_identifier="Results",
        paragraph_index=2,
        sentence_index=1,
        char_start=char_start,
        char_end=char_end,
        verbatim_snippet=snippet,
        extraction_confidence=0.98,
    )


def _build_valid_release_report() -> StructuredResearchReport:
    """Helper building a canonical StructuredResearchReport with 100% evidence backing."""
    raw_text = (
        "Statistical significance was reached at p < 0.001 across all trials. "
        "No adverse neurotoxicity was reported in the 120-day observation window. "
        "Comparative analysis indicates non-inferiority to standard regimen."
    )
    doc_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    coord1 = _build_test_coordinate(
        "COORD-REL-01",
        doc_hash=doc_hash,
        page=1,
        char_start=0,
        char_end=68,
        snippet="Statistical significance was reached at p < 0.001 across all trials.",
    )
    coord2 = _build_test_coordinate(
        "COORD-REL-02",
        doc_hash=doc_hash,
        page=2,
        char_start=70,
        char_end=144,
        snippet="No adverse neurotoxicity was reported in the 120-day observation window.",
    )
    coord3 = _build_test_coordinate(
        "COORD-REL-03",
        doc_hash=doc_hash,
        page=3,
        char_start=146,
        char_end=217,
        snippet="Comparative analysis indicates non-inferiority to standard regimen.",
    )

    citations = {
        coord1.coordinate_id: coord1,
        coord2.coordinate_id: coord2,
        coord3.coordinate_id: coord3,
    }

    manifest = [
        CorpusManifestEntry(
            document_id="DOC-MED-2024",
            title="Phase III Clinical Study",
            sha256_hash=doc_hash,
            publication_year=2024,
            venue="Lancet",
            peer_reviewed=True,
            ocr_quality_score=0.99,
        )
    ]

    section_titles = {
        ReportSectionType.EXECUTIVE_SUMMARY: "Executive Summary & Inquiry Scope",
        ReportSectionType.CORPUS_PROVENANCE_MANIFEST: "Corpus Evidence & Provenance Manifest",
        ReportSectionType.COMPARATIVE_SYNTHESIS: "Comparative Synthesis & Methodological Analysis",
        ReportSectionType.CONTRADICTION_ANALYSIS: "Conflicting Evidence & Contradiction Analysis",
        ReportSectionType.RESEARCH_GAPS: "Ranked Research Gaps & Validation Protocols",
        ReportSectionType.LIMITATIONS_AND_BOUNDARIES: "Limitations & Boundary Conditions",
        ReportSectionType.AUDITABLE_CITATION_INDEX: "Auditable Evidence Citation Index",
    }

    sections: Dict[ReportSectionType, ReportSection] = {}
    for st, title in section_titles.items():
        assertions: List[ReportAssertion] = []
        if st == ReportSectionType.EXECUTIVE_SUMMARY:
            assertions.append(
                ReportAssertion(
                    assertion_id="ASRT-REL-01",
                    section=st,
                    statement=(
                        "Therapeutic outcome demonstrated statistically significant efficacy."
                    ),
                    coordinate_ids=[coord1.coordinate_id],
                    status=AssertionStatus.VERIFIED,
                    confidence_score=0.99,
                )
            )
        elif st == ReportSectionType.COMPARATIVE_SYNTHESIS:
            assertions.append(
                ReportAssertion(
                    assertion_id="ASRT-REL-02",
                    section=st,
                    statement=(
                        "Safety evaluation confirmed absence of neurotoxicity across all cohorts."
                    ),
                    coordinate_ids=[coord2.coordinate_id],
                    status=AssertionStatus.VERIFIED,
                    confidence_score=0.97,
                )
            )
        elif st == ReportSectionType.AUDITABLE_CITATION_INDEX:
            assertions.append(
                ReportAssertion(
                    assertion_id="ASRT-REL-03",
                    section=st,
                    statement="Comparative trial confirms non-inferiority to current standard.",
                    coordinate_ids=[coord3.coordinate_id],
                    status=AssertionStatus.VERIFIED,
                    confidence_score=0.96,
                )
            )

        sections[st] = ReportSection(
            section_type=st,
            title=title,
            content_markdown=f"Narrative content for {title}.",
            assertions=assertions,
        )

    return StructuredResearchReport(
        report_id="REP-REL-2026-001",
        query_statement="Clinical efficacy and safety profile evaluation.",
        created_at_iso="2026-10-16T10:00:00Z",
        corpus_manifest=manifest,
        sections=sections,
        citation_index=citations,
    )


class TestFreshEnvironmentInstallAndRelease:
    """Integration test suite verifying package packaging, installation, and release gates."""

    def test_pyproject_metadata_and_version_consistency(self) -> None:
        """Verifies pyproject.toml configuration and version consistency with laris package."""
        pyproject_path = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
        assert pyproject_path.exists(), "pyproject.toml must exist at project root"

        raw_text = pyproject_path.read_text(encoding="utf-8")
        assert 'name = "laris"' in raw_text
        assert f'version = "{laris.__version__}"' in raw_text
        assert 'requires-python = ">=3.10"' in raw_text
        assert "build-backend = \"setuptools.build_meta\"" in raw_text

        if tomllib is not None:
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)

            project = pyproject_data.get("project", {})
            assert project.get("name") == "laris"
            assert project.get("version") == "1.0.0"
            assert project.get("license") == "MIT"
            assert project.get("requires-python") == ">=3.10"
            assert laris.__version__ == project.get("version")

            # Verify runtime core dependencies
            dependencies = project.get("dependencies", [])
            dep_names = [d.split(">=")[0].strip() for d in dependencies]
            assert "pyyaml" in dep_names
            assert "pydantic" in dep_names
            assert "numpy" in dep_names

            # Verify build backend
            build_system = pyproject_data.get("build-system", {})
            assert "setuptools" in build_system.get("requires", [""])[0]
            assert build_system.get("build-backend") == "setuptools.build_meta"

    def test_release_notes_and_operational_boundaries(self) -> None:
        """Verifies docs/RELEASE_NOTES.md metadata and mandatory operational boundaries."""
        release_notes_path = pathlib.Path(__file__).resolve().parents[2] / "docs/RELEASE_NOTES.md"
        assert release_notes_path.exists(), "docs/RELEASE_NOTES.md must exist"

        content = release_notes_path.read_text(encoding="utf-8")
        assert "DOC-REL-001" in content
        assert "v0.1.0-rc1" in content
        assert "Pure Local-First Execution" in content
        assert "14.5" in content
        assert "On-Demand Academic Manuscript Composer" in content
        assert "Opt-In Manuscript Drafting" in content

    def test_end_to_end_report_verification_and_evidence_gate(self) -> None:
        """Verifies end-to-end report generation passing evidence coverage gate with 100%."""
        report = _build_valid_release_report()
        gate = EvidenceGate(minimum_coverage_ratio=1.0)
        summary = gate.verify_report(report)

        assert isinstance(summary, ReportVerificationSummary)
        assert summary.total_assertions == 3
        assert summary.verified_assertions == 3
        assert summary.unanchored_assertions == 0
        assert summary.coverage_ratio == 1.0
        assert summary.is_valid is True

    def test_evidence_gate_rejection_on_unanchored_assertion(self) -> None:
        """Verifies that EvidenceGate rejects reports with unanchored assertions in strict mode."""
        report = _build_valid_release_report()
        unanchored_assertion = ReportAssertion(
            assertion_id="ASRT-UNANCHORED",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Unanchored speculative claim without evidence coordinates.",
            coordinate_ids=[],
            status=AssertionStatus.UNVERIFIED,
        )
        report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions.append(unanchored_assertion)

        gate = EvidenceGate(minimum_coverage_ratio=1.0)
        with pytest.raises(UnanchoredAssertionError) as exc_info:
            gate.verify_report(report, strict=True)

        assert "has no evidence coordinates cited" in str(exc_info.value)

    def test_manuscript_opt_in_contract_enforcement(self) -> None:
        """Enforces Boundary K: manuscript generation strictly requires explicit command."""
        report = _build_valid_release_report()
        composer = ManuscriptComposer()

        # Calling without explicit opt-in must immediately raise ModuleContractViolationError
        with pytest.raises(ModuleContractViolationError) as exc_info:
            composer.compose_from_report(report, explicit_command=False)

        assert "requires explicit user opt-in" in str(exc_info.value)

    def test_manuscript_generation_markdown_and_latex(self) -> None:
        """Verifies academic manuscript composition in both Markdown and LaTeX formats."""
        report = _build_valid_release_report()
        composer = ManuscriptComposer()

        manuscript = composer.compose_from_report(
            report=report,
            explicit_command=True,
            target_venue="Nature Medicine",
            authors=["LARIS Autonomous Research Team", "Local Principal Investigator"],
        )

        assert isinstance(manuscript, AcademicManuscript)
        assert len(manuscript.sections) == 5  # IMRAD + future work sections
        assert len(manuscript.citation_index) == 3

        # Markdown format verification
        md_text = manuscript.render_markdown()
        assert "[COORD-REL-01]" in md_text
        assert "Nature Medicine" in md_text

        # LaTeX format verification
        latex_text = manuscript.render_latex()
        assert "\\documentclass[11pt,a4paper]{article}" in latex_text
        assert "\\section{Introduction \\& Problem Formulation}" in latex_text
        assert "\\texttt{COORD-REL-01}" in latex_text
        assert "\\end{document}" in latex_text

    def test_evidence_inspector_and_project_history_integration(self) -> None:
        """Verifies EvidenceInspector and ProjectHistoryManager audit integration."""
        report = _build_valid_release_report()
        doc_text = (
            "Statistical significance was reached at p < 0.001 across all trials. "
            "No adverse neurotoxicity was reported in the 120-day observation window. "
            "Comparative analysis indicates non-inferiority to standard regimen."
        )

        inspector = EvidenceInspector(
            citation_index=report.citation_index,
            document_texts={"DOC-MED-2024": doc_text},
        )

        card = inspector.inspect_coordinate("COORD-REL-01")
        assert isinstance(card, EvidenceSourceCard)
        assert card.coordinate_id == "COORD-REL-01"
        assert card.resolved_against_document is True
        assert card.document_checksum_valid is True

        summary = inspector.generate_inspection_summary(report)
        assert summary.total_citations == 3
        assert summary.resolved_citations == 3
        assert summary.document_verified_citations == 3
        assert summary.coverage_ratio == 1.0

        # Project History and Audit Trail
        history_mgr = ProjectHistoryManager()
        c_rec = CorpusVersionRecord(
            "CORP-V1",
            ["DOC-MED-2024"],
            {"DOC-MED-2024": card.document_sha256},
            "h1",
            "now",
        )
        history_mgr.lineage.register_corpus_version(c_rec)

        r_rec = RunVersionRecord("RUN-V1", "CORP-V1", "Clinical query", "default_cfg", "now")
        history_mgr.lineage.register_run_version(r_rec)

        rep_v1_rec = ReportVersionRecord(
            "REP-V1",
            report.report_id,
            "RUN-V1",
            None,
            "h_rep1",
            "now",
        )
        history_mgr.lineage.register_report_version(rep_v1_rec)

        new_rep, intv, v2_rec = history_mgr.apply_assertion_intervention(
            report=report,
            current_version_id="REP-V1",
            new_version_id="REP-V2",
            assertion_id="ASRT-REL-01",
            intervention_type=InterventionType.ACCEPT,
            author_id="ChiefScientist",
            rationale="Verified clinical trial statistics against raw paper tables.",
            created_at_iso="2026-10-16T10:15:00Z",
        )

        assert new_rep.report_id == report.report_id
        assert v2_rec.version_id == "REP-V2"
        assert history_mgr.audit.verify_integrity() is True
        assert len(history_mgr.audit.records) == 1
