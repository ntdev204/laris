"""Proposals inbox: what the system learned at runtime waits for the owner's review.

Proposals are written to `_inbox/` of the *project* vault. They are never retrieved or shown to the
model until accepted, and accepting one copies it into the project vault; nothing here (or anywhere
at runtime) writes to the system brain, which is protected and read-only.
"""

from dataclasses import dataclass
from typing import List, Optional

from laris.shared.vault.index import VaultIndex
from laris.shared.vault.project import ProjectVault, RecordResult
from laris.shared.vault.writer import resolve_inside, safe_title

TARGETS = {"memory": "Memory", "decision": "Decisions", "concept": "Concepts"}
PROPOSAL_BLOCK = "proposal"


@dataclass(frozen=True)
class Proposal:
    path: str
    title: str
    origin: str
    created: str
    text: str


def pending(vault: ProjectVault) -> List[Proposal]:
    folder = vault.root / vault.cfg.inbox_dir
    if not folder.is_dir():
        return []
    index = VaultIndex.build(folder)
    found = []
    for path, note in sorted(index.notes.items()):
        if note.props.get("type") != "proposal" or note.props.get("status") != "pending":
            continue
        text = "\n".join(
            vault._block_lines(vault._existing(f"{vault.cfg.inbox_dir}/{path}"), PROPOSAL_BLOCK)
        )
        found.append(
            Proposal(
                f"{vault.cfg.inbox_dir}/{path}",
                note.title,
                str(note.props.get("origin", "")),
                str(note.props.get("created", "")),
                text,
            )
        )
    return found


def propose(vault: ProjectVault, title: str, text: str, origin: str = "user") -> RecordResult:
    return vault.propose(title, text, origin)


def _find(vault: ProjectVault, title: str) -> Optional[Proposal]:
    wanted = safe_title(title).lower()
    for item in pending(vault):
        if item.title.lower() == wanted:
            return item
    return None


def _remove(vault: ProjectVault, item: Proposal) -> None:
    path = resolve_inside(vault.root, item.path)
    vault.writer._backup(path, path.read_text(encoding="utf-8"))
    path.unlink()


def accept(vault: ProjectVault, title: str, into: str = "memory") -> RecordResult:
    """Copy the proposal into the project vault (memory, decision or concept) and clear it."""
    if into not in TARGETS:
        raise ValueError(f"into must be one of: {', '.join(sorted(TARGETS))}")
    item = _find(vault, title)
    if item is None:
        raise KeyError(f"no pending proposal named '{title}'")
    if into == "memory":
        result = vault.record_memory(item.title, item.text)
    else:
        result = vault._write(
            TARGETS[into],
            item.title,
            {
                "type": into,
                "origin": f"accepted proposal ({item.origin})",
                "created": vault._today(),
            },
            {"text": item.text},
            lead=f"# {safe_title(item.title)}",
        )
    if result.status in {"created", "updated", "unchanged"}:
        _remove(vault, item)
    return result


def reject(vault: ProjectVault, title: str) -> bool:
    item = _find(vault, title)
    if item is None:
        return False
    _remove(vault, item)
    return True
