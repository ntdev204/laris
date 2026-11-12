import os
import sqlite3

import pytest

from laris.server.serverdata.crypto import SecretBox
from laris.server.serverdata.db import Database
from laris.server.serverdata.keys import KeyStore
from laris.server.serverdata.traces import TraceStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.ports import Principal
from laris.server.storage.importer import ImportError_, import_sqlite

ROLES = {"user": ["chat", "account"], "admin": ["chat", "account", "keys.manage"]}
MASTER = b"m" * 32


def _keys(db):
    return KeyStore(db, ROLES, ["admin"], ["keys.manage"], ["chat", "account", "keys.manage"],
                    SecretBox(MASTER))  # fmt: skip


@pytest.fixture
def fixture_db(tmp_path):
    db = Database(tmp_path / "laris-server.db")
    keys = _keys(db)
    made = {}
    a, made["a"] = keys.create("lab a", "user", 5000, allowed_ips=["10.0.0.0/8"], now=1_700_000_000)
    b, made["b"] = keys.create("root", "admin", None, ["keys.manage"], builtin=True,
                               now=1_700_100_000)  # fmt: skip
    r, made["r"] = keys.create("old", "user", 10, now=1_700_200_000)
    keys.revoke(r.id, now=1_700_300_000)
    usage = UsageStore(db)
    caller = Principal(a.id, "user", frozenset(["chat"]))
    for n in range(7):
        row = {"prompt_tokens": 10 + n, "completion_tokens": n, "session_id": f"s{n}"}
        usage.record(caller, row)
    trace = {"task": "t", "reasoning": "r", "model": "m", "answer_chars": 3}
    TraceStore(db).record(caller, trace)
    db.connection().execute("UPDATE usage SET ts = ts - 86400 * 70 WHERE id <= 2")  # older month
    return tmp_path / "laris-server.db", made, (a, b, r)


def test_import_is_lossless_and_keys_verify_and_reveal(pg, fixture_db):
    path, plaintext, (a, b, r) = fixture_db
    added = import_sqlite(pg, path)
    assert added == {"keys": 3, "usage": 7, "traces": 1}
    keys = _keys(pg)
    assert keys.verify(plaintext["a"]).id == a.id and keys.reveal(a.id) == plaintext["a"]
    assert keys.reveal(b.id) == plaintext["b"] and keys.default_key().id == b.id
    assert keys.verify(plaintext["r"]) is None  # the revoked key stays revoked
    source = _keys(Database(path))
    for record in (a, b, r):  # every field: limits, rules, use, timestamps
        assert keys.get(record.id) == source.get(record.id)
    assert keys.get(a.id).tokens_used == 112 and keys.get(a.id).allowed_ips == ("10.0.0.0/8",)
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    for table, order in (("usage", "id"), ("traces", "id")):
        old = [dict(x) for x in src.execute(f"SELECT * FROM {table} ORDER BY {order}")]
        new = pg.session().execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        assert new == old
    usage = UsageStore(pg)
    assert usage.summary() == [
        {
            "key_id": a.id,
            "requests": 7,
            "prompt": sum(10 + n for n in range(7)),
            "completion": sum(range(7)),
        }  # fmt: skip
    ]
    # new rows continue after the imported ids, and a second import adds nothing
    usage.record(Principal(a.id, "user", frozenset(["chat"])), {"prompt_tokens": 1})
    top = pg.session().execute("SELECT max(id) AS m FROM usage").fetchone()["m"]
    assert top == 8
    assert import_sqlite(pg, path) == {"keys": 0, "usage": 0, "traces": 0}


def test_import_reads_a_file_that_predates_encrypted_keys(pg, tmp_path):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.executescript(
        "CREATE TABLE keys (id TEXT PRIMARY KEY, digest TEXT, label TEXT, role TEXT,"
        " extra_permissions TEXT, token_limit INTEGER, tokens_used INTEGER, created_at REAL,"
        " expires_at REAL, revoked_at REAL, last_used_at REAL);"
        "CREATE TABLE usage (id INTEGER PRIMARY KEY, key_id TEXT, ts REAL, session_id TEXT,"
        " kind TEXT, prompt_tokens INTEGER, completion_tokens INTEGER);"
        "CREATE TABLE traces (id INTEGER PRIMARY KEY, key_id TEXT, ts REAL, session_id TEXT,"
        " model TEXT, prompt_sha256 TEXT, task TEXT, reasoning TEXT, tool_calls TEXT, brain TEXT,"
        " answer_chars INTEGER);"
        "INSERT INTO keys VALUES ('k1','dg','l','user','[]',9,1,1.0,NULL,NULL,NULL);"
    )
    conn.commit()
    conn.close()
    assert import_sqlite(pg, old) == {"keys": 1, "usage": 0, "traces": 0}
    row = pg.session().execute("SELECT * FROM keys WHERE id='k1'").fetchone()
    assert row["secret_enc"] is None and row["allowed_ips"] == "[]" and row["builtin"] == 0


def test_import_refuses_other_files_and_is_all_or_nothing(pg, tmp_path):
    with pytest.raises(ImportError_):
        import_sqlite(pg, tmp_path / "missing.db")
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE x (a)").connection.commit()
    with pytest.raises(ImportError_):
        import_sqlite(pg, other)
    assert pg.session().execute("SELECT COUNT(*) AS n FROM keys").fetchone()["n"] == 0


def test_db_import_sqlite_command(pg, fixture_db, tmp_path, monkeypatch, capsys):
    from cli.server import main

    dsn = os.environ["LARIS_TEST_PG_DSN"]
    sep = "&" if "?" in dsn else "?"
    monkeypatch.setenv("LARIS_DATABASE_URL", f"{dsn}{sep}options=-csearch_path%3D{pg.schema}")
    monkeypatch.setenv("LARIS_SERVING__DATABASE_ENGINE", "postgres")
    monkeypatch.chdir(tmp_path)
    assert main(["db", "import-sqlite", str(fixture_db[0])]) == 0
    assert "imported 3 key(s), 7 usage row(s), 1 trace(s)" in capsys.readouterr().out
    monkeypatch.setenv("LARIS_SERVING__DATABASE_ENGINE", "sqlite")
    assert main(["db", "import-sqlite", str(fixture_db[0])]) == 2
