"""A `psycopg_pool` connection pool behind the interface the SQLite-era stores already use.

`KeyStore`, `UsageStore` and `TraceStore` call `db.connection().execute(sql, params)` with `?`
placeholders and read rows by column name. `PgDatabase` keeps that surface: each statement runs
on a pooled connection in autocommit mode, `?` becomes `%s`, rows are dicts, and `SUM()` results
(numeric in PostgreSQL) come back as plain integers. `transaction()` binds one connection for
several statements that must commit together. The key logic itself is reused unchanged.
"""

import time
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set

from laris.server.storage.migrate import migrate


class StorageError(RuntimeError):
    """The database is unreachable or misconfigured."""


def _translate(sql: str) -> str:
    return sql.replace("?", "%s")


def _plain(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: int(v) if isinstance(v, Decimal) and v == v.to_integral_value() else v
            for k, v in row.items()}  # fmt: skip


class Result:
    def __init__(self, rows: List[Dict[str, Any]], rowcount: int) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Dict[str, Any]]:
        return list(self._rows)


class Session:
    """Runs statements on one connection (a pooled autocommit one, or a transaction's)."""

    def __init__(self, db: "PgDatabase", conn: Any = None) -> None:
        self._db, self._conn = db, conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        if sql.lstrip()[:11].upper() in ("INSERT INTO",) and sql.split()[2] in ("usage", "traces"):
            self._db.ensure_current_partitions()  # rows are written "now": its month must exist
        if self._conn is not None:
            return self._run(self._conn, sql, params)
        with self._db.pool.connection() as conn:
            return self._run(conn, sql, params)

    @staticmethod
    def _run(conn: Any, sql: str, params: Sequence[Any]) -> Result:
        cur = conn.execute(_translate(sql) if params else sql, tuple(params) if params else None)
        rows = [_plain(r) for r in cur.fetchall()] if cur.description else []
        return Result(rows, cur.rowcount)


class PgDatabase:
    def __init__(
        self,
        dsn: str,
        schema: Optional[str] = None,
        min_size: int = 1,
        max_size: int = 10,
        timeout_s: float = 10.0,
        apply_migrations: bool = True,
    ) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # the server extra provides both
            raise StorageError("PostgreSQL needs psycopg and psycopg_pool (laris[server])") from exc
        self.schema = schema
        self._ensured: Set[str] = set()
        self.auto_partitions = True  # off only for tests that run old migrations by hand
        options = f"-c search_path={schema}" if schema else None
        kwargs: Dict[str, Any] = {"autocommit": True, "row_factory": dict_row}
        if options:
            kwargs["options"] = options
        self.pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, kwargs=kwargs, open=False,
            timeout=timeout_s,
        )  # fmt: skip
        try:
            self.pool.open(wait=True, timeout=timeout_s)
        except Exception as exc:
            raise StorageError(f"cannot reach PostgreSQL: {type(exc).__name__}") from exc
        if schema:
            self.session().execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        if apply_migrations:
            migrate(self)

    def ensure_current_partitions(self) -> None:
        """Once per month per process: create this and the next months' partitions."""
        key = time.strftime("%Y%m", time.gmtime())
        if not self.auto_partitions or key in self._ensured:
            return
        from laris.server.storage.maintenance import Maintenance

        Maintenance(self).ensure_partitions()
        self._ensured.add(key)

    def session(self) -> Session:
        return Session(self)

    def connection(self) -> Session:  # the name the stores call
        return self.session()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """One connection, `BEGIN` … `COMMIT`; any exception rolls everything back."""
        with self.pool.connection() as conn:
            with conn.transaction():
                yield Session(self, conn)

    def close(self) -> None:
        self.pool.close()
