import json
import sqlite3
import threading

from laris.client.store import MIGRATIONS, Store, migrate_legacy, space_path


def _legacy(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    rows = [
        {
            "chunk_id": f"d:{n}",
            "doc_id": "d",
            "source": "a.txt",
            "title": "A",
            "text": f"passage {n}",
            "start": n,
            "end": n + 9,
        }
        for n in range(3)
    ]
    (ws / "chunks.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    chats = tmp_path / "chat"
    chats.mkdir()
    conv = {"id": "0123456789ab", "title": "t", "created": 1.0, "updated": 2.0, "messages": []}
    (chats / "0123456789ab.json").write_text(json.dumps(conv), encoding="utf-8")
    (chats / "junk.json").write_text("not json", encoding="utf-8")
    return ws, chats


def test_space_path_is_per_project_and_key(tmp_path):
    a = space_path(tmp_path, tmp_path / "p1", "AB12")
    assert a.parent.parent == tmp_path / "projects" and a.name == "ab12.sqlite"
    assert space_path(tmp_path, tmp_path / "p2", "ab12").parent != a.parent
    assert space_path(tmp_path, tmp_path / "p1").name == "local.sqlite"


def test_store_uses_wal_and_migrates_once(tmp_path):
    store = Store(tmp_path / "s" / "x.sqlite")
    assert store.version() == MIGRATIONS[-1][0] and store.migrate() == 0
    with store.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == store.busy_timeout_ms


def test_failed_transaction_rolls_back(tmp_path):
    store = Store(tmp_path / "x.sqlite")
    try:
        with store.transaction() as conn:
            conn.execute("INSERT INTO meta VALUES ('k','v')")
            raise RuntimeError
    except RuntimeError:
        pass
    assert store.get_meta("k") is None


def test_migration_is_lossless_idempotent_and_backed_up(tmp_path):
    ws, chats = _legacy(tmp_path)
    store = Store(tmp_path / "home" / "projects" / "p" / "local.sqlite")
    assert migrate_legacy(store, ws, chats) == {"chunks": 3, "conversations": 1, "learning": 0}
    with store.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT text FROM chunks ORDER BY ordinal")] == [
            "passage 0",
            "passage 1",
            "passage 2",
        ]
        data = json.loads(conn.execute("SELECT data FROM conversations").fetchone()[0])
    assert data["title"] == "t"
    backups = sorted(p.name for p in (store.path.parent / "backups").iterdir())
    assert len(backups) == 2 and (ws / "chunks.jsonl").exists()  # originals are kept
    before = store.path.read_bytes()
    assert migrate_legacy(store, ws, chats) == {"chunks": 0, "conversations": 0, "learning": 0}
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 3
    assert len(list((store.path.parent / "backups").iterdir())) == 2
    assert before[:16] == store.path.read_bytes()[:16]


def test_concurrent_writers_lose_nothing(tmp_path):
    store = Store(tmp_path / "x.sqlite")

    def write(n):
        for i in range(20):
            with store.transaction() as conn:
                conn.execute("INSERT INTO meta VALUES (?, 'x')", (f"{n}-{i}",))

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 80
