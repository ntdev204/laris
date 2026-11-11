"""Integrity of the protected policy files: `LARIS.md`, prompts, rules and workflows.

`integrity.lock` stores a SHA-256 per file. The harness refuses to start a session when a protected
file was added, removed or changed without refreshing the lock (rule G-3).
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List

from config.runtime_schemas import PromptConfig

ROOT_FILE = "LARIS.md"


class IntegrityError(RuntimeError):
    """A protected policy file does not match the lock."""


def _folder(root: Path, relative: str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else root / path


def protected_files(root: Path, cfg: PromptConfig) -> List[Path]:
    files: List[Path] = []
    if (root / ROOT_FILE).is_file():
        files.append(root / ROOT_FILE)
    helper = _folder(root, cfg.help_file)
    if helper.is_file():
        files.append(helper)
    for relative in (cfg.dir, cfg.rules_dir, cfg.workflows_dir, cfg.brain_dir, cfg.vault_dir):
        folder = _folder(root, relative)
        if folder.is_dir():
            files += [p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(set(files))


def _label(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def compute(root: Path, cfg: PromptConfig) -> Dict[str, str]:
    return {
        _label(root, p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in protected_files(root, cfg)
    }


def write_lock(root: Path, cfg: PromptConfig) -> Path:
    lock = _folder(root, cfg.integrity_lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    payload = {"algorithm": "sha256", "files": compute(root, cfg)}
    lock.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


def verify(root: Path, cfg: PromptConfig) -> List[str]:
    """Problems found (empty = intact). Messages name files relative to the project only."""
    lock = _folder(root, cfg.integrity_lock)
    if not lock.is_file():
        return ["integrity lock is missing"]
    try:
        expected = json.loads(lock.read_text(encoding="utf-8"))["files"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return ["integrity lock is unreadable"]
    actual = compute(root, cfg)
    problems = [
        f"changed: {name}"
        for name in sorted(actual)
        if name in expected and actual[name] != expected[name]
    ]
    problems += [f"added: {name}" for name in sorted(set(actual) - set(expected))]
    problems += [f"missing: {name}" for name in sorted(set(expected) - set(actual))]
    return problems
