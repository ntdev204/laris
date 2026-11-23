"""T276: fixture problems per domain give the known answer, verified by the independent route."""

import pytest

from laris.model.solver import SolverError, SolverSettings, solve

S = SolverSettings(isolate=False)


def ask(**problem):
    return solve(problem, S)


def verified(**problem):
    out = ask(**problem)
    assert out["status"] == "verified", out
    assert out["checks"] and all(c["passed"] for c in out["checks"])
    return out


# -- algebra ---------------------------------------------------------------------------------------
def test_evaluate_is_exact_and_numeric():
    out = verified(operation="evaluate", expression="2^10 + sqrt(8)")
    assert out["answer"] == "2*sqrt(2) + 1024" and out["numeric"].startswith("1026.828427")
    assert verified(operation="evaluate", expression="0.1 + 0.2")["answer"] == "3/10"
    assert verified(operation="evaluate", expression="Mod(7^222, 10)")["answer"] == "9"


def test_evaluate_with_a_codata_constant_names_its_source():
    out = verified(
        operation="evaluate", expression="m*c^2", substitutions={"m": "2", "c": {"constant": "c"}}
    )
    assert out["answer"] == str(2 * 299792458**2)
    assert out["sources"][0]["name"] == "CODATA 2022 (NIST)"


@pytest.mark.parametrize(
    "operation, expression, answer",
    [
        ("simplify", "(x^2 - 1)/(x - 1)", "x + 1"),
        ("simplify", "sin(x)^2 + cos(x)^2", "1"),
        ("expand", "(x + 1)^3", "x^3 + 3*x^2 + 3*x + 1"),
        ("factor", "x^3 - 6x^2 + 11x - 6", "(x - 3)*(x - 2)*(x - 1)"),
    ],
)
def test_rewrites(operation, expression, answer):
    assert verified(operation=operation, expression=expression)["answer"] == answer


def test_solve_real_and_complex():
    assert verified(operation="solve", expression="x^2 - 5x + 6 = 0")["answer"] == ["2", "3"]
    assert verified(operation="solve", expression="x^2 + 1")["answer"] == []
    assert verified(operation="solve", expression="x^2 + 1", domain="complex")["answer"] == [
        "-I",
        "I",
    ]
    assert verified(operation="solve", expression="(x^2 - 1)/(x - 1) = 0")["answer"] == ["-1"]
    out = verified(operation="solve", expression="x^3 = 2x")
    assert out["answer"] == ["0", "-sqrt(2)", "sqrt(2)"] or sorted(out["answer"]) == sorted(
        ["0", "-sqrt(2)", "sqrt(2)"]
    )


def test_solve_keeps_a_periodic_or_transcendental_set_a_proposal():
    assert ask(operation="solve", expression="sin(x) = 1/2")["status"] == "proposal"
    out = ask(operation="solve", expression="exp(x) = 2")
    assert out["answer"] == ["log(2)"] and out["status"] == "proposal"
    assert any(c["route"] == "completeness" and not c["passed"] for c in out["checks"])


def test_solve_system():
    out = verified(operation="solve_system", expressions=["x + y = 3", "x - y = 1"])
    assert out["answer"] == [{"x": "2", "y": "1"}]
    out = ask(operation="solve_system", expressions=["x^2 + y^2 = 25", "x - y = 1"])
    assert out["status"] == "proposal" and len(out["answer"]) == 2  # non-linear: not complete


# -- calculus --------------------------------------------------------------------------------------
def test_calculus():
    assert verified(operation="differentiate", expression="x^3*sin(x)")["answer"] == (
        "x^3*cos(x) + 3*x^2*sin(x)"
    )
    assert verified(operation="differentiate", expression="x^4", order=2)["answer"] == "12*x^2"
    assert verified(operation="integrate", expression="x*exp(x)")["answer"] == "(x - 1)*exp(x)"
    assert verified(operation="integrate", expression="x^2", lower="0", upper="3")["answer"] == "9"
    assert (
        verified(operation="integrate", expression="exp(-x^2)", lower="-oo", upper="oo")["answer"]
        == "sqrt(pi)"
    )
    assert verified(operation="limit", expression="sin(x)/x", point="0")["answer"] == "1"
    assert verified(operation="limit", expression="(1 + 1/n)^n", point="oo")["answer"] == "E"
    assert verified(operation="limit", expression="1/x", point="0", direction="+")["answer"] == "oo"
    assert (
        verified(operation="sum", expression="1/k^2", lower="1", upper="oo")["answer"] == "pi^2/6"
    )
    assert verified(operation="sum", expression="k^2", lower="1", upper="10")["answer"] == "385"
    assert (
        verified(operation="sum", expression="k", lower="1", upper="n")["answer"] == "n^2/2 + n/2"
    )


def test_a_two_sided_limit_that_does_not_exist_is_refused():
    with pytest.raises(SolverError) as caught:
        ask(operation="limit", expression="abs(x)/x", point="0")
    assert caught.value.code == "rejected"
    assert (
        verified(operation="limit", expression="abs(x)/x", point="0", direction="-")["answer"]
        == "-1"
    )


def test_definite_integral_without_closed_form_is_a_numeric_proposal():
    out = ask(operation="integrate", expression="sin(sin(x))", lower="0", upper="1")
    assert out["status"] == "proposal"
    assert out["numeric"].startswith("0.43060610312069")


# -- linear algebra --------------------------------------------------------------------------------
def test_linear_algebra():
    assert verified(operation="determinant", matrix=[["1", "2"], ["3", "4"]])["answer"] == "-2"
    assert (
        verified(operation="determinant", matrix=[["a", "b"], ["c", "d"]])["answer"] == "a*d - b*c"
    )
    assert verified(operation="inverse", matrix=[["1", "2"], ["3", "4"]])["answer"] == [
        ["-2", "1"],
        ["3/2", "-1/2"],
    ]
    assert verified(operation="rank", matrix=[["1", "2"], ["2", "4"]])["answer"] == 1
    assert verified(operation="eigenvalues", matrix=[["2", "1"], ["1", "2"]])["answer"] == [
        {"value": "1", "multiplicity": 1},
        {"value": "3", "multiplicity": 1},
    ]
    assert verified(operation="solve_linear", matrix=[[1, 1], [1, -1]], vector=[3, 1])[
        "answer"
    ] == [
        "2",
        "1",
    ]
    with pytest.raises(SolverError) as caught:
        ask(operation="inverse", matrix=[["1", "2"], ["2", "4"]])
    assert caught.value.code == "rejected"


# -- number theory ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "problem, answer",
    [
        ({"operation": "gcd", "integers": [84, 126, 210]}, 42),
        ({"operation": "lcm", "integers": [4, 6, 10]}, 60),
        ({"operation": "is_prime", "integer": 2**61 - 1}, True),
        ({"operation": "is_prime", "integer": 561}, False),
        ({"operation": "mod_pow", "base": 3, "exponent": 200, "modulus": 13}, 9),
        ({"operation": "mod_inverse", "integer": 3, "modulus": 11}, 4),
        ({"operation": "totient", "integer": 36}, 12),
        ({"operation": "binomial", "n": 8, "k": 4}, 70),
        ({"operation": "factorial", "integer": 10}, 3628800),
        ({"operation": "from_base", "digits": "ff", "base": 16}, 255),
        ({"operation": "to_base", "integer": 255, "base": 2}, "11111111"),
    ],
)
def test_number_theory(problem, answer):
    assert verified(**problem)["answer"] == answer


def test_factorisation_divisors_and_crt():
    out = verified(operation="factor_integer", integer="360")
    assert out["answer"] == [
        {"prime": 2, "exponent": 3},
        {"prime": 3, "exponent": 2},
        {"prime": 5, "exponent": 1},
    ]
    assert verified(operation="divisors", integer=28)["answer"] == {
        "divisors": [1, 2, 4, 7, 14, 28],
        "count": 6,
        "sum": 56,
    }
    assert verified(operation="crt", integers=[2, 3, 2], moduli=[3, 5, 7])["answer"] == {
        "residue": 23,
        "modulus": 105,
    }


def test_a_factor_beyond_the_deterministic_bound_stays_a_proposal():
    big = 2**89 - 1  # a Mersenne prime above 3.3e24
    assert ask(operation="is_prime", integer=str(big))["status"] == "proposal"


# -- units, constants ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, unit, target, answer",
    [
        ("60", "km/h", "m/s", "50/3"),
        ("1", "atm", "Torr", "760"),
        ("1", "eV", "J", "1.602176634e-19"),
        ("1", "kcal/mol", "kJ mol^-1", "523/125"),
        ("3", "ft", "in", "36"),
        ("2", "L", "cm^3", "2000"),
        ("1", "mi", "km", "25146/15625"),
        ("100", "degC", "degF", "212"),
        ("0", "K", "degC", "-273.15"),
        ("1", "kW h", "MJ", "18/5"),
    ],
)
def test_unit_conversion(value, unit, target, answer):
    import sympy

    out = verified(operation="convert_unit", value=value, unit=unit, target_unit=target)
    assert (
        sympy.Rational(out["answer"].replace("^", "**")) == sympy.Rational(answer)
        or sympy.N(sympy.sympify(out["answer"].replace("^", "**")) - sympy.Rational(answer)) == 0
    )


def test_incompatible_units_are_refused_and_unknown_units_named():
    with pytest.raises(SolverError) as caught:
        ask(operation="convert_unit", value="1", unit="kg", target_unit="m")
    assert "incompatible dimensions" in caught.value.message
    with pytest.raises(SolverError):
        ask(operation="convert_unit", value="1", unit="furlong", target_unit="m")


def test_dimension_and_constants():
    out = verified(operation="dimension", unit="J mol^-1 K^-1")
    assert out["answer"]["dimension"] == {"m": 2, "kg": 1, "s": -2, "K": -1, "mol": -1}
    g = verified(operation="constant", constant="G")["answer"]
    assert (
        g["value"] == "6.67430e-11" and g["uncertainty"] == "0.00015e-11" and g["release"] == "2022"
    )
    assert (
        verified(operation="constant", constant="electron mass")["answer"]["value"]
        == "9.1093837139e-31"
    )
    r = verified(operation="constant", constant="R")
    assert r["answer"]["exact"] and r["answer"]["truncated"] and r["notes"]
    with pytest.raises(SolverError) as caught:
        ask(operation="constant", constant="proton")
    assert "several" in caught.value.message


# -- chemistry -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reaction, equation",
    [
        ("C3H8 + O2 -> CO2 + H2O", "C3H8 + 5 O2 -> 3 CO2 + 4 H2O"),
        ("Fe + O2 -> Fe2O3", "4 Fe + 3 O2 -> 2 Fe2O3"),
        ("Ca(OH)2 + H3PO4 -> Ca3(PO4)2 + H2O", "3 Ca(OH)2 + 2 H3PO4 -> Ca3(PO4)2 + 6 H2O"),
        ("CuSO4·5H2O -> CuSO4 + H2O", "CuSO4·5H2O -> CuSO4 + 5 H2O"),
        (
            "MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O",
            "MnO4^- + 5 Fe^2+ + 8 H^+ -> Mn^2+ + 5 Fe^3+ + 4 H2O",
        ),
    ],
)
def test_balance(reaction, equation):
    assert verified(operation="balance", reaction=reaction)["answer"]["equation"] == equation


def test_stoichiometry_and_unbalanceable_reactions():
    out = verified(
        operation="stoichiometry",
        reaction="H2 + O2 -> H2O",
        species="O2",
        amount="1.5",
        molar_masses={"H2O": "18"},
    )
    assert out["answer"]["moles"] == {"H2": "3", "O2": "3/2", "H2O": "3"}
    # H2 and O2 from the CIAAW table, H2O from the caller
    assert out["answer"]["grams"] == {"H2": "6.048", "O2": "47.997", "H2O": "54"}
    assert out["sources"][0]["name"] == "CIAAW Abridged Standard Atomic Weights 2024"
    grams = verified(
        operation="stoichiometry",
        reaction="C3H8 + O2 -> CO2 + H2O",
        species="C3H8",
        amount="44.097",
        amount_unit="g",
    )
    assert grams["answer"]["moles"]["CO2"] == "3" and grams["answer"]["grams"]["H2O"] == "72.06"
    with pytest.raises(SolverError):
        ask(operation="balance", reaction="H2 -> O2")
    with pytest.raises(SolverError):
        ask(operation="balance", reaction="Xx + O2 -> XxO")


@pytest.mark.parametrize(
    "formula, value",
    [
        ("H2O", "18.015"),
        ("CO2", "44.009"),
        ("NaCl", "58.44"),
        ("CuSO4·5H2O", "249.677"),
        ("Ca3(PO4)2", "310.174"),
        ("SO4^2-", "96.056"),
        ("C6H12O6", "180.156"),
    ],
)
def test_molar_mass_from_ciaaw(formula, value):
    out = verified(operation="molar_mass", formula=formula)
    assert out["answer"]["value"] == value and out["answer"]["unit"] == "g/mol"
    assert out["sources"][0]["url"] == "https://www.ciaaw.org/abridged-atomic-weights.htm"


def test_an_element_without_a_standard_atomic_weight_has_no_molar_mass():
    with pytest.raises(SolverError) as caught:
        ask(operation="molar_mass", formula="TcO4^-")
    assert "no standard atomic weight" in caught.value.message
