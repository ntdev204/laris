"""Unit tests for Layer 0 corpus schemas and invariants (Issue #45)."""

import hashlib
import unittest

from laris.core.errors import DuplicateCorpusError, LicenseViolationError
from laris.corpus.schemas import (
    CorpusManifest,
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


class TestCorpusSchemas(unittest.TestCase):
    """Test suite validating typed fields, invariants, and collision detection."""

    def setUp(self) -> None:
        self.sample_text = "Quantum electrodynamics provides relativistic field equations."
        self.sample_bytes = len(self.sample_text.encode("utf-8"))
        self.sample_hash = hashlib.sha256(self.sample_text.encode("utf-8")).hexdigest()
        self.valid_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="arXiv API metadata cross-reference",
            verified_by="LARIS Ingestion Agent v1",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )

    def test_valid_corpus_item_construction(self) -> None:
        item = ValidatedCorpusItem(
            corpus_id="CORP-001",
            clean_text=self.sample_text,
            sha256=self.sample_hash,
            split=DatasetSplit.TRAIN,
            license_provenance=self.valid_provenance,
            byte_length=self.sample_bytes,
            metadata={"domain": "physics"},
        )
        self.assertEqual(item.corpus_id, "CORP-001")
        self.assertEqual(item.byte_length, self.sample_bytes)
        self.assertEqual(item.split, DatasetSplit.TRAIN)
        self.assertEqual(item.license_provenance.declared_license, LicenseType.CC_BY_4_0)

    def test_invalid_sha256_format_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ValidatedCorpusItem(
                corpus_id="CORP-002",
                clean_text=self.sample_text,
                sha256="invalid_short_hash",
                split=DatasetSplit.UNASSIGNED,
                license_provenance=self.valid_provenance,
                byte_length=self.sample_bytes,
            )

    def test_byte_length_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ValidatedCorpusItem(
                corpus_id="CORP-003",
                clean_text=self.sample_text,
                sha256=self.sample_hash,
                split=DatasetSplit.UNASSIGNED,
                license_provenance=self.valid_provenance,
                byte_length=self.sample_bytes + 10,
            )

    def test_empty_corpus_id_or_text_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ValidatedCorpusItem(
                corpus_id="",
                clean_text=self.sample_text,
                sha256=self.sample_hash,
                split=DatasetSplit.UNASSIGNED,
                license_provenance=self.valid_provenance,
                byte_length=self.sample_bytes,
            )
        with self.assertRaises(ValueError):
            ValidatedCorpusItem(
                corpus_id="CORP-004",
                clean_text="",
                sha256=self.sample_hash,
                split=DatasetSplit.UNASSIGNED,
                license_provenance=self.valid_provenance,
                byte_length=0,
            )

    def test_license_provenance_validation(self) -> None:
        # Empty verification source
        with self.assertRaises(ValueError):
            LicenseAuthorizationProvenance(
                declared_license=LicenseType.MIT,
                verification_source="",
                verified_by="Agent",
                authorized=True,
            )

        # Empty verified_by
        with self.assertRaises(ValueError):
            LicenseAuthorizationProvenance(
                declared_license=LicenseType.MIT,
                verification_source="source",
                verified_by="  ",
                authorized=True,
            )

        # Authorizing proprietary document raises LicenseViolationError
        with self.assertRaises(LicenseViolationError):
            LicenseAuthorizationProvenance(
                declared_license=LicenseType.PROPRIETARY_UNAUTHORIZED,
                verification_source="audit log",
                verified_by="Auditor",
                authorized=True,
            )

        # Authorizing non-permitted license raises LicenseViolationError
        with self.assertRaises(LicenseViolationError):
            LicenseAuthorizationProvenance(
                declared_license=LicenseType.UNKNOWN,
                verification_source="audit log",
                verified_by="Auditor",
                authorized=True,
            )

        # Non-authorized item record is permitted for audit
        unauth = LicenseAuthorizationProvenance(
            declared_license=LicenseType.PROPRIETARY_UNAUTHORIZED,
            verification_source="audit log",
            verified_by="Auditor",
            authorized=False,
            notes="Flagged during initial scrape",
        )
        self.assertFalse(unauth.authorized)

    def test_corpus_manifest_aggregates_and_deduplication(self) -> None:
        item1 = ValidatedCorpusItem(
            corpus_id="CORP-001",
            clean_text=self.sample_text,
            sha256=self.sample_hash,
            split=DatasetSplit.TRAIN,
            license_provenance=self.valid_provenance,
            byte_length=self.sample_bytes,
        )

        text2 = "Second unique scientific paper on condensed matter physics."
        hash2 = hashlib.sha256(text2.encode("utf-8")).hexdigest()
        item2 = ValidatedCorpusItem(
            corpus_id="CORP-002",
            clean_text=text2,
            sha256=hash2,
            split=DatasetSplit.VAL,
            license_provenance=self.valid_provenance,
            byte_length=len(text2.encode("utf-8")),
        )

        manifest = CorpusManifest(
            manifest_id="MAN-001",
            created_at="2026-10-16T00:00:00Z",
            items=[item1],
        )
        self.assertEqual(manifest.total_items, 1)
        self.assertEqual(manifest.total_bytes, self.sample_bytes)

        manifest.add_item(item2)
        self.assertEqual(manifest.total_items, 2)
        self.assertEqual(manifest.split_counts["TRAIN"], 1)
        self.assertEqual(manifest.split_counts["VAL"], 1)
        self.assertEqual(manifest.split_counts["TEST"], 0)
        self.assertEqual(manifest.license_distribution["CC-BY-4.0"], 2)

        # Attempt duplicate corpus_id
        duplicate_id_item = ValidatedCorpusItem(
            corpus_id="CORP-001",
            clean_text="Different text with duplicate ID",
            sha256=hashlib.sha256(b"Different text with duplicate ID").hexdigest(),
            split=DatasetSplit.TEST,
            license_provenance=self.valid_provenance,
            byte_length=len(b"Different text with duplicate ID"),
        )
        with self.assertRaises(DuplicateCorpusError):
            manifest.add_item(duplicate_id_item)

        # Attempt duplicate sha256
        duplicate_hash_item = ValidatedCorpusItem(
            corpus_id="CORP-003",
            clean_text=self.sample_text,
            sha256=self.sample_hash,
            split=DatasetSplit.TEST,
            license_provenance=self.valid_provenance,
            byte_length=self.sample_bytes,
        )
        with self.assertRaises(DuplicateCorpusError):
            manifest.add_item(duplicate_hash_item)


if __name__ == "__main__":
    unittest.main()
