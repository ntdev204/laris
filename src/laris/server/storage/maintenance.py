"""Monthly partitions, the daily usage summary and retention for PostgreSQL (T62).

`ensure_partitions` makes sure this and the next months have partitions; `summarise` writes one
`usage_daily` row per key and UTC day from the raw rows; `purge` drops whole partitions that lie
entirely before the retention cutoff (usage only after its days are summarised) and deletes the
older rows of the month that straddles it. `RetentionWorker` repeats all of it every
`serving.retention_interval_s`. Everything runs under an advisory lock, so several API containers
can run it at once.
"""

import datetime as dt
import threading
import time
from typing import Any, Dict, List, Optional

_LOCK = 7_260_002
PARENTS = ("usage", "traces")


def _month_start(moment: dt.datetime, add: int = 0) -> dt.datetime:
    index = moment.year * 12 + moment.month - 1 + add
    return dt.datetime(index // 12, index % 12 + 1, 1, tzinfo=dt.timezone.utc)


def _utc(now: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(now, dt.timezone.utc)


class Maintenance:
    def __init__(
        self, db: Any, usage_retention_days: float = 90.0, trace_retention_days: float = 30.0
    ) -> None:
        self.db = db
        self.usage_retention_days = usage_retention_days
        self.trace_retention_days = trace_retention_days

    # -- partitions ------------------------------------------------------------------------
    def ensure_partitions(self, now: Optional[float] = None, months_ahead: int = 2) -> List[str]:
        now = time.time() if now is None else now
        made = []
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(?)", (_LOCK,))
            for add in range(-1, months_ahead + 1):
                stamp = _month_start(_utc(now), add).timestamp()
                for parent in PARENTS:
                    row = tx.execute(
                        "SELECT laris_month_partition(?::text, ?::double precision) AS p",
                        (parent, stamp),
                    )
                    made.append(row.fetchone()["p"])
        return made

    def partitions(self, parent: str) -> List[str]:
        rows = self.db.connection().execute(
            "SELECT c.relname AS name FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = ? "
            "AND p.relnamespace = current_schema()::regnamespace ORDER BY c.relname",
            (parent,),
        )
        return [r["name"] for r in rows.fetchall()]

    @staticmethod
    def _upper_bound(parent: str, name: str) -> float:
        month = dt.datetime.strptime(name[len(parent) + 1 :], "%Y%m").replace(
            tzinfo=dt.timezone.utc
        )
        return _month_start(month, 1).timestamp()

    # -- daily summary ---------------------------------------------------------------------
    def summarise(self, now: Optional[float] = None) -> int:
        """Rebuild the summary from the last summarised day (inclusive) onward; returns rows."""
        now = time.time() if now is None else now
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(?)", (_LOCK,))
            last = tx.execute("SELECT MAX(day) AS d FROM usage_daily").fetchone()["d"]
            since = (
                dt.datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
                if last
                else 0.0
            )
            done = tx.execute(
                "INSERT INTO usage_daily (day, key_id, requests, prompt_tokens, completion_tokens) "
                "SELECT to_char(to_timestamp(ts) AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, key_id,"
                " COUNT(*), SUM(prompt_tokens), SUM(completion_tokens) FROM usage "
                "WHERE ts >= ? AND ts <= ? GROUP BY 1, 2 "
                "ON CONFLICT (day, key_id) DO UPDATE SET requests = EXCLUDED.requests,"
                " prompt_tokens = EXCLUDED.prompt_tokens,"
                " completion_tokens = EXCLUDED.completion_tokens",
                (since, now),
            )
        return int(done.rowcount)

    def daily(self, since_day: str = "0000-00-00") -> List[Dict[str, Any]]:
        rows = self.db.connection().execute(
            "SELECT day, key_id, requests, prompt_tokens, completion_tokens FROM usage_daily "
            "WHERE day >= ? ORDER BY day, key_id",
            (since_day,),
        )
        return list(rows.fetchall())

    # -- retention -------------------------------------------------------------------------
    def purge(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        dropped: List[str] = []
        deleted = 0
        for parent, days in (("usage", self.usage_retention_days),
                             ("traces", self.trace_retention_days)):  # fmt: skip
            cutoff = now - days * 86400
            if parent == "usage":
                self.summarise(now)  # a day is summarised before its raw rows can go
            for name in self.partitions(parent):
                if self._upper_bound(parent, name) <= cutoff:
                    self.db.connection().execute(f'DROP TABLE IF EXISTS "{name}"')
                    dropped.append(name)
            row = self.db.connection().execute(f"DELETE FROM {parent} WHERE ts < ?", (cutoff,))
            deleted += int(row.rowcount)
        return {"dropped": dropped, "rows_deleted": deleted}

    def run_once(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        return {
            "partitions": self.ensure_partitions(now),
            "summarised": self.summarise(now),
            **self.purge(now),
        }


class RetentionWorker:
    """Runs `Maintenance.run_once` now and then every `interval_s` until stopped."""

    def __init__(self, maintenance: Maintenance, interval_s: float) -> None:
        self.maintenance = maintenance
        self.interval_s = interval_s
        self.last: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="retention")

    def start(self) -> "RetentionWorker":
        self._thread.start()
        return self

    def _loop(self) -> None:
        while True:
            try:
                self.last, self.last_error = self.maintenance.run_once(), None
            except Exception as exc:  # keep serving; the next round tries again
                self.last_error = f"{type(exc).__name__}: {exc}"
            if self._stop.wait(self.interval_s):
                return

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
