"""Expressions of the solver: text in a small Python-like syntax turned into SymPy without `eval`.

The text is parsed by Python's `ast` and every node is checked against a whitelist: numbers,
names, `+ - * / ** %`, unary signs and calls of the functions in `FUNCTIONS`. The SymPy tree is
built from the checked nodes, so no input reaches SymPy's own parser (which evaluates Python).
Decimal literals become exact rationals (`0.1` is `1/10`). Size guards (`SolverSettings`): text
length, node count, integer digits, constant exponents and factorial arguments; the worker
process's time and memory ceilings bound the rest.

Accepted conveniences: `^` for power, `×`/`·` for product, `−` for minus, implicit products after
a number or a closing bracket (`2x`, `3(x+1)`, `(a)(b)`), and a call on a single-letter name read as
a product (`x(x+1)`). Equations are `lhs = rhs` (or `==`); a bare expression means `= 0`.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Dict, Iterable, List, Optional, Tuple

from laris.model.solver.errors import SolverError
from laris.model.solver.settings import SolverSettings

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,23}\Z")
_IMPLICIT_NUMBER = re.compile(r"(?<![A-Za-z_0-9.])(\d+(?:\.\d+)?)\s*(?=[A-Za-z(])(?![eE][+-]?\d)")
_IMPLICIT_CLOSE = re.compile(r"\)\s*(?=[A-Za-z0-9(])")

ASSUMPTIONS = ("none", "real", "positive", "integer")

# name -> (SymPy attribute, allowed argument counts)
FUNCTIONS: Dict[str, Tuple[str, Tuple[int, ...]]] = {
    "sqrt": ("sqrt", (1,)),
    "cbrt": ("cbrt", (1,)),
    "root": ("root", (2,)),
    "exp": ("exp", (1,)),
    "log": ("log", (1, 2)),
    "ln": ("log", (1,)),
    "sin": ("sin", (1,)),
    "cos": ("cos", (1,)),
    "tan": ("tan", (1,)),
    "cot": ("cot", (1,)),
    "sec": ("sec", (1,)),
    "csc": ("csc", (1,)),
    "asin": ("asin", (1,)),
    "acos": ("acos", (1,)),
    "atan": ("atan", (1,)),
    "atan2": ("atan2", (2,)),
    "sinh": ("sinh", (1,)),
    "cosh": ("cosh", (1,)),
    "tanh": ("tanh", (1,)),
    "asinh": ("asinh", (1,)),
    "acosh": ("acosh", (1,)),
    "atanh": ("atanh", (1,)),
    "abs": ("Abs", (1,)),
    "Abs": ("Abs", (1,)),
    "sign": ("sign", (1,)),
    "floor": ("floor", (1,)),
    "ceiling": ("ceiling", (1,)),
    "ceil": ("ceiling", (1,)),
    "factorial": ("factorial", (1,)),
    "binomial": ("binomial", (2,)),
    "gamma": ("gamma", (1,)),
    "re": ("re", (1,)),
    "im": ("im", (1,)),
    "conjugate": ("conjugate", (1,)),
    "Mod": ("Mod", (2,)),
    "mod": ("Mod", (2,)),
    "gcd": ("gcd", (2,)),
    "lcm": ("lcm", (2,)),
    "min": ("Min", (2, 3, 4, 5, 6, 7, 8)),
    "max": ("Max", (2, 3, 4, 5, 6, 7, 8)),
    "Min": ("Min", (2, 3, 4, 5, 6, 7, 8)),
    "Max": ("Max", (2, 3, 4, 5, 6, 7, 8)),
}
CONSTANTS = ("pi", "E", "I", "oo")


def normalise_text(text: str) -> str:
    out = text.strip().replace("^", "**").replace("×", "*").replace("·", "*").replace("−", "-")
    out = _IMPLICIT_NUMBER.sub(r"\1*", out)
    return _IMPLICIT_CLOSE.sub(")*", out)


class Parser:
    """Builds SymPy expressions from checked text; one parser shares symbols across a call."""

    def __init__(self, settings: SolverSettings, assume: str = "none") -> None:
        import sympy

        if assume not in ASSUMPTIONS:
            raise SolverError(
                "invalid_arguments", f"assume must be one of: {', '.join(ASSUMPTIONS)}"
            )
        self.sympy = sympy
        self.settings = settings
        self.assume = assume
        self.symbols: Dict[str, object] = {}

    # -- public -----------------------------------------------------------------------------------
    def symbol(self, name: str):
        if (
            not isinstance(name, str)
            or not _NAME.match(name)
            or name in FUNCTIONS
            or name in CONSTANTS
        ):
            raise SolverError(
                "invalid_arguments", "a variable must be a plain name such as x or t1"
            )
        if name not in self.symbols:
            flags = {} if self.assume == "none" else {self.assume: True}
            self.symbols[name] = self.sympy.Symbol(name, **flags)
        return self.symbols[name]

    def expression(self, text: object, field: str = "expression"):
        if isinstance(text, bool):
            raise SolverError("invalid_arguments", f"{field} must be a string or a number")
        if isinstance(text, int):
            text = str(text)
        elif isinstance(text, float):
            if not math.isfinite(text):
                raise SolverError("invalid_arguments", f"{field} must be finite")
            text = repr(text)
        if not isinstance(text, str) or not text.strip():
            raise SolverError("invalid_arguments", f"{field} must be a non-empty string")
        if len(text) > self.settings.max_expression_chars:
            raise SolverError(
                "input_too_large",
                f"{field} is longer than {self.settings.max_expression_chars} characters",
            )
        source = normalise_text(text)
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError:
            raise SolverError("invalid_arguments", f"{field} is not a valid expression") from None
        count = sum(1 for _ in ast.walk(tree))
        if count > self.settings.max_nodes:
            raise SolverError(
                "input_too_large", f"{field} has more than {self.settings.max_nodes} parts"
            )
        return self._build(tree.body, source, field)

    def equation(self, text: object, field: str = "equation"):
        """`lhs - rhs` of `lhs = rhs` (a bare expression is `expression = 0`)."""
        if not isinstance(text, str):
            return self.expression(text, field)
        parts = re.split(r"(?<![<>!=])==?(?!=)", text)
        if len(parts) == 1:
            return self.expression(text, field)
        if len(parts) != 2:
            raise SolverError("invalid_arguments", f"{field} must hold at most one '='")
        return self.expression(parts[0], field) - self.expression(parts[1], field)

    def number(self, text: object, field: str):
        value = self.expression(text, field)
        if value.free_symbols:
            raise SolverError("invalid_arguments", f"{field} must not contain variables")
        return value

    def integer(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise SolverError("invalid_arguments", f"{field} must be an integer")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and re.fullmatch(r"\s*[+-]?\d+\s*", value):
            if len(value.strip().lstrip("+-")) > self.settings.max_integer_digits:
                raise SolverError("input_too_large", f"{field} has too many digits")
            number = int(value)
        else:
            raise SolverError("invalid_arguments", f"{field} must be an integer")
        if len(str(abs(number))) > self.settings.max_integer_digits:
            raise SolverError("input_too_large", f"{field} has too many digits")
        return number

    def variables(
        self, names: Optional[Iterable[object]], expressions: List[object]
    ) -> List[object]:
        """The named variables, or the free symbols of `expressions` sorted by name."""
        if names is None:
            free = set()
            for e in expressions:
                free |= e.free_symbols
            return sorted(free, key=str)
        if not isinstance(names, list) or not names:
            raise SolverError("invalid_arguments", "variables must be a non-empty list of names")
        if len(names) > self.settings.max_items:
            raise SolverError(
                "input_too_large", f"variables holds more than {self.settings.max_items} names"
            )
        return [self.symbol(n) for n in names]

    # -- tree -------------------------------------------------------------------------------------
    def _build(self, node: ast.AST, source: str, field: str):
        sp = self.sympy
        if isinstance(node, ast.Constant):
            return self._constant(node, source, field)
        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return {"pi": sp.pi, "E": sp.E, "I": sp.I, "oo": sp.oo}[node.id]
            if node.id in FUNCTIONS:
                raise SolverError(
                    "invalid_arguments", f"{field}: {node.id} is a function and needs arguments"
                )
            return self.symbol(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self._build(node.operand, source, field)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left = self._build(node.left, source, field)
            right = self._build(node.right, source, field)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return sp.Mod(left, right)
            if isinstance(node.op, ast.Pow):
                self._guard_power(left, right, field)
                return left**right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            args = [self._build(a, source, field) for a in node.args]
            if name in FUNCTIONS:
                attribute, counts = FUNCTIONS[name]
                if len(args) not in counts:
                    raise SolverError(
                        "invalid_arguments", f"{field}: {name} takes {counts[0]} argument(s)"
                    )
                if attribute == "factorial":
                    self._guard_factorial(args[0], field)
                if attribute == "binomial":
                    self._guard_factorial(args[0], field)
                return getattr(sp, attribute)(*args)
            if len(name) == 1 and len(args) == 1:  # x(x+1) is a product
                return self.symbol(name) * args[0]
            raise SolverError("invalid_arguments", f"{field}: unknown function {name}")
        raise SolverError("invalid_arguments", f"{field} uses syntax the solver does not accept")

    def _constant(self, node: ast.Constant, source: str, field: str):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SolverError(
                "invalid_arguments", f"{field} may hold only numbers, names and operators"
            )
        if isinstance(value, int):
            if len(str(abs(value))) > self.settings.max_integer_digits:
                raise SolverError(
                    "input_too_large", f"{field} holds an integer with too many digits"
                )
            return self.sympy.Integer(value)
        text = ast.get_source_segment(source, node) or repr(value)
        mantissa = re.sub(r"[eE].*", "", text)
        if len(mantissa.replace(".", "")) > self.settings.max_integer_digits:
            raise SolverError("input_too_large", f"{field} holds a number with too many digits")
        exponent = re.search(r"[eE]([+-]?\d+)", text)
        if exponent and abs(int(exponent.group(1))) > self.settings.max_integer_digits:
            raise SolverError(
                "input_too_large", f"{field} holds a number with too large an exponent"
            )
        return self.sympy.Rational(text)

    def _guard_power(self, base, exponent, field: str) -> None:
        if not exponent.is_number:
            return
        if exponent.is_Integer:
            if abs(int(exponent)) > self.settings.max_exponent:
                raise SolverError(
                    "input_too_large",
                    f"{field} holds an exponent above {self.settings.max_exponent}",
                )
            if base.is_Rational and base != 0:
                size = abs(int(exponent)) * max(
                    math.log10(abs(int(base.p))) if base.p else 0.0,
                    math.log10(abs(int(base.q))),
                )
                if size > self.settings.max_integer_digits:
                    raise SolverError(
                        "input_too_large", f"{field} holds a power with too many digits"
                    )
        elif exponent.is_Rational and abs(int(exponent.p)) > self.settings.max_exponent:
            raise SolverError(
                "input_too_large", f"{field} holds an exponent above {self.settings.max_exponent}"
            )

    def _guard_factorial(self, argument, field: str) -> None:
        if argument.is_number and argument.is_real and abs(argument) > self.settings.max_exponent:
            raise SolverError(
                "input_too_large",
                f"{field} holds a factorial argument above {self.settings.max_exponent}",
            )
