"""Safe writing into a vault: path confinement, atomic writes, managed blocks, conflict detection.

LARIS writes only inside blocks it owns, marked by comments:

    <!-- laris:begin NAME sha=0123abcd -->
    ...generated text...
    <!-- laris:end NAME -->

`sha` is the hash of the text LARIS last wrote there. If the text no longer matches, a person edited
the block, so LARIS leaves it alone and reports a conflict instead of overwriting the edit.
"""

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from laris.shared.vault.notes import FORBIDDEN_NAME_CHARS

MAX_TITLE_CHARS = 100
BACKUP_DIR = ".laris/backups"
_BLOCK = re.compile(
    r"<!-- laris:begin (?P<name>[\w.-]+) sha=(?P<sha>[0-9a-f]{8,64}) -->\n"
    r"(?P<body>.*?)\n?<!-- laris:end (?P=name) -->",
    re.DOTALL,
)


class VaultWriteError(ValueError):
    """A write was refused (path escape, unsafe content, size)."""


def safe_title(text: str, fallback: str = "Untitled") -> str:
    """A note name that cannot break a wikilink or a file name."""
    cleaned = "".join(" " if c in FORBIDDEN_NAME_CHARS or ord(c) < 32 else c for c in text)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned[:MAX_TITLE_CHARS].strip(" .") or fallback


def resolve_inside(root: Path, relative: str) -> Path:
    """Path of `relative` below `root`; rejects absolute paths, `..` and symlink escapes."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not relative.strip():
        raise VaultWriteError("path must be relative and stay inside the vault")
    base = root.resolve()
    target = (base / rel).resolve()
    if base != target and base not in target.parents:
        raise VaultWriteError("path escapes the vault")
    return target


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=".laris-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _digest(text: str) -> str:
    return hashlib.sha256(text.strip("\n").encode("utf-8")).hexdigest()[:16]


def block(name: str, content: str) -> str:
    content = content.strip("\n")
    return (
        f"<!-- laris:begin {name} sha={_digest(content)} -->\n{content}\n<!-- laris:end {name} -->"
    )


def upsert_block(text: str, name: str, content: str) -> Tuple[str, str]:
    """Insert or replace one managed block. Returns (new text, status): created, updated,
    unchanged or conflict (a person edited the block; text is returned unchanged)."""
    new = block(name, content)
    for match in _BLOCK.finditer(text):
        if match.group("name") != name:
            continue
        if _digest(match.group("body")) != match.group("sha"):
            return text, "conflict"
        if match.group(0) == new:
            return text, "unchanged"
        return text[: match.start()] + new + text[match.end() :], "updated"
    return text.rstrip("\n") + ("\n\n" if text.strip() else "") + new + "\n", "created"


def render_note(props: Dict[str, Any], body: str) -> str:
    front = yaml.safe_dump(props, sort_keys=False, allow_unicode=True, width=1000).strip()
    return f"---\n{front}\n---\n\n{body.strip()}\n"


Scanner = Callable[[str], bool]


class VaultWriter:
    """Writes notes below a root. `scan` returns True for text that must not be stored."""

    def __init__(
        self,
        root: Path,
        max_chars: int = 12000,
        scan: Optional[Scanner] = None,
        backup: bool = True,
        max_writes_per_minute: int = 0,
        redact: Optional[Callable[[str], str]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = Path(root)
        self.max_chars = max_chars
        self.scan = scan
        self.backup = backup
        self.max_writes = max_writes_per_minute  # 0 = unlimited
        self.redact = redact
        self._clock = clock
        self._stamps: List[float] = []

    def _rate(self) -> None:
        if self.max_writes <= 0:
            return
        now = self._clock()
        self._stamps = [t for t in self._stamps if now - t < 60.0]
        if len(self._stamps) >= self.max_writes:
            raise VaultWriteError("too many note writes in a minute")
        self._stamps.append(now)

    def _backup(self, path: Path, text: str) -> None:
        """Keep the text being replaced under `.laris/backups/` (never indexed, restorable)."""
        if not self.backup:
            return
        rel = path.relative_to(self.root.resolve()).as_posix().replace("/", "__")
        folder = self.root / BACKUP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.time_ns():020d}"
        atomic_write(folder / f"{rel}.{stamp}.{_digest(text)[:8]}.bak", text)

    def _check(self, text: str) -> None:
        if len(text) > self.max_chars:
            raise VaultWriteError("note is too large")
        if self.scan is not None and self.scan(text):
            raise VaultWriteError("note content was refused by the injection scan")

    def write_note(
        self, relative: str, props: Dict[str, Any], blocks: Dict[str, str], lead: str = ""
    ) -> str:
        """Create the note, or update only its managed blocks. Returns created, updated,
        unchanged or conflict. Text outside managed blocks is never touched."""
        path = resolve_inside(self.root, relative)
        if path.suffix != ".md":
            raise VaultWriteError("notes are Markdown files")
        if self.redact is not None:
            blocks = {k: self.redact(v) for k, v in blocks.items()}
        for text in blocks.values():
            self._check(text)
        self._rate()
        if not path.exists():
            body = lead.strip()
            text = render_note(props, body) if body else render_note(props, "")
            for name, content in blocks.items():
                text, _ = upsert_block(text, name, content)
            atomic_write(path, text)
            return "created"
        text = path.read_text(encoding="utf-8")
        statuses = []
        for name, content in blocks.items():
            text, status = upsert_block(text, name, content)
            statuses.append(status)
        if "conflict" in statuses:
            return "conflict"
        if all(s == "unchanged" for s in statuses):
            return "unchanged"
        self._backup(path, path.read_text(encoding="utf-8"))
        atomic_write(path, text)
        return "updated"
