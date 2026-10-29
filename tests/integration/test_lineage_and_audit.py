"""Integration tests for version lineage navigation and user intervention audit trail.

Tests compliance with DOC-SPEC-REP-001, DOC-SPEC-MOD-001 (Boundary K), ADR-004, and Issue #107:
- Multi-generational lineage navigation linking corpus manifests, execution runs, and reports
- Branching lineage trees and ancestral history traversal with cycle prevention
- Source-span navigation and bitwise document coordinate verification on synthetic corpora
- Append-only cryptographic SHA-256 audit chaining across multi-user review workflows
- Non-destructive report derivation and structured version diffing
- Adversarial audit log tampering detection and cryptographic integrity verification
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Tuple

import pytest

from laris.core.errors import (
    AuditIntegrityError,
    CoordinateResolutionError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.reporting import (
    AssertionStatus,
    CorpusManifestEntry,
    CorpusVersionRecord,
    EvidenceInspector,
    EvidenceSourceCard,
    InterventionType,
    LineageRegistry,
    ProjectHistoryManager,
    ReportAssertion,
    ReportSectionType,
    ReportVersionRecord,
    RunVersionRecord,
    StructuredReportGenerator,
    StructuredResearchReport,
    UserInterventionRecord,
)


def _build_synthetic_corpus_fixtures() -> Tuple[
    List[CorpusManifestEntry], Dict[str, str], Dict[str, EvidenceCoordinate]
]:
    """Build synthetic scientific papers, corpus manifest entries, and coordinates."""
    text_paper_1 = (
        "Kinetic Characterization of Dual-Specificity Kinase Inhibitors.\n\n"
        "Abstract: We report compound K-724 as a selective inhibitor with sub-nanomolar "
        "potency (IC50 = 0.42 nM) against CDK4 and CDK6 kinase domains. In vitro assays "
        "demonstrate minimal off-target binding across a 400-kinase panel.\n\n"
        "Methods: Recombinant assays were performed at 25 degrees Celsius in Tris buffer."
    )
    hash_paper_1 = hashlib.sha256(text_paper_1.encode("utf-8")).hexdigest()

    text_paper_2 = (
        "Thermal Shift and Permeability Limitations of Benzimidazole Inhibitors.\n\n"
        "Abstract: While compound K-724 shows high biochemical potency in purified assays, "
        "cellular target engagement is constrained by poor membrane permeability (Papp < 0.5).\n\n"
        "Discussion: Efficacy in vivo will require prodrug esterification or formulation."
    )
    hash_paper_2 = hashlib.sha256(text_paper_2.encode("utf-8")).hexdigest()

    manifest = [
        CorpusManifestEntry(
            document_id="DOC-2024-K724-01",
            title="Kinetic Characterization of Dual-Specificity Kinase Inhibitors",
            sha256_hash=hash_paper_1,
            publication_year=2024,
            venue="J. Med. Chem.",
            peer_reviewed=True,
            ocr_quality_score=0.99,
        ),
        CorpusManifestEntry(
            document_id="DOC-2024-K724-02",
            title="Thermal Shift and Permeability Limitations of Benzimidazole Inhibitors",
            sha256_hash=hash_paper_2,
            publication_year=2024,
            venue="ACS Chem. Biol.",
            peer_reviewed=True,
            ocr_quality_score=0.97,
        ),
    ]

    doc_texts = {
        "DOC-2024-K724-01": text_paper_1,
        "DOC-2024-K724-02": text_paper_2,
    }

    # Snippet 1
    s1 = "sub-nanomolar potency (IC50 = 0.42 nM)"
    idx1 = text_paper_1.index(s1)
    coord_1 = EvidenceCoordinate(
        coordinate_id="COORD-K724-POTENCY",
        document_id="DOC-2024-K724-01",
        document_sha256=hash_paper_1,
        page_number=1,
        section_identifier="Abstract",
        paragraph_index=1,
        sentence_index=1,
        char_start=idx1,
        char_end=idx1 + len(s1),
        verbatim_snippet=s1,
        extraction_confidence=0.98,
    )

    # Snippet 2
    s2 = "cellular target engagement is constrained by poor membrane permeability (Papp < 0.5)"
    idx2 = text_paper_2.index(s2)
    coord_2 = EvidenceCoordinate(
        coordinate_id="COORD-K724-PERMEABILITY",
        document_id="DOC-2024-K724-02",
        document_sha256=hash_paper_2,
        page_number=1,
        section_identifier="Abstract",
        paragraph_index=1,
        sentence_index=1,
        char_start=idx2,
        char_end=idx2 + len(s2),
        verbatim_snippet=s2,
        extraction_confidence=0.96,
    )

    coordinates = {
        coord_1.coordinate_id: coord_1,
        coord_2.coordinate_id: coord_2,
    }

    return manifest, doc_texts, coordinates


def _generate_canonical_report(
    report_id: str,
    manifest: List[CorpusManifestEntry],
    coordinates: Dict[str, EvidenceCoordinate],
    assertions: List[ReportAssertion],
) -> StructuredResearchReport:
    """Generate canonical 7-section report using StructuredReportGenerator."""
    gen = StructuredReportGenerator()
    sections_content = {
        st: f"Content for section {st.value}" for st in ReportSectionType
    }
    report, _ = gen.generate_report(
        report_id=report_id,
        query_statement="Evaluate biochemical potency and translational feasibility of K-724.",
        corpus_manifest=manifest,
        sections_content=sections_content,
        assertions=assertions,
        citation_index=coordinates,
        strict_gate=True,
    )
    return report


class TestLineageNavigationAndAuditIntegration:
    """Integration test suite for source-span inspection, lineage navigation, and audit trails."""

    def test_end_to_end_source_span_inspection(self) -> None:
        """Inspect source spans across multiple documents and verify coordinate integrity."""
        manifest, doc_texts, coordinates = _build_synthetic_corpus_fixtures()

        a1 = ReportAssertion(
            assertion_id="ASRT-001",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Compound K-724 demonstrates sub-nanomolar biochemical inhibition.",
            coordinate_ids=["COORD-K724-POTENCY"],
            status=AssertionStatus.VERIFIED,
            confidence_score=0.95,
        )
        a2 = ReportAssertion(
            assertion_id="ASRT-002",
            section=ReportSectionType.LIMITATIONS_AND_BOUNDARIES,
            statement="Cellular target engagement is impeded by membrane permeability barriers.",
            coordinate_ids=["COORD-K724-PERMEABILITY"],
            status=AssertionStatus.VERIFIED,
            confidence_score=0.92,
        )

        report = _generate_canonical_report(
            report_id="REP-K724-V1",
            manifest=manifest,
            coordinates=coordinates,
            assertions=[a1, a2],
        )

        # Initialize local-first inspector with corpus texts
        inspector = EvidenceInspector(
            citation_index=report.citation_index,
            document_texts=doc_texts,
        )

        # Inspect assertion 1
        cards_a1 = inspector.inspect_assertion(a1, context_window=40)
        assert len(cards_a1) == 1
        c1 = cards_a1[0]
        assert isinstance(c1, EvidenceSourceCard)
        assert c1.coordinate_id == "COORD-K724-POTENCY"
        assert c1.document_id == "DOC-2024-K724-01"
        assert c1.resolved_against_document is True
        assert c1.document_checksum_valid is True
        assert "sub-nanomolar potency" in c1.verbatim_snippet
        assert "selective inhibitor with" in c1.context_before
        assert "against CDK4 and CDK6" in c1.context_after

        # Inspect assertion 2
        cards_a2 = inspector.inspect_assertion(a2, context_window=30)
        assert len(cards_a2) == 1
        c2 = cards_a2[0]
        assert c2.coordinate_id == "COORD-K724-PERMEABILITY"
        assert c2.document_id == "DOC-2024-K724-02"
        assert c2.resolved_against_document is True
        assert c2.document_checksum_valid is True
        assert "poor membrane permeability" in c2.verbatim_snippet

        # Inspection summary across complete report
        summary = inspector.generate_inspection_summary(report)
        assert summary.total_citations == 2
        assert summary.resolved_citations == 2
        assert summary.document_verified_citations == 2
        assert summary.coverage_ratio == 1.0
        assert len(summary.unresolved_citations) == 0

    def test_corrupt_document_fails_bitwise_verification(self) -> None:
        """Bitwise document corruption is detected during source span inspection."""
        manifest, doc_texts, coordinates = _build_synthetic_corpus_fixtures()

        # Corrupt document text in local store
        corrupted_texts = dict(doc_texts)
        corrupted_texts["DOC-2024-K724-01"] = (
            doc_texts["DOC-2024-K724-01"] + "\n[UNAUTHORIZED TAMPERING DETECTED]"
        )

        inspector = EvidenceInspector(
            citation_index=coordinates,
            document_texts=corrupted_texts,
        )

        card = inspector.inspect_coordinate("COORD-K724-POTENCY")
        assert card.resolved_against_document is True
        # Checksum must be invalid because document text changed
        assert card.document_checksum_valid is False

        # Attempting to resolve non-existent coordinate fails cleanly
        with pytest.raises(CoordinateResolutionError, match="could not be resolved"):
            inspector.resolve_coordinate("COORD-NON-EXISTENT")

    def test_multi_stage_lineage_and_branching_navigation(self) -> None:
        """Test multi-generational lineage with branching review paths and ancestry tracing."""
        manifest, _, coordinates = _build_synthetic_corpus_fixtures()

        a1 = ReportAssertion(
            assertion_id="ASRT-001",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Compound K-724 demonstrates sub-nanomolar potency in vitro.",
            coordinate_ids=["COORD-K724-POTENCY"],
            status=AssertionStatus.VERIFIED,
        )
        report_v1 = _generate_canonical_report("REP-001", manifest, coordinates, [a1])

        # 1. Setup Lineage Registry
        reg = LineageRegistry()

        # Register Corpus Version V1
        corpus_v1 = CorpusVersionRecord(
            corpus_version_id="CORP-V1",
            document_ids=[m.document_id for m in manifest],
            document_checksums={m.document_id: m.sha256_hash for m in manifest},
            corpus_hash=hashlib.sha256("corpus-v1-bytes".encode("utf-8")).hexdigest(),
            created_at_iso="2026-10-16T07:00:00Z",
        )
        reg.register_corpus_version(corpus_v1)

        # Register Initial Run
        run_v1 = RunVersionRecord(
            run_id="RUN-TRAINING-1",
            corpus_version_id="CORP-V1",
            query_statement="Translational assessment of K-724",
            config_hash=hashlib.sha256("config-default".encode("utf-8")).hexdigest(),
            executed_at_iso="2026-10-16T07:30:00Z",
        )
        reg.register_run_version(run_v1)

        # Register Root Report Version
        rep_rec_v1 = ReportVersionRecord(
            version_id="REP-001-V1",
            report_id=report_v1.report_id,
            run_id="RUN-TRAINING-1",
            parent_version_id=None,
            content_sha256=hashlib.sha256(report_v1.render_markdown().encode("utf-8")).hexdigest(),
            created_at_iso="2026-10-16T08:00:00Z",
            description="Initial automated synthesis report",
        )
        reg.register_report_version(rep_rec_v1)

        # 2. Branch 1: Reviewer A modifies the assertion scope
        mgr = ProjectHistoryManager(lineage_registry=reg)

        rep_v2_branch_a, intv_a, ver_v2_a = mgr.apply_assertion_intervention(
            report=report_v1,
            current_version_id="REP-001-V1",
            new_version_id="REP-001-V2-BRANCH-A",
            assertion_id="ASRT-001",
            intervention_type=InterventionType.MODIFY,
            author_id="reviewer_alice",
            rationale="Scoped assertion strictly to purified CDK4/6 kinase domains.",
            created_at_iso="2026-10-16T08:15:00Z",
            modified_statement="K-724 is potent against purified CDK4/6 kinase domains.",
            modified_confidence=0.99,
        )

        # 3. Branch 2: Reviewer B rejects assertion based on cellular permeability
        rep_v2_branch_b, intv_b, ver_v2_b = mgr.apply_assertion_intervention(
            report=report_v1,
            current_version_id="REP-001-V1",
            new_version_id="REP-001-V2-BRANCH-B",
            assertion_id="ASRT-001",
            intervention_type=InterventionType.REJECT,
            author_id="reviewer_bob",
            rationale="In vitro potency does not translate without cellular permeability.",
            created_at_iso="2026-10-16T08:20:00Z",
            modified_caveat="Rejected for clinical translatability pending prodrug data.",
        )

        # 4. Third generation on Branch A: Reviewer C accepts the scoped claim
        rep_v3_branch_a, intv_c, ver_v3_a = mgr.apply_assertion_intervention(
            report=rep_v2_branch_a,
            current_version_id="REP-001-V2-BRANCH-A",
            new_version_id="REP-001-V3-BRANCH-A",
            assertion_id="ASRT-001",
            intervention_type=InterventionType.ACCEPT,
            author_id="editor_carol",
            rationale="Approved revised scope for publication.",
            created_at_iso="2026-10-16T08:30:00Z",
        )

        # Verify lineage tree structure
        # V1 has two direct children (Branch A and Branch B)
        v1_children = reg.get_child_versions("REP-001-V1")
        child_ids = [c.version_id for c in v1_children]
        assert len(child_ids) == 2
        assert "REP-001-V2-BRANCH-A" in child_ids
        assert "REP-001-V2-BRANCH-B" in child_ids

        # Ancestry of V3 Branch A: Root -> V2-A -> V3-A
        history_v3_a = reg.get_report_history("REP-001-V3-BRANCH-A")
        assert len(history_v3_a) == 3
        assert history_v3_a[0].version_id == "REP-001-V1"
        assert history_v3_a[1].version_id == "REP-001-V2-BRANCH-A"
        assert history_v3_a[2].version_id == "REP-001-V3-BRANCH-A"

        # Full provenance trace from leaf back to corpus and run
        trace = reg.trace_full_lineage("REP-001-V3-BRANCH-A")
        assert trace["report_version"]["version_id"] == "REP-001-V3-BRANCH-A"
        assert trace["execution_run"]["run_id"] == "RUN-TRAINING-1"
        assert trace["corpus_version"]["corpus_version_id"] == "CORP-V1"
        assert trace["ancestor_version_count"] == 2
        assert trace["ancestor_chain"] == [
            "REP-001-V1", "REP-001-V2-BRANCH-A", "REP-001-V3-BRANCH-A"
        ]

        # Audit trail integrity across all 3 sequential interventions
        assert mgr.audit.verify_integrity() is True
        assert len(mgr.audit.records) == 3

        # Diff reports: Branch A vs Root
        diff_a_vs_root = reg.diff_reports(report_v1, rep_v2_branch_a)
        assert diff_a_vs_root["modified_count"] == 1
        assert diff_a_vs_root["added_count"] == 0
        assert diff_a_vs_root["removed_count"] == 0
        mod_entry = diff_a_vs_root["modified"][0]
        assert mod_entry["assertion_id"] == "ASRT-001"
        assert mod_entry["before"]["statement"] != mod_entry["after"]["statement"]

    def test_cryptographic_audit_tampering_and_recovery(self) -> None:
        """Adversarial simulation: unauthorized modification of audit record fails verification."""
        manifest, _, coordinates = _build_synthetic_corpus_fixtures()
        a1 = ReportAssertion(
            assertion_id="ASRT-AUDIT",
            section=ReportSectionType.EXECUTIVE_SUMMARY,
            statement="Primary claim for audit integrity test.",
            coordinate_ids=["COORD-K724-POTENCY"],
        )
        report = _generate_canonical_report("REP-AUDIT", manifest, coordinates, [a1])

        mgr = ProjectHistoryManager()
        c_rec = CorpusVersionRecord("C1", ["D1"], {"D1": "a" * 64}, "h", "now")
        mgr.lineage.register_corpus_version(c_rec)
        r_rec = RunVersionRecord("R1", "C1", "query", "cfg", "now")
        mgr.lineage.register_run_version(r_rec)
        v0 = ReportVersionRecord("V0", report.report_id, "R1", None, "h0", "now")
        mgr.lineage.register_report_version(v0)

        # Apply two interventions
        mgr.apply_assertion_intervention(
            report=report,
            current_version_id="V0",
            new_version_id="V1",
            assertion_id="ASRT-AUDIT",
            intervention_type=InterventionType.ACCEPT,
            author_id="user_alice",
            rationale="Legitimate acceptance rationale.",
            created_at_iso="2026-10-16T08:00:00Z",
        )
        mgr.apply_assertion_intervention(
            report=report,
            current_version_id="V1",
            new_version_id="V2",
            assertion_id="ASRT-AUDIT",
            intervention_type=InterventionType.MODIFY,
            author_id="user_bob",
            rationale="Legitimate modification rationale.",
            created_at_iso="2026-10-16T08:10:00Z",
            modified_statement="Modified statement.",
        )

        # Baseline audit trail is cryptographically sound
        assert mgr.audit.verify_integrity() is True

        # Scenario 1: Maliciously tamper with first record's rationale
        r0 = mgr.audit.records[0]
        tampered_r0 = UserInterventionRecord(
            intervention_id=r0.intervention_id,
            intervention_type=r0.intervention_type,
            target_type=r0.target_type,
            target_id=r0.target_id,
            author_id=r0.author_id,
            created_at_iso=r0.created_at_iso,
            rationale="TAMPERED: Altered rationale without recalculating hash.",
            previous_state=r0.previous_state,
            modified_state=r0.modified_state,
            parent_entry_hash=r0.parent_entry_hash,
            entry_hash=r0.entry_hash,
        )
        mgr.audit._records[0] = tampered_r0

        # Verification must catch payload hash mismatch
        with pytest.raises(AuditIntegrityError, match="hash corrupted"):
            mgr.audit.verify_integrity()

        # Scenario 2: Restore r0 but break link between r0 and r1
        mgr.audit._records[0] = r0
        r1 = mgr.audit.records[1]
        tampered_r1 = UserInterventionRecord(
            intervention_id=r1.intervention_id,
            intervention_type=r1.intervention_type,
            target_type=r1.target_type,
            target_id=r1.target_id,
            author_id=r1.author_id,
            created_at_iso=r1.created_at_iso,
            rationale=r1.rationale,
            previous_state=r1.previous_state,
            modified_state=r1.modified_state,
            parent_entry_hash="0" * 64,  # Broken link: points to GENESIS instead of r0.entry_hash
            entry_hash=r1.entry_hash,
        )
        mgr.audit._records[1] = tampered_r1

        # Verification must catch broken parent link
        with pytest.raises(AuditIntegrityError, match="parent hash"):
            mgr.audit.verify_integrity()

        # Scenario 3: Restore r1, verify integrity is restored
        mgr.audit._records[1] = r1
        assert mgr.audit.verify_integrity() is True
