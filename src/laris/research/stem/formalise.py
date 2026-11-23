"""The model-free path of T276: benchmark questions that already state a structured problem.

`formalise(item)` matches a MATH question against a short list of strict patterns ("Compute
$<expression>$.", "Find the greatest common divisor of 91 and 72.", "Convert $314_{10}$ to base 6.",
...) and returns the solver problem plus how to read the answer, or None. A pattern accepts the
whole question or nothing: trailing words, a condition or an unknown LaTeX command leave the item
to the model (T278). `latex_to_solver` turns the LaTeX of a matched question into the solver's
syntax and refuses whatever it does not know, so nothing is guessed.

`answer_model_free(item, settings)` runs the solver and gives an answer only when the solver's
status is `verified`; a proposal is not an answer. Multiple-choice benchmarks (MMLU-Pro, GPQA)
have no pattern here: their questions are prose and need the router's formalisation.

Inference-free and training-free: nothing here calls a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

_SKIP = ("\\left", "\\right", "\\displaystyle", "\\!", "\\,", "\\;", "\\:", "\\ ")
_FUNCS = {"\\sin": "sin", "\\cos": "cos", "\\tan": "tan", "\\cot": "cot", "\\sec": "sec",
          "\\csc": "csc", "\\ln": "log", "\\exp": "exp", "\\arcsin": "asin", "\\arccos": "acos",
          "\\arctan": "atan"}  # fmt: skip


class _Refuse(Exception):
    pass


class _Latex:
    """A recursive reader of a small LaTeX subset; any other command refuses the whole text."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.s[j] if j < len(self.s) else ""

    def skip_space(self) -> None:
        while True:
            while self.peek() in (" ", "\n", "\t"):
                self.i += 1
            for word in _SKIP:
                if self.s.startswith(word, self.i) and not (
                    word in ("\\left", "\\right")
                    and self.s[self.i + len(word) : self.i + len(word) + 1].isalpha()
                ):
                    self.i += len(word)
                    break
            else:
                return

    def command(self) -> str:
        match = re.match(r"\\([A-Za-z]+|.)", self.s[self.i :])
        if not match:
            raise _Refuse
        self.i += match.end()
        return "\\" + match.group(1)

    def group(self) -> str:
        """`{...}` or one character or one command atom, as an expression."""
        self.skip_space()
        if self.peek() == "{":
            self.i += 1
            inner = self.sequence("}")
            if self.peek() != "}":
                raise _Refuse
            self.i += 1
            return f"({inner})"
        if self.peek().isdigit() or self.peek().isalpha():
            char = self.peek()
            self.i += 1
            return char
        if self.peek() == "\\":
            return self.atom()
        raise _Refuse

    def argument(self) -> str:
        """The argument of a function written without brackets: a number (maybe in degrees), a
        letter or a group."""
        self.skip_space()
        if self.peek() in ("(", "{") or self.s.startswith("\\left(", self.i):
            return self.atom()
        match = re.match(r"\d+(?:\.\d+)?", self.s[self.i :])
        if match:
            self.i += match.end()
            value = match.group()
            if re.match(r"\s*\^\s*\{?\s*\\circ\s*\}?", self.s[self.i :]):
                self.i += re.match(r"\s*\^\s*\{?\s*\\circ\s*\}?", self.s[self.i :]).end()
                return f"({value}*pi/180)"
            return value
        if self.peek().isalpha():
            char = self.peek()
            self.i += 1
            return char
        if self.peek() == "\\":
            return self.atom()
        raise _Refuse

    def atom(self) -> str:
        self.skip_space()
        char = self.peek()
        if char == "":
            raise _Refuse
        if char.isdigit() or (char == "." and self.peek(1).isdigit()):
            match = re.match(r"\d*\.?\d+|\d+", self.s[self.i :])
            self.i += match.end()
            number = match.group()
            return "0" + number if number.startswith(".") else number
        if char.isalpha():
            self.i += 1
            return char
        if char in "({":
            close = ")" if char == "(" else "}"
            self.i += 1
            inner = self.sequence(close)
            if self.peek() != close:
                raise _Refuse
            self.i += 1
            return f"({inner})"
        if char == "[":
            self.i += 1
            inner = self.sequence("]")
            if self.peek() != "]":
                raise _Refuse
            self.i += 1
            return f"({inner})"
        if char == "|":
            self.i += 1
            inner = self.sequence("|")
            if self.peek() != "|":
                raise _Refuse
            self.i += 1
            return f"abs({inner})"
        if char != "\\":
            raise _Refuse
        start = self.i
        name = self.command()
        if name in ("\\frac", "\\dfrac", "\\tfrac"):
            top, bottom = self.group(), self.group()
            return f"({top}/{bottom})"
        if name in ("\\binom", "\\dbinom", "\\tbinom"):
            top, bottom = self.group(), self.group()
            return f"binomial({top}, {bottom})"
        if name == "\\sqrt":
            self.skip_space()
            if self.peek() == "[":
                self.i += 1
                index = self.sequence("]")
                if self.peek() != "]":
                    raise _Refuse
                self.i += 1
                return f"root({self.group()}, {index})"
            return f"sqrt({self.group()})"
        if name == "\\pi":
            return "pi"
        if name in ("\\lceil", "\\lfloor"):
            close = "\\rceil" if name == "\\lceil" else "\\rfloor"
            inner = self.sequence(close)
            if not self.s.startswith(close, self.i):
                raise _Refuse
            self.i += len(close)
            return ("ceiling" if name == "\\lceil" else "floor") + f"({inner})"
        if name == "\\log":
            self.skip_space()
            if self.peek() != "_":
                raise _Refuse  # a log without a base is ambiguous in MATH
            self.i += 1
            base = self.group() if self.peek() != "\\" else self.atom()
            return f"log({self.argument()}, {base})"
        if name in _FUNCS:
            self.skip_space()
            if self.peek() == "^":
                raise _Refuse  # sin^2 x
            return f"{_FUNCS[name]}({self.argument()})"
        self.i = start
        raise _Refuse

    def sequence(self, stop: str) -> str:
        """Atoms and operators until `stop`; consecutive atoms are multiplied."""
        out: List[str] = []
        last_atom = False
        while True:
            self.skip_space()
            if self.i >= len(self.s) or (stop and self.s.startswith(stop, self.i)):
                break
            char = self.peek()
            if char in "+-=":
                out.append(char)
                self.i += 1
                last_atom = False
                continue
            if char in "*/":
                out.append(char)
                self.i += 1
                last_atom = False
                continue
            operator = re.match(r"\\(cdot|times|div)(?![A-Za-z])", self.s[self.i :])
            if operator:
                self.i += operator.end()
                out.append("/" if operator.group(1) == "div" else "*")
                last_atom = False
                continue
            if char == "^":
                if not last_atom:
                    raise _Refuse
                self.i += 1
                self.skip_space()
                if re.match(r"\{?\s*\\circ\s*\}?", self.s[self.i :]):
                    self.i += re.match(r"\{?\s*\\circ\s*\}?", self.s[self.i :]).end()
                    out[-1] = f"({out[-1]}*pi/180)"
                    continue
                exponent = self.group()
                out[-1] = f"({out[-1]})**({exponent})"
                continue
            if char == "!":
                if not last_atom:
                    raise _Refuse
                self.i += 1
                out[-1] = f"factorial({out[-1]})"
                continue
            if (
                last_atom
                and re.fullmatch(r"\d+(?:\.\d+)?", out[-1])
                and re.match(r"\\[dt]?frac(?![A-Za-z])", self.s[self.i :])
            ):
                raise _Refuse  # 8\frac13 is the mixed number 8 1/3, not a product
            atom = self.atom()
            if last_atom:
                out.append("*")
            out.append(atom)
            last_atom = True
        return " ".join(out)


def latex_to_solver(text: str) -> Optional[str]:
    """The solver syntax of a LaTeX expression, or None when it uses anything unknown."""
    reader = _Latex(text.strip().rstrip(".").strip())
    try:
        out = reader.sequence("")
    except (_Refuse, RecursionError):
        return None
    if reader.i != len(reader.s) or not out.strip():
        return None
    return out


@dataclass(frozen=True)
class Formal:
    pattern: str
    problem: Dict[str, Any]
    read: Callable[[Dict[str, Any]], Optional[str]]  # solver result -> answer text, or None


def _latex_answer(result: Dict[str, Any]) -> Optional[str]:
    return result.get("latex") or result.get("text")


def _single_solution(result: Dict[str, Any]) -> Optional[str]:
    answer = result.get("answer")
    if isinstance(answer, list) and len(answer) == 1:
        return result.get("latex") or answer[0]
    return None


def _numeric_expression(latex: str) -> Optional[str]:
    expr = latex_to_solver(latex)
    if expr is None or re.search(r"(?<![a-z])[a-zA-Z](?![a-z(])", expr.replace("pi", "")):
        return None  # a free letter: not a number
    return expr


_INT = r"\$?\s*(\d+)\s*\$?"
_END = r"\s*[.?]?\s*$"
_DOLLAR = r"\$\$?\s*(.+?)\s*\$?\$"


def _patterns() -> List[Tuple[str, re.Pattern, Callable[[re.Match], Optional[Formal]]]]:
    rules: List[Tuple[str, re.Pattern, Callable[[re.Match], Optional[Formal]]]] = []

    def rule(name: str, pattern: str):
        def wrap(fn):
            rules.append((name, re.compile(pattern, re.IGNORECASE | re.DOTALL), fn))
            return fn

        return wrap

    @rule(
        "evaluate",
        r"^(?:compute|evaluate|calculate|simplify|find|what is)(?: the value of)?:?\s*"
        + _DOLLAR
        + _END,
    )
    def evaluate(m):
        expr = _numeric_expression(m.group(1))
        if expr is None or "=" in expr:
            return None
        return Formal("evaluate", {"operation": "evaluate", "expression": expr}, _latex_answer)

    @rule("common_fraction", r"^express\s+" + _DOLLAR + r"\s+as a common fraction" + _END)
    def fraction(m):
        expr = _numeric_expression(m.group(1))
        if expr is None:
            return None

        def read(result):
            answer = result.get("answer", "")
            return result.get("latex") if re.fullmatch(r"-?\d+(/\d+)?", answer) else None

        return Formal("common_fraction", {"operation": "evaluate", "expression": expr}, read)

    @rule(
        "gcd",
        r"^(?:find|what is) the greatest common (?:divisor|factor) of "
        + _INT
        + r" and "
        + _INT
        + _END,
    )
    def gcd(m):
        return Formal(
            "gcd",
            {"operation": "gcd", "integers": [m.group(1), m.group(2)]},
            lambda r: str(r["answer"]),
        )

    @rule("lcm", r"^(?:find|what is) the least common multiple of " + _INT + r" and " + _INT + _END)
    def lcm(m):
        return Formal(
            "lcm",
            {"operation": "lcm", "integers": [m.group(1), m.group(2)]},
            lambda r: str(r["answer"]),
        )

    @rule(
        "remainder",
        r"^(?:what is|find) the remainder when " + _DOLLAR + r" is divided by " + _INT + _END,
    )
    def remainder(m):
        expr = _numeric_expression(m.group(1))
        if expr is None:
            return None
        return Formal(
            "remainder",
            {"operation": "evaluate", "expression": f"Mod({expr}, {m.group(2)})"},
            _latex_answer,
        )

    @rule(
        "prime_factor", r"^what is the (largest|greatest|smallest) prime factor of " + _INT + _END
    )
    def prime_factor(m):
        pick = min if m.group(1).lower() == "smallest" else max

        def read(result):
            primes = [f["prime"] for f in result["answer"]]
            return str(pick(primes)) if primes else None

        return Formal("prime_factor", {"operation": "factor_integer", "integer": m.group(2)}, read)

    @rule("to_base", r"^convert \$\s*(\d+)_\{?(\d+)\}?\s*\$ to base (\d+)" + _END)
    def to_base(m):
        number, base, target = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if base != 10 or target > 10:
            return None
        return Formal(
            "to_base",
            {"operation": "to_base", "integer": number, "base": target},
            lambda r: f"{r['answer']}_{target}",
        )

    @rule(
        "divisor_count", r"^how many positive (?:integer )?divisors does " + _INT + r" have" + _END
    )
    def divisor_count(m):
        return Formal(
            "divisor_count",
            {"operation": "divisors", "integer": m.group(1)},
            lambda r: str(r["answer"]["count"]),
        )

    @rule("proper_divisor_sum", r"^what is the sum of the proper divisors of " + _INT + _END)
    def proper_sum(m):
        n = int(m.group(1))
        return Formal(
            "proper_divisor_sum",
            {"operation": "divisors", "integer": n},
            lambda r: str(r["answer"]["sum"] - n),
        )

    @rule("solve_for", r"^solve for \$([a-z])\$(?::| in the equation)\s*" + _DOLLAR + _END)
    def solve_for(m):
        expr = latex_to_solver(m.group(2))
        if expr is None or expr.count("=") != 1:
            return None
        return Formal(
            "solve_for",
            {"operation": "solve", "expression": expr, "variable": m.group(1), "domain": "real"},
            _single_solution,
        )

    @rule("expand", r"^expand(?: the product)?\s*" + _DOLLAR + _END)
    def expand(m):
        expr = latex_to_solver(m.group(1))
        if expr is None or "=" in expr:
            return None
        return Formal("expand", {"operation": "expand", "expression": expr}, _latex_answer)

    return rules


_RULES = _patterns()


def formalise(item: Dict[str, Any]) -> Optional[Formal]:
    """The solver problem of a MATH item whose whole question matches a pattern, else None."""
    if item.get("options"):
        return None
    question = item["question"].strip()
    for _, pattern, build in _RULES:
        match = pattern.match(question)
        if match:
            formal = build(match)
            if formal is not None:
                return formal
    return None


def answer_model_free(item: Dict[str, Any], settings: Any) -> Dict[str, Any]:
    """`{"pattern", "status", "answer"}`; `answer` is set only for a verified solver result."""
    from laris.model.solver import SolverError, run

    formal = formalise(item)
    if formal is None:
        return {"pattern": None, "status": "not_formalised", "answer": None}
    try:
        result = run(formal.problem, settings)
    except SolverError as exc:
        return {"pattern": formal.pattern, "status": f"refused:{exc.code}", "answer": None}
    if result["status"] != "verified":
        return {"pattern": formal.pattern, "status": "proposal", "answer": None}
    if _complex(result) and "i" not in re.findall(r"[a-z]", formal.problem.get("expression", "")):
        # SymPy's principal branch ((-27)^(5/3) = -243 (-1)^(2/3)); MATH means the real root
        return {"pattern": formal.pattern, "status": "complex_branch", "answer": None}
    return {
        "pattern": formal.pattern,
        "status": "verified",
        "answer": math_style(formal.read(result)),
    }


def math_style(answer: Any) -> Any:
    """SymPy LaTeX written as MATH writes answers: `5x^{26}-15x^9`, not `5 x^{26} - 15 x^{9}`.

    Drops `\\left`/`\\right`, braces around a one-character exponent or subscript, and spaces,
    except the one space that ends a command before a letter (`\\pi x` stays readable as `\\pi x`).
    The value is unchanged; only the spelling follows the benchmark's.
    """
    if not isinstance(answer, str):
        return answer
    text = re.sub(r"\\(left|right)(?![A-Za-z])", "", answer)
    text = re.sub(r"([\^_])\{([A-Za-z0-9])\}", r"\1\2", text)
    text = re.sub(r"(\\[A-Za-z]+) +(?=[A-Za-z])", "\\1\x00", text)
    return re.sub(r"\s+", "", text).replace("\x00", " ")


def _complex(result: Dict[str, Any]) -> bool:
    text = " ".join(str(result.get(k) or "") for k in ("answer", "numeric", "latex"))
    return bool(re.search(r"(?<![A-Za-z])I(?![A-Za-z])|\(-1\)\^|\\left\(-1\\right\)\^", text))
