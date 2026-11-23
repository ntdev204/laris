"""One structured problem in, one checked answer out (`solve`), in the caller's process.

`OPERATIONS` maps each operation name to its domain and function. The problem is a flat object:
`operation` plus the fields that operation reads (see `laris.model.tools` for the schema); a
field the operation does not read is refused, so a misspelt argument is not silently ignored.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

from laris.model.solver import (
    algebra,
    calculus,
    chemistry,
    constants,
    linalg,
    number_theory,
    quantities,
)
from laris.model.solver.context import Context
from laris.model.solver.errors import SolverError
from laris.model.solver.expr import Parser
from laris.model.solver.result import Outcome
from laris.model.solver.settings import SolverSettings

COMMON = ("operation", "assume")
# operation -> (domain, function, fields it reads besides COMMON)
OPERATIONS: Dict[str, Tuple[str, Callable[[Context], Outcome], Tuple[str, ...]]] = {
    "evaluate": ("algebra", algebra.evaluate, ("expression", "substitutions")),
    "simplify": ("algebra", algebra.simplify, ("expression",)),
    "expand": ("algebra", algebra.expand, ("expression",)),
    "factor": ("algebra", algebra.factor, ("expression",)),
    "solve": ("algebra", algebra.solve, ("expression", "variable", "domain")),
    "solve_system": ("algebra", algebra.solve_system, ("expressions", "variables")),
    "differentiate": ("calculus", calculus.differentiate, ("expression", "variable", "order")),
    "integrate": ("calculus", calculus.integrate, ("expression", "variable", "lower", "upper")),
    "limit": ("calculus", calculus.limit, ("expression", "variable", "point", "direction")),
    "sum": ("calculus", calculus.summation, ("expression", "variable", "lower", "upper")),
    "determinant": ("linear_algebra", linalg.determinant, ("matrix",)),
    "inverse": ("linear_algebra", linalg.inverse, ("matrix",)),
    "rank": ("linear_algebra", linalg.rank, ("matrix",)),
    "eigenvalues": ("linear_algebra", linalg.eigenvalues, ("matrix",)),
    "solve_linear": ("linear_algebra", linalg.solve_linear, ("matrix", "vector")),
    "gcd": ("number_theory", number_theory.gcd, ("integers",)),
    "lcm": ("number_theory", number_theory.lcm, ("integers",)),
    "factor_integer": ("number_theory", number_theory.factor_integer, ("integer",)),
    "is_prime": ("number_theory", number_theory.is_prime, ("integer",)),
    "mod_pow": ("number_theory", number_theory.mod_pow, ("base", "exponent", "modulus")),
    "mod_inverse": ("number_theory", number_theory.mod_inverse, ("integer", "modulus")),
    "crt": ("number_theory", number_theory.crt, ("integers", "moduli")),
    "totient": ("number_theory", number_theory.totient, ("integer",)),
    "divisors": ("number_theory", number_theory.divisors, ("integer",)),
    "binomial": ("number_theory", number_theory.binomial, ("n", "k")),
    "factorial": ("number_theory", number_theory.factorial, ("integer",)),
    "to_base": ("number_theory", number_theory.to_base, ("integer", "base")),
    "from_base": ("number_theory", number_theory.from_base, ("digits", "base")),
    "convert_unit": ("units", quantities.convert_unit, ("value", "unit", "target_unit")),
    "dimension": ("units", quantities.dimension, ("unit",)),
    "constant": ("constants", constants.constant, ("constant",)),
    "balance": ("chemistry", chemistry.balance, ("reaction",)),
    "molar_mass": ("chemistry", chemistry.molar_mass, ("formula",)),
    "stoichiometry": (
        "chemistry",
        chemistry.stoichiometry,
        ("reaction", "species", "amount", "amount_unit", "molar_masses"),
    ),
}


def engine_versions() -> Dict[str, str]:
    import mpmath
    import sympy

    return {"sympy": sympy.__version__, "mpmath": mpmath.__version__}


def solve(problem: Dict[str, Any], settings: SolverSettings) -> Dict[str, Any]:
    """The checked answer to `problem`; raises `SolverError` on a refusal."""
    if not isinstance(problem, dict):
        raise SolverError("invalid_arguments", "the problem must be an object")
    operation = problem.get("operation")
    if operation not in OPERATIONS:
        raise SolverError(
            "invalid_arguments", "operation must be one of: " + ", ".join(sorted(OPERATIONS))
        )
    domain, run, fields = OPERATIONS[operation]
    extra = sorted(
        k for k, v in problem.items() if v is not None and k not in COMMON and k not in fields
    )
    if extra:
        raise SolverError("invalid_arguments", f"{operation} does not read {extra[0]}")
    parser = Parser(settings, problem.get("assume", "none"))
    ctx = Context(dict(problem), settings, parser)
    try:
        outcome = run(ctx)
    except SolverError:
        raise
    except (ValueError, TypeError, ArithmeticError, NotImplementedError, AttributeError) as exc:
        # SymPy's refusals; the class only, since the text may quote the input
        raise SolverError(
            "rejected", f"the solver could not handle the problem ({type(exc).__name__})"
        ) from None
    outcome.notes[:0] = ctx.notes
    for source in ctx.sources:
        if source not in outcome.sources:
            outcome.sources.append(source)
    out = outcome.to_dict(operation, engine_versions())
    out["domain"] = domain
    if len(repr(out)) > settings.max_result_chars:
        raise SolverError(
            "input_too_large", f"the answer is longer than {settings.max_result_chars} characters"
        )
    return out
