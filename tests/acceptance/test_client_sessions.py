"""T82 (SR-C1, SR-C4, SR-C7): the same scripted sessions through the engine, headless `stream-json`
and plain mode. What every front end must agree on is the transcript: tool calls in order, tool
results, the answer and how the turn ended. The Ink front end replays the recording of the golden
session in `test_recorded_scenario.py`.

A scripted provider stands in for the model; nothing here measures model quality."""

import io
import json
import threading
import time

import pytest

from laris.client.agent.loop import AgentSession
from laris.client.agent.provider import AssistantTurn, ToolCall
from laris.client.headless import HeadlessOptions, run_headless
from tests.acceptance.conftest import CITED, golden_turns
from tests.acceptance.session import (
    plain_tools,
    reduce_events,
    run_engine,
    run_headless_stream,
    run_plain,
)
from tests.unit.engine.conftest import Harness

pytestmark = pytest.mark.usefixtures("use_placeholder_model")

GOLDEN = [
    ("tool_call", "search_corpus", '{"query": "perovskite", "top_k": 2}'),
    ("tool_result", "search_corpus", "ok"),
    ("tool_call", "Write", '{"content": "hi\\n", "path": "note.txt"}'),
    ("tool_result", "Write", "ok"),
    ("answer", CITED),
    ("done", "completed"),
]


def test_golden_session_through_the_engine(make_chat, project):
    events = run_engine(make_chat(golden_turns()), project)
    assert reduce_events(events) == GOLDEN
    kinds = [e["type"] for e in events]
    assert kinds[0] == "ready" and "permission_request" in kinds and kinds[-1] == "status"
    request = next(e for e in events if e["type"] == "permission_request")
    assert "+hi" in request["diff"] and request["rule"] == "write(note.txt)"
    assert (project / "note.txt").read_text() == "hi\n"


def test_golden_session_through_headless_stream_json(make_chat, project):
    chat = make_chat(golden_turns())
    code, events, err = run_headless_stream(chat, allowed_tools=["Write"])
    assert code == 0 and err == ""
    assert reduce_events(events) == GOLDEN  # equal to the engine's transcript
    assert events[0]["type"] == "ready" and events[0]["engine"] == "headless"
    assert (project / "note.txt").read_text() == "hi\n"


def test_golden_session_through_plain_mode(make_chat, project):
    chat = make_chat(golden_turns())
    code, screen = run_plain(chat, project, ["go", "y"])
    assert code == 0
    assert plain_tools(screen) == ["search_corpus", "Write"]
    assert "Permission: Write" in screen.text and "+hi" in screen.text
    assert CITED in screen.text and (project / "note.txt").read_text() == "hi\n"


def test_a_refused_write_reads_the_same_everywhere(make_chat, project):
    refused = [
        ("tool_call", "search_corpus", '{"query": "perovskite", "top_k": 2}'),
        ("tool_result", "search_corpus", "ok"),
        ("tool_call", "Write", '{"content": "hi\\n", "path": "note.txt"}'),
        ("tool_result", "Write", "approval_denied"),
        ("answer", CITED),
        ("done", "completed"),
    ]
    events = run_engine(make_chat(golden_turns()), project, approvals={"Write": "deny"})
    assert reduce_events(events) == refused
    code, stream, _ = run_headless_stream(make_chat(golden_turns(), "ws2"))  # headless never asks
    assert reduce_events(stream) == refused and code == 0  # a finished turn is exit 0 even so
    code, screen = run_plain(make_chat(golden_turns(), "ws3"), project, ["go", "n"])
    assert plain_tools(screen) == ["search_corpus", "Write"] and CITED in screen.text
    assert not (project / "note.txt").exists()


def test_the_engine_survives_an_interrupt_and_the_saved_conversation_is_consistent(
    make_chat, project, monkeypatch
):
    gate = threading.Event()
    original = AgentSession._execute

    def slow_execute(self, name, arguments):
        gate.wait(10)  # Esc arrives between a tool call and its result
        return original(self, name, arguments)

    monkeypatch.setattr(AgentSession, "_execute", slow_execute)
    chat = make_chat(
        [
            AssistantTurn(None, [ToolCall("s1", "search_corpus", {"query": "perovskite"})]),
            AssistantTurn("Second answer."),
        ]
    )
    h = Harness(chat, project)
    session = h.out.wait("ready")[0]["session"]
    h.feed.send({"type": "user_message", "text": "first"})
    h.out.wait("tool_call")
    h.feed.send({"type": "interrupt"})
    for _ in range(500):
        if h.engine._interrupted.is_set():
            break
        time.sleep(0.01)
    gate.set()
    assert h.out.wait("done")[0]["status"] == "interrupted"
    h.feed.send({"type": "user_message", "text": "second"})
    second = h.out.wait("done", 2)[1]
    assert second["status"] == "completed" and second["answer"] == "Second answer."
    h.stop()
    messages = chat.conversations.get(session)["messages"]
    calls = [c["id"] for m in messages for c in m.get("tool_calls") or []]
    answered = [m["tool_call_id"] for m in messages if m["role"] == "tool"]
    assert calls and sorted(calls) == sorted(answered)  # every call has its answer
    assert [m["role"] for m in messages].count("user") == 2 and messages[-1]["role"] == "assistant"


def test_slash_commands_answer_the_same_in_the_engine_and_in_plain_mode(make_chat, project):
    chat = make_chat([])
    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "command", "name": "context", "args": ""})
    h.feed.send({"type": "command", "name": "nope", "args": ""})
    assert h.out.wait("error")[0]["code"] == "unknown_command"
    h.stop()
    code, screen = run_plain(make_chat([], "ws2"), project, ["/context", "/nope", "/exit"])
    assert code == 0 and "token" in screen.text and "[error] unknown command" in screen.text


def test_headless_exit_codes_and_formats(make_chat, project):
    code, events, _ = run_headless_stream(make_chat([AssistantTurn("All done.")]))
    assert code == 0 and reduce_events(events)[-2:] == [
        ("answer", "All done."),
        ("done", "completed"),
    ]

    chat = make_chat(
        [
            AssistantTurn(None, [ToolCall("w", "Write", {"path": "a.txt", "content": "x"})]),
            AssistantTurn("could not write"),
        ]
    )
    out, err = io.StringIO(), io.StringIO()
    options = HeadlessOptions(prompt="go", output_format="json")
    code = run_headless(chat, options, out, err)
    result = json.loads(out.getvalue())
    assert code == 0 and result["permission_denials"] == ["Write"]  # headless never asks
    assert not (project / "a.txt").exists()

    code, _, err = run_headless_stream(make_chat([]), output_format="yaml")
    assert code == 2 and "--output-format" in err  # usage error
    code, _, err = run_headless_stream(make_chat([]), prompt="")
    assert code == 2 and "nothing to do" in err

    code, events, _ = run_headless_stream(make_chat([]))  # the model has nothing to say: it fails
    assert code == 1 and reduce_events(events)[-1] == ("done", "provider_error")


def test_a_blocking_hook_stops_a_write_in_every_front_end(make_chat, project, tmp_path):
    from laris.shared.config import settings

    def blocked_chat(name):
        chat = make_chat(golden_turns(), name)
        data = settings.read_raw(chat.hooks.settings_file)
        hook = {"type": "command", "command": "echo 'policy says no' >&2; exit 2", "timeout": 5}
        settings.write(
            chat.hooks.settings_file,
            {**data, "hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [hook]}]}},
        )
        return chat

    events = run_engine(blocked_chat("a"), project)
    result = next(e for e in events if e["type"] == "tool_result" and e["name"] == "Write")
    assert "policy says no" in json.dumps(result["result"])
    code, stream, _ = run_headless_stream(blocked_chat("b"), allowed_tools=["Write"])
    assert "policy says no" in json.dumps([e for e in stream if e["type"] == "tool_result"])
    assert not (project / "note.txt").exists()
