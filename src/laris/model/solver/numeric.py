"""The independent numeric route: SymPy trees evaluated with mpmath, and the checks built on it.

`value(expr, point)` walks the tree itself (numbers, symbols, `Add`, `Mul`, `Pow` and the functions
of `_FUNCTIONS`) and computes in mpmath at `SolverSettings.working_digits`; it never calls SymPy's
simplification, so a symbolic result and the input it came from are compared by a route that did
not produce the result. A node it does not know and that holds no symbol is evaluated by SymPy's
`evalf` (noted by the caller as a weaker check); with symbols it raises `NotNumeric`.

Checks return a `Check` (route name, passed); none raises on a numeric failure: a point where
either side is undefined is skipped, and too few usable points fail the check.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

import mpmath

from laris.model.solver.settings import SolverSettings


class NotNumeric(Exception):
    """The tree holds something the numeric route cannot evaluate."""


@dataclass(frozen=True)
class Check:
    route: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {"route": self.route, "passed": self.passed}
        if self.detail:
            out["detail"] = self.detail
        return out


def _real(z):
    if isinstance(z, mpmath.mpc):
        if abs(z.imag) > mpmath.mpf(10) ** (-(mpmath.mp.dps // 2)) * max(1, abs(z.real)):
            raise NotNumeric("complex value where a real one is needed")
        return z.real
    return z


_FUNCTIONS: Dict[str, Callable] = {
    "exp": mpmath.exp,
    "sin": mpmath.sin,
    "cos": mpmath.cos,
    "tan": mpmath.tan,
    "cot": mpmath.cot,
    "sec": mpmath.sec,
    "csc": mpmath.csc,
    "asin": mpmath.asin,
    "acos": mpmath.acos,
    "atan": mpmath.atan,
    "acot": mpmath.acot,
    "sinh": mpmath.sinh,
    "cosh": mpmath.cosh,
    "tanh": mpmath.tanh,
    "asinh": mpmath.asinh,
    "acosh": mpmath.acosh,
    "atanh": mpmath.atanh,
    "Abs": lambda z: mpmath.mpf(abs(z)),
    "gamma": mpmath.gamma,
    "factorial": mpmath.factorial,
    "re": lambda z: mpmath.re(z),
    "im": lambda z: mpmath.im(z),
    "conjugate": mpmath.conj,
    "floor": lambda z: mpmath.floor(_real(z)),
    "ceiling": lambda z: mpmath.ceil(_real(z)),
    "sign": lambda z: mpmath.sign(z),
    "erf": mpmath.erf,
}


def value(expr, point: Optional[Dict[object, object]] = None):
    """The mpmath value of `expr` with `point` (symbol -> number) at the current precision."""
    import sympy

    point = point or {}
    if not isinstance(expr, sympy.Basic):
        expr = sympy.sympify(expr)
    if expr.is_Symbol:
        if expr not in point:
            raise NotNumeric("a symbol has no value")
        return point[expr]
    if expr.is_Integer:
        return mpmath.mpf(int(expr))
    if expr.is_Rational:
        return mpmath.mpf(int(expr.p)) / int(expr.q)
    if expr.is_Float:
        return mpmath.mpf(str(expr))
    if expr is sympy.pi:
        return +mpmath.pi
    if expr is sympy.E:
        return +mpmath.e
    if expr is sympy.I:
        return mpmath.mpc(0, 1)
    if expr is sympy.EulerGamma:
        return +mpmath.euler
    if expr in (sympy.oo, -sympy.oo, sympy.zoo, sympy.nan):
        raise NotNumeric("not a finite number")
    if expr.is_Add:
        return mpmath.fsum(value(a, point) for a in expr.args)
    if expr.is_Mul:
        out = mpmath.mpf(1)
        for a in expr.args:
            out *= value(a, point)
        return out
    if expr.is_Pow:
        base, exponent = value(expr.base, point), value(expr.exp, point)
        if base == 0 and mpmath.re(exponent) < 0:
            raise NotNumeric("division by zero")
        return mpmath.power(base, exponent)
    name = type(expr).__name__
    if name == "log":
        args = [value(a, point) for a in expr.args]
        if args[0] == 0:
            raise NotNumeric("log of zero")
        return mpmath.log(args[0]) if len(args) == 1 else mpmath.log(args[0], args[1])
    if name == "binomial":
        n, k = (value(a, point) for a in expr.args)
        return mpmath.binomial(n, k)
    if name == "atan2":
        y, x = (_real(value(a, point)) for a in expr.args)
        return mpmath.atan2(y, x)
    if name == "Mod":
        a, b = (_real(value(x, point)) for x in expr.args)
        return a - b * mpmath.floor(a / b)
    if name in ("Min", "Max"):
        items = [_real(value(a, point)) for a in expr.args]
        return min(items) if name == "Min" else max(items)
    if name in _FUNCTIONS and len(expr.args) == 1:
        return _FUNCTIONS[name](value(expr.args[0], point))
    if not expr.free_symbols:  # e.g. CRootOf: SymPy's own numeric evaluation
        number = sympy.N(expr, mpmath.mp.dps)
        if not number.is_number:
            raise NotNumeric("no numeric value")
        return mpmath.mpc(complex(number)) if not number.is_real else mpmath.mpf(str(number))
    raise NotNumeric(f"{name} is not evaluated numerically")


def close(a, b, tolerance: float) -> bool:
    if not (mpmath.isfinite(a) and mpmath.isfinite(b)):
        return False
    scale = max(mpmath.mpf(1), abs(a), abs(b))
    return abs(a - b) <= tolerance * scale


def sample_points(symbols: Sequence[object], settings: SolverSettings, kind: str) -> List[Dict]:
    """`settings.check_points` seeded points; `kind`: complex, real, positive or integer."""
    rng = random.Random(settings.check_seed)
    points = []
    for _ in range(settings.check_points):
        point = {}
        for s in sorted(symbols, key=str):
            if kind == "integer":
                point[s] = mpmath.mpf(rng.randint(2, 9))
                continue
            magnitude = mpmath.mpf(rng.randint(11, 290)) / 100
            if kind == "positive":
                point[s] = magnitude
            elif kind == "real":
                point[s] = magnitude if rng.random() < 0.5 else -magnitude
            else:
                point[s] = mpmath.mpc(magnitude, mpmath.mpf(rng.randint(-200, 200)) / 100)
        points.append(point)
    return points


def point_kind(assume: str) -> str:
    return {"none": "complex", "real": "real", "positive": "positive", "integer": "integer"}[assume]


def identity(left, right, settings: SolverSettings, assume: str, route: str) -> Check:
    """Whether `left` and `right` agree at seeded points (or as numbers when both are constant)."""
    symbols = left.free_symbols | right.free_symbols
    with mpmath.workdps(settings.working_digits):
        points = sample_points(symbols, settings, point_kind(assume)) if symbols else [{}]
        usable = 0
        for point in points:
            try:
                a, b = value(left, point), value(right, point)
            except (NotNumeric, ZeroDivisionError, ValueError, OverflowError):
                continue
            if not (mpmath.isfinite(a) and mpmath.isfinite(b)):
                continue
            usable += 1
            if not close(a, b, settings.check_tolerance):
                return Check(route, False, "the two sides differ at a test point")
        needed = 1 if not symbols else max(1, (len(points) + 1) // 2)
        if usable < needed:
            return Check(route, False, "too few points where both sides are defined")
    return Check(route, True)


def residual(expr, point: Dict, settings: SolverSettings, scale_terms: bool = True) -> bool:
    """Whether `expr` (an equation's `lhs - rhs`) vanishes at `point`, relative to its terms."""
    with mpmath.workdps(settings.working_digits):
        total = value(expr, point)
        scale = mpmath.mpf(1)
        if scale_terms and expr.is_Add:
            for term in expr.args:
                try:
                    scale = max(scale, abs(value(term, point)))
                except NotNumeric:
                    pass
        return mpmath.isfinite(total) and abs(total) <= settings.check_tolerance * scale
