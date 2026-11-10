"""Pure-file checks for work-plan drift; no model or optimizer is invoked."""

import shutil

import pytest
import yaml

from scripts.validate_work_plan import REPO_ROOT, read_file, validate_work_plan


@pytest.fixture
def work_files(tmp_path):
    shutil.copytree(REPO_ROOT / ".agents", tmp_path / ".agents")
    for name, key in (("spec", "requirements"), ("plan", "steps"), ("task", "tasks")):
        path = tmp_path / ".agents" / name
        data, body = read_file(path)
        first = data[key][0]
        if first["status"] != "done":
            first.update(status="done", note="Fixture completion")
            if name == "task":
                first["evidence"] = ["AGENTS.md"]
                label = f"T01 — {first['title']}"
                body = body.replace(f"- [ ] {label}",
                                    f"- [x] ~~{label}~~ — Note: Fixture completion")
            path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True) + "---" + body)
    plan, _ = read_file(tmp_path / ".agents" / "plan")
    ledger, _ = read_file(tmp_path / ".agents" / "task")
    paths = [p for step in plan["steps"] for p in step["deliverables"]]
    paths += [p for task in ledger["tasks"] for p in task["evidence"]]
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("fixture")
    return tmp_path


def edit(root, name, mutate):
    path = root / ".agents" / name
    data, body = read_file(path)
    mutate(data)
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True) + "---" + body)


def test_current_work_files_agree(work_files):
    assert validate_work_plan(work_files) == []


@pytest.mark.parametrize("defect", ["status", "note", "orphan", "cycle", "training", "promotion"])
def test_drift_blocks_completion(work_files, defect):
    if defect == "status":
        edit(work_files, "plan", lambda d: d["steps"][0].update(status="invalid"))
    elif defect == "note":
        edit(work_files, "task", lambda d: d["tasks"][0].update(note="different note"))
    elif defect == "orphan":
        edit(work_files, "task", lambda d: d["tasks"].pop())
    elif defect == "cycle":
        edit(work_files, "plan", lambda d: d["steps"][0].update(depends_on=["T06"]))
    elif defect == "training":
        edit(work_files, "spec", lambda d: d.update(no_training=False))
    elif defect == "promotion":
        edit(work_files, "spec", lambda d: d["model_status"].update(natural_language="qualified"))
    assert validate_work_plan(work_files)


def test_completed_task_requires_real_deliverables(work_files):
    plan, _ = read_file(work_files / ".agents" / "plan")
    assert plan["steps"][0]["status"] == "done"
    (work_files / "AGENTS.md").unlink()
    assert any("missing" in e for e in validate_work_plan(work_files))


def test_checked_item_requires_strike_through(work_files):
    path = work_files / ".agents" / "task"
    path.write_text(path.read_text().replace("~~T01", "T01", 1))
    data, _ = read_file(path)
    assert data["tasks"][0]["status"] == "done"
    assert any("strike-through" in e for e in validate_work_plan(work_files))
