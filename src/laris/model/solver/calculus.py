"""Calculus: differentiate, integrate, limit, sum.

Checks (numeric, independent of SymPy's symbolic step):
- differentiate: mpmath's numeric derivative of the input at seeded points.
- integrate: indefinite, mpmath's numeric derivative of the antiderivative equals the integrand;
  definite, mpmath quadrature of the integrand. When SymPy finds no closed form, the quadrature
  value is returned as a `proposal`.
- limit: the function at x0 +- 10^-k (or at 10^k for an infinite point) approaches the limit.
- sum: a finite numeric range is added term by term; an infinite one by `mpmath.nsum`; a symbolic
  upper bound is compared with the direct sum at n = 1..6.
"""

from __future__ import annotations

import mpmath

from laris.model.solver.context import Context
from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check, NotNumeric, close, point_kind, sample_points, value
from laris.model.solver.result import Outcome, latex, numeric_text, show


def _function(expr, x, point):
    def f(t):
        full = dict(point)
        full[x] = t
        return value(expr, full)

    return f


def differentiate(ctx: Context) -> Outcome:
    import sympy

    expr = ctx.expression()
    x = ctx.variable([expr])
    order = ctx.args.get("order", 1)
    if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= 10:
        raise SolverError("invalid_arguments", "order must be an integer from 1 to 10")
    result = sympy.diff(expr, x, order)
    others = sorted(expr.free_symbols - {x}, key=str)
    kind = "positive" if ctx.assume in ("none", "positive") else point_kind(ctx.assume)
    points = sample_points([x, *others], ctx.settings, kind)
    route = "mpmath numeric derivative at seeded points"
    usable, failed = 0, False
    with mpmath.workdps(ctx.settings.working_digits):
        for point in points:
            try:
                f = _function(expr, x, point)
                numeric = mpmath.diff(f, point[x], order)
                symbolic = value(result, point)
            except (NotNumeric, ZeroDivisionError, ValueError):
                continue
            usable += 1
            if not close(numeric, symbolic, ctx.settings.quad_tolerance):
                failed = True
                break
    ok = not failed and usable >= max(1, len(points) // 2)
    checks = [Check(route, ok, "" if ok else "the numeric derivative differs")]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )


def _bound(ctx: Context, key: str):
    import sympy

    raw = ctx.args.get(key)
    if raw is None:
        return None
    if raw in ("oo", "inf", "+oo"):
        return sympy.oo
    if raw in ("-oo", "-inf"):
        return -sympy.oo
    return ctx.parser.expression(raw, key)


def _mp(bound):
    import sympy

    if bound == sympy.oo:
        return mpmath.inf
    if bound == -sympy.oo:
        return -mpmath.inf
    return value(bound)


def integrate(ctx: Context) -> Outcome:
    import sympy

    expr = ctx.expression()
    x = ctx.variable([expr])
    lower, upper = _bound(ctx, "lower"), _bound(ctx, "upper")
    if (lower is None) != (upper is None):
        raise SolverError("invalid_arguments", "give both lower and upper, or neither")
    if lower is None:
        result = sympy.integrate(expr, x)
        if result.has(sympy.Integral):
            raise SolverError("rejected", "no closed-form antiderivative was found")
        others = sorted(expr.free_symbols - {x}, key=str)
        points = sample_points([x, *others], ctx.settings, "positive")
        usable, failed = 0, False
        with mpmath.workdps(ctx.settings.working_digits):
            for point in points:
                try:
                    derivative = mpmath.diff(_function(result, x, point), point[x])
                    integrand = value(expr, point)
                except (NotNumeric, ZeroDivisionError, ValueError):
                    continue
                usable += 1
                if not close(derivative, integrand, ctx.settings.quad_tolerance):
                    failed = True
                    break
        ok = not failed and usable >= max(1, len(points) // 2)
        checks = [Check("mpmath derivative of the antiderivative", ok)]
        ctx.notes.append("an antiderivative; any constant may be added")
        return Outcome(show(result), show(result), checks, latex(result))
    if expr.free_symbols - {x} or lower.free_symbols or upper.free_symbols:
        result = sympy.integrate(expr, (x, lower, upper))
        ctx.notes.append("symbolic bounds or parameters: not checked numerically")
        return Outcome(show(result), show(result), [], latex(result))
    with mpmath.workdps(ctx.settings.working_digits):
        try:
            quad = mpmath.quad(_function(expr, x, {}), [_mp(lower), _mp(upper)])
        except (NotNumeric, ZeroDivisionError, ValueError):
            quad = None
    result = sympy.integrate(expr, (x, lower, upper))
    if result.has(sympy.Integral):
        if quad is None:
            raise SolverError("rejected", "the integral has no closed form and no numeric value")
        text = mpmath.nstr(quad, ctx.settings.output_digits)
        ctx.notes.append("no closed form was found; the value is numeric quadrature only")
        return Outcome(text, text, [], None, text)
    if quad is None:
        return Outcome(
            show(result), show(result), [Check("mpmath quadrature", False, "no numeric value")]
        )
    with mpmath.workdps(ctx.settings.working_digits):
        try:
            ok = close(value(result), quad, ctx.settings.quad_tolerance)
        except NotNumeric:
            ok = False
    checks = [Check("mpmath quadrature", ok)]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )


def limit(ctx: Context) -> Outcome:
    import sympy

    expr = ctx.expression()
    x = ctx.variable([expr])
    point = _bound(ctx, "point")
    if point is None:
        raise SolverError("invalid_arguments", "this operation needs point")
    direction = ctx.args.get("direction", "+-")
    if direction not in ("+", "-", "+-"):
        raise SolverError("invalid_arguments", "direction must be +, - or +-")
    if point.free_symbols or expr.free_symbols - {x}:
        raise SolverError("invalid_arguments", "a limit needs a numeric point and one variable")
    infinite = point in (sympy.oo, -sympy.oo)
    try:
        result = sympy.limit(expr, x, point, "+" if infinite else direction)
    except ValueError:
        raise SolverError(
            "rejected", "the limit does not exist (the one-sided limits differ)"
        ) from None
    sides = ["+"] if infinite else (["+", "-"] if direction == "+-" else [direction])
    ok = all(_approaches(expr, x, point, result, side, ctx) for side in sides)
    checks = [Check("mpmath values approaching the point", ok)]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )


def _approaches(expr, x, point, result, side: str, ctx: Context) -> bool:
    import sympy

    digits = ctx.settings.working_digits
    steps = (digits // 6, digits // 4, digits // 3)
    with mpmath.workdps(digits * 2):
        f = _function(expr, x, {})
        try:
            if point == sympy.oo:
                samples = [f(mpmath.mpf(10) ** k) for k in steps]
            elif point == -sympy.oo:
                samples = [f(-(mpmath.mpf(10) ** k)) for k in steps]
            else:
                x0 = value(point)
                sign = 1 if side == "+" else -1
                samples = [f(x0 + sign * mpmath.mpf(10) ** (-k)) for k in steps]
        except (NotNumeric, ZeroDivisionError, ValueError):
            return False
        if result in (sympy.oo, -sympy.oo):
            want = 1 if result == sympy.oo else -1
            reals = []
            for s in samples:
                if abs(mpmath.im(s)) > 0:
                    return False
                reals.append(mpmath.re(s) * want)
            return reals[0] < reals[1] < reals[2] and reals[2] > 10**6
        try:
            target = value(result)
        except NotNumeric:
            return False
        errors = [abs(s - target) for s in samples]
        scale = max(1, abs(target))
        return errors[-1] <= ctx.settings.limit_tolerance * scale and errors[-1] <= errors[
            0
        ] + mpmath.mpf(10) ** (-digits)


def summation(ctx: Context) -> Outcome:
    import sympy

    expr = ctx.expression()
    k = ctx.variable([expr])
    lower, upper = _bound(ctx, "lower"), _bound(ctx, "upper")
    if lower is None or upper is None:
        raise SolverError("invalid_arguments", "a sum needs lower and upper")
    result = sympy.summation(expr, (k, lower, upper))
    if result.has(sympy.Sum):
        raise SolverError("rejected", "no closed form for the sum was found")
    route_ok, route = False, ""
    params = expr.free_symbols - {k}
    with mpmath.workdps(ctx.settings.working_digits):
        try:
            if not params and not lower.free_symbols and upper == sympy.oo and lower.is_Integer:
                route = "mpmath nsum"
                total = mpmath.nsum(_function(expr, k, {}), [int(lower), mpmath.inf])
                route_ok = close(value(result), total, ctx.settings.quad_tolerance)
            elif not params and lower.is_Integer and upper.is_Integer:
                count = int(upper) - int(lower) + 1
                if count > ctx.settings.max_sum_terms:
                    route = "direct sum (too many terms; not run)"
                else:
                    route = "direct term-by-term sum"
                    f = _function(expr, k, {})
                    total = mpmath.fsum(f(mpmath.mpf(i)) for i in range(int(lower), int(upper) + 1))
                    route_ok = close(value(result), total, ctx.settings.check_tolerance)
            elif (
                lower.is_Integer
                and upper.free_symbols
                and len(upper.free_symbols) == 1
                and not params
            ):
                (n,) = upper.free_symbols
                route = "direct sum at n = 1..6"
                f = _function(expr, k, {})
                route_ok = True
                for m in range(1, 7):
                    stop = int(upper.subs(n, m))
                    total = mpmath.fsum(f(mpmath.mpf(i)) for i in range(int(lower), stop + 1))
                    if not close(
                        value(result, {n: mpmath.mpf(m)}), total, ctx.settings.check_tolerance
                    ):
                        route_ok = False
                        break
            else:
                route = "not checked (parameters)"
        except (NotNumeric, ZeroDivisionError, ValueError):
            route_ok = False
    checks = [Check(route or "numeric sum", route_ok)]
    return Outcome(
        show(result), show(result), checks, latex(result), numeric_text(result, ctx.settings)
    )
