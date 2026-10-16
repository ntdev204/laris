"""Unit tests for Layer 0 canonical content digest and exact deduplication.

Addresses Issue #47 (M1-DATA-003-SUB-01, Refs #14).
Validates:
- SHA-256 computation over normalized UTF-8 text
- Explicit encoding, algorithm, and version contracts
- Empty, whitespace, Unicode, and ligature input vectors
- Cryptographic digest verification
- Exact deduplication registry, collision detection, and batch partitioning
"""

import hashlib
import unittest

from laris.core.errors import DuplicateCorpusError
from laris.corpus.dedup import (
    DIGEST_ALGORITHM,
    DIGEST_ENCODING,
    DIGEST_SPEC_VERSION,
    DuplicateRecord,
    ExactDeduplicator,
    compute_canonical_content_digest,
    verify_content_digest,
)
from laris.corpus.schemas import (
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


class TestCanonicalContentDigest(unittest.TestCase):
    """Test suite for SHA-256 canonical digest computation and verification."""

    def test_digest_metadata_constants(self) -> None:
        """Explicit algorithm and encoding contracts must be defined and immutable."""
        self.assertEqual(DIGEST_ALGORITHM, "SHA-256")
        self.assertEqual(DIGEST_ENCODING, "utf-8")
        self.assertEqual(DIGEST_SPEC_VERSION, "1.0")

    def test_empty_string_digest(self) -> None:
        """Empty string digest must match NIST SHA-256 test vector."""
        expected_empty_sha256 = (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        self.assertEqual(
            compute_canonical_content_digest("", normalize=False),
            expected_empty_sha256,
        )
        self.assertEqual(
            compute_canonical_content_digest("", normalize=True),
            expected_empty_sha256,
        )

    def test_non_string_input_raises_type_error(self) -> None:
        """Non-string inputs must be rejected with TypeError."""
        for invalid_input in (None, 12345, b"raw bytes", ["list"], {"key": "val"}):
            with self.subTest(invalid_input=invalid_input):
                with self.assertRaises(TypeError):
                    compute_canonical_content_digest(invalid_input)  # type: ignore[arg-type]

    def test_unicode_and_scientific_text_digest(self) -> None:
        """Multi-byte Unicode, Greek symbols, and formulas must produce deterministic hashes."""
        text = (
            "Superconducting qubit Hamiltonian: "
            "$\\mathcal{H} = \\hbar \\omega (a^\\dagger a + 1/2)$ at 15mK."
        )
        digest1 = compute_canonical_content_digest(text)
        digest2 = compute_canonical_content_digest(text)

        self.assertEqual(digest1, digest2)
        self.assertEqual(len(digest1), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest1))

    def test_normalization_invariance(self) -> None:
        """Text with ligatures, SI spacing, or fullwidth produces identical normalized digest."""
        variant_a = "The ﬁeld ﬂow eﬀect measured at 42GHz."
        variant_b = "The field flow effect measured at 42 GHz."

        # When normalized, both resolve to identical canonical text and identical digest
        digest_a = compute_canonical_content_digest(variant_a, normalize=True)
        digest_b = compute_canonical_content_digest(variant_b, normalize=True)
        self.assertEqual(digest_a, digest_b)

        # Without normalization, raw character differences yield distinct hashes
        raw_digest_a = compute_canonical_content_digest(variant_a, normalize=False)
        raw_digest_b = compute_canonical_content_digest(variant_b, normalize=False)
        self.assertNotEqual(raw_digest_a, raw_digest_b)

    def test_verify_content_digest(self) -> None:
        """Cryptographic digest verification must support case-insensitivity
        and reject mismatches.
        """
        text = "Verified scientific assertion regarding quantum coherence."
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Exact match (unnormalized)
        self.assertTrue(verify_content_digest(text, expected, normalize=False))
        # Case-insensitive hex matching
        self.assertTrue(verify_content_digest(text, expected.upper(), normalize=False))
        # Tampered text
        self.assertFalse(verify_content_digest(text + " tampered", expected, normalize=False))
        # Malformed hash length or type
        self.assertFalse(verify_content_digest(text, "short_hash", normalize=False))
        self.assertFalse(verify_content_digest(text, 12345, normalize=False))  # type: ignore[arg-type]


class TestExactDeduplicator(unittest.TestCase):
    """Test suite for ExactDeduplicator registry, collision handling, and batch operations."""

    def setUp(self) -> None:
        self.dedup = ExactDeduplicator()
        self.sample_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2401.00001",
            verified_by="test-agent",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )

    def test_initial_state(self) -> None:
        """New deduplicator instance must be empty."""
        self.assertEqual(len(self.dedup), 0)
        dummy_hash = "a" * 64
        self.assertFalse(self.dedup.is_duplicate(dummy_hash))
        self.assertIsNone(self.dedup.get_canonical_id(dummy_hash))

    def test_empty_corpus_id_raises_value_error(self) -> None:
        """Registering with an empty corpus_id must be rejected."""
        with self.assertRaises(ValueError):
            self.dedup.register("", "Sample content")

    def test_register_unique_and_duplicate_items(self) -> None:
        """First occurrence is accepted as canonical; subsequent duplicate is detected."""
        text1 = "Quantum error correction thresholds in surface codes."
        digest1, is_unique1, dup1 = self.dedup.register("doc-001", text1)

        self.assertTrue(is_unique1)
        self.assertIsNone(dup1)
        self.assertEqual(len(self.dedup), 1)
        self.assertTrue(self.dedup.is_duplicate(digest1))
        self.assertEqual(self.dedup.get_canonical_id(digest1), "doc-001")

        # Re-registering identical text with a different corpus ID
        digest2, is_unique2, dup2 = self.dedup.register("doc-002", text1)
        self.assertEqual(digest1, digest2)
        self.assertFalse(is_unique2)
        self.assertIsNotNone(dup2)
        self.assertIsInstance(dup2, DuplicateRecord)
        assert dup2 is not None  # type narrowing
        self.assertEqual(dup2.duplicate_corpus_id, "doc-002")
        self.assertEqual(dup2.canonical_corpus_id, "doc-001")
        self.assertEqual(dup2.similarity_score, 1.0)
        self.assertEqual(dup2.match_type, "EXACT")
        self.assertIn("Exact SHA-256 content collision", dup2.rationale)
        self.assertEqual(len(self.dedup), 1)

    def test_register_or_raise(self) -> None:
        """register_or_raise returns digest for unique items and raises
        DuplicateCorpusError on collision.
        """
        text = "Topological phases of matter and Majorana zero modes."
        digest = self.dedup.register_or_raise("doc-001", text)
        self.assertEqual(len(digest), 64)

        with self.assertRaises(DuplicateCorpusError) as ctx:
            self.dedup.register_or_raise("doc-002", text)
        self.assertIn("Duplicate corpus item 'doc-002'", str(ctx.exception))
        self.assertIn("doc-001", str(ctx.exception))

    def test_deduplicate_batch(self) -> None:
        """Batch deduplication must separate unique items from duplicate records
        deterministically.
        """
        text_a = "Article A on cryogenic low-noise amplifiers."
        text_b = "Article B on parametric frequency conversion."
        text_c = text_a  # Exact duplicate of A

        hash_a = hashlib.sha256(text_a.encode("utf-8")).hexdigest()
        hash_b = hashlib.sha256(text_b.encode("utf-8")).hexdigest()
        hash_c = hash_a

        item_a = ValidatedCorpusItem(
            corpus_id="doc-A",
            clean_text=text_a,
            sha256=hash_a,
            split=DatasetSplit.TRAIN,
            license_provenance=self.sample_provenance,
            byte_length=len(text_a.encode("utf-8")),
        )
        item_b = ValidatedCorpusItem(
            corpus_id="doc-B",
            clean_text=text_b,
            sha256=hash_b,
            split=DatasetSplit.VAL,
            license_provenance=self.sample_provenance,
            byte_length=len(text_b.encode("utf-8")),
        )
        item_c = ValidatedCorpusItem(
            corpus_id="doc-C",
            clean_text=text_c,
            sha256=hash_c,
            split=DatasetSplit.TEST,
            license_provenance=self.sample_provenance,
            byte_length=len(text_c.encode("utf-8")),
        )

        uniques, duplicates = self.dedup.deduplicate_batch([item_a, item_b, item_c])

        self.assertEqual(len(uniques), 2)
        self.assertEqual([u.corpus_id for u in uniques], ["doc-A", "doc-B"])
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].duplicate_corpus_id, "doc-C")
        self.assertEqual(duplicates[0].canonical_corpus_id, "doc-A")
        self.assertEqual(duplicates[0].similarity_score, 1.0)
        self.assertEqual(duplicates[0].match_type, "EXACT")

    def test_clear_resets_index(self) -> None:
        """clear() must purge all indexed content hashes."""
        self.dedup.register("doc-001", "Sample text")
        self.assertEqual(len(self.dedup), 1)
        self.dedup.clear()
        self.assertEqual(len(self.dedup), 0)


if __name__ == "__main__":
    unittest.main()
