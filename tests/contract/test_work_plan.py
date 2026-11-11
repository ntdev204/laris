"""Pure-file checks for system/plan/task drift; no model or optimizer is invoked."""

import shutil

import pytest
import yaml

from scripts.validate_work_plan import REPO_ROOT, read_file, validate_work_plan


@pytest.fixture
def work_files(tmp_path):
    shutil.copytree(REPO_ROOT / ".agents", tmp_path / ".agents")
    plan, _ = read_file(tmp_path / ".agents" / "plan.md")
    ledger, _ = read_file(tmp_path / ".agents" / "task.md")
    paths = [p for step in plan["steps"] if step["status"] == "done" for p in step["deliverables"]]
    paths += [p for task in ledger["tasks"] for p in task["evidence"]]
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("fixture")
    return tmp_path


def edit(root, name, mutate):
    path = root / ".agents" / f"{name}.md"
    data, body = read_file(path)
    mutate(data)
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True) + "---" + body)


def test_current_work_files_agree(work_files):
    assert validate_work_plan(work_files) == []


@pytest.mark.parametrize(
    "defect",
    [
        "status",
        "note",
        "orphan",
        "cycle",
        "training",
        "promotion",
        "stage_order",
        "requirement",
        "stage_bypass",
        "training_owner",
        "next_task",
        "missing_evidence",
    ],
)
def test_drift_blocks_completion(work_files, defect):
    if defect == "status":
        edit(work_files, "plan", lambda d: d["steps"][0].update(status="invalid"))
    elif defect == "note":
        edit(work_files, "task", lambda d: d["tasks"][0].update(note="different note"))
    elif defect == "orphan":
        edit(work_files, "task", lambda d: d["tasks"].pop())
    elif defect == "cycle":
        edit(work_files, "plan", lambda d: d["steps"][0].update(depends_on=["P03"]))
    elif defect == "training":
        edit(work_files, "spec", lambda d: d.update(no_training=False))
    elif defect == "promotion":
        for name in ("spec", "plan", "task"):
            edit(
                work_files,
                name,
                lambda d: d["models"]["foundation"].update(status="qualified", owner_approved=True),
            )
    elif defect == "stage_order":
        edit(work_files, "plan", lambda d: d["stage_order"].reverse())
    elif defect == "requirement":
        edit(work_files, "spec", lambda d: d["requirements"][0]["task_ids"].pop())
    elif defect == "stage_bypass":
        edit(
            work_files,
            "plan",
            lambda d: next(s for s in d["steps"] if s["id"] == "S01").update(depends_on=["G01"]),
        )
    elif defect == "training_owner":
        edit(
            work_files,
            "plan",
            lambda d: next(s for s in d["steps"] if s["id"] == "F06").update(owner="agent"),
        )
    elif defect == "next_task":
        for name in ("spec", "plan", "task"):
            edit(work_files, name, lambda d: d.update(next_task="S01"))
    elif defect == "missing_evidence":
        edit(work_files, "task", lambda d: d["tasks"][0].update(evidence=[]))
    assert validate_work_plan(work_files)


def test_completed_task_requires_real_deliverables(work_files):
    plan, _ = read_file(work_files / ".agents" / "plan.md")
    (work_files / plan["steps"][0]["deliverables"][0]).unlink()
    assert any("missing" in e for e in validate_work_plan(work_files))


def test_checked_item_requires_strike_through(work_files):
    path = work_files / ".agents" / "task.md"
    path.write_text(path.read_text().replace("~~G00", "G00", 1))
    assert any("strike-through" in e for e in validate_work_plan(work_files))


def test_legacy_extensionless_files_are_rejected(work_files):
    (work_files / ".agents" / "spec").write_text("obsolete")
    assert any("legacy extensionless" in e for e in validate_work_plan(work_files))


def test_system_requirements_cover_multiple_project_tasks(work_files):
    spec, _ = read_file(work_files / ".agents" / "spec.md")
    assert any(len(r["task_ids"]) > 1 for r in spec["requirements"])
