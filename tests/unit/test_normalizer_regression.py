"""Regression and idempotence test suite for Layer 0 deterministic normalizer.

Addresses Issue #78 (M1-DATA-002-SUB-02, Refs #13).
Validates normalization invariance across:
- Fullwidth alphanumeric and punctuation characters
- Invisible whitespace, zero-width controls, and BOM codepoints
- Broken and consecutive typographic ligatures
- Greek symbols and relational mathematical operators
- SI unit spacing across integers, floats, and boundary punctuation
- Inline and display LaTeX equations
- Malformed inputs, non-string types, and unclosed delimiters
- Determinism and mathematical idempotence: f(f(x)) == f(x)
"""

import unittest

from laris.corpus.normalizer import normalize_scientific_text


class TestNormalizerRegression(unittest.TestCase):
    """Exhaustive regression test suite for text and math normalization invariants."""

    def test_fullwidth_alphanumeric_and_punctuation(self) -> None:
        """Fullwidth ASCII characters should be normalized to canonical halfwidth ASCII."""
        raw = "Ｔｅｓｔｉｎｇ　ｆｕｌｌｗｉｄｔｈ：　１２３．４５　ＧＨｚ！　（Ｓａｍｐｌｅ）"
        expected = "Testing fullwidth: 123.45 GHz! (Sample)"
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_all_invisible_and_format_codepoints_purged(self) -> None:
        """All zero-width, directional, and formatting codepoints must be removed."""
        invisible_chars = [
            "\u200b",  # zero-width space
            "\u200c",  # zero-width non-joiner
            "\u200d",  # zero-width joiner
            "\u200e",  # left-to-right mark
            "\u200f",  # right-to-left mark
            "\u202a",  # left-to-right embedding
            "\u202b",  # right-to-left embedding
            "\u202c",  # pop directional formatting
            "\u202d",  # left-to-right override
            "\u202e",  # right-to-left override
            "\u2060",  # word joiner
            "\u2061",  # function application
            "\u2062",  # invisible times
            "\u2063",  # invisible separator
            "\u2064",  # invisible plus
            "\ufeff",  # byte order mark / zero-width no-break space
            "\u00ad",  # soft hyphen
        ]
        base_word = "Superconductivity"
        corrupted = "".join(
            f"{char}{part}"
            for char, part in zip(invisible_chars, base_word[: len(invisible_chars)])
        )
        corrupted += base_word[len(invisible_chars) :]

        self.assertEqual(normalize_scientific_text(corrupted), base_word)

    def test_broken_and_consecutive_ligatures(self) -> None:
        """All defined typographic ligatures must unfold to standard ASCII equivalents."""
        # \ufb00=ff, \ufb01=fi, \ufb02=fl, \ufb03=ffi, \ufb04=ffl, \ufb05=st, \ufb06=st
        raw = "ﬄuﬀy eﬃcient ﬂow ﬁeld in a ﬆable ﬅructure"
        expected = "ffluffy efficient flow field in a stable structure"
        self.assertEqual(normalize_scientific_text(raw), expected)

    def test_greek_alphabet_and_math_operators_preserved(self) -> None:
        """Greek characters and mathematical relation symbols must be strictly preserved."""
        raw = (
            "Lower: α, β, γ, δ, ε, ζ, η, θ, ι, κ, λ, μ, ν, ξ, ο, π, ρ, σ, τ, υ, φ, χ, ψ, ω.\n"
            "Upper: Γ, Δ, Θ, Λ, Ξ, Π, Σ, Φ, Ψ, Ω.\n"
            "Operators: ±, ×, ·, ≤, ≥, ≠, ≈, ≡, ∝, ∞, ∂, ∇, ∈, ∉, ⊂, ⊆, ∪, ∩."
        )
        normalized = normalize_scientific_text(raw)
        self.assertEqual(normalized, raw)

    def test_si_unit_spacing_comprehensive(self) -> None:
        """SI units must have a single space after numerical values in varied syntaxes."""
        test_cases = [
            ("10GHz", "10 GHz"),
            ("100nm", "100 nm"),
            ("0.5um", "0.5 um"),
            ("2.4µs", "2.4 μs"),
            ("2.4μs", "2.4 μs"),
            ("500MPa", "500 MPa"),
            ("12dBm", "12 dBm"),
            ("50kΩ", "50 kΩ"),
            ("300K", "300 K"),
            ("4.2kJ", "4.2 kJ"),
            ("5W", "5 W"),
            ("10nW", "10 nW"),
            ("100mmol", "100 mmol"),
            ("(10GHz)", "(10 GHz)"),
            ("at 42GHz,", "at 42 GHz,"),
            ("value is 5W.", "value is 5 W."),
            ("already 10 GHz spaced", "already 10 GHz spaced"),
        ]
        for raw, expected in test_cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_scientific_text(raw), expected)

    def test_latex_inline_and_display_math_preserved(self) -> None:
        """LaTeX math formulas must preserve syntax without unwanted unit spacing."""
        raw = (
            "We define the Hamiltonian as:\n"
            "$$\\mathcal{H} = \\sum_{k} \\hbar \\omega_k "
            "\\left( a_k^\\dagger a_k + \\frac{1}{2} \\right)$$\n"
            "where $m = 9.11 \\times 10^{-31}$ kg is electron mass and "
            "$\\Delta t = 2s$ is duration."
        )
        normalized = normalize_scientific_text(raw)
        self.assertIn("$$\\mathcal{H} = \\sum_{k} \\hbar \\omega_k", normalized)
        self.assertIn("$\\Delta t = 2s$", normalized)
        self.assertIn("kg is electron mass", normalized)

    def test_escaped_dollar_in_prose_not_treated_as_math(self) -> None:
        """Escaped dollar signs must not trigger inline math blocks."""
        raw = r"The GPU hardware cost was \$1500 and saved \$3000 in cloud expenses."
        normalized = normalize_scientific_text(raw)
        self.assertIn(r"\$1500", normalized)
        self.assertIn(r"\$3000", normalized)

    def test_malformed_and_boundary_inputs(self) -> None:
        """Malformed inputs, wrong types, and empty strings must behave deterministically."""
        # Non-string types must raise TypeError
        with self.assertRaises(TypeError):
            normalize_scientific_text(None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            normalize_scientific_text(12345)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            normalize_scientific_text({"text": "sample"})  # type: ignore[arg-type]

        # Empty and whitespace-only
        self.assertEqual(normalize_scientific_text(""), "")
        self.assertEqual(normalize_scientific_text("   \n\n\t  "), "")

        # Unclosed LaTeX delimiter should not raise an exception
        unclosed = "Equation with unclosed delimiter $E = mc^2 without ending delimiter."
        normalized = normalize_scientific_text(unclosed)
        self.assertIsInstance(normalized, str)

        # Excessive blank lines collapsed to at most two
        excessive = "Paragraph 1\n\n\n\n\n\nParagraph 2"
        self.assertEqual(normalize_scientific_text(excessive), "Paragraph 1\n\nParagraph 2")

    def test_idempotence_on_synthetic_scientific_paper(self) -> None:
        """Multi-stage normalization of synthetic scientific prose must be strictly idempotent."""
        synthetic_paper = (
            "  Abstract—We investigate high-eﬃciency 1550nm photonic resonators.\n\n"
            "The measured quality factor $Q = 1.2 \\times 10^6$ at 4.2K corresponds to\n"
            "an intrinsic dissipation of 10nW.\n\n"
            "\\begin{equation}\n"
            "$$\\nabla \\times \\mathbf{B} = \\mu_0 \\mathbf{J} + "
            "\\mu_0 \\epsilon_0 \\frac{\\partial \\mathbf{E}}{\\partial t}$$\n"
            "\\end{equation}\n\n\n\n"
            "Here, $\\epsilon_0$ and $\\mu_0$ denote the vacuum permittivity and permeability,\n"
            "with angular frequency $\\omega = 2\\pi f$ operating at 28GHz.\n"
        )
        step1 = normalize_scientific_text(synthetic_paper)
        step2 = normalize_scientific_text(step1)
        step3 = normalize_scientific_text(step2)

        self.assertEqual(step1, step2)
        self.assertEqual(step2, step3)
        self.assertIn("high-efficiency", step1)
        self.assertIn("1550 nm", step1)
        self.assertIn("4.2 K", step1)
        self.assertIn("10 nW", step1)
        self.assertIn("28 GHz", step1)
        self.assertNotIn("\n\n\n", step1)


if __name__ == "__main__":
    unittest.main()
