"""Integration tests for report assertion-to-evidence coverage gate.

Tests compliance with DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-004, and Issue #106:
- Report generation across valid, conflicting, insufficient, and absent evidence conditions
- Strict rejection of unanchored factual assertions via UnanchoredAssertionError
- Permissive annotation with explicit caveats and coverage tracking
- End-to-end corpus boundary verification ensuring all coordinates map to ingested documents
- Structured markdown output validation
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from laris.core.errors import (
    ReportSchemaValidationError,
    UnanchoredAssertionError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer11_reporting.report_generator import (
    StructuredReportGenerator,
)
from laris.layers.layer11_reporting.report_schema import (
    AssertionStatus,
    CorpusManifestEntry,
    EvidenceGate,
    ReportAssertion,
    ReportSectionType,
)


def _build_synthetic_corpus_and_coordinates() -> tuple[
    List[CorpusManifestEntry], Dict[str, EvidenceCoordinate]
]:
    """Build synthetic corpus manifest and physical evidence coordinates."""
    doc_a = CorpusManifestEntry(
        document_id="DOC-ARXIV-2401.001",
        title="Kinetic Analysis of Kinase Phosphorylation",
        sha256_hash="1" * 64,
        publication_year=2024,
        venue="Cell Systems",
        peer_reviewed=True,
        ocr_quality_score=0.98,
    )
    doc_b = CorpusManifestEntry(
        document_id="DOC-ARXIV-2402.002",
        title="Thermal Stability and Kinase Inhibition Discrepancies",
        sha256_hash="2" * 64,
        publication_year=2024,
        venue="Biophysical Journal",
        peer_reviewed=True,
        ocr_quality_score=0.96,
    )

    coord_1 = EvidenceCoordinate(
        coordinate_id="COORD-DOC-A#p2s3",
        document_id=doc_a.document_id,
        document_sha256=doc_a.sha256_hash,
        page_number=2,
        section_identifier="Results",
        paragraph_index=1,
        sentence_index=3,
        char_start=120,
        char_end=210,
        verbatim_snippet="Kinase phosphorylation rate increased 2.4-fold at 37 degrees Celsius.",
        extraction_confidence=0.94,
    )
    coord_2 = EvidenceCoordinate(
        coordinate_id="COORD-DOC-B#p4s1",
        document_id=doc_b.document_id,
        document_sha256=doc_b.sha256_hash,
        page_number=4,
        section_identifier="Discussion",
        paragraph_index=0,
        sentence_index=1,
        char_start=50,
        char_end=155,
        verbatim_snippet="Thermal denaturation reduced kinase activity above 35 degrees Celsius.",
        extraction_confidence=0.91,
    )

    return [doc_a, doc_b], {
        coord_1.coordinate_id: coord_1,
        coord_2.coordinate_id: coord_2,
    }


def _canonical_sections_content() -> Dict[ReportSectionType, str]:
    """Return synthetic markdown content for all seven canonical report sections."""
    return {
        ReportSectionType.EXECUTIVE_SUMMARY: (
            "This report analyzes temperature-dependent kinase phosphorylation dynamics."
        ),
        ReportSectionType.CORPUS_PROVENANCE_MANIFEST: (
            "Two peer-reviewed studies (DOC-A and DOC-B) analyzed under Boundary K controls."
        ),
        ReportSectionType.COMPARATIVE_SYNTHESIS: (
            "Methodological comparison reveals divergent kinetic responses based on temperature."
        ),
        ReportSectionType.CONTRADICTION_ANALYSIS: (
            "Direct empirical contradiction observed between DOC-A and DOC-B above 35C."
        ),
        ReportSectionType.RESEARCH_GAPS: (
            "Gap: in vitro assay temperatures do not account for macromolecular crowding."
        ),
        ReportSectionType.LIMITATIONS_AND_BOUNDARIES: (
            "Findings limited to mammalian kinases; bacterial homologs remain uncharacterized."
        ),
        ReportSectionType.AUDITABLE_CITATION_INDEX: (
            "Complete index of cited physical evidence coordinates."
        ),
    }


class TestReportEvidenceCoverageGateWorkloads:
    """Integration tests evaluating evidence gating across realistic research scenarios."""

    def test_report_generation_with_valid_anchored_evidence(self) -> None:
        """Verify successful generation when all assertions are anchored to verified coordinates."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        sections_content = _canonical_sections_content()

        assertions = [
            ReportAssertion(
                assertion_id="ASRT-VALID-1",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Kinase activity increases with temperature up to 37C.",
                coordinate_ids=["COORD-DOC-A#p2s3"],
            ),
            ReportAssertion(
                assertion_id="ASRT-VALID-2",
                section=ReportSectionType.COMPARATIVE_SYNTHESIS,
                statement="Thermal degradation impacts enzymatic turnover.",
                coordinate_ids=["COORD-DOC-B#p4s1"],
            ),
        ]

        generator = StructuredReportGenerator()
        report, summary = generator.generate_report(
            report_id="REP-INT-VALID-001",
            query_statement="Investigate thermal effects on kinase phosphorylation.",
            corpus_manifest=manifest,
            sections_content=sections_content,
            assertions=assertions,
            citation_index=citations,
            strict_gate=True,
        )

        assert report.report_id == "REP-INT-VALID-001"
        assert report.verify_all_sections_present()
        assert summary.is_valid
        assert summary.total_assertions == 2
        assert summary.verified_assertions == 2
        assert summary.unanchored_assertions == 0
        assert summary.coverage_ratio == 1.0

        # Verify markdown output contains badges and citations
        md = report.render_markdown()
        assert "**[VERIFIED]**" in md
        assert "`COORD-DOC-A#p2s3`" in md
        assert "`COORD-DOC-B#p4s1`" in md

    def test_report_generation_with_conflicting_evidence(self) -> None:
        """Verify Section 4 contradiction analysis with opposing evidence coordinates."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        sections_content = _canonical_sections_content()

        # Two contradictory assertions citing opposing physical sources
        assertions = [
            ReportAssertion(
                assertion_id="ASRT-CONTRA-A",
                section=ReportSectionType.CONTRADICTION_ANALYSIS,
                statement="DOC-A reports 2.4-fold activity increase at 37C.",
                coordinate_ids=["COORD-DOC-A#p2s3"],
            ),
            ReportAssertion(
                assertion_id="ASRT-CONTRA-B",
                section=ReportSectionType.CONTRADICTION_ANALYSIS,
                statement="DOC-B reports activity reduction above 35C due to denaturation.",
                coordinate_ids=["COORD-DOC-B#p4s1"],
            ),
        ]

        generator = StructuredReportGenerator()
        report, summary = generator.generate_report(
            report_id="REP-INT-CONTRA-002",
            query_statement="Resolve contradiction in thermal kinase kinetics.",
            corpus_manifest=manifest,
            sections_content=sections_content,
            assertions=assertions,
            citation_index=citations,
            strict_gate=True,
        )

        assert summary.is_valid
        assert summary.verified_assertions == 2
        contra_assertions = report.sections[ReportSectionType.CONTRADICTION_ANALYSIS].assertions
        assert len(contra_assertions) == 2
        assert all(a.status == AssertionStatus.VERIFIED for a in contra_assertions)

    def test_report_generation_with_insufficient_evidence_annotated(self) -> None:
        """Verify permissive mode annotates claims with missing coordinates and tracks deficit."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        sections_content = _canonical_sections_content()

        assertions = [
            ReportAssertion(
                assertion_id="ASRT-WELL-GROUNDED",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Verified kinase finding.",
                coordinate_ids=["COORD-DOC-A#p2s3"],
            ),
            ReportAssertion(
                assertion_id="ASRT-MISSING-COORD",
                section=ReportSectionType.LIMITATIONS_AND_BOUNDARIES,
                statement="Speculative assertion without physical evidence coordinate.",
                coordinate_ids=["COORD-MISSING-PHY-999"],
            ),
        ]

        # In permissive mode, unanchored claims are flagged with caveats rather than aborting
        generator = StructuredReportGenerator(default_strict_gate=False)
        report, summary = generator.generate_report(
            report_id="REP-INT-INSUFFICIENT-003",
            query_statement="Analyze kinase limitations under ungrounded assumptions.",
            corpus_manifest=manifest,
            sections_content=sections_content,
            assertions=assertions,
            citation_index=citations,
            strict_gate=False,
        )

        assert not summary.is_valid
        assert summary.total_assertions == 2
        assert summary.verified_assertions == 1
        assert summary.unanchored_assertions == 1
        assert summary.coverage_ratio == 0.50
        assert summary.missing_evidence_ids == ["ASRT-MISSING-COORD"]

        # Check that the flagged assertion received an explicit caveat
        flagged = report.sections[ReportSectionType.LIMITATIONS_AND_BOUNDARIES].assertions[0]
        assert flagged.status == AssertionStatus.FLAGGED_MISSING_EVIDENCE
        assert flagged.caveat is not None
        assert "COORD-MISSING-PHY-999" in flagged.caveat

    def test_report_generation_with_absent_evidence_strictly_rejected(self) -> None:
        """Verify strict gate raises UnanchoredAssertionError on absent evidence."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        sections_content = _canonical_sections_content()

        assertions = [
            ReportAssertion(
                assertion_id="ASRT-UNGROUNDED",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Completely fabricated scientific claim.",
                coordinate_ids=[],  # Zero coordinates
            )
        ]

        generator = StructuredReportGenerator(default_strict_gate=True)
        with pytest.raises(UnanchoredAssertionError, match="has no evidence coordinates cited"):
            generator.generate_report(
                report_id="REP-INT-REJECT-004",
                query_statement="Fabricated inquiry.",
                corpus_manifest=manifest,
                sections_content=sections_content,
                assertions=assertions,
                citation_index=citations,
                strict_gate=True,
            )

    def test_unanchored_assertion_rejection_boundary(self) -> None:
        """Verify that dropping unanchored assertions produces 100% verified report output."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        sections_content = _canonical_sections_content()

        assertions = [
            ReportAssertion(
                assertion_id="ASRT-KEEP",
                section=ReportSectionType.EXECUTIVE_SUMMARY,
                statement="Solid empirical finding.",
                coordinate_ids=["COORD-DOC-A#p2s3"],
            ),
            ReportAssertion(
                assertion_id="ASRT-DROP",
                section=ReportSectionType.RESEARCH_GAPS,
                statement="Ungrounded speculation to drop.",
                coordinate_ids=[],
            ),
        ]

        generator = StructuredReportGenerator()
        report, _ = generator.generate_report(
            report_id="REP-INT-SANITIZE-005",
            query_statement="Sanitize ungrounded gaps.",
            corpus_manifest=manifest,
            sections_content=sections_content,
            assertions=assertions,
            citation_index=citations,
            strict_gate=False,
        )

        # Sanitize report by dropping unanchored assertions
        gate = EvidenceGate()
        sanitized_report = gate.filter_or_annotate_unanchored_assertions(
            report, drop_unanchored=True
        )

        # After dropping unanchored claims, strict verification must pass with 100% coverage
        summary = gate.verify_report(sanitized_report, strict=True)
        assert summary.is_valid
        assert summary.total_assertions == 1
        assert summary.verified_assertions == 1
        assert summary.unanchored_assertions == 0
        assert summary.coverage_ratio == 1.0

    def test_missing_mandatory_section_content_raises_error(self) -> None:
        """Verify generator rejects incomplete report specifications."""
        manifest, citations = _build_synthetic_corpus_and_coordinates()
        incomplete_content = {
            ReportSectionType.EXECUTIVE_SUMMARY: "Only summary provided.",
        }

        generator = StructuredReportGenerator()
        with pytest.raises(ReportSchemaValidationError, match="missing content for mandatory"):
            generator.generate_report(
                report_id="REP-INT-INCOMPLETE-006",
                query_statement="Incomplete query.",
                corpus_manifest=manifest,
                sections_content=incomplete_content,
                assertions=[],
                citation_index=citations,
            )
