import datetime as dt
import threading
import time

from laris.server.serverdata.traces import TraceStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.ports import Principal
from laris.server.storage.maintenance import Maintenance, RetentionWorker

DAY = 86400.0
NOW = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.timezone.utc).timestamp()


def _put_usage(pg, key, ts, prompt, completion):
    Maintenance(pg).ensure_partitions(ts, 0)
    pg.session().execute(
        "INSERT INTO usage (key_id, ts, session_id, kind, prompt_tokens, completion_tokens)"
        " VALUES (?,?,?,?,?,?)",
        (key, ts, "", "chat", prompt, completion),
    )


def test_tables_are_partitioned_by_month_and_inserts_create_their_partition(pg):
    usage = UsageStore(pg)
    principal = Principal("k1", "user", frozenset())
    pg.session().execute(
        "INSERT INTO keys (id, digest, role, created_at) VALUES ('k1','d','user',0)"
    )
    usage.record(principal, {"prompt_tokens": 3, "completion_tokens": 2})
    month = time.strftime("%Y%m", time.gmtime())
    maintenance = Maintenance(pg)
    assert f"usage_{month}" in maintenance.partitions("usage")
    assert len(maintenance.partitions("traces")) >= 3  # this month, last month and the next two
    kind = (
        pg.session()
        .execute(
            "SELECT relkind FROM pg_class WHERE relname='usage' "
            "AND relnamespace = current_schema()::regnamespace"
        )
        .fetchone()["relkind"]
    )
    assert kind == "p"


def test_expired_partitions_are_dropped_and_the_summary_matches_raw_usage(pg):
    maintenance = Maintenance(pg, usage_retention_days=60, trace_retention_days=30)
    old = NOW - 200 * DAY
    recent = NOW - 2 * DAY
    for ts, p, c in ((old, 10, 5), (old + 3600, 1, 1), (recent, 7, 3), (recent + 60, 2, 2)):
        _put_usage(pg, "kA", ts, p, c)
    _put_usage(pg, "kB", recent, 4, 4)
    old_month = dt.datetime.fromtimestamp(old, dt.timezone.utc).strftime("%Y%m")
    assert f"usage_{old_month}" in maintenance.partitions("usage")
    result = maintenance.run_once(NOW)
    assert f"usage_{old_month}" in result["dropped"]
    assert f"usage_{old_month}" not in maintenance.partitions("usage")
    daily = {(r["day"], r["key_id"]): r for r in maintenance.daily()}
    old_day = dt.datetime.fromtimestamp(old, dt.timezone.utc).strftime("%Y-%m-%d")
    # the dropped days stay in the summary, with the totals of their raw rows
    assert daily[(old_day, "kA")]["requests"] == 2 and daily[(old_day, "kA")]["prompt_tokens"] == 11
    recent_day = dt.datetime.fromtimestamp(recent, dt.timezone.utc).strftime("%Y-%m-%d")
    raw = (
        pg.session()
        .execute(
            "SELECT key_id, COUNT(*) AS n, SUM(prompt_tokens) AS p, SUM(completion_tokens) AS c "
            "FROM usage WHERE ts >= ? GROUP BY key_id ORDER BY key_id",
            (recent - 1,),
        )
        .fetchall()
    )
    for row in raw:
        summary = daily[(recent_day, row["key_id"])]
        assert (summary["requests"], summary["prompt_tokens"], summary["completion_tokens"]) == (
            row["n"], row["p"], row["c"])  # fmt: skip
    again = maintenance.run_once(NOW)  # a second run changes nothing
    assert again["dropped"] == [] and {k: v for k, v in daily.items()} == {
        (r["day"], r["key_id"]): r for r in maintenance.daily()
    }


def test_traces_expire_by_partition_and_by_row_in_the_boundary_month(pg):
    maintenance = Maintenance(pg, trace_retention_days=30)
    store = TraceStore(pg)
    for ts in (NOW - 120 * DAY, NOW - 40 * DAY, NOW - DAY):
        maintenance.ensure_partitions(ts, 0)
        pg.session().execute(
            "INSERT INTO traces (key_id, ts, task) VALUES ('k', ?, ?)", (ts, f"t{int(ts)}")
        )
    result = maintenance.run_once(NOW)
    left = [r["task"] for r in pg.session().execute("SELECT task FROM traces").fetchall()]
    assert left == [f"t{int(NOW - DAY)}"] and result["dropped"] and store.list(None, 10)


def test_maintenance_from_several_processes_at_once_and_the_worker(pg):
    maintenance = Maintenance(pg)
    errors = []

    def run():
        try:
            maintenance.run_once(NOW)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    worker = RetentionWorker(maintenance, 0.05).start()
    deadline = time.time() + 5
    while worker.last is None and time.time() < deadline:
        time.sleep(0.02)
    worker.stop()
    assert worker.last is not None and worker.last_error is None


def test_rows_written_before_partitioning_survive_the_migration(pg):
    """Run 0001 + 0002 on a fresh schema with data, then apply 0003."""
    import os
    import uuid

    from laris.server.storage import PgDatabase, migration_files
    from laris.server.storage.maintenance import Maintenance as M

    schema = "m_" + uuid.uuid4().hex[:8]
    db = PgDatabase(os.environ["LARIS_TEST_PG_DSN"], schema=schema, apply_migrations=False)
    db.auto_partitions = False
    try:
        with db.transaction() as tx:
            tx.execute(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "applied_at TIMESTAMPTZ DEFAULT now())"
            )
            for number, name, sql in migration_files()[:2]:
                tx.execute(sql)
                tx.execute(
                    "INSERT INTO schema_version (version, name) VALUES (?, ?)", (number, name)
                )
            tx.execute(
                "INSERT INTO usage (key_id, ts, prompt_tokens) VALUES ('k', ?, 5)",
                (NOW - 90 * DAY,),
            )
            tx.execute(
                "INSERT INTO traces (key_id, ts, task) VALUES ('k', ?, 'x')", (NOW - 95 * DAY,)
            )
        from laris.server.storage import migrate

        assert migrate(db) == len(migration_files()) - 2
        assert (
            db.session().execute("SELECT SUM(prompt_tokens) AS n FROM usage").fetchone()["n"] == 5
        )
        assert db.session().execute("SELECT task FROM traces").fetchone()["task"] == "x"
        assert any(M(db).partitions("usage"))
    finally:
        db.session().execute(f'DROP SCHEMA "{schema}" CASCADE')
        db.close()
