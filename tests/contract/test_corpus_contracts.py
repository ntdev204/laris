"""Contract verification tests for Layer 0 corpus schemas and manifest invariants (Issue #77)."""

import hashlib
import unittest

from laris.core.errors import (
    ModuleContractViolationError,
)
from laris.corpus import (
    CorpusManifest,
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
    validate_manifest_consistency,
    verify_item_authorization,
    verify_item_content_hash,
)


class TestCorpusManifestContracts(unittest.TestCase):
    """Verifies manifest invariants, authorization provenance, and digest verification."""

    def setUp(self) -> None:
        self.raw_text_1 = "First paper content verifying Einstein field equations."
        self.raw_bytes_1 = self.raw_text_1.encode("utf-8")
        self.valid_hash_1 = hashlib.sha256(self.raw_bytes_1).hexdigest()

        self.valid_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="arXiv API cross-check",
            verified_by="LARIS Compliance Checker",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )

        self.item_1 = ValidatedCorpusItem(
            corpus_id="DOC-CORPUS-001",
            clean_text=self.raw_text_1,
            sha256=self.valid_hash_1,
            split=DatasetSplit.TRAIN,
            license_provenance=self.valid_provenance,
            byte_length=len(self.raw_bytes_1),
        )

    def test_checksum_presence_vs_byte_verification(self) -> None:
        """A valid hex string in sha256 is NOT proof that arbitrary bytes match the content."""
        # Genuine match
        self.assertTrue(verify_item_content_hash(self.item_1, self.raw_bytes_1))

        # Tampered / mismatched bytes with identical item
        tampered_bytes = b"Tampered malicious content"
        self.assertFalse(verify_item_content_hash(self.item_1, tampered_bytes))

    def test_license_identifier_vs_permission_authorization(self) -> None:
        """Declaring a license string does not constitute affirmative permission."""
        # Audit item: declared CC-BY-4.0 but unauthorized/pending verification
        pending_item = ValidatedCorpusItem(
            corpus_id="DOC-CORPUS-PENDING",
            clean_text="Text awaiting license check.",
            sha256=hashlib.sha256(b"Text awaiting license check.").hexdigest(),
            split=DatasetSplit.UNASSIGNED,
            license_provenance=LicenseAuthorizationProvenance(
                declared_license=LicenseType.CC_BY_4_0,
                verification_source="scrape header",
                verified_by="Crawler",
                authorized=False,
                notes="Pending affirmative authorization",
            ),
            byte_length=len(b"Text awaiting license check."),
        )
        self.assertFalse(verify_item_authorization(pending_item))
        self.assertTrue(verify_item_authorization(self.item_1))

    def test_unsplit_and_unassigned_split_isolation(self) -> None:
        """UNASSIGNED split items are explicitly recorded and tracked in manifest."""
        unsplit_item = ValidatedCorpusItem(
            corpus_id="DOC-CORPUS-UNSPLIT",
            clean_text="Unsplit exploratory text.",
            sha256=hashlib.sha256(b"Unsplit exploratory text.").hexdigest(),
            split=DatasetSplit.UNASSIGNED,
            license_provenance=self.valid_provenance,
            byte_length=len(b"Unsplit exploratory text."),
        )
        manifest = CorpusManifest(
            manifest_id="MAN-UNSPLIT-001",
            created_at="2026-10-16T00:00:00Z",
            items=[unsplit_item],
        )
        self.assertEqual(manifest.split_counts["UNASSIGNED"], 1)
        self.assertEqual(manifest.split_counts["TRAIN"], 0)

    def test_manifest_consistency_verification(self) -> None:
        """Inconsistent manifest aggregate expectations raise ModuleContractViolationError."""
        manifest = CorpusManifest(
            manifest_id="MAN-CONSISTENCY-001",
            created_at="2026-10-16T00:00:00Z",
            items=[self.item_1],
        )

        # Valid assertions pass
        validate_manifest_consistency(
            manifest,
            expected_total_items=1,
            expected_total_bytes=len(self.raw_bytes_1),
            expected_split_counts={"TRAIN": 1, "VAL": 0, "TEST": 0},
        )

        # Mismatched items count
        with self.assertRaises(ModuleContractViolationError):
            validate_manifest_consistency(manifest, expected_total_items=5)

        # Mismatched bytes count
        with self.assertRaises(ModuleContractViolationError):
            validate_manifest_consistency(manifest, expected_total_bytes=99999)

        # Mismatched split counts
        with self.assertRaises(ModuleContractViolationError):
            validate_manifest_consistency(
                manifest, expected_split_counts={"TRAIN": 0, "VAL": 1}
            )

    def test_checksum_is_not_licensing_authorization(self) -> None:
        """A cryptographically valid checksum provides zero guarantee of legal redistribution."""
        # A proprietary document can have a perfectly valid SHA-256 digest
        proprietary_text = b"Classified commercial dataset"
        item_unauth = ValidatedCorpusItem(
            corpus_id="DOC-PROPRIETARY",
            clean_text="Classified commercial dataset",
            sha256=hashlib.sha256(proprietary_text).hexdigest(),
            split=DatasetSplit.UNASSIGNED,
            license_provenance=LicenseAuthorizationProvenance(
                declared_license=LicenseType.PROPRIETARY_UNAUTHORIZED,
                verification_source="License audit",
                verified_by="Legal Agent",
                authorized=False,
            ),
            byte_length=len(proprietary_text),
        )
        # Checksum is verified
        self.assertTrue(verify_item_content_hash(item_unauth, proprietary_text))
        # But authorization MUST be false
        self.assertFalse(verify_item_authorization(item_unauth))


if __name__ == "__main__":
    unittest.main()
