import threading
import time

from laris.protocol import engine as e1


def _valid(events):
    for event in events:
        e1.parse_event(event)  # every line the engine wrote is a valid E1 event
    return events


def _kinds(events):
    return [e["type"] for e in events]


def test_ready_carries_the_version_and_a_turn_streams_valid_events(run):
    h = run()
    ready = h.out.wait("ready")[0]
    assert ready["version"] == e1.E1_VERSION and ready["engine"] == "2.0.0-test"
    assert e1.check_version(ready) is None
    h.feed.send({"type": "user_message", "text": "perovskite efficiency"})
    h.out.wait("done")
    events = _valid(h.out.events())
    kinds = _kinds(events)
    assert kinds[0] == "ready" and kinds[-1] == "done" and "tool_call" in kinds
    call = next(e for e in events if e["type"] == "tool_call")
    result = next(e for e in events if e["type"] == "tool_result")
    assert call["id"] == result["id"] == "call_1" and call["name"] == "search_corpus"
    assert "usage" in kinds
    assert h.stop() == 0


def test_a_scripted_session_replays_to_the_same_transcript(chat, project, use_placeholder_model):
    from tests.unit.engine.conftest import Harness

    def transcript():
        h = Harness(chat, project)
        h.out.wait("ready")
        h.feed.send({"type": "user_message", "text": "perovskite efficiency"})
        h.out.wait("done")
        h.stop()
        events = [
            e for e in h.out.events() if not (e["type"] == "status" and e["kind"] == "learning")
        ]  # what was stored (new vs duplicate) depends on earlier runs, not on the protocol
        for event in events:
            event.pop("session", None)
        return events

    first, second = transcript(), transcript()
    assert first == second and len(first) > 4


def test_permission_round_trip_remember_and_interrupt(run):
    h = run()
    h.out.wait("ready")
    answers = []

    def ask(name):
        answers.append((name, h.engine._approve(name, {"path": "a.txt"})))

    t = threading.Thread(target=ask, args=("write_file",))
    t.start()
    request = h.out.wait("permission_request")[0]
    assert request["tool"] == "write_file" and request["id"] == "perm_1"
    h.feed.send(
        {"type": "permission_response", "id": "perm_1", "decision": "allow", "remember": True}
    )
    t.join(5)
    assert answers == [("write_file", True)]
    h.engine._allowed.add("write_file")  # `remember` is applied by the engine on the answer
    assert h.engine._approve("write_file", {}) is True  # no second request
    t2 = threading.Thread(target=ask, args=("save_memory",))
    t2.start()
    h.out.wait("permission_request", 2)
    h.feed.send({"type": "interrupt"})  # nobody can answer now: it is a refusal
    t2.join(5)
    assert answers[-1] == ("save_memory", False)
    h.feed.send({"type": "permission_response", "id": "perm_9", "decision": "allow"})
    assert h.out.wait("error")[-1]["code"] == "unknown_permission"
    h.stop()


def test_bad_lines_and_unknown_commands_do_not_stop_the_engine(run):
    h = run()
    h.out.wait("ready")
    h.feed.raw("this is not json\n")
    h.feed.send({"type": "bogus"})
    h.feed.send({"type": "command", "name": "nope"})
    codes = [e["code"] for e in h.out.wait("error", 3)]
    assert codes == ["bad_command", "bad_command", "unknown_command"]
    h.feed.send({"type": "set_mode", "mode": "auto"})
    status = h.out.wait("status")[0]
    assert status["kind"] == "mode" and status["data"] == {"mode": "auto"}
    h.feed.send({"type": "command", "name": "help"})
    h.out.wait("done")
    assert h.stop() == 0


def test_completion_for_commands_and_files(run, project):
    (project / "notes.md").write_text("x", encoding="utf-8")
    h = run()
    h.out.wait("ready")
    h.feed.send({"type": "complete", "id": "c1", "trigger": "/", "text": "co"})
    h.feed.send({"type": "complete", "id": "c2", "trigger": "@", "text": "notes"})
    got = {c["id"]: c for c in h.out.wait("completion", 2)}
    assert [i["value"] for i in got["c1"]["items"]] == ["compact"]
    assert [i["value"] for i in got["c2"]["items"]] == ["notes.md"]
    h.stop()


def test_a_busy_engine_refuses_a_second_message_and_interrupt_ends_the_turn(
    chat, project, monkeypatch
):
    from tests.unit.engine.conftest import Harness

    release = threading.Event()

    def slow_send(conversation_id, text, approve=None):
        yield {"type": "text", "delta": "start "}
        release.wait(10)
        yield {"type": "text", "delta": "never shown"}
        yield {"type": "done", "status": "completed", "answer": "x"}

    monkeypatch.setattr(chat, "send", slow_send)
    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": "one"})
    h.out.wait("text")
    h.feed.send({"type": "user_message", "text": "two"})
    assert h.out.wait("error")[0]["code"] == "busy"
    h.feed.send({"type": "interrupt"})
    for _ in range(500):  # the reader thread acts on it; only then let the model go on
        if h.engine._interrupted.is_set():
            break
        time.sleep(0.01)
    release.set()
    done = h.out.wait("done")[0]
    assert done["status"] == "interrupted"
    assert all(e.get("delta") != "never shown" for e in h.out.events())
    h.stop()


def test_killing_the_front_end_still_saves_the_conversation(chat, project):
    from tests.unit.engine.conftest import Harness

    h = Harness(chat, project)
    h.out.wait("ready")
    h.feed.send({"type": "user_message", "text": "perovskite efficiency"})
    h.out.wait("done")
    session_id = h.out.events()[0]["session"]
    h.feed.close()  # the front end died: end of input
    h.thread.join(10)
    assert h.code == [0]
    saved = chat.conversations.get(session_id)
    assert [m["role"] for m in saved["messages"]][0] == "user" and len(saved["messages"]) >= 2


def test_the_cli_command_speaks_e1_on_stdio(chat, monkeypatch, capsys):
    import io
    import json
    import sys

    from cli import client

    monkeypatch.setattr("cli.commands.engine.make_chat", lambda args, interactive=True: chat)
    monkeypatch.setattr("cli.bootstrap.ensure_global_home", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"type": "shutdown"}) + "\n"))
    assert client.main(["engine", "--stdio"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "ready" and lines[0]["version"] == e1.E1_VERSION
    assert len(lines) == 1
