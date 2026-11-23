"""T276: the verification routes reject seeded wrong results.

Each test replaces the primary (symbolic) route with one that returns a wrong answer and checks
that the independent route notices: the answer becomes a `proposal` with a failed check, never a
`verified` wrong answer."""

import pytest
import sympy

from laris.model.solver import SolverSettings, chemistry, number_theory, solve

S = SolverSettings(isolate=False)
x = sympy.Symbol("x")


def rejected(problem):
    out = solve(problem, S)
    assert out["status"] == "proposal", out
    assert any(not c["passed"] for c in out["checks"])
    return out


def test_wrong_simplification(monkeypatch):
    monkeypatch.setattr(sympy, "simplify", lambda e, *a, **k: e + sympy.Rational(1, 10**12))
    rejected({"operation": "simplify", "expression": "(x^2 - 1)/(x - 1)"})
    rejected({"operation": "evaluate", "expression": "2 + 2"})


def test_wrong_factorisation(monkeypatch):
    monkeypatch.setattr(sympy, "factor", lambda e, *a, **k: (x - 1) * (x - 2) * (x - 4))
    rejected({"operation": "factor", "expression": "x^3 - 6x^2 + 11x - 6"})


def test_wrong_and_missing_roots(monkeypatch):
    real = sympy.solveset
    monkeypatch.setattr(sympy, "solveset", lambda *a, **k: sympy.FiniteSet(2, 4))
    rejected({"operation": "solve", "expression": "x^2 - 5x + 6 = 0"})
    monkeypatch.setattr(sympy, "solveset", lambda *a, **k: sympy.FiniteSet(2))
    out = rejected({"operation": "solve", "expression": "x^2 - 5x + 6 = 0"})
    assert any("completeness" in c["route"] and not c["passed"] for c in out["checks"])
    monkeypatch.setattr(sympy, "solveset", real)


def test_wrong_system_solution(monkeypatch):
    monkeypatch.setattr(
        sympy, "solve", lambda *a, **k: [{sympy.Symbol("x"): 2, sympy.Symbol("y"): 2}]
    )
    rejected({"operation": "solve_system", "expressions": ["x + y = 3", "x - y = 1"]})


def test_wrong_calculus(monkeypatch):
    monkeypatch.setattr(sympy, "diff", lambda e, *a, **k: 3 * x**2 * sympy.sin(x))
    rejected({"operation": "differentiate", "expression": "x^3*sin(x)"})
    monkeypatch.undo()
    monkeypatch.setattr(sympy, "integrate", lambda *a, **k: x * sympy.exp(x))
    rejected({"operation": "integrate", "expression": "x*exp(x)"})
    monkeypatch.setattr(sympy, "integrate", lambda *a, **k: sympy.Integer(10))
    rejected({"operation": "integrate", "expression": "x^2", "lower": "0", "upper": "3"})
    monkeypatch.undo()
    monkeypatch.setattr(sympy, "limit", lambda *a, **k: sympy.Integer(2))
    rejected({"operation": "limit", "expression": "sin(x)/x", "point": "0"})
    monkeypatch.undo()
    monkeypatch.setattr(sympy, "summation", lambda *a, **k: sympy.pi**2 / 7)
    rejected({"operation": "sum", "expression": "1/k^2", "lower": "1", "upper": "oo"})
    monkeypatch.setattr(sympy, "summation", lambda *a, **k: sympy.Integer(386))
    rejected({"operation": "sum", "expression": "k^2", "lower": "1", "upper": "10"})


def test_wrong_linear_algebra(monkeypatch):
    monkeypatch.setattr(
        sympy.Matrix,
        "det",
        lambda self, method="bareiss": (
            sympy.Integer(-3) if method == "bareiss" else sympy.Integer(-2)
        ),
    )
    rejected({"operation": "determinant", "matrix": [["1", "2"], ["3", "4"]]})
    monkeypatch.undo()
    monkeypatch.setattr(
        sympy.Matrix, "eigenvals", lambda self: {sympy.Integer(1): 1, sympy.Integer(4): 1}
    )
    rejected({"operation": "eigenvalues", "matrix": [["2", "1"], ["1", "2"]]})
    monkeypatch.undo()
    monkeypatch.setattr(sympy.Matrix, "rank", lambda self, **k: 2)
    rejected({"operation": "rank", "matrix": [["1", "2"], ["2", "4"]]})
    monkeypatch.undo()
    monkeypatch.setattr(sympy.Matrix, "inv", lambda self, **k: sympy.Matrix([[-2, 1], [1, 0]]))
    rejected({"operation": "inverse", "matrix": [["1", "2"], ["3", "4"]]})


def test_wrong_number_theory(monkeypatch):
    monkeypatch.setattr(sympy, "igcd", lambda a, b: 21)
    rejected({"operation": "gcd", "integers": [84, 126]})
    monkeypatch.setattr(sympy, "factorint", lambda n: {2: 3, 3: 2, 7: 1})
    rejected({"operation": "factor_integer", "integer": 360})
    monkeypatch.setattr(sympy, "factorint", lambda n: {4: 1, 9: 1})  # product right, not primes
    rejected({"operation": "factor_integer", "integer": 36})
    monkeypatch.undo()
    monkeypatch.setattr(sympy, "isprime", lambda n: True)
    rejected({"operation": "is_prime", "integer": 561})
    monkeypatch.setattr(sympy, "totient", lambda n: 13)
    rejected({"operation": "totient", "integer": 36})
    monkeypatch.setattr(sympy, "binomial", lambda n, k: 71)
    rejected({"operation": "binomial", "n": 8, "k": 4})
    monkeypatch.setattr(sympy, "mod_inverse", lambda a, m: 5)
    rejected({"operation": "mod_inverse", "integer": 3, "modulus": 11})


def test_wrong_crt(monkeypatch):
    import sympy.ntheory.modular as modular

    monkeypatch.setattr(modular, "crt", lambda *a, **k: (24, 105))
    rejected({"operation": "crt", "integers": [2, 3, 2], "moduli": [3, 5, 7]})


def test_wrong_unit_factor(monkeypatch):
    from laris.model.solver import quantities

    table = quantities._table

    def seeded():
        out = dict(table())
        factor, dims, prefixable, route = out["mi"]
        out["mi"] = (factor * sympy.Rational(1001, 1000), dims, prefixable, route)
        return out

    monkeypatch.setattr(quantities, "_table", seeded)
    rejected({"operation": "convert_unit", "value": "1", "unit": "mi", "target_unit": "km"})


def test_wrong_balance(monkeypatch):
    real = chemistry.balance_reaction

    def seeded(reaction, max_items):
        left, right, coefficients = real(reaction, max_items)
        coefficients = list(coefficients)
        coefficients[0] += 1
        return left, right, coefficients

    monkeypatch.setattr(chemistry, "balance_reaction", seeded)
    rejected({"operation": "balance", "reaction": "C3H8 + O2 -> CO2 + H2O"})


def test_miller_rabin_agrees_with_known_primes_and_pseudoprimes():
    primes = [2, 3, 97, 7919, 2**31 - 1, 2**61 - 1, 1_000_000_007]
    composites = [1, 4, 561, 1105, 3215031751, 2**32 + 1, 3825123056546413051]
    assert all(number_theory.miller_rabin(p) for p in primes)
    assert not any(number_theory.miller_rabin(c) for c in composites)


def test_codata_table_with_a_changed_hash_is_refused(tmp_path):
    from laris.model.solver import SolverError
    from laris.model.solver.constants import PACKAGED

    changed = tmp_path / "codata.txt"
    changed.write_bytes(PACKAGED.read_bytes().replace(b"6.674 30 e-11", b"6.674 31 e-11"))
    settings = SolverSettings(isolate=False, codata_file=str(changed))
    with pytest.raises(SolverError) as caught:
        solve({"operation": "constant", "constant": "G"}, settings)
    assert "SHA-256" in caught.value.message


def test_wrong_molar_mass(monkeypatch):
    real = chemistry._mass

    def seeded(counts, weights):
        value, uncertainty = real(counts, weights)
        return value + sympy.Rational(1, 1000), uncertainty

    monkeypatch.setattr(chemistry, "_mass", seeded)
    rejected({"operation": "molar_mass", "formula": "H2O"})
    rejected(
        {"operation": "stoichiometry", "reaction": "H2 + O2 -> H2O", "species": "O2", "amount": "1"}
    )


def test_atomic_weights_table_with_a_changed_hash_is_refused(tmp_path):
    from laris.model.solver import SolverError
    from laris.model.solver.elements import PACKAGED

    changed = tmp_path / "weights.tsv"
    changed.write_bytes(PACKAGED.read_bytes().replace(b"15.999", b"15.990"))
    settings = SolverSettings(isolate=False, atomic_weights_file=str(changed))
    with pytest.raises(SolverError) as caught:
        solve({"operation": "molar_mass", "formula": "H2O"}, settings)
    assert "SHA-256" in caught.value.message
