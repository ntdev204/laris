"""One SQLite file per private space at `<home>/projects/<slug>/<key-fp>.sqlite`.

WAL journal, a busy timeout, one short-lived connection per operation (so threads never share a
connection) and numbered migrations recorded in `schema_version`. Nothing here is a tunable
secret: the home folder and the timeout come from the caller.
"""

import hashlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

MIGRATIONS: Tuple[Tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, source TEXT NOT NULL,
            title TEXT NOT NULL, text TEXT NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
            ordinal INTEGER NOT NULL);
        CREATE INDEX chunks_doc ON chunks(doc_id);
        CREATE TABLE embeddings (
            chunk_id TEXT NOT NULL, model_id TEXT NOT NULL, dim INTEGER NOT NULL,
            vector BLOB NOT NULL, PRIMARY KEY (chunk_id, model_id));
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL,
            updated REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE learning (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, created REAL NOT NULL,
            data TEXT NOT NULL);
        CREATE TABLE vault_index (path TEXT PRIMARY KEY, mtime REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """,
    ),
)

_SAFE = re.compile(r"[^a-z0-9._-]+")


def slug_of(project_root: Path) -> str:
    """Readable and collision-free: the folder name plus a short hash of its full path."""
    resolved = Path(project_root).resolve()
    name = _SAFE.sub("-", resolved.name.lower()).strip("-") or "project"
    return f"{name}-{hashlib.sha256(str(resolved).encode('utf-8')).hexdigest()[:8]}"


def space_path(home: Path, project_root: Path, key_fingerprint: Optional[str] = None) -> Path:
    fingerprint = _SAFE.sub("", (key_fingerprint or "local").lower()) or "local"
    return Path(home).expanduser() / "projects" / slug_of(project_root) / f"{fingerprint}.sqlite"


class Store:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._migrate_lock = threading.Lock()
        self.migrate()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None)
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """`BEGIN IMMEDIATE`: writers queue on the busy timeout instead of failing half way."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def version(self) -> int:
        with self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='schema_version'"
            ).fetchone():
                return 0
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return int(row[0] or 0)

    def migrate(self) -> int:
        """Apply the migrations not yet applied, each in its own transaction; returns how many."""
        with self._migrate_lock:
            applied = 0
            with self.transaction() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
                )
            for number, script in MIGRATIONS:
                with self.transaction() as conn:
                    done = conn.execute(
                        "SELECT 1 FROM schema_version WHERE version = ?", (number,)
                    ).fetchone()
                    if done:
                        continue
                    for statement in script.split(";"):
                        if statement.strip():
                            conn.execute(statement)
                    conn.execute("INSERT INTO schema_version VALUES (?)", (number,))
                    applied += 1
            return applied

    # -- meta ------------------------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row[0])
