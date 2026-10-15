"""Contract verification tests for LARIS module boundaries."""

import unittest
from laris.core.schemas import EpistemicStatus, ScientificClaim, EvidenceCoordinate


class TestModuleContracts(unittest.TestCase):
    """Verifies that inter-module payloads adhere to contract invariants."""

    def test_epistemic_provenance_contract(self):
        coord = EvidenceCoordinate(
            coordinate_id="COORD-100",
            document_id="DOC-TEST-001",
            document_sha256="b" * 64,
            page_number=2,
            section_identifier="sec-results",
            paragraph_index=1,
            sentence_index=3,
            char_start=120,
            char_end=240,
            verbatim_snippet="The measured cut-off frequency was 42 GHz.",
        )
        claim = ScientificClaim(
            claim_id="CLAIM-100",
            canonical_text="Cut-off frequency reaches 42 GHz.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
            evidence_coordinates=[coord.coordinate_id],
            confidence_score=0.99,
        )
        self.assertIn(coord.coordinate_id, claim.evidence_coordinates)
        self.assertEqual(claim.epistemic_status, EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING)


if __name__ == "__main__":
    unittest.main()
