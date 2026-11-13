#!/usr/bin/env python3
"""Run the model block's checks on `laris-v2` without any training (T94, SR-G3, SR-M3).

Steps: no-training guard, ruff, mypy on `src/laris`, then pytest on every test file the guard
does not exclude. A test file is excluded, and named in the report, when it
 - calls a training or profiling entry point (the trainer, `run_training`, memory profiling,
   the tokenizer or encoder training scripts),
 - runs a backward pass or an optimizer step, or
 - sets `LARIS_TRAINING_AUTHORIZED` (or the tokenizer variant) in the environment.
Files that cannot run on `laris-v2` for other reasons are listed in `OBSOLETE_ON_V2`.
The script refuses to run when the authorization variable is set in its own environment and
removes it from the environment of every child process.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
AUTH_VARS = ("LARIS_TRAINING_AUTHORIZED", "LARIS_TOKENIZER_TRAINING_AUTHORIZED")
TRAINING_NAMES = {
    "LanguageEncoderTrainer",
    "run_training",
    "profile_memory",
    "train_tokenizer",
    "train_language_encoder",
    "fit_offline",
}
TRAINING_ATTRIBUTES = {"backward", "train_step", "zero_grad"}
OPTIMIZER_STEP = re.compile(r"(optimizer|optim|opt|scaler)\w*\.step\(")
OBSOLETE_ON_V2 = {
    "tests/contract/test_spec_ledger.py": "v1 ledger; see validate_spec.py",
    "tests/documentation/test_docs.py": "links to documents removed on laris-v2",
    "tests/unit/architecture/test_layers.py": "reads src/laris/client/agent, removed on laris-v2",
}


def guard_findings(path: Path) -> List[str]:
    """Reasons why a test file trains, profiles with an optimizer, or authorizes training."""
    text = path.read_text(encoding="utf-8")
    findings: List[str] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"unparseable ({exc.msg})"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in TRAINING_NAMES:
            findings.append(f"line {node.lineno}: uses training entry point {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in TRAINING_ATTRIBUTES:
            findings.append(f"line {node.lineno}: calls .{node.attr}")
        elif isinstance(node, ast.alias) and node.name.split(".")[-1] in TRAINING_NAMES:
            findings.append(f"line {node.lineno}: imports training entry point {node.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in AUTH_VARS:
                reads_only = False
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.Call) and node in parent.args:
                        func = parent.func
                        name = func.attr if isinstance(func, ast.Attribute) else ""
                        reads_only = name == "delenv"
                if not reads_only:
                    findings.append(f"line {node.lineno}: touches {node.value}")
    for match in OPTIMIZER_STEP.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(f"line {line}: optimizer step")
    return sorted(set(findings))


def classify_tests(tests_dir: Path, root: Path) -> Dict[str, Dict[str, object]]:
    """Return `{"run": [...], "training": {file: reasons}, "obsolete": {file: reason}}`."""
    run: List[str] = []
    training: Dict[str, List[str]] = {}
    obsolete: Dict[str, str] = {}
    for path in sorted(tests_dir.rglob("test_*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in OBSOLETE_ON_V2:
            obsolete[rel] = OBSOLETE_ON_V2[rel]
            continue
        findings = guard_findings(path)
        if findings:
            training[rel] = findings
        else:
            run.append(rel)
    return {"run": run, "training": training, "obsolete": obsolete}


def child_env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in AUTH_VARS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_step(name: str, cmd: Sequence[str]) -> bool:
    print(f"\n== {name}: {' '.join(cmd[:6])}{' ...' if len(cmd) > 6 else ''}", flush=True)
    result = subprocess.run(list(cmd), cwd=ROOT, env=child_env())
    ok = result.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
    return ok


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="only print the test classification")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args(argv)

    for var in AUTH_VARS:
        if os.environ.get(var):
            print(f"[FAIL] {var} is set; verification never runs with training authorized.")
            return 2

    plan = classify_tests(ROOT / "tests", ROOT)
    run: List[str] = plan["run"]  # type: ignore[assignment]
    training: Dict[str, List[str]] = plan["training"]  # type: ignore[assignment]
    obsolete: Dict[str, str] = plan["obsolete"]  # type: ignore[assignment]
    print(f"Test files run: {len(run)}")
    print(f"Excluded (train, profile or authorize training): {len(training)}")
    for rel, reasons in training.items():
        print(
            f"  - {rel}: {reasons[0]}"
            + (f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else "")
        )
    print(f"Excluded (obsolete on laris-v2): {len(obsolete)}")
    for rel, reason in obsolete.items():
        print(f"  - {rel}: {reason}")
    if args.list:
        return 0

    py = sys.executable
    ok = run_step("ruff", [py, "-m", "ruff", "check", "src", "tests", "scripts"])
    ok = run_step("mypy", [py, "-m", "mypy", "src/laris"]) and ok
    ok = (
        run_step("pytest", [py, "-m", "pytest", "-p", "no:cacheprovider", *run, *args.pytest_args])
        and ok
    )
    print("\n[PASS] model-block verification" if ok else "\n[FAIL] model-block verification")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
