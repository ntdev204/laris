"""Reserve before the model call, settle after it in one transaction (T61). Runs on SQLite always
and on PostgreSQL when LARIS_TEST_PG_DSN is set."""

import os
import threading
import uuid

import pytest

from laris.client.agent.provider import AssistantTurn, ChatProvider
from laris.server.gateway import PolicyGateway
from laris.server.serverdata.crypto import SecretBox
from laris.server.serverdata.db import Database
from laris.server.serverdata.keys import KeyStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.ports import Principal, QuotaExceeded
from laris.shared.harness.runtime import HarnessRuntime

ROLES = {"user": ["chat", "account"]}


@pytest.fixture(params=["sqlite", "postgres"])
def stores(request, tmp_path):
    if request.param == "sqlite":
        db = Database(tmp_path / "q.db")
        cleanup = None
    else:
        dsn = os.environ.get("LARIS_TEST_PG_DSN")
        if not dsn:
            pytest.skip("LARIS_TEST_PG_DSN is not set")
        from laris.server.storage import PgDatabase

        schema = "q_" + uuid.uuid4().hex[:10]
        db = PgDatabase(dsn, schema=schema, max_size=24)
        cleanup = schema
    keys = KeyStore(db, ROLES, [], [], ["chat", "account"], SecretBox(b"1" * 32))
    yield db, keys, UsageStore(db)
    if cleanup:
        db.session().execute(f'DROP SCHEMA "{cleanup}" CASCADE')
        db.close()


def _row(db, key_id):
    return db.connection().execute("SELECT * FROM keys WHERE id=?", (key_id,)).fetchone()


def _principal(record):
    return Principal(record.id, "user", frozenset(["chat"]), record.token_limit)


def test_parallel_requests_never_pass_the_limit(stores):
    db, keys, usage = stores
    record, _ = keys.create("lab", "user", 100)
    principal = _principal(record)
    won, lost = [], []

    def worker():
        try:
            won.append(usage.reserve(principal, 10))
        except QuotaExceeded:
            lost.append(1)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(won) == 10 and len(lost) == 30
    assert _row(db, record.id)["tokens_reserved"] == 100
    for reservation in won:
        reservation.settle({"prompt_tokens": 6, "completion_tokens": 4})
    row = _row(db, record.id)
    assert (row["tokens_used"], row["tokens_reserved"]) == (100, 0)
    with pytest.raises(QuotaExceeded):
        usage.reserve(principal, 1)  # the limit is spent
    assert usage.summary()[0]["requests"] == 10


def test_release_returns_the_tokens_and_ending_twice_does_nothing(stores):
    db, keys, usage = stores
    record, _ = keys.create("lab", "user", 50)
    principal = _principal(record)
    first = usage.reserve(principal, 50)
    with pytest.raises(QuotaExceeded):
        usage.reserve(principal, 1)
    first.release()
    first.release()
    first.settle({"prompt_tokens": 99})  # already ended: ignored
    assert (_row(db, record.id)["tokens_reserved"], _row(db, record.id)["tokens_used"]) == (0, 0)
    usage.reserve(principal, 50).settle({"prompt_tokens": 20, "completion_tokens": 5})
    assert _row(db, record.id)["tokens_used"] == 25
    assert usage.account(principal)["tokens_left"] == 25


def test_unlimited_and_revoked_keys(stores):
    db, keys, usage = stores
    record, _ = keys.create("free", "user", None)
    usage.reserve(_principal(record), 10**9).release()
    keys.revoke(record.id)
    with pytest.raises(QuotaExceeded):
        usage.reserve(_principal(record), 1)


class Echo(ChatProvider):
    name = "echo"

    def chat(self, messages, tools):
        return AssistantTurn("Perovskite is stable.")

    def stream(self, messages, tools):
        for part in ("Perovskite ", "is ", "stable."):
            yield {"type": "text", "delta": part}
        yield {"type": "turn", "turn": AssistantTurn("Perovskite is stable.")}


def test_a_client_that_disconnects_is_still_settled(stores):
    db, keys, usage = stores
    record, _ = keys.create("lab", "user", 10_000)
    principal = _principal(record)
    from pathlib import Path

    runtime = HarnessRuntime.load(Path(__file__).resolve().parents[3])
    gateway = PolicyGateway(runtime, Echo(), "m", meter=usage)
    body = {
        "messages": [{"role": "user", "content": "Is perovskite stable?"}],
        "laris": {"kind": "turn", "session_id": "abc123", "task": "t"},
    }
    reservation = usage.reserve(principal, 500)
    stream = gateway.stream(body, principal, reservation)
    next(stream)  # the model has been called and one chunk has gone out …
    stream.close()  # … and the client drops the connection
    row = _row(db, record.id)
    assert row["tokens_reserved"] == 0 and row["tokens_used"] > 0
    assert usage.summary()[0]["requests"] == 1


def test_a_refused_request_gives_its_reservation_back(stores):
    db, keys, usage = stores
    record, _ = keys.create("lab", "user", 1000)
    principal = _principal(record)
    from pathlib import Path

    runtime = HarnessRuntime.load(Path(__file__).resolve().parents[3])
    gateway = PolicyGateway(runtime, Echo(), "m", meter=usage)
    reservation = usage.reserve(principal, 300)
    with pytest.raises(Exception):
        list(gateway.stream({"messages": []}, principal, reservation))
    assert _row(db, record.id)["tokens_reserved"] == 0 and reservation.done
