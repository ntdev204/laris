"""Unit and contract tests for structured research report schema and evidence gate.

Tests compliance with DOC-SPEC-REP-001, Boundary K, and Issue #74:
- Mandatory seven canonical sections representation
- Assertion-to-evidence coordinate validation (strict and permissive modes)
- Serialization and deserialization roundtripping
- Edge cases: invalid fields, empty inputs, missing sections, and unanchored claims
"""

from __future__ import annotations

import pytest

from laris.core.errors import (
    ReportSchemaValidationError,
    UnanchoredAssertionError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer11_reporting import (
    AssertionStatus,
    CorpusManifestEntry,
    EvidenceGate,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    ReportVerificationSummary,
    StructuredReportGenerator,
    StructuredResearchReport,
)


def _sample_coordinate(coord_id: str = "COORD-DOC1#p1s1") -> EvidenceCoordinate:
    """Helper creating a valid EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id=coord_id,
        document_id="DOC-2024-001",
        document_sha256="a" * 64,
        page_number=1,
        section_identifier="Abstract",
        paragraph_index=0,
        sentence_index=1,
        char_start=0,
        char_end=45,
        verbatim_snippet="Sample empirical finding in biological context.",
        extraction_confidence=0.95,
    )


def _sample_report_sections() -> dict[ReportSectionType, ReportSection]:
    """Helper generating all seven canonical sections."""
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
        sections[st] = ReportSection(
            section_type=st,
            title=title,
            content_markdown=f"Content for {title}.",
            assertions=[],
        )
    return sections


class TestReportAssertionContracts:
    """Contract tests for ReportAssertion schema and validation."""

    def test_valid_assertion_serialization_roundtrip(self) -> None:
        """Verify serialization and deserialization of ReportAssertion."""
        assertion = ReportAssertion(
            assertion_id="ASRT-001",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Target protein binds with nanomolar affinity.",
            coordinate_ids=["COORD-DOC1#p1s1"],
            status=AssertionStatus.VERIFIED,
            confidence_score=0.95,
            caveat=None,
        )
        data = assertion.to_dict()
        assert data["assertion_id"] == "ASRT-001"
        assert data["section"] == "executive_summary"
        assert data["status"] == "verified"

        restored = ReportAssertion.from_dict(data)
        assert restored.assertion_id == assertion.assertion_id
        assert restored.section == assertion.section
        assert restored.statement == assertion.statement
        assert restored.coordinate_ids == assertion.coordinate_ids
        assert restored.status == assertion.status
        assert restored.confidence_score == assertion.confidence_score
        assert restored.caveat is None

    def test_invalid_assertion_id_raises_error(self) -> None:
        """Verify empty assertion_id raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="assertion_id cannot be empty"):
            ReportAssertion(
                assertion_id="   ",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Valid statement.",
                coordinate_ids=["COORD-1"],
            )

    def test_invalid_statement_raises_error(self) -> None:
        """Verify empty statement raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="statement cannot be empty"):
            ReportAssertion(
                assertion_id="ASRT-002",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="",
                coordinate_ids=["COORD-1"],
            )

    def test_invalid_confidence_score_raises_error(self) -> None:
        """Verify confidence score outside [0, 1] raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="confidence_score must be between"):
            ReportAssertion(
                assertion_id="ASRT-003",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Valid statement.",
                coordinate_ids=["COORD-1"],
                confidence_score=1.5,
            )


class TestCorpusManifestEntryContracts:
    """Contract tests for CorpusManifestEntry schema."""

    def test_valid_manifest_entry_roundtrip(self) -> None:
        """Verify CorpusManifestEntry serialization and deserialization."""
        entry = CorpusManifestEntry(
            document_id="DOC-ARXIV-2401.0001",
            title="Analysis of Protein Synthesis Pathways",
            sha256_hash="e" * 64,
            publication_year=2024,
            venue="Bioinformatics",
            peer_reviewed=True,
            ocr_quality_score=0.99,
        )
        data = entry.to_dict()
        assert data["document_id"] == "DOC-ARXIV-2401.0001"
        assert data["publication_year"] == 2024

        restored = CorpusManifestEntry.from_dict(data)
        assert restored == entry

    def test_invalid_sha256_raises_error(self) -> None:
        """Verify non-64-character hash raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="sha256_hash must be a 64-character"):
            CorpusManifestEntry(
                document_id="DOC-1",
                title="Title",
                sha256_hash="tooshort",
                publication_year=2024,
                venue="Venue",
            )

    def test_invalid_ocr_quality_raises_error(self) -> None:
        """Verify OCR score outside [0, 1] raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="ocr_quality_score must be between"):
            CorpusManifestEntry(
                document_id="DOC-1",
                title="Title",
                sha256_hash="a" * 64,
                publication_year=2024,
                venue="Venue",
                ocr_quality_score=-0.1,
            )

    def test_empty_document_id_raises_error(self) -> None:
        """Verify empty document_id raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="document_id cannot be empty"):
            CorpusManifestEntry(
                document_id="   ",
                title="Title",
                sha256_hash="a" * 64,
                publication_year=2024,
                venue="Venue",
            )


class TestStructuredResearchReportContracts:
    """Contract tests for complete StructuredResearchReport lifecycle and rendering."""

    def test_valid_report_roundtrip_and_rendering(self) -> None:
        """Verify complete report serialization and deterministic markdown generation."""
        coord = _sample_coordinate("COORD-TEST-001")
        sections = _sample_report_sections()

        assertion = ReportAssertion(
            assertion_id="ASRT-SYNTH-1",
            section=ReportSectionType.COMPARATIVE_SYNTHESIS,
            statement="Method A outperforms Method B by 12% across all benchmarks.",
            coordinate_ids=["COORD-TEST-001"],
            status=AssertionStatus.VERIFIED,
            confidence_score=0.92,
        )
        sections[ReportSectionType.COMPARATIVE_SYNTHESIS].assertions.append(assertion)

        report = StructuredResearchReport(
            report_id="REP-2026-001",
            query_statement="What are the latest findings on protein phosphorylation kinetics?",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[
                CorpusManifestEntry(
                    document_id="DOC-2024-001",
                    title="Protein Synthesis Dynamics",
                    sha256_hash="b" * 64,
                    publication_year=2024,
                    venue="Nature Protocols",
                )
            ],
            sections=sections,
            citation_index={"COORD-TEST-001": coord},
            metadata={"run_mode": "offline", "pipeline_version": "1.0.0"},
        )

        assert report.verify_all_sections_present()
        assert len(report.all_assertions()) == 1

        # Check markdown rendering
        md = report.render_markdown()
        assert "# LARIS Structured Research Report: REP-2026-001" in md
        assert "## Executive Summary & Inquiry Scope" in md
        assert "## Comparative Synthesis & Methodological Analysis" in md
        assert "Method A outperforms Method B by 12%" in md
        assert "**[VERIFIED]**" in md

        # Roundtrip via dict
        data = report.to_dict()
        restored = StructuredResearchReport.from_dict(data)
        assert restored.report_id == report.report_id
        assert restored.verify_all_sections_present()
        assert len(restored.corpus_manifest) == 1
        assert "COORD-TEST-001" in restored.citation_index
        assert restored.citation_index["COORD-TEST-001"].verbatim_snippet == coord.verbatim_snippet

    def test_missing_report_id_raises_error(self) -> None:
        """Verify empty report_id raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="report_id cannot be empty"):
            StructuredResearchReport(
                report_id="  ",
                query_statement="Valid query",
                created_at_iso="2026-10-16T08:00:00Z",
                corpus_manifest=[],
                sections={},
                citation_index={},
            )

    def test_empty_query_statement_raises_error(self) -> None:
        """Verify empty query_statement raises ReportSchemaValidationError."""
        with pytest.raises(ReportSchemaValidationError, match="query_statement cannot be empty"):
            StructuredResearchReport(
                report_id="REP-VALID",
                query_statement="   ",
                created_at_iso="2026-10-16T08:00:00Z",
                corpus_manifest=[],
                sections={},
                citation_index={},
            )

    def test_render_markdown_with_missing_optional_section(self) -> None:
        """Verify markdown rendering succeeds when some sections are absent."""
        report = StructuredResearchReport(
            report_id="REP-SPARSE",
            query_statement="Test inquiry",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections={
                ReportSectionType.EXECUTIVE_SUMMARY: ReportSection(
                    section_type=ReportSectionType.EXECUTIVE_SUMMARY,
                    title="Executive Summary",
                    content_markdown="Summary text.",
                )
            },
            citation_index={},
        )
        md = report.render_markdown()
        assert "## Executive Summary" in md
        assert "## Research Gaps" not in md



class TestEvidenceGateVerification:
    """Contract tests for EvidenceGate verification, rejection, and annotation."""

    def test_validate_assertion_strict_missing_coordinate(self) -> None:
        """Verify strict mode raises UnanchoredAssertionError for missing coordinates."""
        gate = EvidenceGate()
        assertion = ReportAssertion(
            assertion_id="ASRT-FAIL-1",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Unverified assertion.",
            coordinate_ids=[],
        )
        with pytest.raises(UnanchoredAssertionError, match="has no evidence coordinates cited"):
            gate.validate_assertion(assertion, {}, strict=True)

    def test_validate_assertion_strict_unindexed_coordinate(self) -> None:
        """Verify strict mode raises UnanchoredAssertionError when coordinate ID not in index."""
        gate = EvidenceGate()
        assertion = ReportAssertion(
            assertion_id="ASRT-FAIL-2",
            section=ReportSectionType.RESEARCH_GAPS,
            statement="Claim citing non-existent coordinate.",
            coordinate_ids=["COORD-NONEXISTENT"],
        )
        with pytest.raises(UnanchoredAssertionError, match="cites missing evidence coordinates"):
            gate.validate_assertion(assertion, {}, strict=True)

    def test_validate_assertion_permissive_annotation(self) -> None:
        """Verify permissive mode annotates unanchored assertion with caveat and status."""
        gate = EvidenceGate()
        assertion = ReportAssertion(
            assertion_id="ASRT-PERM-1",
            section=ReportSectionType.LIMITATIONS_AND_BOUNDARIES,
            statement="Claim without source.",
            coordinate_ids=[],
        )
        updated = gate.validate_assertion(assertion, {}, strict=False)
        assert updated.status == AssertionStatus.FLAGGED_MISSING_EVIDENCE
        assert updated.caveat is not None
        assert "Missing empirical evidence coordinates" in updated.caveat

    def test_verify_report_missing_section_raises_error(self) -> None:
        """Verify verify_report raises error when not all 7 canonical sections are present."""
        gate = EvidenceGate()
        partial_sections = {
            ReportSectionType.EXECUTIVE_SUMMARY: ReportSection(
                section_type=ReportSectionType.EXECUTIVE_SUMMARY,
                title="Executive Summary",
                content_markdown="Summary text.",
            )
        }
        report = StructuredResearchReport(
            report_id="REP-PARTIAL",
            query_statement="Query",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections=partial_sections,
            citation_index={},
        )
        with pytest.raises(ReportSchemaValidationError, match="missing mandatory sections"):
            gate.verify_report(report)

    def test_verify_report_permissive_coverage_summary(self) -> None:
        """Verify non-strict verify_report computes accurate verification summary."""
        gate = EvidenceGate(minimum_coverage_ratio=0.80)
        coord = _sample_coordinate("COORD-1")
        sections = _sample_report_sections()

        # Add 1 verified and 1 unanchored assertion
        sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions = [
            ReportAssertion(
                assertion_id="A-VERIFIED",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Verified claim.",
                coordinate_ids=["COORD-1"],
            ),
            ReportAssertion(
                assertion_id="A-UNANCHORED",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Unanchored claim.",
                coordinate_ids=["COORD-MISSING"],
            ),
        ]

        report = StructuredResearchReport(
            report_id="REP-MIXED",
            query_statement="Inquiry",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections=sections,
            citation_index={"COORD-1": coord},
        )

        summary: ReportVerificationSummary = gate.verify_report(report, strict=False)
        assert not summary.is_valid
        assert summary.total_assertions == 2
        assert summary.verified_assertions == 1
        assert summary.unanchored_assertions == 1
        assert summary.coverage_ratio == 0.50
        assert summary.missing_evidence_ids == ["A-UNANCHORED"]
        assert isinstance(summary.to_dict(), dict)

    def test_filter_or_annotate_unanchored_assertions(self) -> None:
        """Verify dropping unanchored assertions when drop_unanchored=True."""
        gate = EvidenceGate()
        coord = _sample_coordinate("COORD-1")
        sections = _sample_report_sections()

        sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions = [
            ReportAssertion(
                assertion_id="A1",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Anchored statement.",
                coordinate_ids=["COORD-1"],
            ),
            ReportAssertion(
                assertion_id="A2",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Unanchored statement.",
                coordinate_ids=[],
            ),
        ]

        report = StructuredResearchReport(
            report_id="REP-FILTER",
            query_statement="Inquiry",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections=sections,
            citation_index={"COORD-1": coord},
        )

        # Drop unanchored
        gate.filter_or_annotate_unanchored_assertions(report, drop_unanchored=True)
        remaining = report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions
        assert len(remaining) == 1
        assert remaining[0].assertion_id == "A1"
        assert remaining[0].status == AssertionStatus.VERIFIED

    def test_verify_report_strict_raises_unanchored_error(self) -> None:
        """Verify strict verify_report raises UnanchoredAssertionError on unanchored claim."""
        gate = EvidenceGate()
        sections = _sample_report_sections()
        sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions = [
            ReportAssertion(
                assertion_id="A-STRICT-FAIL",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Unanchored claim.",
                coordinate_ids=[],
            )
        ]
        report = StructuredResearchReport(
            report_id="REP-STRICT-FAIL",
            query_statement="Inquiry",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections=sections,
            citation_index={},
        )
        with pytest.raises(UnanchoredAssertionError, match="has no evidence coordinates cited"):
            gate.verify_report(report, strict=True)

    def test_filter_or_annotate_keep_unanchored(self) -> None:
        """Verify retaining annotated unanchored assertions when drop_unanchored=False."""
        gate = EvidenceGate()
        sections = _sample_report_sections()
        sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions = [
            ReportAssertion(
                assertion_id="A-KEEP",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Unanchored claim to keep.",
                coordinate_ids=[],
            )
        ]
        report = StructuredResearchReport(
            report_id="REP-KEEP",
            query_statement="Inquiry",
            created_at_iso="2026-10-16T08:00:00Z",
            corpus_manifest=[],
            sections=sections,
            citation_index={},
        )
        gate.filter_or_annotate_unanchored_assertions(report, drop_unanchored=False)
        remaining = report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions
        assert len(remaining) == 1
        assert remaining[0].status == AssertionStatus.FLAGGED_MISSING_EVIDENCE


class TestStructuredReportGeneratorUnit:
    """Unit tests for StructuredReportGenerator edge cases and properties."""

    def test_generator_properties_and_validation(self) -> None:
        """Verify generator properties and input validation checks."""
        generator = StructuredReportGenerator()
        assert isinstance(generator.evidence_gate, EvidenceGate)

        # Empty report_id
        with pytest.raises(ReportSchemaValidationError, match="report_id cannot be empty"):
            generator.generate_report(
                report_id="   ",
                query_statement="Valid",
                corpus_manifest=[],
                sections_content={},
                assertions=[],
                citation_index={},
            )

        # Empty query_statement
        with pytest.raises(ReportSchemaValidationError, match="query_statement cannot be empty"):
            generator.generate_report(
                report_id="REP-VALID",
                query_statement="",
                corpus_manifest=[],
                sections_content={},
                assertions=[],
                citation_index={},
            )

    def test_generator_unknown_section_fallback(self) -> None:
        """Verify assertions with unmapped sections fall back to executive summary."""
        generator = StructuredReportGenerator()
        sections_content = {st: f"Content for {st.value}" for st in ReportSectionType}
        coord = _sample_coordinate("COORD-1")
        assertion = ReportAssertion(
            assertion_id="ASRT-FALLBACK",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Valid statement.",
            coordinate_ids=["COORD-1"],
        )
        object.__setattr__(assertion, "section", "UNKNOWN_SECTION")

        report, summary = generator.generate_report(
            report_id="REP-FALLBACK",
            query_statement="Valid query",
            corpus_manifest=[],
            sections_content=sections_content,
            assertions=[assertion],
            citation_index={"COORD-1": coord},
            strict_gate=True,
        )
        assert summary.is_valid
        exec_assertions = report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions
        assert len(exec_assertions) == 1
        assert exec_assertions[0].assertion_id == "ASRT-FALLBACK"


