#!/usr/bin/env python3
"""Check that `.claude/spec/spec.md`, `plan/*.md` and `task/*.md` agree with each other.

Rules: requirement ids are unique and each names exactly one known owner (`Owner:` line);
task ids are unique across all task files; every task cites known requirements and earlier
tasks; every requirement is covered by a task; each plan file lists, phase by phase, exactly
the tasks of its task file (same file name); statuses are valid; a `done` or `blocked` task
has a note; a `done` task has only `done` dependencies; the spec progress index names every
phase span.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1] / ".claude" / "spec"
STATUSES = {"pending", "in_progress", "done", "blocked"}
OWNERS = {"governance", "model", "protocol", "shared", "harness", "server", "client", "brain"}
Task = Dict[str, object]


def requirement_problems(spec: str) -> Tuple[List[str], List[str]]:
    problems: List[str] = []
    reqs: List[str] = []
    for block in re.split(r"^(?=### )", spec, flags=re.M):
        match = re.match(r"^### (SR-[A-Z]\d+) — ", block)
        if not match:
            continue
        req = match.group(1)
        if req in reqs:
            problems.append(f"{req}: duplicate requirement id")
        reqs.append(req)
        owners = re.findall(r"^Owner: *(\S*)\s*$", block, re.M)
        if len(owners) != 1:
            problems.append(f"{req}: needs exactly one Owner line, found {len(owners)}")
        elif owners[0] not in OWNERS:
            problems.append(f"{req}: unknown owner {owners[0]!r}")
    return reqs, problems


def parse_tasks(text: str) -> Tuple[List[Tuple[str, Task]], Dict[str, List[str]]]:
    tasks: List[Tuple[str, Task]] = []
    phases: Dict[str, List[str]] = {}
    phase = ""
    entry: Task = {}
    for line in text.splitlines():
        match = re.match(r"^## (Phase \d+)", line)
        if match:
            phase, entry = match.group(1), {}
            phases.setdefault(phase, [])
            continue
        match = re.match(r"^### (T\d+) — ", line)
        if match:
            entry = {"reqs": [], "deps": [], "status": "", "note": False}
            tasks.append((match.group(1), entry))
            phases.setdefault(phase, []).append(match.group(1))
            continue
        if not entry:
            continue
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


def validate(spec: str, plans: Dict[str, str], task_files: Dict[str, str]) -> List[str]:
    reqs, problems = requirement_problems(spec)
    if sorted(plans) != sorted(task_files):
        problems.append(f"plan files {sorted(plans)} and task files {sorted(task_files)} differ")
    tasks: Dict[str, Task] = {}
    all_phases: Dict[str, List[str]] = {}
    for name, text in sorted(task_files.items()):
        parsed, phases = parse_tasks(text)
        for tid, entry in parsed:
            if tid in tasks:
                problems.append(f"{tid}: duplicate task id ({name})")
            tasks[tid] = entry
        for phase, items in phases.items():
            if phase in all_phases and items:
                problems.append(f"{phase}: appears in more than one task file")
            all_phases[phase] = items
        plan_phases = parse_plan(plans.get(name, ""))
        if plan_phases != {k: v for k, v in phases.items() if v}:
            problems.append(f"plan/{name} phases do not list the same tasks as task/{name}")
    if not tasks:
        problems.append("no tasks found")
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
    index = re.search(r"## 10\. Task progress index(.*)$", spec, re.S)
    if not index:
        problems.append("spec.md has no section 10 task progress index")
    else:
        for phase, items in all_phases.items():
            if items and f"{phase}: {items[0]}-{items[-1]}" not in index.group(1):
                problems.append(f"spec.md progress index misses {phase}: {items[0]}-{items[-1]}")
    return problems


def read_dir(name: str) -> Dict[str, str]:
    paths = sorted((ROOT / name).glob("*.md"))
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def main() -> int:
    spec = (ROOT / "spec.md").read_text(encoding="utf-8")
    task_files = read_dir("task")
    problems = validate(spec, read_dir("plan"), task_files)
    for problem in problems:
        print(f"[FAIL] {problem}")
    if problems:
        return 1
    tasks = [entry for text in task_files.values() for _, entry in parse_tasks(text)[0]]
    done = sum(1 for entry in tasks if entry["status"] == "done")
    files = len(task_files)
    print(f"[PASS] spec.md, {files} plan and task files agree ({len(tasks)} tasks, {done} done).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
