"""Units and dimensions: convert a quantity, give the dimension of a unit expression.

Route 1 (the answer): the solver's own table of exact factors over the seven SI base units, with
the SI prefixes (2022 set, quecto to quetta); exact SI definitions, and CODATA 2022 for the dalton.
Route 2 (the check): the same units expressed in `sympy.physics.units` and converted by SymPy; a
unit without a SymPy counterpart leaves the answer a `proposal`. The routes agree within
`SolverSettings.unit_tolerance` (SymPy carries the 2018 dalton, 1.4e-9 apart).

Temperatures with an offset (degC, degF, degR) convert only on their own; the check is the
textbook formula for the pair, not the table.

Unit expressions: names joined by `*`, `/`, spaces or `.`, powers with `^` or `**` (`m s^-2`,
`kg*m^2/s^2`, `J mol^-1 K^-1`, `(km/h)`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check
from laris.model.solver.result import Outcome, show

BASES = ("m", "kg", "s", "A", "K", "mol", "cd")
PREFIXES: Dict[str, int] = {
    "Q": 30, "R": 27, "Y": 24, "Z": 21, "E": 18, "P": 15, "T": 12, "G": 9, "M": 6, "k": 3,
    "h": 2, "da": 1, "d": -1, "c": -2, "m": -3, "µ": -6, "μ": -6, "u": -6, "n": -9, "p": -12,
    "f": -15, "a": -18, "z": -21, "y": -24, "r": -27, "q": -30,
}  # fmt: skip
DALTON_KG = "1.66053906892e-27"  # CODATA 2022 atomic mass constant


@dataclass(frozen=True)
class Unit:
    factor: object  # exact SymPy number: the size in SI base units
    dims: Tuple[int, ...]  # powers of m, kg, s, A, K, mol, cd

    def __mul__(self, other: "Unit") -> "Unit":
        return Unit(self.factor * other.factor, tuple(a + b for a, b in zip(self.dims, other.dims)))

    def __pow__(self, n: int) -> "Unit":
        return Unit(self.factor**n, tuple(a * n for a in self.dims))


def _dims(**powers: int) -> Tuple[int, ...]:
    return tuple(powers.get(b, 0) for b in ("m", "kg", "s", "A", "K", "mol", "cd"))


# name -> (factor as text over SI base units, dims, prefixable, SymPy route-2 expression)
def _table():
    import sympy
    import sympy.physics.units as u

    R = sympy.Rational
    L, M, T, CUR, TH, N, J = (_dims(**{b: 1}) for b in ("m", "kg", "s", "A", "K", "mol", "cd"))
    force, energy = _dims(m=1, kg=1, s=-2), _dims(m=2, kg=1, s=-2)
    power, charge = _dims(m=2, kg=1, s=-3), _dims(s=1, A=1)
    volt = _dims(m=2, kg=1, s=-3, A=-1)
    pressure = _dims(m=-1, kg=1, s=-2)
    none = _dims()
    e = R("1.602176634e-19")
    inch = R("0.0254")
    pound = R("0.45359237")
    julian_year = R(36525, 100) * 86400
    table = {
        "m": (1, L, True, u.meter),
        "g": (R(1, 1000), M, True, u.gram),
        "s": (1, T, True, u.second),
        "A": (1, CUR, True, u.ampere),
        "K": (1, TH, True, u.kelvin),
        "mol": (1, N, True, u.mole),
        "cd": (1, J, True, u.candela),
        "Hz": (1, _dims(s=-1), True, u.hertz),
        "N": (1, force, True, u.newton),
        "Pa": (1, pressure, True, u.pascal),
        "J": (1, energy, True, u.joule),
        "W": (1, power, True, u.watt),
        "C": (1, charge, True, u.coulomb),
        "V": (1, volt, True, u.volt),
        "F": (1, _dims(m=-2, kg=-1, s=4, A=2), True, u.farad),
        "ohm": (1, _dims(m=2, kg=1, s=-3, A=-2), True, u.ohm),
        "Ω": (1, _dims(m=2, kg=1, s=-3, A=-2), True, u.ohm),
        "S": (1, _dims(m=-2, kg=-1, s=3, A=2), True, u.siemens),
        "Wb": (1, _dims(m=2, kg=1, s=-2, A=-1), True, u.weber),
        "T": (1, _dims(kg=1, s=-2, A=-1), True, u.tesla),
        "H": (1, _dims(m=2, kg=1, s=-2, A=-2), True, u.henry),
        "lm": (1, J, True, u.candela * u.steradian),
        "lx": (1, _dims(m=-2, cd=1), True, u.lux),
        "Bq": (1, _dims(s=-1), True, u.becquerel),
        "Gy": (1, _dims(m=2, s=-2), True, u.gray),
        "Sv": (1, _dims(m=2, s=-2), True, u.gray),
        "kat": (1, _dims(mol=1, s=-1), True, u.katal),
        "L": (R(1, 1000), _dims(m=3), True, u.liter),
        "l": (R(1, 1000), _dims(m=3), True, u.liter),
        "M": (1000, _dims(mol=1, m=-3), True, u.mole / u.liter),
        "eV": (e, energy, True, u.electronvolt),
        "Da": (R(DALTON_KG), M, True, u.dalton),
        "u": (R(DALTON_KG), M, False, u.amu),
        "bar": (100000, pressure, True, u.bar),
        "cal": (R("4.184"), energy, True, R("4.184") * u.joule),
        "min": (60, T, False, u.minute),
        "h": (3600, T, False, u.hour),
        "d": (86400, T, False, u.day),
        "yr": (julian_year, T, False, u.julian_year),
        "au": (149597870700, L, False, u.astronomical_unit),
        "ly": (299792458 * julian_year, L, False, u.lightyear),
        "pc": (149597870700 * 648000 / sympy.pi, L, False, u.astronomical_unit * 648000 / sympy.pi),
        "Å": (R(1, 10**10), L, False, u.angstrom),
        "atm": (101325, pressure, False, u.atmosphere),
        "Torr": (R(101325, 760), pressure, False, u.atmosphere / 760),
        "mmHg": (R("133.322387415"), pressure, False, u.mmHg),
        "psi": (pound * R("9.80665") / inch**2, pressure, False, u.psi),
        "erg": (R(1, 10**7), energy, False, u.gram * u.centimeter**2 / u.second**2),
        "dyn": (R(1, 10**5), force, False, u.gram * u.centimeter / u.second**2),
        "in": (inch, L, False, u.inch),
        "ft": (12 * inch, L, False, u.foot),
        "yd": (36 * inch, L, False, u.yard),
        "mi": (63360 * inch, L, False, u.mile),
        "nmi": (1852, L, False, u.nautical_mile),
        "lb": (pound, M, False, u.pound),
        "oz": (pound / 16, M, False, u.pound / 16),
        "lbf": (pound * R("9.80665"), force, False, u.pound * u.acceleration_due_to_gravity),
        "gal": (231 * inch**3, _dims(m=3), False, 231 * u.inch**3),
        "rad": (1, none, False, u.radian),
        "sr": (1, none, False, u.steradian),
        "deg": (sympy.pi / 180, none, False, u.degree),
        "%": (R(1, 100), none, False, u.percent),
        "ppm": (R(1, 10**6), none, False, u.percents / 10**4),
    }
    return table


SPELLED = {
    "meter": "m", "metre": "m", "gram": "g", "second": "s", "sec": "s", "ampere": "A",
    "kelvin": "K", "mole": "mol", "candela": "cd", "hertz": "Hz", "newton": "N", "pascal": "Pa",
    "joule": "J", "watt": "W", "coulomb": "C", "volt": "V", "farad": "F", "siemens": "S",
    "weber": "Wb", "tesla": "T", "henry": "H", "liter": "L", "litre": "L", "electronvolt": "eV",
    "dalton": "Da", "calorie": "cal", "minute": "min", "hour": "h", "hr": "h", "day": "d",
    "year": "yr", "angstrom": "Å", "atmosphere": "atm", "torr": "Torr", "inch": "in",
    "inches": "in", "foot": "ft", "feet": "ft", "yard": "yd", "mile": "mi", "pound": "lb",
    "ounce": "oz", "gallon": "gal", "radian": "rad", "degree": "deg", "°": "deg",
    "percent": "%", "molar": "M", "μm": "µm", "lightyear": "ly", "parsec": "pc",
}  # fmt: skip
TEMPERATURES = {
    "degC": "C", "°C": "C", "celsius": "C", "degF": "F", "°F": "F", "fahrenheit": "F",
    "degR": "R", "°R": "R", "rankine": "R", "K": "K", "kelvin": "K",
}  # fmt: skip

_TOKEN = re.compile(r"\s*(\*\*|[*/().^]|[-+]?\d+(?:/\d+)?|[A-Za-zµμΩÅ°%][A-Za-z0-9µμΩÅ°_%]*)")


class UnitParser:
    def __init__(self) -> None:
        self.table = _table()
        self.used: List[Tuple[str, int, int]] = []  # (table name, prefix power, exponent sign)

    def name(self, token: str) -> Tuple[Unit, object]:
        import sympy

        word = SPELLED.get(token, token)
        if word not in self.table and word.endswith("s") and SPELLED.get(word[:-1]):
            word = SPELLED[word[:-1]]
        if word in self.table:
            factor, dims, _, route = self.table[word]
            return Unit(sympy.sympify(factor), dims), route
        for prefix in sorted(PREFIXES, key=len, reverse=True):
            if word.startswith(prefix) and word[len(prefix) :] in self.table:
                factor, dims, prefixable, route = self.table[word[len(prefix) :]]
                if prefixable:
                    scale = sympy.Integer(10) ** PREFIXES[prefix]
                    return Unit(sympy.sympify(factor) * scale, dims), route * scale
        raise SolverError("rejected", f"unknown unit: {token[:20]}")

    def parse(self, text: str) -> Tuple[Unit, object]:
        import sympy

        tokens, pos = [], 0
        clean = text.strip()
        while pos < len(clean):
            match = _TOKEN.match(clean, pos)
            if not match or match.end() == pos:
                raise SolverError(
                    "invalid_arguments", "the unit holds a character the solver does not read"
                )
            tokens.append(match.group(1))
            pos = match.end()
        self._tokens, self._at = tokens, 0
        unit, route = self._product()
        if self._at != len(tokens):
            raise SolverError("invalid_arguments", "the unit is not a valid unit expression")
        return unit, sympy.sympify(route)

    # product := power ((* | / | juxtaposition) power)*
    def _product(self):
        unit, route = self._power()
        while self._at < len(self._tokens) and self._tokens[self._at] != ")":
            op = self._tokens[self._at]
            if op in ("*", "/", "."):
                self._at += 1
            right, right_route = self._power()
            if op == "/":
                unit, route = unit * right**-1, route / right_route
            else:
                unit, route = unit * right, route * right_route
        return unit, route

    def _power(self):
        unit, route = self._atom()
        if self._at < len(self._tokens) and self._tokens[self._at] in ("^", "**"):
            self._at += 1
            exponent = self._exponent()
            return unit**exponent, route**exponent
        if self._at < len(self._tokens) and re.fullmatch(r"-\d+", self._tokens[self._at]):
            exponent = int(self._tokens[self._at])  # NIST style "s-1" is not used; "s^-1" is
            self._at += 1
            return unit**exponent, route**exponent
        return unit, route

    def _exponent(self) -> int:
        if self._at >= len(self._tokens):
            raise SolverError("invalid_arguments", "a unit power has no exponent")
        token = self._tokens[self._at]
        self._at += 1
        if token == "(":
            value = self._exponent()
            if self._at >= len(self._tokens) or self._tokens[self._at] != ")":
                raise SolverError("invalid_arguments", "unbalanced brackets in a unit")
            self._at += 1
            return value
        if not re.fullmatch(r"[-+]?\d+", token) or abs(int(token)) > 12:
            raise SolverError("invalid_arguments", "a unit exponent must be a small integer")
        return int(token)

    def _atom(self):
        import sympy

        if self._at >= len(self._tokens):
            raise SolverError("invalid_arguments", "the unit is incomplete")
        token = self._tokens[self._at]
        self._at += 1
        if token == "(":
            inner = self._product()
            if self._at >= len(self._tokens) or self._tokens[self._at] != ")":
                raise SolverError("invalid_arguments", "unbalanced brackets in a unit")
            self._at += 1
            return inner
        if token == "1":
            return Unit(sympy.Integer(1), _dims()), sympy.Integer(1)
        if not re.match(r"[A-Za-zµμΩÅ°%]", token):
            raise SolverError("invalid_arguments", "the unit is not a valid unit expression")
        return self.name(token)


def describe(dims: Tuple[int, ...]) -> str:
    parts = [f"{b}^{p}" if p != 1 else b for b, p in zip(BASES, dims) if p]
    return " ".join(parts) or "1"


def _sympy_ratio(route_from, route_to):
    import sympy
    import sympy.physics.units as u
    from sympy.physics.units import convert_to

    base = [u.meter, u.kilogram, u.second, u.ampere, u.kelvin, u.mole, u.candela]
    ratio = convert_to(route_from / route_to, base)
    ratio = sympy.nsimplify(ratio) if ratio.free_symbols else ratio
    if ratio.atoms(u.Quantity):
        return None
    return ratio


def _temperature(value, source: str, target: str):
    """`(answer, check)` for an offset temperature conversion."""
    import sympy

    R = sympy.Rational
    to_kelvin = {
        "K": lambda t: t,
        "C": lambda t: t + R("273.15"),
        "F": lambda t: (t + R("459.67")) * R(5, 9),
        "R": lambda t: t * R(5, 9),
    }
    from_kelvin = {
        "K": lambda k: k,
        "C": lambda k: k - R("273.15"),
        "F": lambda k: k * R(9, 5) - R("459.67"),
        "R": lambda k: k * R(9, 5),
    }
    answer = from_kelvin[target](to_kelvin[source](value))
    direct = {
        ("C", "F"): lambda t: t * R(9, 5) + 32,
        ("F", "C"): lambda t: (t - 32) * R(5, 9),
        ("C", "K"): lambda t: t + R("273.15"),
        ("K", "C"): lambda t: t - R("273.15"),
        ("F", "K"): lambda t: (t - 32) * R(5, 9) + R("273.15"),
        ("K", "F"): lambda t: (t - R("273.15")) * R(9, 5) + 32,
        ("R", "F"): lambda t: t - R("459.67"),
        ("F", "R"): lambda t: t + R("459.67"),
        ("R", "K"): lambda t: t * R(5, 9),
        ("K", "R"): lambda t: t * R(9, 5),
        ("C", "R"): lambda t: (t + R("273.15")) * R(9, 5),
        ("R", "C"): lambda t: t * R(5, 9) - R("273.15"),
    }
    if source == target:
        return answer, Check("same unit", True)
    other = direct[(source, target)](value)
    return answer, Check("textbook formula for the pair", sympy.simplify(answer - other) == 0)


def convert_unit(ctx) -> Outcome:
    import sympy

    from laris.model.solver.result import numeric_text

    value = ctx.parser.number(ctx.require("value"), "value")
    source, target = ctx.text("unit"), ctx.text("target_unit")
    if source.strip() in TEMPERATURES and target.strip() in TEMPERATURES:
        a, b = TEMPERATURES[source.strip()], TEMPERATURES[target.strip()]
        if a != "K" or b != "K":
            answer, check = _temperature(value, a, b)
            text = f"{show(answer)} {target.strip()}"
            return Outcome(show(answer), text, [check], numeric=numeric_text(answer, ctx.settings))
    for name in (source, target):
        if any(t in name for t in ("degC", "°C", "degF", "°F", "degR", "°R")):
            raise SolverError("rejected", "a temperature with an offset converts only on its own")
    parser = UnitParser()
    unit_from, route_from = parser.parse(source)
    unit_to, route_to = parser.parse(target)
    if unit_from.dims != unit_to.dims:
        raise SolverError(
            "rejected",
            f"incompatible dimensions: {describe(unit_from.dims)} and {describe(unit_to.dims)}",
        )
    answer = sympy.nsimplify(value * unit_from.factor / unit_to.factor)
    try:
        ratio = _sympy_ratio(route_from, route_to)
    except Exception:
        ratio = None
    if ratio is None or ratio.free_symbols:
        check = Check("sympy.physics.units conversion", False, "a unit has no SymPy counterpart")
    else:
        second = value * ratio
        scale = max(abs(sympy.N(answer, 30)), sympy.Integer(1))
        ok = abs(sympy.N(answer - second, 30)) <= ctx.settings.unit_tolerance * scale
        check = Check("sympy.physics.units conversion", bool(ok))
    numeric = numeric_text(answer, ctx.settings)
    text = f"{numeric or show(answer)} {target.strip()}"
    out = Outcome(show(answer), text, [check], numeric=numeric)
    out.notes.append(f"dimension {describe(unit_from.dims)}")
    return out


def dimension(ctx) -> Outcome:
    from sympy.physics.units import Dimension
    from sympy.physics.units.systems.si import SI, dimsys_SI

    text = ctx.text("unit")
    unit, route = UnitParser().parse(text)
    expected = dict(zip(BASES, unit.dims))
    try:
        found = dimsys_SI.get_dimensional_dependencies(Dimension(SI.get_dimensional_expr(route)))
        names = {"length": "m", "mass": "kg", "time": "s", "current": "A", "temperature": "K",
                 "amount_of_substance": "mol", "luminous_intensity": "cd"}  # fmt: skip
        second = {b: 0 for b in BASES}
        for key, power in found.items():
            second[names[str(key.name)]] = int(power)
        check = Check("sympy.physics.units dimension", second == expected)
    except Exception:
        check = Check("sympy.physics.units dimension", False, "not available")
    answer = {"dimension": {b: p for b, p in expected.items() if p}, "si": describe(unit.dims)}
    answer["factor"] = show(unit.factor)
    return Outcome(answer, f"{describe(unit.dims)} (factor {show(unit.factor)})", [check])
