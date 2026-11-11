#!/usr/bin/env python3
"""Check that `.claude/spec/{spec,plan,task}.md` agree with each other.

Rules: requirement and task ids are unique; every task cites known requirements and earlier tasks;
every requirement is covered by a task; plan phases list exactly the tasks of the same phase in
task.md; statuses are valid; a `done` task has a note and only `done` dependencies.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1] / ".claude" / "spec"
STATUSES = {"pending", "in_progress", "done", "blocked"}


def _ids(text: str, pattern: str) -> List[str]:
    return re.findall(pattern, text, re.M)


def parse_tasks(text: str) -> Tuple[Dict[str, Dict[str, object]], Dict[str, List[str]]]:
    tasks: Dict[str, Dict[str, object]] = {}
    phases: Dict[str, List[str]] = {}
    phase, current = "", ""
    for line in text.splitlines():
        match = re.match(r"^## (Phase \d+)", line)
        if match:
            phase, current = match.group(1), ""
            phases.setdefault(phase, [])
            continue
        match = re.match(r"^### (T\d+) — ", line)
        if match:
            current = match.group(1)
            tasks[current] = {"reqs": [], "deps": [], "status": "", "note": False, "phase": phase}
            phases.setdefault(phase, []).append(current)
            continue
        if not current:
            continue
        entry = tasks[current]
        if line.startswith("- Requirements:"):
            entry["reqs"] = re.findall(r"SR-[A-Z]\d+", line)
        elif line.startswith("- Depends:"):
            entry["deps"] = re.findall(r"T\d+", line)
        elif line.startswith("- Status:"):
            entry["status"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Note:"):
            entry["note"] = True
    return tasks, phases


def parse_plan(text: str) -> Dict[str, List[str]]:
    phases: Dict[str, List[str]] = {}
    phase = ""
    for line in text.splitlines():
        match = re.match(r"^### (Phase \d+)", line)
        if match:
            phase = match.group(1)
        elif phase and line.startswith("Tasks:"):
            phases[phase] = re.findall(r"T\d+", line)
    return phases


def validate(spec: str, plan: str, task: str) -> List[str]:
    problems: List[str] = []
    reqs = _ids(spec, r"^### (SR-[A-Z]\d+) — ")
    if len(reqs) != len(set(reqs)):
        problems.append("duplicate requirement ids in spec.md")
    tasks, task_phases = parse_tasks(task)
    ids = list(tasks)
    if len(ids) != len(set(ids)) or not ids:
        problems.append("duplicate or missing task ids in task.md")
    covered = set()
    for tid, entry in tasks.items():
        if not entry["reqs"]:
            problems.append(f"{tid}: no requirements cited")
        for req in entry["reqs"]:  # type: ignore[attr-defined]
            if req not in reqs:
                problems.append(f"{tid}: unknown requirement {req}")
            covered.add(req)
        for dep in entry["deps"]:  # type: ignore[attr-defined]
            if dep not in tasks:
                problems.append(f"{tid}: unknown dependency {dep}")
            elif int(dep[1:]) >= int(tid[1:]):
                problems.append(f"{tid}: dependency {dep} must come earlier")
            elif entry["status"] == "done" and tasks[dep]["status"] != "done":
                problems.append(f"{tid}: done but dependency {dep} is not done")
        if entry["status"] not in STATUSES:
            problems.append(f"{tid}: invalid status {entry['status']!r}")
        if entry["status"] in ("done", "blocked") and not entry["note"]:
            problems.append(f"{tid}: {entry['status']} needs a note")
    for req in reqs:
        if req not in covered:
            problems.append(f"{req}: not covered by any task")
    plan_phases = parse_plan(plan)
    if plan_phases != {k: v for k, v in task_phases.items() if v}:
        problems.append("plan.md phases do not list the same tasks as task.md")
    listed = [t for v in plan_phases.values() for t in v]
    if sorted(listed) != sorted(ids):
        problems.append("plan.md must list every task exactly once")
    index = re.search(r"## 10\. Task progress index(.*)$", spec, re.S)
    if index:
        for phase, items in plan_phases.items():
            if not items:
                continue
            span = f"{items[0]}-{items[-1]}"
            if span not in index.group(1):
                problems.append(f"spec.md progress index misses {span}")
    return problems


def main() -> int:
    texts = [
        (ROOT / name).read_text(encoding="utf-8") for name in ("spec.md", "plan.md", "task.md")
    ]
    problems = validate(*texts)
    for problem in problems:
        print(f"[FAIL] {problem}")
    if problems:
        return 1
    tasks, _ = parse_tasks(texts[2])
    done = sum(1 for t in tasks.values() if t["status"] == "done")
    print(f"[PASS] spec.md <-> plan.md <-> task.md agree ({len(tasks)} tasks, {done} done).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
