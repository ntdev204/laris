"""Answer extraction and MATH answer equivalence (T275, ADR-026 gate B1). Protocol `math-equiv-1`,
frozen.

Extraction:
- `last_boxed(text)`: the content of the last `\\boxed{...}` (or `\\fbox{...}`), braces balanced.
- `extract_math_answer(text)`: the last boxed answer, else the text after "final answer is".
- `extract_choice(text, letters)`: the letter of an "Answer: X" line, a boxed letter, or a last line
  that is only a letter; nothing is guessed from a letter elsewhere in the text.

Equivalence (`math_equivalent(pred, gold)`):
1. Both are normalised (spacing commands, `\\left`/`\\right`, `\\dfrac`, `\\text{}`, degrees,
   percent, dollar signs, a leading `x =`, trailing period, thousands separators) and compared as
   strings.
2. Otherwise both are split into top-level elements: a parenthesised or bracketed list is ordered
   and its brackets must match; a bare comma list or a set is unordered. Each element pair is
   compared by string, then by value: the LaTeX is turned into a SymPy expression (only digits,
   operators, single-letter symbols and a short list of function names pass; anything else is not
   parsed, because SymPy's parser evaluates Python) and two expressions are equal when their
   difference evaluates to 0 within `rel_tol` (numbers), or at seeded random points with the same
   free symbols (expressions). No `simplify` is called, so a hostile power tower cannot stall the
   check.

Inference evaluation only; nothing here trains.
"""

from __future__ import annotations

import math
import random
import re
import signal
import threading
from contextlib import contextmanager
from typing import Iterator, List, Optional, Sequence, Tuple

EQUIVALENCE_PROTOCOL = "math-equiv-1"

# -- extraction -----------------------------------------------------------------------------------


def _braced(text: str, start: int) -> Optional[Tuple[str, int]]:
    """`(content, end)` of the brace group opening at `text[start] == "{"`."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return None


def last_boxed(text: str) -> Optional[str]:
    """The content of the last `\\boxed{...}` / `\\fbox{...}` (or `\\boxed 5`), or None."""
    best = None
    for match in re.finditer(r"\\(?:boxed|fbox)\s*", text):
        end = match.end()
        group = _braced(text, end)
        if group is not None:
            best = group[0]
        elif end < len(text) and text[end] != "{":
            bare = re.match(r"([^\s$]+)", text[end:])
            if bare:
                best = bare.group(1)
    return best.strip() if best is not None else None


_FINAL = re.compile(r"final answer\s*(?:is|:)\s*:?\s*(.+)", re.IGNORECASE)


def extract_math_answer(text: str) -> Optional[str]:
    boxed = last_boxed(text)
    if boxed is not None:
        return boxed
    matches = _FINAL.findall(text)
    if matches:
        answer = matches[-1].replace("$", "").strip()
        answer = re.sub(r"[.\s]+$", "", answer)
        return answer or None
    return None


def extract_choice(text: str, letters: str) -> Optional[str]:
    """The chosen option letter, or None when the text does not state one."""
    allowed = set(letters)
    pattern = re.compile(
        r"answer\s*(?:is|:)?\s*[:\-]?\s*(?:\*\*)?\s*[\(\[]?\s*"
        r"(?:\\boxed\{|\\text\{|\\textbf\{|\\mathrm\{|\$)*\s*([A-Z])\b",
        re.IGNORECASE,
    )
    found = [m.group(1) for m in pattern.finditer(text) if m.group(1) in allowed]
    if found:
        return found[-1]
    boxed = last_boxed(text)
    if boxed is not None:
        letter = re.sub(r"\\text\{|\\textbf\{|\\mathrm\{|[{}()\s.$]", "", boxed)
        if letter in allowed:
            return letter
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if lines:
        last = re.sub(r"[*()\[\].:\s$]", "", lines[-1])
        if last in allowed:
            return last
    return None


# -- normalisation --------------------------------------------------------------------------------

_TEXT_CMD = re.compile(r"\\(?:text|textbf|textrm|mathrm|mbox|operatorname)\s*\{")


def _replace_text_commands(text: str) -> str:
    out = text
    while True:
        match = _TEXT_CMD.search(out)
        if not match:
            return out
        group = _braced(out, match.end() - 1)
        if group is None:
            return out
        content, end = group
        out = out[: match.start()] + content + out[end:]


def _fix_fracs(text: str) -> str:
    # \frac12 -> \frac{1}{2}, \frac1b -> \frac{1}{b}, \frac{1}2 -> \frac{1}{2}
    text = re.sub(r"\\frac\s*([0-9a-zA-Z])\s*([0-9a-zA-Z])", r"\\frac{\1}{\2}", text)
    text = re.sub(r"\\frac\s*\{([^{}]*)\}\s*([0-9a-zA-Z])", r"\\frac{\1}{\2}", text)
    text = re.sub(r"\\frac\s*([0-9a-zA-Z])\s*\{", r"\\frac{\1}{", text)
    return re.sub(r"\\sqrt\s*([0-9a-zA-Z])", r"\\sqrt{\1}", text)


def normalise(answer: str) -> str:
    """The MATH answer in a canonical string form (protocol `math-equiv-1`)."""
    text = str(answer).strip()
    text = text.replace("\n", "").replace("\\!", "").replace("\\displaystyle", "")
    text = re.sub(r"(?<!\\)\\[,;: ]", "", text)
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)(?![a-zA-Z])", "", text)
    text = text.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    text = text.replace("\\$", "").replace("$", "")
    text = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "", text).replace("\\circ", "").replace("°", "")
    text = text.replace("\\%", "").replace("%", "")
    # a unit written as text after a number: "10\text{ cm}", "5 \mbox{inches}"
    text = re.sub(r"(?<=[0-9}])\s*\\(?:text|mbox|mathrm)\{\s*[a-zA-Z][a-zA-Z ^2]+\}\s*$", "", text)
    text = _replace_text_commands(text)
    text = re.sub(r"\b(?:degrees?|units?)\b", "", text)
    text = text.replace("\\{", "{").replace("\\}", "}") if "\\{" in text else text
    text = text.strip()
    text = re.sub(r"\.\s*$", "", text)
    # a leading single-variable assignment: "x = 5", "k=3"
    text = re.sub(r"^[a-zA-Z]\s*=\s*(?=[^=]+$)", "", text)
    text = _fix_fracs(text)
    text = text.replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    text = re.sub(r"(?<![0-9])\.(\d)", r"0.\1", text)
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".")[0]
    return text


# -- structure ------------------------------------------------------------------------------------


def _split_top(text: str, sep: str = ",") -> List[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == sep and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


def _structure(text: str) -> Tuple[str, List[str]]:
    """`(kind, elements)`: kind is `"("`, `"["`, `"(]"` etc. for ordered tuples and intervals,
    `"set"` for an unordered list, `"matrix"` for a matrix, `""` for a single value."""
    matrix = re.fullmatch(r"\\begin\{[pbv]?matrix\}(.*)\\end\{[pbv]?matrix\}", text)
    if matrix:
        cells = re.split(r"&|\\\\", matrix.group(1))
        return "matrix", [c for c in cells if c != ""]
    if len(text) >= 2 and text[0] in "([" and text[-1] in ")]":
        inner = text[1:-1]
        if _balanced(inner):
            parts = _split_top(inner)
            if len(parts) > 1:
                return text[0] + text[-1], parts
    if len(text) >= 2 and text[0] == "{" and text[-1] == "}" and _balanced(text[1:-1]):
        parts = _split_top(text[1:-1])
        if len(parts) > 1:
            return "set", parts
    parts = _split_top(text)
    if len(parts) > 1:
        return "set", parts
    return "", [text]


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


# -- values ---------------------------------------------------------------------------------------

_FUNCTIONS = {"sqrt", "sin", "cos", "tan", "log", "ln", "exp", "pi", "oo", "E", "I"}


def latex_to_expr(text: str) -> Optional[str]:
    """A SymPy-parsable expression string for simple LaTeX, or None when it is not simple."""
    out = text
    for _ in range(50):
        match = re.search(r"\\frac\{", out)
        if not match:
            break
        top = _braced(out, match.end() - 1)
        if top is None:
            return None
        bottom = _braced(out, top[1])
        if bottom is None:
            return None
        out = out[: match.start()] + f"(({top[0]})/({bottom[0]}))" + out[bottom[1] :]
    for _ in range(50):
        match = re.search(r"\\sqrt(\[[^\]]*\])?\{", out)
        if not match:
            break
        group = _braced(out, match.end() - 1)
        if group is None:
            return None
        root = match.group(1)
        inner = f"(({group[0]})**(1/({root[1:-1]})))" if root else f"sqrt({group[0]})"
        out = out[: match.start()] + inner + out[group[1] :]
    replacements = {
        "\\pi": " pi ",
        "\\infty": " oo ",
        "\\cdot": "*",
        "\\times": "*",
        "\\div": "/",
        "\\ln": " log",
        "\\log": " log",
        "\\sin": " sin",
        "\\cos": " cos",
        "\\tan": " tan",
        "\\exp": " exp",
    }
    for key, value in replacements.items():
        out = out.replace(key, value)
    out = out.replace("{", "(").replace("}", ")").replace("^", "**")
    if "\\" in out or len(out) > 200:
        return None
    if not re.fullmatch(r"[0-9a-zA-Z+\-*/().\s]*", out) or not out.strip():
        return None
    for name in re.findall(r"[A-Za-z]+", out):
        if len(name) > 1 and name not in _FUNCTIONS:
            return None
    if re.search(r"\d{31,}", out) or out.count("**") > 3:
        return None
    return out


@contextmanager
def _time_limit(seconds: float) -> Iterator[None]:
    """A wall-clock limit (main thread only; elsewhere no limit)."""
    if threading.current_thread() is not threading.main_thread() or seconds <= 0:
        yield
        return

    def expire(signum, frame):  # noqa: ARG001
        raise TimeoutError

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _sympy(text: str):
    import sympy
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    expr = latex_to_expr(text)
    if expr is None:
        return None
    names = {name: getattr(sympy, name) for name in ("sqrt", "sin", "cos", "tan", "log", "exp")}
    names.update(pi=sympy.pi, oo=sympy.oo, E=sympy.E, I=sympy.I, ln=sympy.log)
    transformations = standard_transformations + (implicit_multiplication_application,)
    return parse_expr(
        expr,
        local_dict=names,
        global_dict=_sympy_globals(),
        transformations=transformations,
        evaluate=False,
    )


def _sympy_globals():
    """SymPy's names for the parser's generated code (`Integer`, `Mul`, ...), no Python builtins;
    the input was already restricted by `latex_to_expr`."""
    import sympy

    names = {k: v for k, v in vars(sympy).items() if not k.startswith("_")}
    names["__builtins__"] = {}
    return names


def _finite(value: complex) -> bool:
    return math.isfinite(value.real) and math.isfinite(value.imag)


def _values_equal(a, b, rel_tol: float) -> bool:
    import sympy

    free = a.free_symbols | b.free_symbols
    if a.free_symbols != b.free_symbols:
        return False
    diff = a - b
    if not free:
        left, right = complex(sympy.N(a, 30)), complex(sympy.N(b, 30))
        if not all(map(_finite, (left, right))):
            return False
        scale = max(abs(left), abs(right), 1.0)
        return abs(left - right) <= rel_tol * scale
    rng = random.Random(275)
    symbols = sorted(free, key=str)
    for _ in range(5):
        point = {s: sympy.Rational(rng.randint(1, 97), rng.randint(1, 13)) for s in symbols}
        value = complex(sympy.N(diff.subs(point), 30))
        at = complex(sympy.N(a.subs(point), 30))
        if not (_finite(value) and _finite(at)):
            return False
        scale = max(abs(at), 1.0)
        if abs(value) > rel_tol * scale:
            return False
    return True


def element_equivalent(pred: str, gold: str, rel_tol: float, timeout_s: float) -> bool:
    if pred == gold:
        return True
    if re.fullmatch(r"[A-Za-z ]+", pred) and re.fullmatch(r"[A-Za-z ]+", gold):
        return pred.casefold() == gold.casefold()
    if pred.count("=") == 1 and gold.count("=") == 1:
        (pl, pr), (gl, gr) = pred.split("="), gold.split("=")
        return pl == gl and element_equivalent(pr, gr, rel_tol, timeout_s)
    try:
        with _time_limit(timeout_s):
            a, b = _sympy(pred), _sympy(gold)
            if a is None or b is None:
                return False
            return _values_equal(a, b, rel_tol)
    except Exception:  # unparsable, undefined (zoo, nan), timeout: not equivalent
        return False


def math_equivalent(
    pred: Optional[str], gold: str, rel_tol: float = 1e-9, timeout_s: float = 5.0
) -> bool:
    """Whether a predicted MATH answer equals the gold one under protocol `math-equiv-1`."""
    if pred is None:
        return False
    p, g = normalise(pred), normalise(gold)
    if p == g:
        return True
    p_kind, p_parts = _structure(p)
    g_kind, g_parts = _structure(g)
    if p_kind != g_kind or len(p_parts) != len(g_parts):
        return False
    if p_kind == "set":
        return _match_unordered(p_parts, g_parts, rel_tol, timeout_s)
    return all(element_equivalent(a, b, rel_tol, timeout_s) for a, b in zip(p_parts, g_parts))


def _match_unordered(
    pred: Sequence[str], gold: Sequence[str], rel_tol: float, timeout_s: float
) -> bool:
    remaining = list(gold)
    for item in pred:
        for index, candidate in enumerate(remaining):
            if element_equivalent(item, candidate, rel_tol, timeout_s):
                del remaining[index]
                break
        else:
            return False
    return not remaining
