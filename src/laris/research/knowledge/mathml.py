"""Presentation MathML as linear text, and simple formulas read strictly as solver input (T277).

`linear(node)` writes any MathML element as one line of plain text (`v_0`, `x^{2}`, `(a)/(b)`,
`sqrt(x)`, `∫_{a}^{b}`); it is what a Source's text holds where the book has a formula, so a
quote of a formula is a quote of that line.

`solver_form(node)` reads only a small, closed subset (identifiers, numbers, `+ - * / =`, powers,
fractions, roots, subscripts, the solver's functions) and returns an equation in the solver's
syntax (`laris.model.solver.expr`), or `None` for anything else: a vector, an integral, a sum, an
inequality, an ellipsis. It never guesses; a formula it cannot read stays text.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

MATHML = "{http://www.w3.org/1998/Math/MathML}"

# accents written over a base, as the linear text names them
_ACCENTS = {
    "→": "vec",
    "⇀": "vec",
    "^": "hat",
    "ˆ": "hat",
    "¯": "bar",
    "―": "bar",
    "‾": "bar",
    "˙": "dot",
    "¨": "ddot",
    "~": "tilde",
    "˜": "tilde",
}
_SKIP = {
    "annotation",
    "annotation-xml",
    "mprescripts",
    "none",
    "mphantom",
    "maligngroup",
    "malignmark",
    "mspace",
}

# Greek letters the solver can read as names
_GREEK = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma_",
    "δ": "delta",
    "ε": "epsilon",
    "ϵ": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda_",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "ϕ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "Γ": "Gamma",
    "Δ": "Delta",
    "Θ": "Theta",
    "Λ": "Lambda",
    "Σ": "Sigma",
    "Φ": "Phi",
    "Ψ": "Psi",
    "Ω": "Omega",
    "π": "pi",
}
_FUNCTIONS = {
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "sinh",
    "cosh",
    "tanh",
    "exp",
    "ln",
    "log",
    "sqrt",
    "abs",
}
_OPERATORS = {
    "+": "+",
    "−": "-",
    "-": "-",
    "=": "=",
    "·": "*",
    "⋅": "*",
    "×": "*",
    "*": "*",
    "/": "/",
    "(": "(",
    ")": ")",
    "⁢": "*",
    "⁡": "",
}
_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,23}\Z")


def _tag(node: ET.Element) -> str:
    return node.tag.replace(MATHML, "") if isinstance(node.tag, str) else ""


def _text(node: ET.Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _group(text: str) -> str:
    return text if len(text) <= 1 else "{" + text + "}"


_ATOM = re.compile(r"\d+(?:\.\d+)?|[^\W\d_]|[^\W\d_]_(?:\w|\{[\w,]+\})")


def _paren(text: str) -> str:
    """A fraction's part, bracketed unless it is one number, letter or subscripted letter."""
    return text if _ATOM.fullmatch(text) else "(" + text + ")"


def linear(node: ET.Element) -> str:
    """The element as one line of text."""
    tag = _tag(node)
    kids = [k for k in node if _tag(k) not in _SKIP]
    if tag in _SKIP:
        return ""
    if tag == "mtext" and re.fullmatch(r"[^\W\d_]{2,}(?: [^\W\d_]+)*", _text(node)):
        return f" {_text(node)} "  # a word inside a formula ("then", "or") keeps its spaces
    if tag in ("mi", "mn", "mtext", "ms"):
        return _text(node)
    if tag == "mo":
        op = _text(node)
        if op in (
            "=",
            "+",
            "−",
            "-",
            "×",
            "·",
            "⋅",
            "<",
            ">",
            "≤",
            "≥",
            "≈",
            "∝",
            "≠",
            "→",
            "⇌",
            "⟶",
        ):
            return f" {op} "
        if op in (",", ";"):
            return op + " "
        return op
    if tag == "semantics":
        return linear(kids[0]) if kids else ""
    if tag == "msub" and len(kids) == 2:
        return linear(kids[0]) + "_" + _group(linear(kids[1]).strip())
    if tag == "msup" and len(kids) == 2:
        return linear(kids[0]) + "^" + _group(linear(kids[1]).strip())
    if tag == "msubsup" and len(kids) == 3:
        return (
            linear(kids[0])
            + "_"
            + _group(linear(kids[1]).strip())
            + "^"
            + _group(linear(kids[2]).strip())
        )
    if tag == "mfrac" and len(kids) == 2:
        return _paren(linear(kids[0]).strip()) + "/" + _paren(linear(kids[1]).strip())
    if tag == "msqrt":
        return "sqrt(" + "".join(linear(k) for k in kids).strip() + ")"
    if tag == "mroot" and len(kids) == 2:
        return "root(" + linear(kids[0]).strip() + ", " + linear(kids[1]).strip() + ")"
    if tag in ("mover", "munder", "munderover") and kids:
        base = linear(kids[0])
        if tag == "mover" and len(kids) == 2:
            mark = linear(kids[1]).strip()
            if mark in _ACCENTS:
                return f"{_ACCENTS[mark]}({base.strip()})"
            return base + "^" + _group(mark)
        if tag == "munder" and len(kids) == 2:
            return base + "_" + _group(linear(kids[1]).strip())
        if tag == "munderover" and len(kids) == 3:
            return (
                base + "_" + _group(linear(kids[1]).strip()) + "^" + _group(linear(kids[2]).strip())
            )
    if tag == "mfenced":
        open_, close = node.get("open", "("), node.get("close", ")")
        sep = (node.get("separators", ",") or ",")[0]
        return open_ + f"{sep} ".join(linear(k).strip() for k in kids) + close
    if tag == "mtable":
        return "; ".join(linear(row).strip() for row in kids)
    if tag in ("mtr", "mlabeledtr"):
        return " ".join(linear(cell).strip() for cell in kids)
    return "".join(linear(k) for k in kids)


def as_text(math: ET.Element) -> str:
    """A `<m:math>` element as linear text with single spaces."""
    return " ".join(linear(math).split())


# -- solver form ----------------------------------------------------------------------------------


class _Refused(Exception):
    pass


def _name(text: str) -> str:
    text = text.strip()
    if text in _GREEK:
        return _GREEK[text]
    if _NAME.fullmatch(text):
        return text
    raise _Refused(text)


def _tokens(node: ET.Element) -> List[str]:
    """Solver tokens of a node; raises `_Refused` outside the subset."""
    tag = _tag(node)
    kids = [k for k in node if _tag(k) not in _SKIP]
    if tag in ("math", "mrow", "mstyle", "mpadded", "semantics"):
        if tag == "semantics":
            kids = kids[:1]
        out: List[str] = []
        for k in kids:
            out.extend(_tokens(k))
        return out
    if tag == "mi":
        text = _text(node)
        if text in _FUNCTIONS:
            return ["fn:" + text]
        return ["name:" + _name(text)]
    if tag == "mn":
        text = _text(node).replace(",", "")
        if not _NUMBER.fullmatch(text):
            raise _Refused(text)
        return ["num:" + text]
    if tag == "mo":
        text = _text(node)
        if text not in _OPERATORS:
            raise _Refused(text)
        return ["op:" + _OPERATORS[text]] if _OPERATORS[text] else []
    if tag == "msub" and len(kids) == 2:
        base = _plain(kids[0])
        sub = _plain(kids[1])
        return ["name:" + _name(base + "_" + sub)]
    if tag == "msup" and len(kids) == 2:
        return ["op:("] + _tokens(kids[0]) + ["op:)", "op:**", "op:("] + _tokens(kids[1]) + ["op:)"]
    if tag == "mfrac" and len(kids) == 2:
        return (
            ["op:(", "op:("]
            + _tokens(kids[0])
            + ["op:)", "op:/", "op:("]
            + _tokens(kids[1])
            + ["op:)", "op:)"]
        )
    if tag == "msqrt":
        inner: List[str] = []
        for k in kids:
            inner.extend(_tokens(k))
        return ["fn:sqrt", "op:("] + inner + ["op:)"]
    if (
        tag == "mfenced"
        and node.get("open", "(") == "("
        and node.get("close", ")") == ")"
        and len(kids) == 1
    ):
        return ["op:("] + _tokens(kids[0]) + ["op:)"]
    raise _Refused(tag)


def _plain(node: ET.Element) -> str:
    """Letters and digits of a subscript or a base, for a compound name like `v_0`."""
    text = "".join(_GREEK.get(c, c) for c in _text(node).replace(" ", ""))
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        raise _Refused(text)
    return text


def _join(tokens: List[str]) -> str:
    """Tokens as solver text, with an explicit `*` wherever two operands meet."""
    out: List[str] = []
    prev_end = False
    for tok in tokens:
        kind, _, value = tok.partition(":")
        starts = kind in ("name", "num", "fn") or (kind == "op" and value == "(")
        if starts and prev_end:
            out.append("*")
        out.append(value)
        prev_end = kind in ("name", "num") or (kind == "op" and value == ")")
    return "".join(out)


def solver_form(math: ET.Element) -> Optional[str]:
    """`lhs = rhs` in the solver's syntax, or `None` when the formula is outside the subset."""
    try:
        tokens = _tokens(math)
    except _Refused:
        return None
    text = _join(tokens)
    if text.count("=") != 1 or "**()" in text or "()" in text:
        return None
    lhs, rhs = text.split("=")
    if not lhs or not rhs or not any(t.startswith("name:") for t in tokens):
        return None
    for i, tok in enumerate(tokens):
        # a function must be applied to a bracket
        if tok.startswith("fn:") and (i + 1 >= len(tokens) or tokens[i + 1] != "op:("):
            return None
    return f"{lhs} = {rhs}"
