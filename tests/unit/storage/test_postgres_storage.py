import json
import threading

import pytest

from laris.server.serverdata.crypto import SecretBox
from laris.server.serverdata.keys import KeyStore
from laris.server.serverdata.traces import TraceStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.ports import Principal, QuotaExceeded
from laris.server.storage import migrate, migration_files

ROLES = {"user": ["chat", "account"], "admin": ["chat", "account", "keys.manage"]}


def _keys(db):
    box = SecretBox(b"0" * 32)
    return KeyStore(db, ROLES, ["admin"], ["keys.manage"], ["chat", "account", "keys.manage"], box)


def test_migrations_are_numbered_without_gaps_and_apply_once(pg):
    files = migration_files()
    assert [n for n, _, _ in files] == list(range(1, len(files) + 1))
    assert migrate(pg) == 0  # PgDatabase already applied them
    rows = pg.session().execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == [n for n, _, _ in files]


def test_two_processes_migrating_together_apply_each_once():
    import os
    import uuid

    from laris.server.storage import PgDatabase

    dsn = os.environ.get("LARIS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("LARIS_TEST_PG_DSN is not set")
    schema = "mm_" + uuid.uuid4().hex[:8]
    db = PgDatabase(dsn, schema=schema, apply_migrations=False, max_size=8)
    errors = []

    def run():
        try:
            migrate(db)
        except Exception as exc:  # pragma: no cover - the assertion reports it
            errors.append(exc)

    try:
        threads = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors
        count = db.session().execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        assert count == len(migration_files())
    finally:
        db.session().execute(f'DROP SCHEMA "{schema}" CASCADE')
        db.close()


def test_keys_create_verify_reveal_revoke_limit(pg):
    keys = _keys(pg)
    record, plaintext = keys.create("lab", "user", 1000, allowed_ips=["10.0.0.0/8"])
    assert plaintext.startswith("lk_") and record.allowed_ips == ("10.0.0.0/8",)
    assert keys.verify(plaintext).id == record.id
    assert keys.verify(plaintext + "x") is None and keys.verify("") is None
    assert keys.reveal(record.id) == plaintext
    assert keys.set_limit(record.id, 500, add=True).token_limit == 1500
    assert keys.revoke(record.id).revoked_at is not None and keys.verify(plaintext) is None
    admin, _ = keys.create("root", "admin", None, ["keys.manage"], builtin=True)
    assert keys.default_key().id == admin.id and len(keys.list()) == 2


def test_usage_records_and_summarises_as_plain_numbers(pg):
    keys = _keys(pg)
    record, _ = keys.create("u", "user", 100)
    usage = UsageStore(pg)
    principal = Principal(record.id, "user", frozenset(["chat"]), 100)
    usage.record(principal, {"prompt_tokens": 30, "completion_tokens": 10, "kind": "chat"})
    usage.record(principal, {"prompt_tokens": 5, "completion_tokens": 5})
    summary = usage.summary()
    assert summary == [{"key_id": record.id, "requests": 2, "prompt": 35, "completion": 15}]
    json.dumps(summary)  # no Decimal leaks into JSON
    assert usage.account(principal)["tokens_left"] == 50
    usage.check(principal, 50)
    with pytest.raises(QuotaExceeded):
        usage.check(principal, 51)


def test_traces_are_redacted_listed_and_purged(pg):
    store = TraceStore(pg, redact=lambda t: t.replace("SECRET", "***"))
    principal = Principal("k1", "user", frozenset())
    store.record(principal, {"task": "t SECRET", "reasoning": "r SECRET", "model": "m"})
    row = store.list(None, 5)[0]
    assert row["key_id"] == "k1" and store.get(row["id"])["reasoning"] == "r ***"
    assert store.purge(older_than_days=-1) == 1 and store.list(None, 5) == []


def test_db_migrate_command_and_server_data_on_postgres(tmp_path, monkeypatch, pg, capsys):
    import os

    from cli.server import main
    from laris.server.serverdata import ServerData
    from laris.shared.config.runtime_schemas import ServingConfig

    dsn = os.environ["LARIS_TEST_PG_DSN"]
    schema = pg.schema
    sep = "&" if "?" in dsn else "?"
    monkeypatch.setenv("LARIS_DATABASE_URL", f"{dsn}{sep}options=-csearch_path%3D{schema}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LARIS_SERVING__DATABASE_ENGINE", "postgres")
    assert main(["db", "migrate"]) == 0
    assert "PostgreSQL schema at version" in capsys.readouterr().out
    cfg = ServingConfig(database_engine="postgres", master_file=str(tmp_path / "m.secret"))
    data = ServerData(
        cfg, tmp_path, environ=dict(os.environ, LARIS_DATABASE_URL=os.environ["LARIS_DATABASE_URL"])
    )
    first = data.ensure_default_key()
    assert first and first.startswith("lk_") and data.ensure_default_key() is None
    assert data.keys.reveal(data.keys.default_key().id) == first
    principal = data.auth.authenticate(first, "127.0.0.1")  # the default key works from here
    assert principal is not None and principal.role == "admin"
