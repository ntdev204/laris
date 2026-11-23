"""Linear algebra: determinant, inverse, rank, eigenvalues, linear system A x = b.

Checks:
- determinant: Bareiss and Berkowitz (two algorithms) agree, and for a numeric matrix mpmath's LU
  determinant agrees.
- inverse: A times the inverse is the identity (exact for numeric entries, else at seeded points).
- rank: the rank equals the column count minus the nullspace dimension, and mpmath's numeric rank.
- eigenvalues: multiplicities add to n, the trace and determinant equal the sum and product of
  the eigenvalues, and det(A - lambda I) vanishes numerically for each.
- solve_linear: A x - b is zero (parameters of a family sampled).
"""

from __future__ import annotations

import mpmath

from laris.model.solver.context import Context
from laris.model.solver.errors import SolverError
from laris.model.solver.numeric import Check, NotNumeric, close, identity, sample_points, value
from laris.model.solver.result import Outcome, latex, show


def _matrix(ctx: Context, key: str = "matrix"):
    import sympy

    rows = ctx.items(key)
    if not all(isinstance(r, list) and r for r in rows):
        raise SolverError("invalid_arguments", f"{key} must be a list of non-empty rows")
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise SolverError("invalid_arguments", f"the rows of {key} must have the same length")
    size = ctx.settings.max_matrix_size
    if len(rows) > size or width > size:
        raise SolverError("input_too_large", f"{key} is larger than {size} x {size}")
    return sympy.Matrix([[ctx.parser.expression(c, f"{key} entry") for c in row] for row in rows])


def _square(m) -> None:
    if m.rows != m.cols:
        raise SolverError("invalid_arguments", "the matrix must be square")


def _numeric(m) -> bool:
    return not m.free_symbols


def _mp_matrix(m):
    return mpmath.matrix([[value(m[i, j]) for j in range(m.cols)] for i in range(m.rows)])


def _show_matrix(m):
    return [[show(m[i, j]) for j in range(m.cols)] for i in range(m.rows)]


def determinant(ctx: Context) -> Outcome:
    m = _matrix(ctx)
    _square(m)
    bareiss = m.det(method="bareiss")
    berkowitz = m.det(method="berkowitz")
    checks = [identity(bareiss, berkowitz, ctx.settings, ctx.assume, "Bareiss and Berkowitz agree")]
    if _numeric(m):
        with mpmath.workdps(ctx.settings.working_digits):
            try:
                ok = close(mpmath.det(_mp_matrix(m)), value(bareiss), ctx.settings.check_tolerance)
            except (NotNumeric, ZeroDivisionError):
                ok = False
        checks.append(Check("mpmath LU determinant", ok))
    return Outcome(show(bareiss), show(bareiss), checks, latex(bareiss))


def inverse(ctx: Context) -> Outcome:
    import sympy

    m = _matrix(ctx)
    _square(m)
    det = m.det(method="bareiss")
    if det == 0:
        raise SolverError("rejected", "the matrix is singular")
    inv = sympy.simplify(m.inv(method="LU"))
    product = sympy.simplify(m * inv)
    eye = sympy.eye(m.rows)
    if _numeric(m):
        ok = product == eye
        checks = [Check("A times the inverse is the identity (exact)", ok)]
    else:
        checks = [
            identity(
                product[i, j],
                eye[i, j],
                ctx.settings,
                ctx.assume,
                "A times the inverse is the identity",
            )
            for i in range(m.rows)
            for j in range(m.cols)
        ]
        ok = all(c.passed for c in checks)
        checks = [Check("A times the inverse is the identity (seeded points)", ok)]
    answer = _show_matrix(inv)
    return Outcome(answer, show(inv), checks, latex(inv))


def rank(ctx: Context) -> Outcome:
    m = _matrix(ctx)
    found = m.rank()
    checks = [Check("columns minus nullspace dimension", found == m.cols - len(m.nullspace()))]
    if _numeric(m):
        with mpmath.workdps(ctx.settings.working_digits):
            try:
                singular = mpmath.svd_r(_mp_matrix(m), compute_uv=False)
                tol = mpmath.mpf(10) ** (-(ctx.settings.working_digits // 2))
                top = max([abs(s) for s in singular] + [mpmath.mpf(1)])
                numeric = sum(1 for s in singular if abs(s) > tol * top)
                checks.append(Check("mpmath singular values", numeric == found))
            except (NotNumeric, ZeroDivisionError, ValueError):
                checks.append(Check("mpmath singular values", False, "not evaluated"))
    return Outcome(found, str(found), checks)


def eigenvalues(ctx: Context) -> Outcome:
    import sympy

    m = _matrix(ctx)
    _square(m)
    if not _numeric(m):
        raise SolverError("invalid_arguments", "eigenvalues need numeric entries")
    found = m.eigenvals()  # value -> algebraic multiplicity
    items = sorted(found.items(), key=lambda kv: sympy.default_sort_key(kv[0]))
    checks = [Check("multiplicities add to n", sum(found.values()) == m.rows)]
    total = sum((v * k for v, k in items), sympy.Integer(0))
    product = sympy.Integer(1)
    for v, k in items:
        product *= v**k
    checks.append(
        identity(total, m.trace(), ctx.settings, "none", "sum of eigenvalues is the trace")
    )
    checks.append(
        identity(
            product, m.det(), ctx.settings, "none", "product of eigenvalues is the determinant"
        )
    )
    with mpmath.workdps(ctx.settings.working_digits):
        a = _mp_matrix(m)
        ok = True
        for v, _ in items:
            try:
                lam = value(v)
                shifted = a - lam * mpmath.eye(m.rows)
                scale = max(mpmath.mpf(1), mpmath.mnorm(a, 1)) ** m.rows
                if (
                    abs(mpmath.det(shifted))
                    > mpmath.mpf(10) ** (-(ctx.settings.working_digits // 2)) * scale
                ):
                    ok = False
            except (NotNumeric, ZeroDivisionError):
                ok = False
        checks.append(Check("det(A - lambda I) vanishes (mpmath)", ok))
    answer = [{"value": show(v), "multiplicity": int(k)} for v, k in items]
    text = ", ".join(f"{a['value']} (x{a['multiplicity']})" for a in answer)
    return Outcome(answer, text, checks)


def solve_linear(ctx: Context) -> Outcome:
    import sympy

    m = _matrix(ctx)
    rhs_items = ctx.items("vector")
    if len(rhs_items) != m.rows:
        raise SolverError("invalid_arguments", "vector must have one entry per matrix row")
    b = sympy.Matrix([ctx.parser.expression(v, "vector entry") for v in rhs_items])
    try:
        solution, params = m.gauss_jordan_solve(b)
    except ValueError:
        raise SolverError("rejected", "the system has no solution") from None
    free = sorted(params.free_symbols | solution.free_symbols, key=str)
    points = sample_points(free, ctx.settings, "positive") if free else [{}]
    route = "A x - b vanishes (mpmath)"
    ok = True
    residual = m * solution - b
    with mpmath.workdps(ctx.settings.working_digits):
        for point in points:
            for i in range(residual.rows):
                try:
                    r = value(sympy.expand(residual[i]), point)
                except (NotNumeric, ZeroDivisionError):
                    ok = False
                    continue
                if abs(r) > ctx.settings.check_tolerance:
                    ok = False
    checks = [Check(route, ok)]
    if params.rows:
        ctx.notes.append(f"a family of solutions with {params.rows} free parameter(s) named tau")
    answer = [show(solution[i]) for i in range(solution.rows)]
    return Outcome(answer, "(" + ", ".join(answer) + ")", checks, latex(solution))
