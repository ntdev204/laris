"""T79 (SR-C1): status line, /cost and /context, queued input, interrupt leaves a valid history."""

import subprocess
import threading
import time

from laris.client.agent.loop import AgentSession
from laris.client.engine import statusline
from laris.server.serverdata.crypto import SecretBox
from laris.server.serverdata.db import Database
from laris.server.serverdata.keys import KeyStore
from laris.server.serverdata.usage import UsageStore
from laris.server.serving.ports import Principal
from tests.unit.engine.conftest import Harness, wait_status


class RouteClient:
    """Answers `/laris/account` with the server's own meter, as the route does."""

    def __init__(self, usage, principal):
        self.usage, self.principal, self.calls = usage, principal, 0

    def get(self, path):
        assert path == "/laris/account"
        self.calls += 1
        return self.usage.account(self.principal)


def _account(tmp_path, limit=1000, spent=250):
    db = Database(tmp_path / "meter.db")
    keys = KeyStore(
        db, {"user": ["chat", "account"]}, [], [], ["chat", "account"], SecretBox(b"1" * 32)
    )
    usage = UsageStore(db)
    record, _ = keys.create("lab", "user", limit)
    principal = Principal(record.id, "user", frozenset(["chat", "account"]), limit)
    if spent:
        usage.reserve(principal, spent).settle(
            {"prompt_tokens": spent - 50, "completion_tokens": 50}
        )
    return RouteClient(usage, principal)


def _serve(chat, client, monkeypatch):
    """Point the chat at a server whose account route is `client` (the runtime is rebuilt on
    every access, so the address goes in through the overrides and the client on the class)."""
    from laris.shared.harness.runtime import HarnessRuntime

    chat.overrides = {**(chat.overrides or {}), "model_api": {"base_url": "http://account.test"}}
    monkeypatch.setattr(HarnessRuntime, "server_client", lambda self: client)


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _lines(h):
    return [e["data"] for e in h.out.events() if e["type"] == "status" and e["kind"] == "line"]


def test_status_line_matches_the_account_route_and_the_context_estimator(
    chat, project, tmp_path, monkeypatch
):
    client = _account(tmp_path)
    _serve(chat, client, monkeypatch)
    _git(project, "init", "-q", "-b", "feature/x")
    h = Harness(chat, project)
    h.out.wait("ready")
    deadline = time.time() + 10
    while time.time() < deadline and not any(d["tokens_left"] is not None for d in _lines(h)):
        time.sleep(0.02)
    line = [d for d in _lines(h) if d["tokens_left"] is not None][-1]
    expected = client.usage.account(client.principal)
    assert line["tokens_left"] == expected["tokens_left"] == 750
    assert line["token_limit"] == 1000 and line["tokens_used"] == 250
    usage = chat.usage(h.engine.conversation["id"])
    assert (
        line["context"]["tokens"] == usage["tokens"]
        and line["context"]["window"] == usage["window"]
    )
    assert line["branch"] == "feature/x" and line["mode"] == chat.permissions.mode
    assert line["model"] == chat.runtime.config.model_api.model
    assert line["sandbox"] in {"unknown", "ready", "missing", "building", "failed", "broken"}
    h.stop()


def test_status_line_is_sent_again_after_a_turn_and_a_mode_change(chat, project):
    h = Harness(chat, project)
    h.out.wait("ready")
    first = len(_lines(h))
    h.feed.send({"type": "set_mode", "mode": "plan"})
    h.out.wait("status", 2)
    h.feed.send({"type": "user_message", "text": "perovskite efficiency"})
    h.out.wait("done")
    deadline = time.time() + 10
    while time.time() < deadline and len(_lines(h)) < first + 2:
        time.sleep(0.02)
    lines = _lines(h)
    assert len(lines) >= first + 2 and lines[-1]["mode"] == "plan"
    h.stop()


def test_no_server_and_no_repository_give_empty_values_not_errors(chat, project, tmp_path):
    assert statusline.git_branch(tmp_path / "nowhere") is None
    data = statusline.collect(chat, chat.conversations.create()["id"], tmp_path, "ready", None)
    assert data["tokens_left"] is None and data["unlimited"] is False and data["branch"] is None


def test_unlimited_account_is_marked(chat, project, tmp_path, monkeypatch):
    _serve(chat, _account(tmp_path, limit=None, spent=0), monkeypatch)
    data = statusline.collect(
        chat,
        chat.conversations.create()["id"],
        project,
        "ready",
        statusline.Account(chat).refresh(),
    )
    assert data["unlimited"] is True and data["tokens_left"] is None


def test_cost_and_context_commands_use_the_same_values(chat, project, tmp_path, monkeypatch):
    from laris.client.engine.commands import BUILTIN, Context

    client = _account(tmp_path)
    _serve(chat, client, monkeypatch)
    ctx = Context(chat, dict(chat.conversations.create()), tmp_path, project, None, BUILTIN)
    cost = BUILTIN.dispatch("/cost", ctx).text
    use = chat.usage(ctx.conversation["id"])
    assert f"≈ {use['tokens']} tokens of {use['window']}" in cost
    assert "used on the account: 250" in cost and "left: 750" in cost
    context = BUILTIN.dispatch("/context", ctx).text
    assert f"≈ {use['tokens']}/{use['window']} tokens" in context and "%" in context


def test_cost_without_a_server_says_so(chat, project, tmp_path):
    from laris.client.engine.commands import BUILTIN, Context

    ctx = Context(chat, dict(chat.conversations.create()), tmp_path, project, None, BUILTIN)
    assert "account: not available" in BUILTIN.dispatch("/cost", ctx).text


def test_messages_typed_while_working_are_queued_and_run_in_order(chat, project, monkeypatch):
    release, seen = threading.Event(), []

    def slow_send(conversation_id, text, approve=None):
        seen.append(text)
        if text == "one":
            release.wait(10)
        yield {"type": "text", "delta": f"answer to {text}"}
        yield {"type": "done", "status": "completed", "answer": text}

    monkeypatch.setattr(chat, "send", slow_send)
    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": "one"})
    h.feed.send({"type": "user_message", "text": "two"})
    h.feed.send({"type": "user_message", "text": "three"})
    queued = wait_status(h.out, "queued", 2)
    assert [e["data"]["count"] for e in queued] == [1, 2]
    assert seen == ["one"] and not [e for e in h.out.events() if e["type"] == "error"]
    release.set()
    h.out.wait("done", 3)
    assert seen == ["one", "two", "three"]
    assert [e["answer"] for e in h.out.events() if e["type"] == "done"] == ["one", "two", "three"]
    started = [e["data"].get("started") for e in wait_status(h.out, "queued", 4)]
    assert started[2:] == ["two", "three"]
    h.stop()


def test_interrupt_keeps_the_queue_and_the_next_message_runs(chat, project, monkeypatch):
    release, seen = threading.Event(), []

    def slow_send(conversation_id, text, approve=None):
        seen.append(text)
        yield {"type": "text", "delta": "start "}
        if text == "one":
            release.wait(10)
        yield {"type": "text", "delta": "more"}
        yield {"type": "done", "status": "completed", "answer": text}

    monkeypatch.setattr(chat, "send", slow_send)
    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": "one"})
    h.out.wait("text")
    h.feed.send({"type": "user_message", "text": "two"})
    wait_status(h.out, "queued")
    h.feed.send({"type": "interrupt"})
    for _ in range(500):
        if h.engine._interrupted.is_set():
            break
        time.sleep(0.01)
    release.set()
    dones = h.out.wait("done", 2)
    assert [d["status"] for d in dones] == ["interrupted", "completed"] and seen == ["one", "two"]
    h.stop()


def test_an_interrupted_turn_leaves_a_valid_saved_conversation(chat, project, monkeypatch):
    """Esc between a tool call and its result: the saved history has an answer for every call."""
    gate = threading.Event()
    original = AgentSession._execute

    def slow_execute(self, name, arguments):
        gate.wait(10)
        return original(self, name, arguments)

    monkeypatch.setattr(AgentSession, "_execute", slow_execute)
    h = Harness(chat, project)
    h.out.wait("ready")
    session_id = h.out.events()[0]["session"]
    h.feed.send({"type": "user_message", "text": "perovskite efficiency"})
    h.out.wait("tool_call")
    h.feed.send({"type": "interrupt"})
    for _ in range(500):
        if h.engine._interrupted.is_set():
            break
        time.sleep(0.01)
    gate.set()
    assert h.out.wait("done")[0]["status"] == "interrupted"
    h.stop()
    messages = chat.conversations.get(session_id)["messages"]
    calls = [c["id"] for m in messages for c in m.get("tool_calls") or []]
    answers = [m["tool_call_id"] for m in messages if m["role"] == "tool"]
    assert calls and sorted(calls) == sorted(answers)
    for index, message in enumerate(messages):  # every result follows its assistant message
        if message["role"] == "tool":
            before = messages[:index]
            assert any(
                c["id"] == message["tool_call_id"]
                for m in before
                for c in m.get("tool_calls") or []
            )
    sealed = [m for m in messages if m["role"] == "tool" and "interrupted" in m["content"]]
    assert sealed


def test_seal_interrupted_is_idempotent_and_keeps_results_together():
    class Stub(AgentSession):
        def __init__(self):
            self.messages = [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "q"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "a",
                            "type": "function",
                            "function": {"name": "x", "arguments": "{}"},
                        },
                        {
                            "id": "b",
                            "type": "function",
                            "function": {"name": "x", "arguments": "{}"},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "a", "content": "{}"},
            ]

    stub = Stub()
    assert stub.seal_interrupted() == 1 and stub.seal_interrupted() == 0
    assert [m["role"] for m in stub.messages] == ["system", "user", "assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in stub.messages if m["role"] == "tool"] == ["a", "b"]
