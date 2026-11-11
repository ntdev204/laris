"""Cross-check system requirements, project plan and task ledger; execute no project tasks."""

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGES = [
    "governance",
    "foundation",
    "scientific_language",
    "ocr",
    "manuscript",
    "integration",
    "specialists",
    "product",
]
MODEL_STAGES = STAGES[1:-1]
STATUSES = {"pending", "blocked", "in_progress", "done"}


def read_file(path: Path) -> tuple[dict, str]:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path}: expected YAML front matter")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping")
    return data, parts[2]


def _index(rows: list[dict], label: str) -> dict:
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate {label} IDs")
    return indexed


def _ancestors(task_id: str, steps: dict) -> set[str]:
    found: set[str] = set()
    pending = list(steps[task_id]["depends_on"])
    while pending:
        dependency = pending.pop()
        if dependency in found:
            continue
        found.add(dependency)
        if dependency in steps:
            pending.extend(steps[dependency]["depends_on"])
    return found


def validate_work_plan(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    try:
        files = {
            name: read_file(root / ".agents" / f"{name}.md") for name in ("spec", "plan", "task")
        }
        for name, (data, _) in files.items():
            if (root / ".agents" / name).exists():
                errors.append(f"{name}: legacy extensionless file must be removed")
            if data.get("document") != name or data.get("no_training") is not True:
                errors.append(f"{name}: identity or no_training constraint mismatch")
            if type(data.get("schema_version")) is not int or data["schema_version"] != 2:
                errors.append(f"{name}: unsupported work-file schema")
            if data.get("stage_order") != STAGES:
                errors.append(
                    f"{name}: stage order must preserve foundation before scientific learning"
                )
        spec, plan, tasks = [files[n][0] for n in ("spec", "plan", "task")]
        requirements = _index(spec["requirements"], "requirement")
        steps = _index(plan["steps"], "plan task")
        ledger = _index(tasks["tasks"], "ledger task")
        progress = _index(spec["task_progress"], "spec task progress")
        if set(steps) != set(ledger) or set(steps) != set(progress):
            errors.append("spec/plan/task task coverage differs")
        mapped_tasks = []
        for rid, requirement in requirements.items():
            if not requirement["acceptance"].strip():
                errors.append(f"{rid}: system acceptance criteria are missing")
            if not requirement["task_ids"]:
                errors.append(f"{rid}: requirement has no implementation tasks")
            for tid in requirement["task_ids"]:
                mapped_tasks.append(tid)
                if tid not in steps or steps[tid]["requirement"] != rid:
                    errors.append(f"{rid}/{tid}: requirement mapping mismatch")
        if len(mapped_tasks) != len(set(mapped_tasks)) or set(mapped_tasks) != set(steps):
            errors.append("Requirements must cover every task exactly once")
        if {step["requirement"] for step in steps.values()} != set(requirements):
            errors.append("Requirement coverage differs")
        models = spec["models"]
        if not (models == plan["models"] == tasks["models"]):
            errors.append("Model state differs across three files")
        if set(models) != set(MODEL_STAGES):
            errors.append("Model stages differ from the ordered system specification")
        positions = {tid: index for index, tid in enumerate(steps)}
        for tid, step in steps.items():
            task, recorded = ledger[tid], progress[tid]
            if task["requirement"] != step["requirement"] or task["title"] != step["title"]:
                errors.append(f"{tid}: requirement/title differs across plan and task")
            status = task["status"]
            if status not in STATUSES or not (status == step["status"] == recorded["status"]):
                errors.append(f"{tid}: completion status differs across three files")
            if not (task["note"] == step["note"] == recorded["note"]):
                errors.append(f"{tid}: notes differ across three files")
            if step["stage"] not in STAGES or step["owner"] not in {"agent", "owner", "joint"}:
                errors.append(f"{tid}: invalid stage or owner")
            if step["operation"] not in {
                "engineering",
                "documentation",
                "implementation",
                "training",
                "qualification",
            }:
                errors.append(f"{tid}: invalid operation")
            if step["operation"] == "training" and step["owner"] != "owner":
                errors.append(f"{tid}: training must remain owner-only")
            if not step["acceptance"].strip() or not step["deliverables"]:
                errors.append(f"{tid}: deliverables/acceptance are missing")
            for dependency in step["depends_on"]:
                if dependency not in positions or positions[dependency] >= positions[tid]:
                    errors.append(f"{tid}: dependency is missing, cyclic or out of order")
                elif status in {"in_progress", "done"} and ledger[dependency]["status"] != "done":
                    errors.append(f"{tid}: predecessor {dependency} is unfinished")
            stage_index = STAGES.index(step["stage"])
            if stage_index >= 2:
                previous = models[STAGES[stage_index - 1]]
                if previous["qualification_task"] not in _ancestors(tid, steps):
                    errors.append(f"{tid}: dependency graph bypasses preceding stage qualification")
                if status in {"in_progress", "done"} and previous["status"] != "qualified":
                    errors.append(f"{tid}: preceding model is not qualified")
            lines = re.findall(
                rf"^- \[[ x]\] (?:~~)?{re.escape(tid)} — .*$", files["task"][1], re.M
            )
            label = f"{tid} — {task['title']}"
            expected = (
                f"- [x] ~~{label}~~ — Note: {task['note']}"
                if status == "done"
                else f"- [ ] {label}"
            )
            if lines != [expected]:
                errors.append(f"{tid}: checklist must match status and strike-through")
            if status == "done":
                if not task["note"].strip() or not task["evidence"]:
                    errors.append(f"{tid}: completion needs a note and evidence")
                for path in step["deliverables"] + task["evidence"]:
                    candidate = (root / path).resolve()
                    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                        errors.append(f"{tid}: missing or external deliverable/evidence {path}")
        for index, stage in enumerate(MODEL_STAGES):
            model = models[stage]
            gate = steps[model["qualification_task"]]
            if gate["operation"] != "qualification" or gate["stage"] != stage:
                errors.append(f"{stage}: qualification must refer to its own qualification task")
            if model["status"] not in {
                "not_implemented",
                "implemented",
                "not_qualified",
                "qualified",
            }:
                errors.append(f"{stage}: invalid model status")
            if model["status"] == "qualified":
                if gate["status"] != "done" or model.get("owner_approved") is not True:
                    errors.append(
                        f"{stage}: qualification requires completed evidence and owner review"
                    )
                if index and models[MODEL_STAGES[index - 1]]["status"] != "qualified":
                    errors.append(f"{stage}: previous model is not qualified")
        next_task = spec["next_task"]
        if not (next_task == plan["next_task"] == tasks["next_task"]):
            errors.append("Next task differs across three files")
        if next_task is None:
            if any(t["status"] != "done" for t in ledger.values()):
                errors.append("Next task is missing although project work remains")
        elif next_task not in steps or steps[next_task]["status"] == "done":
            errors.append("Next task must identify unfinished project work")
        elif any(ledger[dep]["status"] != "done" for dep in steps[next_task]["depends_on"]):
            errors.append("Next task has unfinished dependencies")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        errors.append(f"Invalid work files: {exc}")
    return errors


def main() -> int:
    errors = validate_work_plan()
    for error in errors:
        print(f"[ERROR] {error}")
    if not errors:
        print(
            "[PASS] spec.md <-> plan.md <-> task.md: system requirements and project tasks agree."
        )
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
