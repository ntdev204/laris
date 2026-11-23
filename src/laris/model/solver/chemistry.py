"""Stoichiometry: balance a reaction, and the amounts of every species from one known amount.

Formulas: element symbols with counts, brackets `()` and `[]`, hydrates (`CuSO4·5H2O`,
`CuSO4*5H2O`), and a charge written `^2+`, `^{3-}`, `^+` (counted as the pseudo-element
`charge`, so ionic equations balance charge too); the electron is `e^-`. Reactions use `->`, `→`,
`=` or `<=>` between sides and ` + ` (with spaces) between species, optional leading coefficients
ignored.

The coefficients are the integer nullspace vector of the composition matrix (SymPy), scaled to the
smallest positive integers; a reaction whose nullspace is not one-dimensional is refused. The check
recounts every element on both sides with the coefficients, in plain integers, from a second
reading of the formulas.

Masses need molar masses; no table of atomic weights is shipped (no approved source yet), so the
caller gives `molar_masses` (g/mol per species) and the answer names them as given.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import reduce
from typing import Dict, List, Tuple

from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check
from laris.model.solver.result import Outcome, show

ELEMENTS = frozenset(
    """H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se
    Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy
    Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf
    Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og D T""".split()
)
CHARGE = "charge"
_ARROW = re.compile(r"\s*(?:<=>|<->|->|→|⇌|⟶|=)\s*")
_CHARGE = re.compile(r"(?:\^\{?(\d*)([+-])\}?|(?<=[A-Za-z0-9)\]])([+-]))$")


def _charge(formula: str) -> Tuple[str, int]:
    match = _CHARGE.search(formula)
    if not match:
        return formula, 0
    size = int(match.group(1) or 1)
    sign = match.group(2) or match.group(3)
    return formula[: match.start()], size if sign == "+" else -size


def composition(formula: str) -> Counter:
    """Element counts of one formula (first reading: a recursive scan)."""
    text = formula.strip()
    if not text or len(text) > 200:
        raise SolverError("invalid_arguments", "a formula must have 1 to 200 characters")
    if text in ("e^-", "e-", "e^{-}"):
        return Counter({CHARGE: -1})
    body, charge = _charge(text)
    total: Counter = Counter()
    for part in re.split(r"[·*•]|\.(?=\d*[A-Z(\[])", body):
        part = part.strip()
        if not part:
            raise SolverError("invalid_arguments", "a formula has an empty part")
        lead = re.match(r"(\d+)", part)
        times = int(lead.group(1)) if lead else 1
        counts, end = _group(part, lead.end() if lead else 0)
        if end != len(part):
            raise SolverError(
                "invalid_arguments", "a formula holds a character the solver does not read"
            )
        for k, v in counts.items():
            total[k] += v * times
    if charge:
        total[CHARGE] += charge
    return total


def _group(text: str, at: int) -> Tuple[Counter, int]:
    counts: Counter = Counter()
    while at < len(text):
        char = text[at]
        if char in "([":
            inner, at = _group(text, at + 1)
            if at >= len(text) or text[at] not in ")]":
                raise SolverError("invalid_arguments", "unbalanced brackets in a formula")
            at += 1
            number = re.match(r"\d+", text[at:])
            times = int(number.group()) if number else 1
            at += number.end() if number else 0
            for k, v in inner.items():
                counts[k] += v * times
        elif char in ")]":
            return counts, at
        else:
            match = re.match(r"([A-Z][a-z]?)(\d*)", text[at:])
            if not match or match.group(1) not in ELEMENTS:
                raise SolverError("invalid_arguments", "a formula holds an unknown element")
            counts[match.group(1)] += int(match.group(2) or 1)
            at += match.end()
    return counts, at


def recount(formula: str) -> Counter:
    """Element counts by a second reading: expand brackets textually, then count symbols."""
    text = formula.strip()
    if text in ("e^-", "e-", "e^{-}"):
        return Counter({CHARGE: -1})
    body, charge = _charge(text)
    total: Counter = Counter()
    for part in re.split(r"[·*•]|\.(?=\d*[A-Z(\[])", body):
        lead = re.match(r"\d+", part.strip())
        times = int(lead.group()) if lead else 1
        flat = part.strip()[lead.end() if lead else 0 :]
        flat = flat.replace("[", "(").replace("]", ")")
        while "(" in flat:
            flat = re.sub(
                r"\(([^()]*)\)(\d*)",
                lambda m: "".join(
                    f"{el}{int(n or 1) * int(m.group(2) or 1)}"
                    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", m.group(1))
                ),
                flat,
            )
        for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", flat):
            total[el] += int(n or 1) * times
    if charge:
        total[CHARGE] += charge
    return total


def _sides(reaction: str) -> Tuple[List[str], List[str]]:
    parts = _ARROW.split(reaction.strip())
    if len(parts) != 2:
        raise SolverError("invalid_arguments", "a reaction needs one arrow between two sides")

    def species(side: str) -> List[str]:
        names = [re.sub(r"^\d+\s+", "", s.strip()) for s in re.split(r"\s+\+\s+", side.strip())]
        if not all(names):
            raise SolverError("invalid_arguments", "a side of the reaction has an empty species")
        return names

    return species(parts[0]), species(parts[1])


def balance_reaction(reaction: str, max_items: int):
    import sympy

    left, right = _sides(reaction)
    names = left + right
    if len(names) > max_items:
        raise SolverError("input_too_large", "the reaction has too many species")
    comps = [composition(n) for n in names]
    elements = sorted(set().union(*comps))
    matrix = sympy.Matrix(
        [[c[e] * (1 if i < len(left) else -1) for i, c in enumerate(comps)] for e in elements]
    )
    space = matrix.nullspace()
    if len(space) != 1:
        raise SolverError(
            "rejected",
            "the reaction does not balance"
            if not space
            else "the reaction balances in more than one independent way",
        )
    vector = space[0]
    scale = reduce(sympy.ilcm, [sympy.fraction(v)[1] for v in vector], 1)
    ints = [int(v * scale) for v in vector]
    if all(v <= 0 for v in ints):
        ints = [-v for v in ints]
    if any(v <= 0 for v in ints):
        raise SolverError("rejected", "the reaction has no balance with positive coefficients")
    divisor = reduce(math.gcd, ints)
    coefficients = [v // divisor for v in ints]
    return left, right, coefficients


def _recount_check(left, right, coefficients) -> Check:
    lhs: Counter = Counter()
    rhs: Counter = Counter()
    for i, name in enumerate(left + right):
        target = lhs if i < len(left) else rhs
        for el, n in recount(name).items():
            target[el] += n * coefficients[i]
    lhs = Counter({k: v for k, v in lhs.items() if v})
    rhs = Counter({k: v for k, v in rhs.items() if v})
    return Check("element and charge recount on both sides", lhs == rhs)


def _written(left, right, coefficients) -> str:
    def side(names, coefs):
        return " + ".join(f"{c} {n}" if c != 1 else n for n, c in zip(names, coefs))

    return f"{side(left, coefficients[: len(left)])} -> {side(right, coefficients[len(left) :])}"


def balance(ctx) -> Outcome:
    reaction = ctx.text("reaction")
    left, right, coefficients = balance_reaction(reaction, ctx.settings.max_items)
    written = _written(left, right, coefficients)
    answer = {"coefficients": dict(zip(left + right, coefficients)), "equation": written}
    return Outcome(answer, written, [_recount_check(left, right, coefficients)])


def stoichiometry(ctx) -> Outcome:
    import sympy

    reaction = ctx.text("reaction")
    known = ctx.text("species")
    amount = ctx.parser.number(ctx.require("amount"), "amount")
    left, right, coefficients = balance_reaction(reaction, ctx.settings.max_items)
    names = left + right
    if known not in names:
        raise SolverError("invalid_arguments", "species must be one of the reaction's species")
    coef = dict(zip(names, coefficients))
    moles = {n: amount * sympy.Integer(coef[n]) / coef[known] for n in names}
    checks = [_recount_check(left, right, coefficients)]
    ratios_ok = all(moles[n] * coef[known] == amount * coef[n] for n in names)
    checks.append(Check("amount ratios equal the coefficient ratios", ratios_ok))
    answer: Dict[str, object] = {
        "equation": _written(left, right, coefficients),
        "moles": {n: show(v) for n, v in moles.items()},
    }
    masses_given = ctx.args.get("molar_masses")
    if masses_given is not None:
        if not isinstance(masses_given, dict):
            raise SolverError("invalid_arguments", "molar_masses must be an object")
        masses = {}
        for name, given in masses_given.items():
            if name not in names:
                raise SolverError(
                    "invalid_arguments", "molar_masses names a species not in the reaction"
                )
            masses[name] = show(moles[name] * ctx.parser.number(given, f"molar_masses.{name}"))
        answer["grams"] = masses
        ctx.notes.append("masses use the molar masses given by the caller (g/mol)")
    text = "; ".join(f"{n}: {v} mol" for n, v in answer["moles"].items())
    return Outcome(answer, text, checks)
