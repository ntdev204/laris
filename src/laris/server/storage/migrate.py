"""Numbered SQL migrations (`migrations/NNNN_name.sql`), each applied once in its own transaction.

A transaction-level advisory lock makes two processes that start together apply them in turn
instead of racing.
"""

import re
from importlib import resources
from typing import Any, List, Tuple

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_LOCK = 7_260_001  # arbitrary application-wide advisory lock id


def migration_files() -> List[Tuple[int, str, str]]:
    """(number, name, sql) in order; numbers must be 1, 2, 3 … without gaps."""
    found = []
    for entry in resources.files("laris.server.storage").joinpath("migrations").iterdir():
        match = _NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    if [n for n, _, _ in found] != list(range(1, len(found) + 1)):
        raise ValueError("migration numbers must run 1, 2, 3 … without gaps")
    return found


def migrate(db: Any) -> int:
    """Apply the pending migrations; returns how many were applied."""
    applied = 0
    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(?)", (_LOCK,))
        tx.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ DEFAULT now())"
        )
        done = {r["version"] for r in tx.execute("SELECT version FROM schema_version").fetchall()}
        for number, name, sql in migration_files():
            if number in done:
                continue
            tx.execute(sql)
            tx.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (number, name))
            applied += 1
    return applied
