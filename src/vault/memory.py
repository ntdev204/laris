"""Project memory kept in the vault (`Memory/`), with a reversible migration from `.laris/memory`.

One memory is one note `Memory/<name> (memory).md` whose text sits in a managed block. The prompt's
memory section is built from those notes within a size limit. Files still in the legacy folder are
read too until they are migrated; the migration copies (never moves) and records what it made, so
`undo` removes exactly those notes.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from vault.index import VaultIndex
from vault.project import MEMORY_SUFFIX, ProjectVault
from vault.writer import safe_title

MARKER = ".migrated.json"
MEMORY_BLOCK = "memory"


def _note_text(vault: ProjectVault, title: str) -> str:
    text = vault._existing(f"Memory/{safe_title(title) + MEMORY_SUFFIX}.md")
    return "\n".join(vault._block_lines(text, MEMORY_BLOCK))


def write_memory(
    vault: ProjectVault, name: str, content: str, append: bool = True
) -> Tuple[str, str]:
    """Create or extend a memory. Returns (mode, vault-relative path); a refused write raises."""
    existing = _note_text(vault, name) if append else ""
    text = (existing + "\n\n" + content.strip()) if existing else content.strip()
    result = vault.record_memory(name, text)
    if result.status in {"skipped", "conflict"}:
        raise ValueError(result.reason or "memory note is being edited by hand")
    return ("appended" if existing else "created"), result.note


def memory_names(vault: ProjectVault) -> List[str]:
    folder = vault.root / "Memory"
    if not folder.is_dir():
        return []
    return sorted(p.stem.removesuffix(MEMORY_SUFFIX) for p in folder.glob("*.md"))


def read_memory(vault: ProjectVault, legacy: Path, limit: int) -> str:
    """The prompt's memory section: vault memories first, then un-migrated legacy files."""
    parts: List[str] = []
    for name in memory_names(vault):
        body = " ".join(_note_text(vault, name).split())
        if body:
            parts.append(f"- {name}: {body[:400]}")
    migrated = _migrated(legacy)
    if legacy.is_dir():
        index = legacy / "MEMORY.md"
        if index.is_file():
            parts.append(index.read_text(encoding="utf-8").strip())
        names = sorted(
            p.name for p in legacy.glob("*.md") if p.name != "MEMORY.md" and p.stem not in migrated
        )
        if names:
            parts.append("Files: " + ", ".join(names))
    return "\n".join(parts)[:limit]


def _migrated(legacy: Path) -> Dict[str, str]:
    try:
        data = json.loads((legacy / MARKER).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def migrate(vault: ProjectVault, legacy: Path) -> Dict[str, str]:
    """Copy each legacy memory file into the vault. Idempotent; originals stay in place."""
    done = _migrated(legacy)
    if not legacy.is_dir():
        return done
    for path in sorted(legacy.glob("*.md")):
        if path.name == "MEMORY.md" or path.stem in done:
            continue
        result = vault.record_memory(path.stem, path.read_text(encoding="utf-8").strip())
        if result.status in {"created", "updated", "unchanged"}:
            done[path.stem] = result.note
    (legacy / MARKER).write_text(json.dumps(done, indent=2, sort_keys=True), encoding="utf-8")
    return done


def undo_migration(vault: ProjectVault, legacy: Path) -> int:
    """Delete exactly the notes the migration made. The legacy files were never touched."""
    done = _migrated(legacy)
    removed = 0
    for note in done.values():
        path = vault.root / note
        if path.is_file():
            path.unlink()
            removed += 1
    marker = legacy / MARKER
    if marker.exists():
        marker.unlink()
    return removed


def memory_index(vault: ProjectVault) -> VaultIndex:
    return (
        VaultIndex.build(vault.root / "Memory")
        if (vault.root / "Memory").is_dir()
        else VaultIndex(vault.root)
    )
