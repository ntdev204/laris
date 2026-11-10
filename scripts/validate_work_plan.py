"""Cross-check the owner's three work files; never execute their commands."""

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_file(path: Path) -> tuple[dict, str]:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path}: expected YAML front matter")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping")
    return data, parts[2]


def validate_work_plan(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    try:
        files = {name: read_file(root / ".agents" / name) for name in ("spec", "plan", "task")}
        for name, (data, _) in files.items():
            if data.get("document") != name or data.get("no_training") is not True:
                errors.append(f"{name}: identity or no_training constraint mismatch")
            if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
                errors.append(f"{name}: unsupported work-file schema")
        requirements = files["spec"][0]["requirements"]
        steps = files["plan"][0]["steps"]
        tasks = files["task"][0]["tasks"]
        reqs = {r["id"]: r for r in requirements}
        plans = {s["id"]: s for s in steps}
        ledger = {t["id"]: t for t in tasks}
        if len(reqs) != len(requirements) or len(plans) != len(steps) or len(ledger) != len(tasks):
            errors.append("Duplicate requirement or task IDs")
        if set(plans) != set(ledger) or {r["task"] for r in requirements} != set(plans):
            errors.append("spec/plan/task task coverage differs")
        if {s["requirement"] for s in steps} != set(reqs):
            errors.append("Requirement coverage differs")
        positions = {s["id"]: i for i, s in enumerate(steps)}
        for tid, step in plans.items():
            task = ledger[tid]
            requirement = reqs[step["requirement"]]
            if task["requirement"] != requirement["id"] or requirement["task"] != tid:
                errors.append(f"{tid}: requirement mapping mismatch")
            if not (task["title"] == step["title"] == requirement["title"]):
                errors.append(f"{tid}: titles differ across three files")
            status = task["status"]
            if status not in {"pending", "in_progress", "done"}:
                errors.append(f"{tid}: invalid status")
            if {status, step["status"], requirement["status"]} != {status}:
                errors.append(f"{tid}: completion status differs across three files")
            if not (task["note"] == step["note"] == requirement["note"]):
                errors.append(f"{tid}: notes differ across three files")
            for dependency in step["depends_on"]:
                if dependency not in positions or positions[dependency] >= positions[tid]:
                    errors.append(f"{tid}: dependency is missing, cyclic or out of order")
                elif status != "pending" and ledger[dependency]["status"] != "done":
                    errors.append(f"{tid}: predecessor {dependency} is unfinished")
            checklist = re.findall(
                rf"^- \[[ x]\] (?:~~)?{re.escape(tid)}\b.*$", files["task"][1], re.M
            )
            label = f"{tid} — {task['title']}"
            expected = (
                f"- [x] ~~{label}~~ — Note: {task['note']}"
                if status == "done" else f"- [ ] {label}"
            )
            if checklist != [expected]:
                errors.append(f"{tid}: checklist must match status and strike-through")
            if status == "done":
                if not task["note"].strip() or not task["evidence"]:
                    errors.append(f"{tid}: completion needs a note and evidence")
                for path in step["deliverables"] + task["evidence"]:
                    candidate = (root / path).resolve()
                    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                        errors.append(f"{tid}: missing or external deliverable/evidence {path}")
        if files["spec"][0]["model_status"] != {
            "natural_language": "not_qualified",
            "scientific_language": "not_implemented",
            "later_stages": "blocked_by_predecessors",
        }:
            errors.append("Preparation tasks cannot promote model readiness")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"Invalid work files: {exc}")
    return errors


def main() -> int:
    errors = validate_work_plan()
    for error in errors:
        print(f"[ERROR] {error}")
    if not errors:
        print("[PASS] spec <-> plan <-> task: requirements, order, notes and evidence agree.")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
