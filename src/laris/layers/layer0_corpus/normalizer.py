"""Deterministic text and mathematical normalization engine for Layer 0.

Adheres to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
Provides 100% deterministic, idempotent normalization for scientific text,
Unicode artifacts, typographic ligatures, SI unit spacing, and LaTeX formulas.
"""

import re
import unicodedata
from typing import List

# Mapping of typographic ligatures to canonical ASCII equivalents
_LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Invisible control characters and zero-width format characters to purge
_INVISIBLE_CHARS_REGEX = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]"
)

# Standard SI units for scientific notation spacing
_SI_UNITS = (
    r"THz|GHz|MHz|kHz|Hz|"
    r"pm|nm|um|[µμ]m|mm|cm|dm|m|km|"
    r"fs|ps|ns|us|[µμ]s|ms|s|min|h|"
    r"meV|eV|keV|MeV|GeV|TeV|"
    r"fF|pF|nF|uF|[µμ]F|mF|F|"
    r"nV|uV|[µμ]V|mV|V|kV|MV|"
    r"nA|uA|[µμ]A|mA|A|kA|"
    r"dBm|dB|dBc|"
    r"Ohm|kOhm|MOhm|mΩ|Ω|kΩ|MΩ|"
    r"Pa|hPa|kPa|MPa|GPa|"
    r"fW|pW|nW|uW|[µμ]W|mW|W|kW|MW|GW|"
    r"mJ|J|kJ|MJ|"
    r"K|mK|"
    r"mol|mmol|umol|[µμ]mol|nmol|pmol"
)

# Regex to standardize SI unit spacing: e.g., "42GHz" -> "42 GHz"
_SI_SPACING_REGEX = re.compile(rf"\b(\d+(?:\.\d+)?)\s*({_SI_UNITS})\b")

# Regex capturing LaTeX math environments:
# 1) Display math: $$...$$ or \[...\]
# 2) Inline math: $...$ or \(...\)
_MATH_BLOCK_REGEX = re.compile(
    r"(\$\$.*?\$\$|\\\[.*?\\\]|(?<!\\)\$(?!\$).*?(?<!\\)\$|\\\(.*?\\\))",
    re.DOTALL,
)


def _normalize_non_math_segment(text: str) -> str:
    """Normalizes plain scientific prose outside of mathematical equations."""
    # 1. Unfold typographic ligatures
    for lig, replacement in _LIGATURE_MAP.items():
        text = text.replace(lig, replacement)

    # 2. Strip invisible control and zero-width format characters
    text = _INVISIBLE_CHARS_REGEX.sub("", text)

    # 3. Unicode NFKC normalization (normalizes fullwidth chars, compatibility forms)
    text = unicodedata.normalize("NFKC", text)

    # 4. Standardize quotes and typographic dashes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("—", " - ").replace("–", " - ")

    # 5. Standardize SI unit spacing
    text = _SI_SPACING_REGEX.sub(r"\1 \2", text)

    # 6. Normalize whitespace: unify spaces and collapse repeated non-newline whitespace
    text = re.sub(r"[^\S\r\n]+", " ", text)

    return text


def _normalize_math_segment(math_text: str) -> str:
    """Normalizes whitespace inside a LaTeX formula while preserving exact notation."""
    # Strip invisible formatting characters inside math
    math_text = _INVISIBLE_CHARS_REGEX.sub("", math_text)

    # Collapse non-newline whitespace sequences to single space
    math_text = re.sub(r"[^\S\r\n]+", " ", math_text)

    return math_text


def normalize_scientific_text(text: str) -> str:
    """Deterministically normalizes scientific text, Unicode symbols, and LaTeX equations.

    Guarantees:
    - 100% deterministic given identical input.
    - Idempotent: normalize(normalize(x)) == normalize(x).
    - Preserves Greek symbols (α, β, γ, etc.) and mathematical relations.
    - Standardizes SI unit spacing (e.g. 10GHz -> 10 GHz).
    - Cleans invisible control and zero-width whitespace.
    - Preserves inline and display LaTeX equations.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str input, got {type(text).__name__}")
    if not text:
        return ""

    # Split text into alternating (non-math, math) segments
    segments: List[str] = []
    last_end = 0

    for match in _MATH_BLOCK_REGEX.finditer(text):
        start, end = match.span()
        if start > last_end:
            segments.append(_normalize_non_math_segment(text[last_end:start]))
        segments.append(_normalize_math_segment(text[start:end]))
        last_end = end

    if last_end < len(text):
        segments.append(_normalize_non_math_segment(text[last_end:]))

    normalized = "".join(segments)

    # Final cleanup: collapse excessive blank lines (max 2 consecutive newlines)
    # and strip leading/trailing whitespace per paragraph
    lines = [re.sub(r"[^\S\r\n]+", " ", line).strip() for line in normalized.splitlines()]
    result = "\n".join(lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result
