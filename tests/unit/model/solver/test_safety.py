"""T276: hostile or malformed input is refused before SymPy sees it, and the worker process bounds
time and memory. No input text is quoted back in a refusal."""

import pytest

from laris.model.solver import SolverError, SolverSettings, run, solve
from laris.model.tools import Limits, ToolBox, ToolError

S = SolverSettings(isolate=False)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "x.__class__",
        "(lambda: 1)()",
        "[1, 2]",
        "'text'",
        "open('f')",
        "x if y else z",
        "eval('1')",
        "1 < 2",
        "a[0]",
        "f(x=1)",
    ],
)
def test_syntax_outside_the_whitelist_is_refused(expression):
    with pytest.raises(SolverError) as caught:
        solve({"operation": "evaluate", "expression": expression}, S)
    assert caught.value.code == "invalid_arguments"
    assert expression not in caught.value.message


@pytest.mark.parametrize(
    "expression",
    ["9^9^9", "2^100000", "factorial(100000)", "1" * 2000, "+".join(["x"] * 3000)],
)
def test_size_guards(expression):
    with pytest.raises(SolverError) as caught:
        solve({"operation": "evaluate", "expression": expression}, S)
    assert caught.value.code == "input_too_large"


def test_unknown_operation_and_unread_fields_are_refused():
    with pytest.raises(SolverError):
        solve({"operation": "launch"}, S)
    with pytest.raises(SolverError) as caught:
        solve({"operation": "gcd", "integers": [4, 6], "expression": "x"}, S)
    assert "does not read expression" in caught.value.message


def test_implicit_products_and_conveniences():
    assert solve({"operation": "expand", "expression": "2x(x+1)"}, S)["answer"] == "2*x^2 + 2*x"
    assert solve({"operation": "evaluate", "expression": "3 × 4 − 2"}, S)["answer"] == "10"
    assert solve({"operation": "evaluate", "expression": "1.5e3"}, S)["answer"] == "1500"


def test_worker_times_out_and_is_killed():
    settings = SolverSettings(timeout_s=1.0)
    hard = {
        "operation": "integrate",
        "expression": "exp(sin(x)^7*tan(x)^3)/(1+log(x)^5)",
        "variable": "x",
    }
    with pytest.raises(SolverError) as caught:
        run(hard, settings)
    assert caught.value.code == "timed_out"
    assert run({"operation": "evaluate", "expression": "2+2"}, settings)["answer"] == "4"


def test_tool_route_reports_refusals_as_tool_errors():
    tools = ToolBox(Limits(1000, 10), SolverSettings(timeout_s=5.0))
    assert tools.call("solve_stem", {"operation": "gcd", "integers": [12, 18]})["answer"] == 6
    with pytest.raises(ToolError) as caught:
        tools.call("solve_stem", {"operation": "evaluate", "expression": "__import__('os')"})
    assert caught.value.code == "invalid_arguments"
    with pytest.raises(ToolError) as caught:
        tools.call("solve_stem", {"operation": "evaluate", "nonsense": 1})
    assert caught.value.code == "invalid_arguments"
