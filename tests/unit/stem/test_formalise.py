"""T276: the model-free path formalises only questions it fully understands, and answers only with
verified solver results. The questions are written for the test (no benchmark text)."""

import pytest

from laris.model.solver import SolverSettings
from laris.research.stem.answers import math_equivalent
from laris.research.stem.formalise import answer_model_free, formalise, latex_to_solver

S = SolverSettings(isolate=False)


@pytest.mark.parametrize(
    "latex, expected",
    [
        (r"2\cdot 3", "2 * 3"),
        (r"\frac56", "(5/6)"),
        (r"\sin 30^\circ", "sin((30*pi/180))"),
        (r"\log_3 81", "log(81, 3)"),
        (r"\dbinom{10}{3}", "binomial((10), (3))"),
        (r"\sqrt[3]{27}", "root((27), 3)"),
        (r"\left\lfloor 7.5 \right\rfloor", "floor(7.5)"),
        (r"5!", "factorial(5)"),
    ],
)
def test_latex_subset(latex, expected):
    assert latex_to_solver(latex) == expected


@pytest.mark.parametrize(
    "latex",
    [
        r"1 + 2 + \cdots + 9",
        r"\text{cm}",
        r"\log 5",
        r"\sin^2 x",
        r"\overline{3}",
        r"\sum_{n=1}^5 n",
        r"\timesx",
    ],
)
def test_unknown_latex_is_refused(latex):
    assert latex_to_solver(latex) is None


@pytest.mark.parametrize(
    "question, gold",
    [
        ("Compute $\\dbinom{10}{3}$.", "120"),
        ("Evaluate $\\log_3 81$.", "4"),
        ("What is $12 \\div 4 \\cdot 3$?", "9"),
        ("Compute $\\cos 60^\\circ$.", "\\frac{1}{2}"),
        ("Find the greatest common divisor of 48 and 180.", "12"),
        ("What is the least common multiple of 4 and 6?", "12"),
        ("What is the remainder when $3^{100}$ is divided by $7$?", "4"),
        ("What is the largest prime factor of $221$?", "17"),
        ("Convert $100_{10}$ to base 7.", "202_7"),
        ("How many positive divisors does 36 have?", "9"),
        ("What is the sum of the proper divisors of 28?", "28"),
        ("Solve for $y$: $3y + 4 = 19$.", "5"),
        ("Expand the product $(x+2)(x-3)$.", "x^2 - x - 6"),
        ("Express $\\frac{9}{12}+\\frac16$ as a common fraction.", "\\frac{11}{12}"),
    ],
)
def test_formalised_questions_answer_correctly(question, gold):
    out = answer_model_free({"question": question, "options": []}, S)
    assert out["status"] == "verified", out
    assert math_equivalent(out["answer"], gold), out


@pytest.mark.parametrize(
    "question",
    [
        "Evaluate $99\\times 99$ in your head.",  # trailing words
        "What is $\\frac56$ of 30?",
        "If $x^2 - 2x = 0$ and $x \\neq 0$, what is the value of $x$?",
        "Simplify $1-(1+x)$.",  # a variable: not a number
        "Compute $1 + 2 + \\cdots + 10$.",
        "Find the remainder when $x^{10}$ is divided by $7$.",
        "Convert $314_{8}$ to base 6.",  # only base 10 sources
    ],
)
def test_questions_outside_the_patterns_are_left_to_the_model(question):
    assert formalise({"question": question, "options": []}) is None


def test_a_solution_set_with_two_roots_gives_no_answer():
    out = answer_model_free({"question": "Solve for $x$: $x^2 = 4$.", "options": []}, S)
    assert out["status"] == "verified" and out["answer"] is None


def test_multiple_choice_items_are_not_formalised():
    assert formalise({"question": "Compute $2+2$.", "options": ["3", "4"]}) is None
