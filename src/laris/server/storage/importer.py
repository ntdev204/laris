"""Import a SQLite server database (keys, usage, traces) into PostgreSQL, losslessly.

One transaction: either everything is copied or nothing is. Rows are keyed by their ids and
`ON CONFLICT DO NOTHING`, so running it again (or importing into a database that already has some
of the keys) adds only what is missing. Key digests and the sealed secrets are copied as they
are, so the same master secret still verifies and reveals them. Partitions for every month in
the data are created first; sequences continue after the largest imported id; the daily summary
is rebuilt at the end.
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from laris.server.storage.maintenance import Maintenance

KEY_COLUMNS = (
    "id", "digest", "secret_enc", "label", "role", "extra_permissions", "token_limit",
    "tokens_used", "created_at", "expires_at", "revoked_at", "last_used_at", "allowed_ips",
    "builtin",
)  # fmt: skip
USAGE_COLUMNS = ("id", "key_id", "ts", "session_id", "kind", "prompt_tokens", "completion_tokens")
TRACE_COLUMNS = (
    "id", "key_id", "ts", "session_id", "model", "prompt_sha256", "task", "reasoning",
    "tool_calls", "brain", "answer_chars",
)  # fmt: skip


class ImportError_(ValueError):
    """The file is not a LARIS server database."""


def _rows(conn: sqlite3.Connection, table: str, columns: tuple) -> List[Dict[str, Any]]:
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if not have:
        raise ImportError_(f"no table '{table}': is this a laris-server.db file?")
    wanted = [c for c in columns if c in have]  # older files lack secret_enc, builtin ...
    rows = conn.execute(f"SELECT {', '.join(wanted)} FROM {table} ORDER BY 1").fetchall()
    return [dict(zip(wanted, r)) for r in rows]


def import_sqlite(db: Any, path: Path) -> Dict[str, int]:
    path = Path(path)
    if not path.is_file():
        raise ImportError_(f"{path} does not exist")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        keys = _rows(src, "keys", KEY_COLUMNS)
        usage = _rows(src, "usage", USAGE_COLUMNS)
        traces = _rows(src, "traces", TRACE_COLUMNS)
    except sqlite3.DatabaseError as exc:
        raise ImportError_(f"cannot read {path}: {exc}") from exc
    finally:
        src.close()
    maintenance = Maintenance(db)
    stamps = {float(r["ts"]) for r in (*usage, *traces)}
    added = {"keys": 0, "usage": 0, "traces": 0}
    with db.transaction() as tx:
        for stamp in sorted(stamps):
            for parent in ("usage", "traces"):
                tx.execute("SELECT laris_month_partition(?::text, ?::double precision)",
                           (parent, stamp))  # fmt: skip
        for table, rows, name in (("keys", keys, "keys"), ("usage", usage, "usage"),
                                  ("traces", traces, "traces")):  # fmt: skip
            for row in rows:
                columns = list(row)
                marks = ", ".join("?" * len(columns))
                conflict = "(id, ts)" if table != "keys" else "(id)"
                done = tx.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks}) "
                    f"ON CONFLICT {conflict} DO NOTHING",
                    [bytes(v) if isinstance(v, (bytes, memoryview)) else v for v in row.values()],
                )
                added[name] += done.rowcount
        for table, seq in (("usage", "usage_seq"), ("traces", "traces_seq")):
            tx.execute(
                f"SELECT setval('{seq}', GREATEST(COALESCE((SELECT max(id) FROM {table}), 0) + 1,"
                f" (SELECT last_value FROM {seq})), false)"
            )
    maintenance.summarise()
    return added
