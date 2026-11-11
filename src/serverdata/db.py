"""SQLite storage: one file, WAL, one connection per thread, versioned migrations."""

import os
import sqlite3
import threading
from pathlib import Path
from typing import List

MIGRATIONS: List[str] = [
    """
    CREATE TABLE keys (
        id TEXT PRIMARY KEY,
        digest TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL,
        extra_permissions TEXT NOT NULL DEFAULT '[]',
        token_limit INTEGER,
        tokens_used INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        expires_at REAL,
        revoked_at REAL,
        last_used_at REAL
    );
    CREATE TABLE usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_id TEXT NOT NULL,
        ts REAL NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'chat',
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX usage_key_ts ON usage (key_id, ts);
    CREATE TABLE traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_id TEXT NOT NULL,
        ts REAL NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        prompt_sha256 TEXT NOT NULL DEFAULT '',
        task TEXT NOT NULL DEFAULT '',
        reasoning TEXT NOT NULL DEFAULT '',
        tool_calls TEXT NOT NULL DEFAULT '[]',
        brain TEXT NOT NULL DEFAULT '[]',
        answer_chars INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX traces_key_ts ON traces (key_id, ts);
    """,
    """
    ALTER TABLE keys ADD COLUMN secret_enc BLOB;
    ALTER TABLE keys ADD COLUMN allowed_ips TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE keys ADD COLUMN builtin INTEGER NOT NULL DEFAULT 0;
    """,
]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._local = threading.local()
        self._migrate()
        os.chmod(self.path, 0o600)  # keys' digests and reasoning: owner only

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _migrate(self) -> None:
        conn = self.connection()
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for number, script in enumerate(MIGRATIONS, 1):
            if number > current:
                conn.executescript(
                    "BEGIN;" + script + f"INSERT INTO schema_version VALUES({number});COMMIT;"
                )
