"""The spec, plan and task files under `.claude/spec/` must stay consistent."""

import importlib.util
import re
from pathlib import Path
from typing import Dict

import pytest

REPO = Path(__file__).resolve().parents[2]
spec_path = REPO / "scripts" / "validate_spec.py"
loaded = importlib.util.spec_from_file_location("validate_spec", spec_path)
assert loaded and loaded.loader
module = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(module)

SPEC = (REPO / ".claude/spec/spec.md").read_text(encoding="utf-8")
PLANS = module.read_dir("plan")
TASKS = module.read_dir("task")
MODEL = "1-model.md"


def _with(task_text: str, plan_text: str = "") -> tuple:
    """The ledger with the model task file (and optionally its plan file) replaced."""
    tasks: Dict[str, str] = {**TASKS, MODEL: task_text}
    plans: Dict[str, str] = {**PLANS, MODEL: plan_text or PLANS[MODEL]}
    return plans, tasks


def test_repository_ledger_is_consistent():
    assert module.validate(SPEC, PLANS, TASKS) == []


def test_every_programme_has_a_plan_and_a_task_file():
    assert sorted(PLANS) == sorted(TASKS) == ["1-model.md", "2-system.md", "3-brain.md"]


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (
            lambda s, t: (s, t.replace("Requirements: SR-M4", "Requirements: SR-X9", 1)),
            "unknown requirement",
        ),
        (
            lambda s, t: (s, t.replace("Depends: T198\n", "Depends: T9999\n", 1)),
            "unknown dependency",
        ),
        (lambda s, t: (s, t.replace("Status: pending", "Status: maybe", 1)), "invalid status"),
        (lambda s, t: (s + "\n### SR-Z1 — Extra\n", t), "needs exactly one Owner"),
    ],
)
def test_validator_detects_inconsistencies(mutate, expected):
    spec, task = mutate(SPEC, TASKS[MODEL])
    assert task != TASKS[MODEL] or spec != SPEC, "the mutation did not apply"
    plans, tasks = _with(task)
    problems = module.validate(spec, plans, tasks)
    assert any(expected in p for p in problems), problems


def test_plan_that_drops_a_task_is_detected():
    plan = PLANS[MODEL].replace("T198, ", "", 1)
    assert plan != PLANS[MODEL]
    plans, tasks = _with(TASKS[MODEL], plan)
    assert any("do not list the same tasks" in p for p in module.validate(SPEC, plans, tasks))


def test_a_requirement_without_a_task_is_detected():
    spec = SPEC.replace(
        "## 10. Task progress index",
        "### SR-M99 — Extra\nOwner: model\n\n## 10. Task progress index",
        1,
    )
    assert any("not covered" in p for p in module.validate(spec, PLANS, TASKS))


def test_done_task_needs_done_dependencies_and_a_note():
    plans, tasks = _with(
        re.sub(
            r"(### T197 — .*?- Status: )done", r"\g<1>pending", TASKS[MODEL], count=1, flags=re.S
        )
    )
    assert any("T198: done but dependency T197" in p for p in module.validate(SPEC, plans, tasks))
    # drop every note of T197 (a done task needs one)
    text = TASKS[MODEL]
    start = text.index("### T197")
    end = text.index("### T198")
    block = re.sub(r"^- Note.*\n", "", text[start:end], flags=re.M)
    plans, tasks = _with(text[:start] + block + text[end:])
    assert any("T197: done needs a note" in p for p in module.validate(SPEC, plans, tasks))
