"""The spec, plan and task files under `.claude/spec/` must stay consistent."""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec_path = REPO / "scripts" / "validate_spec.py"
loaded = importlib.util.spec_from_file_location("validate_spec", spec_path)
assert loaded and loaded.loader
module = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(module)

SPEC = (REPO / ".claude/spec/spec.md").read_text(encoding="utf-8")
PLAN = (REPO / ".claude/spec/plan.md").read_text(encoding="utf-8")
TASK = (REPO / ".claude/spec/task.md").read_text(encoding="utf-8")


def test_repository_ledger_is_consistent():
    assert module.validate(SPEC, PLAN, TASK) == []


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (
            lambda s, p, t: (s, p, t.replace("Requirements: SR-V3", "Requirements: SR-X9", 1)),
            "unknown requirement",
        ),
        (
            lambda s, p, t: (s, p, t.replace("Depends: T05\n", "Depends: T99\n", 1)),
            "unknown dependency",
        ),
        (
            lambda s, p, t: (s, p, t.replace("Status: pending", "Status: maybe", 1)),
            "invalid status",
        ),
        (lambda s, p, t: (s, p.replace("T05, ", "", 1), t), "plan.md"),
        (lambda s, p, t: (s + "\n### SR-Z1 — Extra\n", p, t), "not covered"),
    ],
)
def test_validator_detects_inconsistencies(mutate, expected):
    problems = module.validate(*mutate(SPEC, PLAN, TASK))
    assert any(expected in p for p in problems), problems


def test_done_task_needs_done_dependencies_and_a_note():
    head, rest = TASK.split("### T05 — ", 1)
    block, tail = rest.split("### T06 — ", 1)
    done = (
        head
        + "### T05 — "
        + block.replace("Status: pending", "Status: done\n- Note: x")
        + "### T06 — "
        + tail
    )
    problems = module.validate(SPEC, PLAN, done)
    assert any("T05: done but dependency T02" in p for p in problems), problems
    no_note = TASK.replace(
        "- Note: Needs the owner's confirmation", "- Remark: Needs the owner's confirmation", 1
    )
    assert any("needs a note" in p for p in module.validate(SPEC, PLAN, no_note))
