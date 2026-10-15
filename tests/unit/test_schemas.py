"""Unit tests for LARIS core data schemas and epistemic invariants."""

import unittest
from laris.core.schemas import (
    EpistemicStatus,
    EvidenceCoordinate,
    ScientificClaim,
    ResearchGapClass,
    CalibratedScores,
    ValidationPlan,
    ResearchGap,
    TelemetrySnapshot,
)


class TestLarisCoreSchemas(unittest.TestCase):
    """Verifies that core data schemas enforce required invariants."""

    def test_evidence_coordinate_valid(self):
        coord = EvidenceCoordinate(
            coordinate_id="COORD-001",
            document_id="DOC-ARXIV-001",
            document_sha256="a" * 64,
            page_number=1,
            section_identifier="sec-1",
            paragraph_index=0,
            sentence_index=0,
            char_start=0,
            char_end=50,
            verbatim_snippet="Sample sentence.",
            extraction_confidence=0.95,
        )
        self.assertEqual(coord.coordinate_id, "COORD-001")
        self.assertEqual(coord.page_number, 1)

    def test_evidence_coordinate_invalid_page(self):
        with self.assertRaises(ValueError):
            EvidenceCoordinate(
                coordinate_id="COORD-002",
                document_id="DOC-ARXIV-001",
                document_sha256="a" * 64,
                page_number=0,  # Invalid: page < 1
                section_identifier="sec-1",
                paragraph_index=0,
                sentence_index=0,
                char_start=0,
                char_end=50,
                verbatim_snippet="Sample sentence.",
            )

    def test_scientific_claim_requires_evidence(self):
        # Claim without evidence coordinate must fail invariant
        with self.assertRaises(ValueError):
            ScientificClaim(
                claim_id="CLAIM-001",
                canonical_text="An unanchored assertion.",
                epistemic_status=EpistemicStatus.DIRECT_AUTHOR_CLAIM,
                evidence_coordinates=[],  # Empty coordinates violates invariant
            )

    def test_calibrated_composite_score(self):
        scores = CalibratedScores(
            novelty=0.8,
            grounding=0.9,
            feasibility=0.7,
            significance=0.85,
            uncertainty=0.2,
        )
        # composite_score calculation:
        # 0.25*0.8 + 0.25*0.9 + 0.20*0.7 + 0.20*0.85 + 0.10*(1.0-0.2)
        # = 0.20 + 0.225 + 0.14 + 0.17 + 0.08 = 0.815
        self.assertAlmostEqual(scores.composite_score, 0.815, places=3)

    def test_telemetry_snapshot_vram_gb(self):
        snap = TelemetrySnapshot(
            timestamp_iso="2026-10-15T22:00:00Z",
            vram_allocated_bytes=4 * (1024 ** 3),
            vram_reserved_bytes=6 * (1024 ** 3),
            host_ram_used_bytes=16 * (1024 ** 3),
            active_specialist_id="SPEC-NLI-001",
            active_param_count=120_000_000,
        )
        self.assertAlmostEqual(snap.vram_allocated_gb, 4.0, places=2)


if __name__ == "__main__":
    unittest.main()
