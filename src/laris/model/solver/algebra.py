"""Algebra: evaluate, simplify, expand, factor, solve one equation, solve a system.

Checks (independent of the symbolic step):
- evaluate/simplify/expand/factor: the result equals the input at seeded points, computed with
  mpmath from the unsimplified input (`numeric.identity`).
- solve: every solution makes the equation vanish at working precision; completeness, for an
  equation whose numerator is a polynomial with numeric coefficients, by mpmath's own polynomial
  roots (Durand-Kerner), denominator roots removed. Any other equation keeps `proposal`.
- solve_system: every solution satisfies every equation (parameters sampled); completeness for a
  linear system by the rank of its coefficient matrix; a non-linear system keeps `proposal`.
"""

from __future__ import annotations

from typing import List

import mpmath

from laris.model.solver.context import Context
from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check, NotNumeric, identity, residual, sample_points, value
from laris.model.solver.result import Outcome, latex, numeric_text, show

DOMAINS = ("real", "complex")


def evaluate(ctx: Context) -> Outcome:
    import sympy

    expr = ctx.expression()
    values = ctx.substitutions()
    given = expr.subs(values) if values else expr
    result = sympy.simplify(given)
    if result.has(sympy.zoo, sympy.nan):
        raise SolverError("rejected", "the expression is undefined")
    checks = [identity(given, result, ctx.settings, ctx.assume, "mpmath value of the input")]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )


def _rewrite(ctx: Context, how: str) -> Outcome:
    import sympy

    expr = ctx.expression()
    result = {"simplify": sympy.simplify, "expand": sympy.expand, "factor": sympy.factor}[how](expr)
    checks = [identity(expr, result, ctx.settings, ctx.assume, "mpmath identity at seeded points")]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )


def simplify(ctx: Context) -> Outcome:
    return _rewrite(ctx, "simplify")


def expand(ctx: Context) -> Outcome:
    return _rewrite(ctx, "expand")


def factor(ctx: Context) -> Outcome:
    return _rewrite(ctx, "factor")


def _domain(ctx: Context):
    import sympy

    name = ctx.args.get("domain", "real")
    if name not in DOMAINS:
        raise SolverError("invalid_arguments", "domain must be real or complex")
    return name, (sympy.S.Reals if name == "real" else sympy.S.Complexes)


def _parameters_points(expr, variable, ctx: Context):
    params = sorted(expr.free_symbols - {variable}, key=str)
    return params, (sample_points(params, ctx.settings, "positive") if params else [{}])


def solve(ctx: Context) -> Outcome:
    import sympy

    raw = ctx.require("expression")
    equation = ctx.parser.equation(raw, "expression")
    x = ctx.variable([equation])
    domain_name, domain = _domain(ctx)
    found = sympy.solveset(equation, x, domain)
    if not isinstance(found, sympy.FiniteSet):
        if found is sympy.S.EmptySet:
            solutions: List = []
        else:
            text = show(found)
            ctx.notes.append("the solution set is not a finite list; it was not checked")
            return Outcome(text, text, [], latex(found))
    else:
        solutions = sorted(found, key=sympy.default_sort_key)
    if len(solutions) > ctx.settings.max_items:
        raise SolverError("input_too_large", "the equation has too many solutions to report")
    params, points = _parameters_points(equation, x, ctx)
    checks = [_substitution_check(equation, x, solutions, points, ctx)]
    complete = (
        _polynomial_completeness(equation, x, solutions, domain_name, ctx) if not params else None
    )
    if complete is None:
        ctx.notes.append(
            "completeness was not checked: the equation is not a polynomial with numeric "
            "coefficients"
        )
        checks.append(Check("completeness", False, "not checked"))
    else:
        checks.append(complete)
    answer = [show(s) for s in solutions]
    text = ", ".join(f"{x} = {a}" for a in answer) if answer else "no solution"
    return Outcome(answer, text, checks, ", ".join(latex(s) for s in solutions) or None)


def _substitution_check(equation, x, solutions, points, ctx: Context) -> Check:
    route = "substitution into the equation (mpmath)"
    for sol in solutions:
        for point in points:
            try:
                with mpmath.workdps(ctx.settings.working_digits):
                    full = dict(point)
                    full[x] = value(sol, point)
                    if not residual(equation, full, ctx.settings):
                        return Check(route, False, "a solution does not satisfy the equation")
            except (NotNumeric, ZeroDivisionError, ValueError):
                return Check(route, False, "a solution could not be evaluated")
    return Check(route, True)


def _polynomial_completeness(equation, x, solutions, domain_name: str, ctx: Context):
    """A `Check` when the numerator is a polynomial in `x` with numeric coefficients, else None."""
    import sympy

    numerator, denominator = sympy.fraction(sympy.together(equation))
    try:
        poly = sympy.Poly(numerator, x)
    except sympy.PolynomialError:
        return None
    if not all(c.is_number for c in poly.all_coeffs()):
        return None
    route = "completeness by mpmath polynomial roots"
    if poly.degree() <= 0:
        ok = not solutions if not poly.is_zero else False
        return Check(route, ok, "" if ok else "constant equation")
    square_free = sympy.Poly(sympy.sqf_part(poly.as_expr()), x)
    with mpmath.workdps(ctx.settings.working_digits):
        coeffs = [value(c) for c in square_free.all_coeffs()]
        try:
            roots = mpmath.polyroots(
                coeffs, maxsteps=400, extraprec=4 * ctx.settings.working_digits
            )
        except mpmath.libmp.NoConvergence:
            return Check(route, False, "the numeric roots did not converge")
        if not isinstance(roots, list):
            roots = [roots]
        tol = mpmath.mpf(10) ** (-(ctx.settings.working_digits // 3))
        kept = []
        for r in roots:
            r = mpmath.mpc(r)
            if domain_name == "real" and abs(r.imag) > tol * max(1, abs(r)):
                continue
            try:
                if abs(value(denominator, {x: r})) <= tol:
                    continue
            except (NotNumeric, ZeroDivisionError):
                continue
            kept.append(r)
        values = []
        for s in solutions:
            values.append(mpmath.mpc(value(s)))
        if len(kept) != len(values):
            return Check(
                route, False, f"{len(kept)} roots found numerically, {len(values)} reported"
            )
        for r in kept:
            if not any(abs(r - v) <= tol * max(1, abs(r)) for v in values):
                return Check(route, False, "a numeric root is missing from the solutions")
    return Check(route, True)


def solve_system(ctx: Context) -> Outcome:
    import sympy

    equations = [ctx.parser.equation(e, "expressions") for e in ctx.items("expressions")]
    variables = ctx.parser.variables(ctx.args.get("variables"), equations)
    found = sympy.solve(equations, variables, dict=True)
    if len(found) > ctx.settings.max_items:
        raise SolverError("input_too_large", "the system has too many solutions to report")
    others = sorted(set().union(*(e.free_symbols for e in equations)) - set(variables), key=str)
    checks = [_system_check(equations, variables, found, others, ctx)]
    linear = all(
        sympy.Poly(e, *variables).total_degree() <= 1
        for e in equations
        if e.free_symbols & set(variables)
    )
    if linear and not others:
        matrix, rhs = sympy.linear_eq_to_matrix(equations, variables)
        rank = matrix.rank()
        augmented = matrix.row_join(rhs).rank()
        expected = 0 if augmented > rank else (1 if rank == len(variables) else None)
        if expected is None:  # a family: the unsolved variables must number n - rank
            ok = len(found) == 1 and len(variables) - len(found[0]) == len(variables) - rank
            checks.append(Check("completeness by coefficient rank", ok, "a family of solutions"))
        else:
            checks.append(Check("completeness by coefficient rank", len(found) == expected))
    else:
        ctx.notes.append(
            "completeness was not checked: the system is not linear with numeric coefficients"
        )
        checks.append(Check("completeness", False, "not checked"))
    answer = [
        {str(k): show(v) for k, v in sorted(s.items(), key=lambda kv: str(kv[0]))} for s in found
    ]
    text = "; ".join(", ".join(f"{k} = {v}" for k, v in s.items()) for s in answer) or "no solution"
    return Outcome(answer, text, checks)


def _system_check(equations, variables, found, others, ctx: Context) -> Check:
    route = "substitution into every equation (mpmath)"
    free = sorted(
        (set(others) | set().union(*(sympy_free(v) for s in found for v in s.values())))
        - set(variables),
        key=str,
    )
    unknown_left = [v for v in variables if any(v not in s for s in found)]
    free = sorted(set(free) | set(unknown_left), key=str)
    points = sample_points(free, ctx.settings, "positive") if free else [{}]
    for solution in found:
        for point in points:
            try:
                with mpmath.workdps(ctx.settings.working_digits):
                    full = dict(point)
                    for var in variables:
                        if var in solution:
                            full[var] = value(solution[var], point)
                    for eq in equations:
                        if not residual(eq, full, ctx.settings):
                            return Check(route, False, "a solution does not satisfy an equation")
            except (NotNumeric, ZeroDivisionError, ValueError):
                return Check(route, False, "a solution could not be evaluated")
    return Check(route, True)


def sympy_free(expr):
    return getattr(expr, "free_symbols", set())
