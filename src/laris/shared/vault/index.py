"""Vault index: notes, resolved links, backlinks and orphans. Deterministic and rebuildable.

Link resolution follows Obsidian's shortest-path rule: a bare name matches a note title
(case-insensitively); a name with a folder part matches the path suffix. Ambiguous names are
reported, never guessed.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from laris.shared.vault.notes import Link, Note, link_name, note_from_dict, note_to_dict, parse_note

IGNORED_DIRS = {".obsidian", ".git", ".trash", "__pycache__", ".laris", "_templates"}
CACHE_VERSION = 1
_CACHE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS vault_index "
    "(path TEXT PRIMARY KEY, mtime REAL NOT NULL, data TEXT NOT NULL)"
)
Fingerprint = Tuple[int, int]  # (mtime_ns, size)


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


@dataclass
class VaultIndex:
    root: Path
    notes: Dict[str, Note] = field(default_factory=dict)  # by relative path
    _stems: Dict[str, List[str]] = field(default_factory=dict)
    _fingerprints: Dict[str, Fingerprint] = field(default_factory=dict)
    _out: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)  # path -> [(target, kind)]
    _in: Dict[str, Set[str]] = field(default_factory=dict)
    unresolved: List[Tuple[str, str]] = field(
        default_factory=list
    )  # (note path, target as written)
    ambiguous: List[Tuple[str, str]] = field(default_factory=list)

    # -- build -----------------------------------------------------------------------------
    @classmethod
    def build(
        cls,
        root: Path,
        previous: Optional["VaultIndex"] = None,
        cache_file: Optional[Path] = None,
    ) -> "VaultIndex":
        """Scan the folder; notes whose size and mtime are unchanged are reused from `previous`
        (or from the disposable `cache_file`, which is rewritten afterwards; deleting it loses
        nothing)."""
        if previous is None and cache_file is not None:
            previous = cls.load_cache(Path(root), Path(cache_file))
        index = cls(root=Path(root))
        base = index.root
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(base)
            if any(part in IGNORED_DIRS for part in rel.parts) or not path.is_file():
                continue
            if path.is_symlink() and not _inside(path, base):
                continue  # a link to a file outside the vault is never read
            stat = path.stat()
            key = rel.as_posix()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            reused = previous.notes.get(key) if previous else None
            if reused is not None and previous and previous._fingerprints.get(key) == fingerprint:
                note = reused
            else:
                note = parse_note(path.read_text(encoding="utf-8", errors="replace"), key)
            index.notes[key] = note
            index._fingerprints[key] = fingerprint
        index._link()
        if cache_file is not None:
            index.save_cache(Path(cache_file))
        return index

    # -- disposable cache --------------------------------------------------------------------
    def dumps(self) -> str:
        """Deterministic serialisation: same notes, same bytes."""
        payload = {
            "version": CACHE_VERSION,
            "notes": {
                p: {"fp": list(self._fingerprints.get(p, (0, 0))), "note": note_to_dict(n)}
                for p, n in sorted(self.notes.items())
            },
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def save_cache(self, path: Path) -> None:
        """Rewrite the disposable cache: one SQLite row per note (`vault_index`, the same table
        the client store defines). A cache that cannot be written is not an error."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=5, isolation_level=None)
            try:
                conn.execute(_CACHE_SCHEMA)
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM vault_index")
                conn.execute(
                    "INSERT OR REPLACE INTO vault_index VALUES ('__version__', 0, ?)",
                    (str(CACHE_VERSION),),
                )
                conn.executemany(
                    "INSERT INTO vault_index VALUES (?, ?, ?)",
                    [
                        (
                            p,
                            float(self._fingerprints.get(p, (0, 0))[0]),
                            json.dumps(
                                {
                                    "fp": list(self._fingerprints.get(p, (0, 0))),
                                    "note": note_to_dict(n),
                                },
                                sort_keys=True,
                                ensure_ascii=False,
                            ),
                        )
                        for p, n in sorted(self.notes.items())
                    ],
                )
                conn.execute("COMMIT")
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            pass

    @classmethod
    def load_cache(cls, root: Path, path: Path) -> Optional["VaultIndex"]:
        try:
            if not path.is_file():
                return None
            conn = sqlite3.connect(path, timeout=5)
            try:
                version = conn.execute(
                    "SELECT data FROM vault_index WHERE path = '__version__'"
                ).fetchone()
                if version is None or version[0] != str(CACHE_VERSION):
                    return None
                index = cls(root=root)
                for key, data in conn.execute(
                    "SELECT path, data FROM vault_index WHERE path != '__version__'"
                ):
                    row = json.loads(data)
                    index.notes[key] = note_from_dict(row["note"])
                    index._fingerprints[key] = (int(row["fp"][0]), int(row["fp"][1]))
                return index
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, IndexError):
            return None  # corrupt or missing: rebuild from the notes

    def _link(self) -> None:
        for path, note in self.notes.items():
            self._stems.setdefault(note.title.lower(), []).append(path)
        for stems in self._stems.values():
            stems.sort()
        for path in self.notes:
            self._out[path] = []
            self._in.setdefault(path, set())
        for path, note in sorted(self.notes.items()):
            seen: Set[str] = set()
            for link in note.links:
                target, status = self.resolve(link, path)
                if status == "self":
                    continue
                if status == "ambiguous":
                    self.ambiguous.append((path, link.target))
                elif target is None:
                    if link.target:
                        self.unresolved.append((path, link.target))
                elif target not in seen and target != path:
                    seen.add(target)
                    self._out[path].append((target, link.prop or "body"))
                    self._in[target].add(path)

    # -- queries ---------------------------------------------------------------------------
    def resolve(self, link: Link, source: str = "") -> Tuple[Optional[str], str]:
        """(note path or None, status) where status is ok, missing, ambiguous or self."""
        name = link.target.strip()
        if not name:
            return (source or None), "self"
        if name.lower().endswith(".md"):
            name = name[:-3]
        lowered = name.lower()
        if "/" in lowered:
            hits = [p for p in self.notes if p[:-3].lower().endswith(lowered)]
        else:
            hits = self._stems.get(lowered, [])
        if len(hits) == 1:
            return hits[0], "ok"
        return None, "ambiguous" if hits else "missing"

    def find(self, title: str) -> Optional[Note]:
        target, status = self.resolve(Link(title))
        return self.notes.get(target) if target and status == "ok" else None

    def outgoing(self, path: str) -> List[Tuple[str, str]]:
        return list(self._out.get(path, []))

    def backlinks(self, path: str) -> List[str]:
        return sorted(self._in.get(path, set()))

    def neighbours(self, path: str) -> List[str]:
        out = {t for t, _ in self._out.get(path, [])}
        return sorted(out | self._in.get(path, set()))

    def orphans(self) -> List[str]:
        """Notes nothing links to and that link to nothing."""
        return sorted(p for p in self.notes if not self._in[p] and not self._out[p])

    def unlinked(self) -> List[str]:
        """Notes nothing links to."""
        return sorted(p for p in self.notes if not self._in[p])

    def by_prop(self, name: str, value: str) -> List[Note]:
        return [n for _, n in sorted(self.notes.items()) if str(n.props.get(name)) == value]

    def targets(self, path: str, prop: str) -> List[str]:
        """Paths a property links to (for example `children`, `requires`)."""
        note = self.notes.get(path)
        if note is None:
            return []
        found = []
        for raw in note.prop_list(prop):
            target, status = self.resolve(Link(link_name(raw)), path)
            if target and status == "ok":
                found.append(target)
        return found
