"""Sync and repair of a project vault: user edits are never lost.

Conflict policy (also in the user guide): LARIS writes only inside its managed blocks. When a
person edits inside a block, the block's hash no longer matches, LARIS stops writing that block and
reports a conflict. `sync` lists conflicts; `sync --accept` adopts the person's text as the new
baseline so LARIS may update the block again from the next write. `repair` fixes damage (a block
whose end marker was deleted, temp files from a crashed write, a missing skeleton) and can restore a
note from the backups LARIS keeps before every rewrite.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from laris.shared.vault.index import IGNORED_DIRS
from laris.shared.vault.project import ProjectVault
from laris.shared.vault.writer import BACKUP_DIR, _digest, atomic_write, resolve_inside

_BEGIN = re.compile(r"<!-- laris:begin (?P<name>[\w.-]+) sha=(?P<sha>[0-9a-f]{8,64}) -->\n")
_FULL = re.compile(
    r"<!-- laris:begin (?P<name>[\w.-]+) sha=(?P<sha>[0-9a-f]{8,64}) -->\n"
    r"(?P<body>.*?)\n?<!-- laris:end (?P=name) -->",
    re.DOTALL,
)


@dataclass(frozen=True)
class Conflict:
    path: str
    block: str


def _notes(root: Path) -> List[Path]:
    return sorted(
        p
        for p in root.rglob("*.md")
        if p.is_file() and not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)
    )


def find_conflicts(root: Path) -> List[Conflict]:
    found = []
    for path in _notes(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _FULL.finditer(text):
            if _digest(match.group("body")) != match.group("sha"):
                found.append(Conflict(path.relative_to(root).as_posix(), match.group("name")))
    return found


def accept_edits(vault: ProjectVault) -> int:
    """Adopt every hand edit inside a managed block as the new baseline (text unchanged)."""
    changed = 0
    for path in _notes(vault.root):
        text = path.read_text(encoding="utf-8")

        def fix(m: "re.Match[str]") -> str:
            body = m.group("body")
            return m.group(0).replace(f"sha={m.group('sha')}", f"sha={_digest(body)}", 1)

        new = _FULL.sub(fix, text)
        if new != text:
            vault.writer._backup(path.resolve(), text)
            atomic_write(path, new)
            changed += 1
    return changed


def backups(vault: ProjectVault, relative: str) -> List[Path]:
    prefix = relative.replace("/", "__") + "."
    folder = vault.root / BACKUP_DIR
    return sorted(folder.glob(prefix + "*.bak")) if folder.is_dir() else []


def restore(vault: ProjectVault, relative: str, which: int = -1) -> Optional[str]:
    """Put a backup back (default: the newest). The text it replaces is backed up first."""
    found = backups(vault, relative)
    if not found:
        return None
    target = resolve_inside(vault.root, relative)
    if target.is_file():
        vault.writer._backup(target, target.read_text(encoding="utf-8"))
    atomic_write(target, found[which].read_text(encoding="utf-8"))
    return found[which].name


@dataclass
class RepairReport:
    closed_blocks: int = 0
    temp_files: int = 0
    skeleton: bool = False


def repair(vault: ProjectVault) -> RepairReport:
    """Idempotent: a second run changes nothing."""
    report = RepairReport()
    for tmp in vault.root.rglob(".laris-*.tmp"):
        tmp.unlink()
        report.temp_files += 1
    for path in _notes(vault.root):
        text = path.read_text(encoding="utf-8", errors="replace")
        fixed = text
        for begin in reversed(list(_BEGIN.finditer(text))):
            tail = text[begin.end() :]
            if (
                f"<!-- laris:end {begin.group('name')} -->"
                not in tail.split("<!-- laris:begin", 1)[0]
            ):
                cut = begin.end() + len(tail.split("<!-- laris:begin", 1)[0].rstrip("\n"))
                fixed = fixed[:cut] + f"\n<!-- laris:end {begin.group('name')} -->" + fixed[cut:]
                report.closed_blocks += 1
        if fixed != text:
            vault.writer._backup(path.resolve(), text)
            atomic_write(path, fixed)
    report.skeleton = vault.ensure()
    vault.refresh_index()
    return report
