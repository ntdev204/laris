"""Unit and contract tests for local-first evidence inspection and version lineage.

Tests compliance with DOC-SPEC-REP-001, Boundary K, ADR-001, ADR-004, and Issue #75:
- Evidence source card generation, offset resolution, and context window extraction
- Local coordinate resolution and bitwise document SHA-256 auditing
- Corpus, run, and report version registration in the lineage DAG
- History tracing, ancestor navigation, and version diffing
- Append-only cryptographic SHA-256 audit log for user interventions (accept, modify, reject)
- Tampering detection and audit integrity verification
"""

from __future__ import annotations

import hashlib

import pytest

from laris.core.errors import (
    AuditIntegrityError,
    CoordinateResolutionError,
    InvalidInterventionError,
    LineageCycleError,
    LineageNotFoundError,
    ReportSchemaValidationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reporting import (
    AssertionStatus,
    CorpusManifestEntry,
    CorpusVersionRecord,
    EvidenceInspector,
    EvidenceSourceCard,
    InspectionSummary,
    InterventionAuditTrail,
    InterventionType,
    LineageRegistry,
    ProjectHistoryManager,
    ReportAssertion,
    ReportSection,
    ReportSectionType,
    ReportVersionRecord,
    RunVersionRecord,
    StructuredResearchReport,
    TargetEntityType,
    UserInterventionRecord,
)


def _make_coord(
    cid: str = "COORD-DOC1#p1s1",
    doc_id: str = "DOC-001",
    doc_hash: str = "a" * 64,
    start: int = 10,
    end: int = 40,
    snippet: str = "target protein binds receptor",
) -> EvidenceCoordinate:
    """Helper creating a valid EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id=cid,
        document_id=doc_id,
        document_sha256=doc_hash,
        page_number=1,
        section_identifier="Results",
        paragraph_index=0,
        sentence_index=0,
        char_start=start,
        char_end=end,
        verbatim_snippet=snippet,
        extraction_confidence=0.95,
    )


def _make_report(
    report_id: str = "REP-TEST-001",
    assertions: list[ReportAssertion] | None = None,
) -> StructuredResearchReport:
    """Helper creating a minimal valid StructuredResearchReport."""
    coord = _make_coord()
    manifest = [
        CorpusManifestEntry(
            document_id="DOC-001",
            title="Binding Study",
            sha256_hash="a" * 64,
            publication_year=2024,
            venue="Nature Bio",
        )
    ]
    sections = {}
    titles = {
        ReportSectionType.EXECUTIVE_SUMMARY: "Executive Summary",
        ReportSectionType.CORPUS_PROVENANCE_MANIFEST: "Corpus Manifest",
        ReportSectionType.COMPARATIVE_SYNTHESIS: "Comparative Synthesis",
        ReportSectionType.CONTRADICTION_ANALYSIS: "Contradiction Analysis",
        ReportSectionType.RESEARCH_GAPS: "Research Gaps",
        ReportSectionType.LIMITATIONS_AND_BOUNDARIES: "Limitations",
        ReportSectionType.AUDITABLE_CITATION_INDEX: "Citation Index",
    }
    for st, title in titles.items():
        if st == ReportSectionType.EXECUTIVE_SUMMARY and assertions:
            sec_assertions = assertions
        else:
            sec_assertions = []
        sections[st] = ReportSection(
            section_type=st,
            title=title,
            content_markdown=f"Section {title}",
            assertions=list(sec_assertions),
        )

    return StructuredResearchReport(
        report_id=report_id,
        query_statement="Investigating binding mechanism.",
        created_at_iso="2026-10-16T08:00:00Z",
        corpus_manifest=manifest,
        sections=sections,
        citation_index={coord.coordinate_id: coord},
    )


class TestEvidenceInspector:
    """Contract tests for local-first evidence coordinate inspection and span resolution."""

    def test_inspect_coordinate_without_document_text(self) -> None:
        """Inspect coordinate when source text is not registered in local storage."""
        coord = _make_coord()
        inspector = EvidenceInspector(citation_index={coord.coordinate_id: coord})

        card = inspector.inspect_coordinate(coord.coordinate_id)
        assert isinstance(card, EvidenceSourceCard)
        assert card.coordinate_id == coord.coordinate_id
        assert card.resolved_against_document is False
        assert card.document_checksum_valid is False
        assert card.context_before == ""
        assert card.context_after == ""
        assert card.verbatim_snippet == coord.verbatim_snippet

        # Markdown rendering check
        md = card.render_markdown()
        assert "Citation Index Only" in md
        assert coord.coordinate_id in md

    def test_inspect_coordinate_with_resolved_document_text(self) -> None:
        """Inspect coordinate with verified source text and matching checksum."""
        prefix = "Preliminary assays indicate that "
        snippet = "target protein binds receptor"
        suffix = " with high affinity in vitro."
        full_text = prefix + snippet + suffix
        doc_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

        start = len(prefix)
        end = start + len(snippet)
        coord = _make_coord(
            cid="COORD-VERIFIED",
            doc_id="DOC-999",
            doc_hash=doc_hash,
            start=start,
            end=end,
            snippet=snippet,
        )

        inspector = EvidenceInspector()
        inspector.register_coordinate(coord)
        inspector.register_document("DOC-999", full_text)

        card = inspector.inspect_coordinate("COORD-VERIFIED", context_window=20)
        assert card.resolved_against_document is True
        assert card.document_checksum_valid is True
        assert card.context_before == prefix[-20:]
        assert card.context_after == suffix[:20]

        md = card.render_markdown()
        assert "Verified Match" in md
        assert "Source Text Resolved" in md
        assert f"[{snippet}]" in md

    def test_inspect_coordinate_checksum_mismatch(self) -> None:
        """Inspect coordinate when registered text checksum does not match coordinate."""
        coord = _make_coord(doc_hash="b" * 64)
        inspector = EvidenceInspector(citation_index={coord.coordinate_id: coord})
        inspector.register_document(coord.document_id, "Different content entirely.")

        card = inspector.inspect_coordinate(coord.coordinate_id)
        assert card.resolved_against_document is True
        assert card.document_checksum_valid is False

    def test_unresolved_coordinate_raises_error(self) -> None:
        """Attempting to resolve non-existent coordinate raises CoordinateResolutionError."""
        inspector = EvidenceInspector()
        with pytest.raises(CoordinateResolutionError, match="could not be resolved"):
            inspector.resolve_coordinate("NON_EXISTENT_COORD")

    def test_register_invalid_inputs(self) -> None:
        """Registering invalid coordinates or empty document IDs raises validation error."""
        inspector = EvidenceInspector()
        with pytest.raises(ReportSchemaValidationError):
            inspector.register_document("", "text")

    def test_inspect_assertion_and_section(self) -> None:
        """Inspect all coordinates cited by an assertion and section."""
        c1 = _make_coord("C1")
        c2 = _make_coord("C2")
        inspector = EvidenceInspector(citation_index={"C1": c1, "C2": c2})

        assertion = ReportAssertion(
            assertion_id="A1",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Statement citing two coordinates.",
            coordinate_ids=["C1", "C2"],
            status=AssertionStatus.VERIFIED,
        )

        cards = inspector.inspect_assertion(assertion)
        assert len(cards) == 2
        assert cards[0].coordinate_id == "C1"
        assert cards[1].coordinate_id == "C2"

        report = _make_report(assertions=[assertion])
        section_inspect = inspector.inspect_section_assertions(
            report, ReportSectionType.EXECUTIVE_SUMMARY
        )
        assert "A1" in section_inspect
        assert len(section_inspect["A1"]) == 2

    def test_inspection_summary_coverage(self) -> None:
        """Generate comprehensive inspection summary across report assertions."""
        text1 = "Sample text for doc1"
        h1 = hashlib.sha256(text1.encode("utf-8")).hexdigest()
        c1_matched = _make_coord(
            "C1", doc_id="DOC1", doc_hash=h1, start=0, end=6, snippet="Sample"
        )

        inspector = EvidenceInspector(citation_index={"C1": c1_matched})
        inspector.register_document("DOC1", text1)

        assertion = ReportAssertion(
            assertion_id="A1",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Statement citing C1 and missing C2.",
            coordinate_ids=["C1", "C2"],
        )
        report = _make_report(assertions=[assertion])

        summary = inspector.generate_inspection_summary(report)
        assert isinstance(summary, InspectionSummary)
        assert summary.total_citations == 2
        assert summary.resolved_citations == 1
        assert summary.document_verified_citations == 1
        assert summary.unresolved_citations == ["C2"]
        assert summary.coverage_ratio == 0.5

        # Empty assertions report summary
        empty_report = _make_report()
        empty_summary = inspector.generate_inspection_summary(empty_report)
        assert empty_summary.total_citations == 0
        assert empty_summary.coverage_ratio == 1.0


class TestLineageAndInterventionAudit:
    """Contract tests for version lineage registry, DAG navigation, and cryptographic audit log."""

    def test_intervention_audit_trail_cryptographic_chain(self) -> None:
        """Verify sequential SHA-256 chaining and tamper-evident audit logging."""
        audit = InterventionAuditTrail()
        assert audit.latest_hash == InterventionAuditTrail.GENESIS_HASH

        # Record first intervention
        r1 = audit.record_intervention(
            intervention_id="intv-001",
            intervention_type=InterventionType.ACCEPT,
            target_type=TargetEntityType.ASSERTION,
            target_id="ASRT-001",
            author_id="researcher_alice",
            created_at_iso="2026-10-16T08:10:00Z",
            rationale="Verified primary source table 2 agrees with finding.",
            previous_state={"status": "unverified", "confidence": 0.8},
            modified_state={"status": "verified", "confidence": 1.0},
        )
        assert r1.parent_entry_hash == InterventionAuditTrail.GENESIS_HASH
        assert r1.is_hash_valid()
        assert audit.latest_hash == r1.entry_hash

        # Record second intervention linked to first
        r2 = audit.record_intervention(
            intervention_id="intv-002",
            intervention_type=InterventionType.MODIFY,
            target_type=TargetEntityType.ASSERTION,
            target_id="ASRT-002",
            author_id="researcher_bob",
            created_at_iso="2026-10-16T08:15:00Z",
            rationale="Adjusted claim bounds to reflect murine model constraint.",
            previous_state={"statement": "Affects all mammals."},
            modified_state={"statement": "Demonstrated strictly in murine model."},
        )
        assert r2.parent_entry_hash == r1.entry_hash
        assert r2.is_hash_valid()
        assert audit.verify_integrity() is True

        # Query methods
        alice_records = audit.get_by_author("researcher_alice")
        assert len(alice_records) == 1
        assert alice_records[0].intervention_id == "intv-001"

        target_records = audit.get_by_target("ASRT-002")
        assert len(target_records) == 1
        assert target_records[0].intervention_id == "intv-002"

    def test_audit_trail_tamper_detection(self) -> None:
        """Tampering with record payload or hash triggers AuditIntegrityError."""
        audit = InterventionAuditTrail()
        audit.record_intervention(
            intervention_id="intv-001",
            intervention_type=InterventionType.ACCEPT,
            target_type=TargetEntityType.ASSERTION,
            target_id="ASRT-001",
            author_id="alice",
            created_at_iso="2026-10-16T08:00:00Z",
            rationale="Accepted.",
            previous_state={},
        )
        rec = audit.records[0]

        # Tampered entry hash
        tampered_rec = UserInterventionRecord(
            intervention_id=rec.intervention_id,
            intervention_type=rec.intervention_type,
            target_type=rec.target_type,
            target_id=rec.target_id,
            author_id=rec.author_id,
            created_at_iso=rec.created_at_iso,
            rationale="Tampered rationale!",
            previous_state=rec.previous_state,
            modified_state=rec.modified_state,
            parent_entry_hash=rec.parent_entry_hash,
            entry_hash=rec.entry_hash,  # Not updated to match tampered rationale!
        )

        bad_audit = InterventionAuditTrail()
        with pytest.raises(AuditIntegrityError, match="Audit hash mismatch"):
            bad_audit.append_record(tampered_rec)

    def test_audit_trail_broken_parent_chain(self) -> None:
        """Appending record with broken parent hash triggers AuditIntegrityError."""
        audit = InterventionAuditTrail()
        bad_rec = UserInterventionRecord(
            intervention_id="intv-bad",
            intervention_type=InterventionType.REJECT,
            target_type=TargetEntityType.ASSERTION,
            target_id="A1",
            author_id="alice",
            created_at_iso="2026-10-16T08:00:00Z",
            rationale="Reject ungrounded claim.",
            previous_state={},
            modified_state={},
            parent_entry_hash="f" * 64,  # Expected GENESIS_HASH
            entry_hash="1" * 64,
        )
        with pytest.raises(AuditIntegrityError, match="Audit chain broken"):
            audit.append_record(bad_rec)

    def test_invalid_intervention_arguments(self) -> None:
        """Recording intervention with missing required fields raises InvalidInterventionError."""
        audit = InterventionAuditTrail()
        with pytest.raises(InvalidInterventionError, match="intervention_id cannot be empty"):
            audit.record_intervention(
                intervention_id="",
                intervention_type=InterventionType.ACCEPT,
                target_type=TargetEntityType.ASSERTION,
                target_id="A1",
                author_id="alice",
                created_at_iso="2026-10-16T08:00:00Z",
                rationale="Rationale",
                previous_state={},
            )

    def test_lineage_registry_registration_and_navigation(self) -> None:
        """Register corpus, run, and report versions and navigate ancestry."""
        reg = LineageRegistry()

        # 1. Register corpus version
        corpus_rec = CorpusVersionRecord(
            corpus_version_id="CORPUS-V1",
            document_ids=["DOC-001", "DOC-002"],
            document_checksums={"DOC-001": "a" * 64, "DOC-002": "b" * 64},
            corpus_hash="c" * 64,
            created_at_iso="2026-10-16T07:00:00Z",
        )
        reg.register_corpus_version(corpus_rec)

        # 2. Register run version
        run_rec = RunVersionRecord(
            run_id="RUN-001",
            corpus_version_id="CORPUS-V1",
            query_statement="Target protein mechanisms",
            config_hash="d" * 64,
            executed_at_iso="2026-10-16T07:30:00Z",
        )
        reg.register_run_version(run_rec)

        # 3. Register initial report version v1
        v1 = ReportVersionRecord(
            version_id="REP-V1",
            report_id="REP-001",
            run_id="RUN-001",
            parent_version_id=None,
            content_sha256="e" * 64,
            created_at_iso="2026-10-16T08:00:00Z",
            description="Initial automated report generation",
        )
        reg.register_report_version(v1)

        # 4. Register derived report version v2
        v2 = ReportVersionRecord(
            version_id="REP-V2",
            report_id="REP-001",
            run_id="RUN-001",
            parent_version_id="REP-V1",
            content_sha256="f" * 64,
            created_at_iso="2026-10-16T08:30:00Z",
            description="Human review: adjusted claim scope",
            derived_by_intervention_id="intv-001",
        )
        reg.register_report_version(v2)

        # Navigate history
        history_v2 = reg.get_report_history("REP-V2")
        assert len(history_v2) == 2
        assert history_v2[0].version_id == "REP-V1"
        assert history_v2[1].version_id == "REP-V2"

        # Children
        children_v1 = reg.get_child_versions("REP-V1")
        assert len(children_v1) == 1
        assert children_v1[0].version_id == "REP-V2"

        # Trace full lineage
        trace = reg.trace_full_lineage("REP-V2")
        assert trace["report_version"]["version_id"] == "REP-V2"
        assert trace["execution_run"]["run_id"] == "RUN-001"
        assert trace["corpus_version"]["corpus_version_id"] == "CORPUS-V1"
        assert trace["ancestor_version_count"] == 1

    def test_lineage_registry_cycle_detection(self) -> None:
        """Attempting to construct a cyclical parent pointer raises LineageCycleError."""
        reg = LineageRegistry()
        corpus_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        reg.register_corpus_version(corpus_rec)
        run_rec = RunVersionRecord("R1", "C1", "q", "ch", "now")
        reg.register_run_version(run_rec)

        v1 = ReportVersionRecord("V1", "REP-1", "R1", None, "h1", "now")
        reg.register_report_version(v1)

        v2 = ReportVersionRecord("V2", "REP-1", "R1", "V1", "h2", "now")
        reg.register_report_version(v2)

        # Attempting self-loop
        v_cycle = ReportVersionRecord("V1", "REP-1", "R1", "V2", "h3", "now")
        with pytest.raises(LineageCycleError, match="Cycle detected"):
            reg.register_report_version(v_cycle)

    def test_lineage_diff_reports(self) -> None:
        """Diff two versions of a report tracking added, removed, and modified assertions."""
        a1_base = ReportAssertion(
            "A1", ReportSectionType.EXECUTIVE_SUMMARY, "Initial claim.", ["C1"],
            confidence_score=0.7,
        )
        a2_base = ReportAssertion(
            "A2", ReportSectionType.EXECUTIVE_SUMMARY, "Claim to be removed.", ["C2"]
        )
        report_base = _make_report("REP-BASE", [a1_base, a2_base])

        a1_target = ReportAssertion(
            "A1", ReportSectionType.EXECUTIVE_SUMMARY, "Modified claim text.", ["C1"],
            confidence_score=0.9,
        )
        a3_target = ReportAssertion(
            "A3", ReportSectionType.EXECUTIVE_SUMMARY, "Newly added claim.", ["C3"]
        )
        report_target = _make_report("REP-TARGET", [a1_target, a3_target])

        reg = LineageRegistry()
        diff = reg.diff_reports(report_base, report_target)

        assert diff["added_count"] == 1
        assert diff["removed_count"] == 1
        assert diff["modified_count"] == 1
        assert diff["added"][0]["assertion_id"] == "A3"
        assert diff["removed"][0]["assertion_id"] == "A2"
        assert diff["modified"][0]["assertion_id"] == "A1"


class TestProjectHistoryManager:
    """Contract tests for end-to-end user intervention application and report versioning."""

    def test_apply_accept_intervention(self) -> None:
        """Accept an assertion: status becomes VERIFIED, audit logged, version registered."""
        assertion = ReportAssertion(
            assertion_id="ASRT-100",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Novel kinase inhibitor exhibits sub-micromolar IC50.",
            coordinate_ids=["COORD-DOC1#p1s1"],
            status=AssertionStatus.UNVERIFIED,
            confidence_score=0.85,
        )
        report = _make_report(assertions=[assertion])

        mgr = ProjectHistoryManager()
        # Setup base lineage
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        mgr.lineage.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "query", "cfg", "now")
        mgr.lineage.register_run_version(r_rec)
        v0 = ReportVersionRecord("REP-V0", report.report_id, "R1", None, "h0", "now")
        mgr.lineage.register_report_version(v0)

        new_rep, intv, v1 = mgr.apply_assertion_intervention(
            report=report,
            current_version_id="REP-V0",
            new_version_id="REP-V1",
            assertion_id="ASRT-100",
            intervention_type=InterventionType.ACCEPT,
            author_id="curator_dr_smith",
            rationale="Verified primary source assay curves in supplementary fig 3.",
            created_at_iso="2026-10-16T08:45:00Z",
        )

        # Check new report state
        new_assertion = new_rep.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions[0]
        assert new_assertion.status == AssertionStatus.VERIFIED

        # Check original report is unmodified (immutability)
        orig_assertion = report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions[0]
        assert orig_assertion.status == AssertionStatus.UNVERIFIED

        # Check audit entry
        assert intv.target_id == "ASRT-100"
        assert intv.author_id == "curator_dr_smith"
        assert intv.intervention_type == InterventionType.ACCEPT
        assert mgr.audit.verify_integrity() is True

        # Check lineage registry
        assert v1.parent_version_id == "REP-V0"
        assert v1.derived_by_intervention_id == intv.intervention_id

    def test_apply_modify_and_reject_interventions(self) -> None:
        """Modify and reject interventions update statement, caveats, and statuses properly."""
        a1 = ReportAssertion(
            assertion_id="A-MOD",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Broad assertion.",
            coordinate_ids=["COORD-DOC1#p1s1"],
            status=AssertionStatus.UNVERIFIED,
        )
        report = _make_report(assertions=[a1])

        mgr = ProjectHistoryManager()
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        mgr.lineage.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "query", "cfg", "now")
        mgr.lineage.register_run_version(r_rec)
        v0 = ReportVersionRecord("REP-V0", report.report_id, "R1", None, "h0", "now")
        mgr.lineage.register_report_version(v0)

        # 1. Modify
        rep_v1, intv1, v1 = mgr.apply_assertion_intervention(
            report=report,
            current_version_id="REP-V0",
            new_version_id="REP-V1",
            assertion_id="A-MOD",
            intervention_type=InterventionType.MODIFY,
            author_id="editor_carol",
            rationale="Specified experimental conditions.",
            created_at_iso="2026-10-16T08:50:00Z",
            modified_statement="Narrowed assertion strictly under pH 7.4 buffer.",
            modified_confidence=0.99,
            modified_caveat="Does not hold under acidic conditions.",
        )
        modified_a = rep_v1.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions[0]
        assert modified_a.statement == "Narrowed assertion strictly under pH 7.4 buffer."
        assert modified_a.confidence_score == 0.99
        assert modified_a.caveat == "Does not hold under acidic conditions."
        assert modified_a.status == AssertionStatus.VERIFIED

        # 2. Reject on rep_v1
        rep_v2, intv2, v2 = mgr.apply_assertion_intervention(
            report=rep_v1,
            current_version_id="REP-V1",
            new_version_id="REP-V2",
            assertion_id="A-MOD",
            intervention_type=InterventionType.REJECT,
            author_id="senior_reviewer",
            rationale="Contradicted by subsequent study.",
            created_at_iso="2026-10-16T08:55:00Z",
            modified_caveat="Rejected due to invalid assay calibration.",
        )
        rejected_a = rep_v2.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions[0]
        assert rejected_a.status == AssertionStatus.REJECTED
        assert rejected_a.caveat == "Rejected due to invalid assay calibration."
        assert mgr.audit.verify_integrity() is True
        assert len(mgr.audit.records) == 2

    def test_apply_intervention_non_existent_assertion_raises(self) -> None:
        """Intervening on an assertion ID not in the report raises InvalidInterventionError."""
        report = _make_report()
        mgr = ProjectHistoryManager()
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        mgr.lineage.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "query", "cfg", "now")
        mgr.lineage.register_run_version(r_rec)
        v0 = ReportVersionRecord("REP-V0", report.report_id, "R1", None, "h0", "now")
        mgr.lineage.register_report_version(v0)

        with pytest.raises(InvalidInterventionError, match="not found in report"):
            mgr.apply_assertion_intervention(
                report=report,
                current_version_id="REP-V0",
                new_version_id="REP-V1",
                assertion_id="DOES_NOT_EXIST",
                intervention_type=InterventionType.ACCEPT,
                author_id="alice",
                rationale="Reason",
                created_at_iso="now",
            )


class TestLineageAndInspectorEdgeCases:
    """Edge cases, validation checks, and serialization roundtrips for Layer 11 inspection."""

    def test_evidence_source_card_to_dict(self) -> None:
        """Verify to_dict on EvidenceSourceCard."""
        coord = _make_coord()
        card = EvidenceSourceCard(
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
            metadata={"source": "unit_test"},
        )
        d = card.to_dict()
        assert d["coordinate_id"] == coord.coordinate_id
        assert d["metadata"]["source"] == "unit_test"

    def test_inspection_summary_to_dict(self) -> None:
        """Verify to_dict on InspectionSummary."""
        summary = InspectionSummary(
            total_citations=3,
            resolved_citations=2,
            unresolved_citations=["C3"],
            document_verified_citations=1,
            coverage_ratio=2 / 3,
        )
        d = summary.to_dict()
        assert d["total_citations"] == 3
        assert d["unresolved_citations"] == ["C3"]

    def test_inspector_register_empty_coordinate_id_raises(self) -> None:
        """Registering coordinate with empty coordinate_id raises ReportSchemaValidationError."""
        coord = EvidenceCoordinate(
            coordinate_id="   ",
            document_id="DOC-1",
            document_sha256="a" * 64,
            page_number=1,
            section_identifier="Sec",
            paragraph_index=0,
            sentence_index=0,
            char_start=0,
            char_end=5,
            verbatim_snippet="Test",
        )
        inspector = EvidenceInspector()
        with pytest.raises(ReportSchemaValidationError):
            inspector.register_coordinate(coord)

    def test_inspect_section_assertions_missing_section(self) -> None:
        """Inspecting section not present in report returns empty dictionary."""
        report = _make_report()
        # Remove executive summary section
        del report.sections[ReportSectionType.EXECUTIVE_SUMMARY]
        inspector = EvidenceInspector()
        res = inspector.inspect_section_assertions(report, ReportSectionType.EXECUTIVE_SUMMARY)
        assert res == {}

    def test_version_records_serialization_roundtrip(self) -> None:
        """Verify serialization and deserialization of version records."""
        # CorpusVersionRecord
        c_rec = CorpusVersionRecord(
            corpus_version_id="CORP-V1",
            document_ids=["DOC-1"],
            document_checksums={"DOC-1": "a" * 64},
            corpus_hash="c" * 64,
            created_at_iso="2026-10-16T08:00:00Z",
            metadata={"env": "test"},
        )
        c_dict = c_rec.to_dict()
        c_rt = CorpusVersionRecord.from_dict(c_dict)
        assert c_rt.corpus_version_id == "CORP-V1"
        assert c_rt.metadata == {"env": "test"}

        # RunVersionRecord
        r_rec = RunVersionRecord(
            run_id="RUN-V1",
            corpus_version_id="CORP-V1",
            query_statement="Testing query",
            config_hash="h" * 64,
            executed_at_iso="2026-10-16T08:00:00Z",
            metadata={"mode": "fast"},
        )
        r_dict = r_rec.to_dict()
        r_rt = RunVersionRecord.from_dict(r_dict)
        assert r_rt.run_id == "RUN-V1"
        assert r_rt.metadata == {"mode": "fast"}

        # ReportVersionRecord
        rep_rec = ReportVersionRecord(
            version_id="REP-V1",
            report_id="REP-001",
            run_id="RUN-V1",
            parent_version_id=None,
            content_sha256="s" * 64,
            created_at_iso="2026-10-16T08:00:00Z",
            description="Initial report",
            derived_by_intervention_id=None,
            metadata={"reviewer": "test"},
        )
        rep_dict = rep_rec.to_dict()
        rep_rt = ReportVersionRecord.from_dict(rep_dict)
        assert rep_rt.version_id == "REP-V1"
        assert rep_rt.metadata == {"reviewer": "test"}

    def test_user_intervention_record_serialization_roundtrip(self) -> None:
        """Verify serialization and deserialization of UserInterventionRecord."""
        trail = InterventionAuditTrail()
        rec = trail.record_intervention(
            intervention_id="intv-001",
            intervention_type=InterventionType.ACCEPT,
            target_type=TargetEntityType.ASSERTION,
            target_id="ASRT-1",
            author_id="user1",
            created_at_iso="2026-10-16T08:00:00Z",
            rationale="Accepted",
            previous_state={"status": "unverified"},
            modified_state={"status": "verified"},
        )
        d = rec.to_dict()
        rt = UserInterventionRecord.from_dict(d)
        assert rt.intervention_id == "intv-001"
        assert rt.is_hash_valid()

        # Trail serialization
        trail_dict = trail.to_dict()
        trail_rt = InterventionAuditTrail.from_dict(trail_dict)
        assert len(trail_rt.records) == 1
        assert trail_rt.verify_integrity() is True

    def test_lineage_registry_validations(self) -> None:
        """Verify error checking for invalid or missing IDs in LineageRegistry."""
        reg = LineageRegistry()

        # Empty corpus_version_id
        with pytest.raises(ReportSchemaValidationError):
            reg.register_corpus_version(
                CorpusVersionRecord("   ", [], {}, "h", "now")
            )

        # Empty run_id
        with pytest.raises(ReportSchemaValidationError):
            reg.register_run_version(
                RunVersionRecord("   ", "CORP-1", "q", "ch", "now")
            )

        # Unregistered corpus_version_id
        with pytest.raises(LineageNotFoundError, match="is not registered"):
            reg.register_run_version(
                RunVersionRecord("RUN-1", "NON_EXISTENT", "q", "ch", "now")
            )

        # Empty report version_id
        with pytest.raises(ReportSchemaValidationError):
            reg.register_report_version(
                ReportVersionRecord("   ", "REP-1", "RUN-1", None, "h", "now")
            )

        # Unregistered run_id
        with pytest.raises(LineageNotFoundError, match="is not registered"):
            reg.register_report_version(
                ReportVersionRecord("V1", "REP-1", "NON_EXISTENT_RUN", None, "h", "now")
            )

        # Register valid corpus and run
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        reg.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "q", "ch", "now")
        reg.register_run_version(r_rec)

        # Unregistered parent_version_id
        with pytest.raises(LineageNotFoundError, match="Parent report version"):
            reg.register_report_version(
                ReportVersionRecord("V1", "REP-1", "R1", "NON_EXISTENT_PARENT", "h", "now")
            )

        # get_report_version on non-existent version
        with pytest.raises(LineageNotFoundError, match="not found in registry"):
            reg.get_report_version("UNKNOWN_V")

    def test_intervention_audit_trail_validation_and_integrity_branches(self) -> None:
        """Test validation error branches in record_intervention and verify_integrity."""
        trail = InterventionAuditTrail()

        with pytest.raises(InvalidInterventionError, match="target_id cannot be empty"):
            trail.record_intervention(
                intervention_id="i1",
                intervention_type=InterventionType.ACCEPT,
                target_type=TargetEntityType.ASSERTION,
                target_id="  ",
                author_id="a1",
                created_at_iso="now",
                rationale="Valid rationale",
                previous_state={},
            )

        with pytest.raises(InvalidInterventionError, match="author_id cannot be empty"):
            trail.record_intervention(
                intervention_id="i1",
                intervention_type=InterventionType.ACCEPT,
                target_type=TargetEntityType.ASSERTION,
                target_id="t1",
                author_id="  ",
                created_at_iso="now",
                rationale="Valid rationale",
                previous_state={},
            )

        with pytest.raises(InvalidInterventionError, match="rationale cannot be empty"):
            trail.record_intervention(
                intervention_id="i1",
                intervention_type=InterventionType.ACCEPT,
                target_type=TargetEntityType.ASSERTION,
                target_id="t1",
                author_id="a1",
                created_at_iso="now",
                rationale="  ",
                previous_state={},
            )

        # Test verify_integrity corrupted parent in middle of chain
        r1 = trail.record_intervention(
            intervention_id="i1",
            intervention_type=InterventionType.ACCEPT,
            target_type=TargetEntityType.ASSERTION,
            target_id="t1",
            author_id="a1",
            created_at_iso="now",
            rationale="Rationale",
            previous_state={},
        )
        r2 = trail.record_intervention(
            intervention_id="i2",
            intervention_type=InterventionType.ACCEPT,
            target_type=TargetEntityType.ASSERTION,
            target_id="t2",
            author_id="a2",
            created_at_iso="now",
            rationale="Rationale",
            previous_state={},
        )
        assert trail.verify_integrity() is True

        # Manually tamper with r1's entry_hash
        trail._records[0] = UserInterventionRecord(
            intervention_id=r1.intervention_id,
            intervention_type=r1.intervention_type,
            target_type=r1.target_type,
            target_id=r1.target_id,
            author_id=r1.author_id,
            created_at_iso=r1.created_at_iso,
            rationale=r1.rationale,
            previous_state=r1.previous_state,
            modified_state=r1.modified_state,
            parent_entry_hash=r1.parent_entry_hash,
            entry_hash="x" * 64,
        )
        with pytest.raises(AuditIntegrityError, match="hash corrupted"):
            trail.verify_integrity()

        # Manually tamper with r2's parent_entry_hash
        trail._records[0] = r1  # restore r1
        trail._records[1] = UserInterventionRecord(
            intervention_id=r2.intervention_id,
            intervention_type=r2.intervention_type,
            target_type=r2.target_type,
            target_id=r2.target_id,
            author_id=r2.author_id,
            created_at_iso=r2.created_at_iso,
            rationale=r2.rationale,
            previous_state=r2.previous_state,
            modified_state=r2.modified_state,
            parent_entry_hash="bad_parent_hash" + "0" * 49,
            entry_hash=r2.entry_hash,
        )
        with pytest.raises(AuditIntegrityError, match="parent hash"):
            trail.verify_integrity()

    def test_apply_unsupported_intervention_type_raises(self) -> None:
        """Applying unsupported intervention type raises InvalidInterventionError."""
        report = _make_report()
        a = ReportAssertion("A1", ReportSectionType.EXECUTIVE_SUMMARY, "Claim", ["C1"])
        report.sections[ReportSectionType.EXECUTIVE_SUMMARY].assertions = [a]
        mgr = ProjectHistoryManager()
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h" * 64, "now")
        mgr.lineage.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "query", "cfg", "now")
        mgr.lineage.register_run_version(r_rec)
        v0 = ReportVersionRecord("REP-V0", report.report_id, "R1", None, "h0", "now")
        mgr.lineage.register_report_version(v0)

        with pytest.raises(InvalidInterventionError, match="Unsupported intervention type"):
            mgr.apply_assertion_intervention(
                report=report,
                current_version_id="REP-V0",
                new_version_id="REP-V1",
                assertion_id="A1",
                intervention_type="INVALID_TYPE",  # type: ignore
                author_id="user",
                rationale="Test",
                created_at_iso="now",
            )

