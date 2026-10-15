"""Unit tests for Layer 0 near-duplicate detection policy and DeduplicationEngine.

Addresses Issue #79 (M1-DATA-003-SUB-02, Refs #14).
Validates:
- Configurable DeduplicationPolicy validation
- Deterministic word shingle generation and Jaccard similarity computation
- Detection of preprint vs. camera-ready academic paper revisions
- Retention of distinct scientific articles
- Configurable threshold boundary adherence
- Deterministic, stable ordering of batch duplicate outputs
"""

import unittest

from laris.layers.layer0_corpus.dedup import (
    DeduplicationEngine,
    DeduplicationPolicy,
    compute_jaccard_similarity,
    generate_word_shingles,
)
from laris.layers.layer0_corpus.schemas import (
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


class TestNearDuplicatePolicyAndShingling(unittest.TestCase):
    """Test suite for DeduplicationPolicy and shingle generation."""

    def test_default_policy_validation(self) -> None:
        """Default policy must specify sound thresholds."""
        policy = DeduplicationPolicy()
        self.assertTrue(policy.exact_deduplication)
        self.assertTrue(policy.near_deduplication)
        self.assertEqual(policy.near_duplicate_threshold, 0.85)
        self.assertEqual(policy.shingle_k, 3)

    def test_invalid_policy_thresholds(self) -> None:
        """Policy must reject non-positive, > 1.0, or zero thresholds."""
        with self.assertRaises(ValueError):
            DeduplicationPolicy(near_duplicate_threshold=0.0)
        with self.assertRaises(ValueError):
            DeduplicationPolicy(near_duplicate_threshold=-0.1)
        with self.assertRaises(ValueError):
            DeduplicationPolicy(near_duplicate_threshold=1.05)
        with self.assertRaises(ValueError):
            DeduplicationPolicy(shingle_k=0)

    def test_generate_word_shingles(self) -> None:
        """Word shingles must form contiguous k-word windows."""
        text = "Quantum computing with surface codes at cryogenic temperatures"
        shingles = generate_word_shingles(text, k=3)
        expected = {
            "Quantum computing with",
            "computing with surface",
            "with surface codes",
            "surface codes at",
            "codes at cryogenic",
            "at cryogenic temperatures",
        }
        self.assertEqual(shingles, expected)

    def test_generate_shingles_short_and_empty_inputs(self) -> None:
        """Short or empty texts must be handled gracefully."""
        self.assertEqual(generate_word_shingles("", k=3), set())
        self.assertEqual(generate_word_shingles("   \n\t ", k=3), set())
        self.assertEqual(generate_word_shingles("One two", k=3), {"One two"})

        with self.assertRaises(TypeError):
            generate_word_shingles(None, k=3)  # type: ignore[arg-type]

    def test_compute_jaccard_similarity(self) -> None:
        """Jaccard similarity must evaluate set intersection over union."""
        set_a = {"alpha", "beta", "gamma"}
        set_b = {"beta", "gamma", "delta"}

        # 2 in intersection, 4 in union -> 2/4 = 0.5
        self.assertAlmostEqual(compute_jaccard_similarity(set_a, set_b), 0.5)

        # Identical sets
        self.assertEqual(compute_jaccard_similarity(set_a, set_a), 1.0)
        # Disjoint sets
        self.assertEqual(compute_jaccard_similarity(set_a, {"zeta", "eta"}), 0.0)
        # Both empty sets
        self.assertEqual(compute_jaccard_similarity(set(), set()), 1.0)
        # One empty set
        self.assertEqual(compute_jaccard_similarity(set_a, set()), 0.0)


class TestDeduplicationEngine(unittest.TestCase):
    """Test suite for integrated DeduplicationEngine."""

    def setUp(self) -> None:
        self.policy = DeduplicationPolicy(
            exact_deduplication=True,
            near_deduplication=True,
            near_duplicate_threshold=0.85,
            shingle_k=3,
        )
        self.engine = DeduplicationEngine(policy=self.policy)
        self.sample_provenance = LicenseAuthorizationProvenance(
            declared_license=LicenseType.CC_BY_4_0,
            verification_source="https://arxiv.org/abs/2401.00001",
            verified_by="test-agent",
            authorized=True,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )
        self.synthetic_paper_body = (
            "We investigate deterministic mathematical and text normalization "
            "for scientific NLP pipelines. "
            "Typographic ligatures such as fi, fl, and ffi are unfolded "
            "into canonical ASCII representations. "
            "Zero-width and invisible control codepoints are purged completely "
            "from document trees. "
            "LaTeX math expressions enclosed in inline and display delimiters "
            "are strictly preserved. "
            "We evaluate the proposed pipeline on 500 scientific documents "
            "across physics and computer science. "
            "Our empirical results demonstrate zero semantic drift across "
            "all benchmark evaluations. "
            "Furthermore, we analyze computational memory overhead on "
            "constrained local workstation hardware."
        )

    def test_preprint_vs_camera_ready_near_duplicate(self) -> None:
        """Preprint and camera-ready papers sharing core body must be detected as near-duplicate."""
        preprint = f"arXiv:2401.00001v1 [cs.AI] 1 Jan 2026. {self.synthetic_paper_body}"
        camera_ready = (
            f"{self.synthetic_paper_body} "
            "Acknowledgments: Supported by NSF grant 12345."
        )

        _, is_unique1, dup1 = self.engine.process_item("doc-preprint", preprint)
        self.assertTrue(is_unique1)
        self.assertIsNone(dup1)

        _, is_unique2, dup2 = self.engine.process_item("doc-camera-ready", camera_ready)
        self.assertFalse(is_unique2)
        self.assertIsNotNone(dup2)
        assert dup2 is not None  # type narrowing
        self.assertEqual(dup2.duplicate_corpus_id, "doc-camera-ready")
        self.assertEqual(dup2.canonical_corpus_id, "doc-preprint")
        self.assertEqual(dup2.match_type, "NEAR_DUPLICATE")
        self.assertGreaterEqual(dup2.similarity_score, 0.85)
        self.assertIn("Near-duplicate detected", dup2.rationale)

    def test_distinct_scientific_papers_retained(self) -> None:
        """Distinct scientific articles must both be retained as unique."""
        paper_quantum = (
            "Superconducting transmon qubits operate in cryogenic dilution refrigerators. "
            "We measure microwave resonator reflection spectra and observe cavity shifts "
            "governed by the Jaynes-Cummings Hamiltonian with coupling g / 2pi = 50 MHz."
        )
        paper_biology = (
            "Cryo-electron microscopy structures of ribosomal subunits reveal conformational "
            "dynamics during translation elongation. Ribosome complexes were purified "
            "and imaged at 2.4 Angstrom resolution with single-particle algorithms."
        )

        _, is_unique1, dup1 = self.engine.process_item("doc-quantum", paper_quantum)
        _, is_unique2, dup2 = self.engine.process_item("doc-biology", paper_biology)

        self.assertTrue(is_unique1)
        self.assertIsNone(dup1)
        self.assertTrue(is_unique2)
        self.assertIsNone(dup2)
        self.assertEqual(len(self.engine), 2)

    def test_threshold_boundary_behavior(self) -> None:
        """Near-duplicate classification must strictly adhere to configured threshold."""
        base_text = "WordA WordB WordC WordD WordE WordF WordG WordH WordI WordJ"
        # 9 out of 10 words identical (approx 81.8% similarity with k=1)
        modified_text = "WordA WordB WordC WordD WordE WordF WordG WordH WordI WordX"

        # Engine with strict threshold 0.90 -> should consider modified_text UNIQUE
        strict_engine = DeduplicationEngine(
            policy=DeduplicationPolicy(near_duplicate_threshold=0.90, shingle_k=1)
        )
        strict_engine.process_item("doc-base", base_text)
        _, is_unique_strict, _ = strict_engine.process_item("doc-mod", modified_text)
        self.assertTrue(is_unique_strict)

        # Engine with lenient threshold 0.75 -> should consider modified_text NEAR_DUPLICATE
        lenient_engine = DeduplicationEngine(
            policy=DeduplicationPolicy(near_duplicate_threshold=0.75, shingle_k=1)
        )
        lenient_engine.process_item("doc-base", base_text)
        _, is_unique_lenient, dup_lenient = lenient_engine.process_item("doc-mod", modified_text)
        self.assertFalse(is_unique_lenient)
        self.assertIsNotNone(dup_lenient)

    def test_batch_deduplication_stable_output_ordering(self) -> None:
        """Batch deduplication must maintain deterministic stable ordering for duplicates."""
        text_orig = self.synthetic_paper_body
        text_dup1 = text_orig + " Minor revision note added to the manuscript."
        text_dup2 = text_orig

        item_orig = ValidatedCorpusItem(
            corpus_id="doc-001",
            clean_text=text_orig,
            sha256="1" * 64,
            split=DatasetSplit.TRAIN,
            license_provenance=self.sample_provenance,
            byte_length=len(text_orig.encode("utf-8")),
        )
        item_dup1 = ValidatedCorpusItem(
            corpus_id="doc-002",
            clean_text=text_dup1,
            sha256="2" * 64,
            split=DatasetSplit.VAL,
            license_provenance=self.sample_provenance,
            byte_length=len(text_dup1.encode("utf-8")),
        )
        item_dup2 = ValidatedCorpusItem(
            corpus_id="doc-003",
            clean_text=text_dup2,
            sha256="3" * 64,
            split=DatasetSplit.TEST,
            license_provenance=self.sample_provenance,
            byte_length=len(text_dup2.encode("utf-8")),
        )

        uniques, duplicates = self.engine.deduplicate_batch([item_orig, item_dup1, item_dup2])

        self.assertEqual(len(uniques), 1)
        self.assertEqual(uniques[0].corpus_id, "doc-001")
        self.assertEqual(len(duplicates), 2)

        # Output ordering must have highest similarity first (EXACT 1.0 > NEAR ~0.95)
        self.assertEqual(duplicates[0].duplicate_corpus_id, "doc-003")
        self.assertEqual(duplicates[0].match_type, "EXACT")
        self.assertEqual(duplicates[1].duplicate_corpus_id, "doc-002")
        self.assertEqual(duplicates[1].match_type, "NEAR_DUPLICATE")

    def test_clear_resets_indexes(self) -> None:
        """clear() must purge both exact and near-duplicate indexes."""
        self.engine.process_item("doc-001", "Text on quantum physics.")
        self.assertEqual(len(self.engine), 1)
        self.engine.clear()
        self.assertEqual(len(self.engine), 0)


if __name__ == "__main__":
    unittest.main()
