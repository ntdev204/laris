"""Answer extraction and MATH equivalence fixtures (T275, protocol math-equiv-1)."""

import pytest

from laris.research.stem.answers import (
    extract_choice,
    extract_math_answer,
    last_boxed,
    latex_to_expr,
    math_equivalent,
    normalise,
)


def test_last_boxed_balances_braces_and_takes_the_last():
    assert last_boxed(r"first \boxed{1} then \boxed{\frac{1}{2}}.") == r"\frac{1}{2}"
    assert last_boxed(r"so \boxed 5$") == "5"
    assert last_boxed(r"\fbox{x+1}") == "x+1"
    assert last_boxed("no box here") is None
    assert last_boxed(r"\boxed{unclosed") is None


def test_extract_math_answer_falls_back_to_final_answer_phrase():
    assert extract_math_answer(r"... \boxed{42}") == "42"
    assert extract_math_answer("Thus the final answer is $7$.") == "7"
    assert extract_math_answer("I do not know") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Reasoning...\nAnswer: C", "C"),
        ("The answer is (B).", "B"),
        ("**Answer: D**", "D"),
        (r"Answer: $\boxed{A}$", "A"),
        (r"so it is \boxed{\text{B}}", "B"),
        ("Long text\n\n(C)", "C"),
        ("Answer: A\nWait, re-checking. Answer: B", "B"),
        ("I think A is wrong and so is B.", None),
        ("Answer: K", None),
    ],
)
def test_extract_choice(text, expected):
    assert extract_choice(text, "ABCD") == expected


def test_extract_choice_takes_ten_letters():
    assert extract_choice("Answer: J", "ABCDEFGHIJ") == "J"


@pytest.mark.parametrize(
    "pred,gold",
    [
        (r"\frac{1}{2}", r"\dfrac12"),
        ("0.5", r"\frac{1}{2}"),
        (".5", "1/2"),
        (r"\left( 3, \frac{\pi}{2} \right)", r"(3,\frac{\pi}{2})"),
        ("x = 5", "5"),
        (r"10\text{ cm}", "10"),
        (r"90^\circ", "90"),
        (r"30\%", "30"),
        (r"\$18.90", "18.90"),
        ("1,000", "1000"),
        ("2, 1", "1, 2"),
        (r"\{1,2\}", r"\{2,1\}"),
        (r"2\sqrt{2}", r"\sqrt{8}"),
        (r"\sqrt[3]{8}", "2"),
        ("2x+2", "2(x+1)"),
        (r"x^2-1", "(x-1)(x+1)"),
        (r"\frac{\sqrt{3}}{2}", r"\frac{\sqrt3}{2}"),
        (r"\text{Monday}", "monday"),
        (r"\begin{pmatrix} 1 \\ 2 \end{pmatrix}", r"\begin{pmatrix}1\\2\end{pmatrix}"),
        ("y=2x+3", "y = 2x + 3"),
        ("5.0", "5"),
        (r"[1, 3)", r"[1,3)"),
    ],
)
def test_equivalent_pairs(pred, gold):
    assert math_equivalent(pred, gold)


@pytest.mark.parametrize(
    "pred,gold",
    [
        ("3", "4"),
        (r"\frac{1}{3}", "0.33"),
        ("(1,2)", "(2,1)"),
        ("[1,3)", "(1,3)"),
        ("1, 2", "1, 2, 3"),
        ("2x", "2y"),
        ("x^2", "x^3"),
        (r"\text{Monday}", "Tuesday"),
        ("5x", "5"),
        (None, "5"),
        ("", "5"),
        (r"\begin{pmatrix} 1 \\ 2 \end{pmatrix}", r"\begin{pmatrix}2\\1\end{pmatrix}"),
    ],
)
def test_not_equivalent_pairs(pred, gold):
    assert not math_equivalent(pred, gold)


def test_latex_to_expr_refuses_python_and_unknown_names():
    assert latex_to_expr("__import__('os').system('true')") is None
    assert latex_to_expr("eval(1)") is None
    assert latex_to_expr(r"\alpha + 1") is None
    assert latex_to_expr("9^9^9^9^9") is None
    assert latex_to_expr(r"\frac{1}{2}") == "((1)/(2))"


def test_hostile_answer_is_not_equivalent_and_does_not_run():
    assert not math_equivalent("__import__('os').system('false')", "0")


def test_power_tower_does_not_stall():
    assert not math_equivalent("9^{9^{9}}", "1", timeout_s=2)


def test_normalise_is_stable():
    assert normalise(r"\left[ 1, 2 \right]") == "[1,2]"
    assert normalise(r"\text{(C)}") == "(C)"
    assert normalise("k = 3.") == "3"


def test_overflowing_values_are_not_equivalent():
    assert not math_equivalent("10^{400}", "10^{401}")
