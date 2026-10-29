"""Unit tests for Layer 0 deterministic text and math normalizer (Issue #46)."""

import unittest

from laris.corpus import normalize_scientific_text


class TestScientificNormalizer(unittest.TestCase):
    """Test suite for deterministic text, Unicode, ligature, SI unit, and LaTeX normalization."""

    def test_empty_and_whitespace_only(self) -> None:
        self.assertEqual(normalize_scientific_text(""), "")
        self.assertEqual(normalize_scientific_text("   \n\t  \n "), "")

    def test_unicode_fullwidth_normalization(self) -> None:
        raw = "Ｔｈｅ ｍｅａｓｕｒｅｄ ｖａｌｕｅ ｉｓ ｈｉｇｈ."
        expected = "The measured value is high."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_invisible_characters_purged(self) -> None:
        # \u200b (zero-width space), \ufeff (BOM), \u200c (ZWNJ)
        raw = "Super\u200bconduc\ufeffting \u200cqbits"
        expected = "Superconducting qbits"
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_typographic_ligatures_unfolded(self) -> None:
        raw = "The ﬁeld ﬂow eﬀect in ﬃ and ﬄ devices."
        expected = "The field flow effect in ffi and ffl devices."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_greek_and_math_symbols_preserved(self) -> None:
        raw = "Parameters: α = 0.05, β ± 0.01, γ ≥ 10.5, and ΔE ≈ 4.2 eV."
        expected = "Parameters: α = 0.05, β ± 0.01, γ ≥ 10.5, and ΔE ≈ 4.2 eV."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_si_unit_spacing_standardization(self) -> None:
        raw = "Operating at 42GHz with 100nm gate length and 5.2ms latency at 300K."
        expected = "Operating at 42 GHz with 100 nm gate length and 5.2 ms latency at 300 K."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_latex_inline_math_preserved(self) -> None:
        raw = "The Hamiltonian is given by $H = \\hbar \\omega (a^\\dagger a + \\frac{1}{2})$."
        expected = "The Hamiltonian is given by $H = \\hbar \\omega (a^\\dagger a + \\frac{1}{2})$."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_latex_display_math_preserved(self) -> None:
        raw = (
            "The integral is defined as:\n"
            "$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}$$\n"
            "which converges."
        )
        expected = (
            "The integral is defined as:\n"
            "$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}$$\n"
            "which converges."
        )
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_latex_bracket_delimiters_preserved(self) -> None:
        raw = r"Using \(E = mc^2\) and \[F = ma\] relations."
        expected = r"Using \(E = mc^2\) and \[F = ma\] relations."
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_mixed_prose_and_math_idempotence(self) -> None:
        raw = (
            "In this work, we study ﬁber-optic sensors at 1550nm wavelength.\n\n"
            "The electric ﬁeld follows $\\mathbf{E}(\\mathbf{r}, t) = "
            "\\mathbf{E}_0 \\cos(\\mathbf{k}\\cdot\\mathbf{r} - \\omega t)$.\n\n"
            "We observe a shift of 2.5GHz at 77K."
        )
        norm1 = normalize_scientific_text(raw)
        norm2 = normalize_scientific_text(norm1)
        norm3 = normalize_scientific_text(norm2)

        self.assertEqual(norm1, norm2)
        self.assertEqual(norm2, norm3)
        self.assertIn("fiber-optic", norm1)
        self.assertIn("1550 nm", norm1)
        self.assertIn("2.5 GHz", norm1)
        self.assertIn("77 K", norm1)
        self.assertIn("$\\mathbf{E}(\\mathbf{r}, t)", norm1)


if __name__ == "__main__":
    unittest.main()
