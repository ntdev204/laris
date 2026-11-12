import threading
import time

from laris.protocol import engine as e1
from tests.unit.engine.conftest import wait_status


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
            e
            for e in h.out.events()
            if not (e["type"] == "status" and e["kind"] in ("learning", "line"))
        ]  # learning depends on earlier runs; the status line is timed by the clock, not the turn
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
    permissions = h.engine.chat.permissions  # `remember` became a session rule
    assert permissions.decide("write_file", {"path": "a.txt"}, True).action == "allow"
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
    h.feed.send({"type": "set_mode", "mode": "acceptEdits"})
    wait_status(h.out, "mode")  # other status events (the status line) arrive too (T79)
    status = next(e for e in h.out.events() if e["type"] == "status" and e["kind"] == "mode")
    assert status["kind"] == "mode" and status["data"] == {"mode": "acceptEdits"}
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
    assert [i["value"] for i in got["c1"]["items"]] == [
        "compact",
        "config",
        "context",
        "continue",
        "cost",
    ]
    assert [i["value"] for i in got["c2"]["items"]] == ["notes.md"]
    h.stop()


def test_a_second_message_is_queued_and_interrupt_ends_the_turn(chat, project, monkeypatch):
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
    h.feed.send({"type": "user_message", "text": "two"})  # typed while working: queued (T79)
    wait_status(h.out, "queued")
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
    assert {x["type"] for x in lines} == {"ready", "status"}  # the start-up status lines (T79)
    assert {x["kind"] for x in lines[1:]} <= {"line", "sandbox"}


def test_custom_commands_complete_and_run_a_turn_through_e1(run):
    from pathlib import Path

    folder = Path.home() / ".laris" / "commands"
    folder.mkdir(parents=True)
    (folder / "greet.md").write_text(
        "---\ndescription: Say hello\n---\nGreet $ARGUMENTS", encoding="utf-8"
    )
    h = run()
    h.out.wait("ready")
    h.feed.send({"type": "complete", "id": "k1", "trigger": "/", "text": "gre"})
    items = h.out.wait("completion")[0]["items"]
    assert items == [{"value": "greet", "description": "Say hello"}]
    h.feed.send({"type": "command", "name": "greet", "args": "world"})
    done = h.out.wait("done")[0]
    assert done["status"]  # the expanded text ran as an agent turn
    h.feed.send({"type": "command", "name": "clear"})
    h.out.wait("done", 2)
    assert "session" in [e.get("kind") for e in h.out.events() if e["type"] == "status"]
    h.feed.send({"type": "command", "name": "exit"})
    h.thread.join(timeout=10)
    assert h.code == [0]


def test_always_allow_scopes_are_saved_and_mode_cycles(run):
    import json
    from pathlib import Path

    h = run()
    h.out.wait("ready")
    permissions = h.engine.chat.permissions

    def ask(path, scope):
        results = []
        t = threading.Thread(
            target=lambda: results.append(h.engine._approve("write_file", {"path": path}))
        )
        t.start()
        count = len(h.out.wait("permission_request", len(asked) + 1))
        asked.append(count)
        request = h.out.wait("permission_request", count)[-1]
        assert request["rule"] == f"write_file({path})" and "project" in request["scopes"]
        h.feed.send(
            {
                "type": "permission_response",
                "id": request["id"],
                "decision": "allow",
                "scope": scope,
            }
        )
        t.join(5)
        return results == [True]

    asked: list = []
    assert ask("p.txt", "project") and ask("e.txt", "everywhere")
    state = json.loads(permissions.state.path.read_text())
    assert state["permissions"]["allow"] == ["write_file(p.txt)"]
    saved = json.loads((Path.home() / ".laris" / "settings.json").read_text())
    assert saved["permissions"]["allow"] == ["write_file(e.txt)"]
    assert permissions.decide("write_file", {"path": "p.txt"}, True).action == "allow"
    assert permissions.decide("write_file", {"path": "other.txt"}, True).action == "ask"
    h.feed.send({"type": "set_mode", "mode": "next"})
    modes = wait_status(h.out, "mode")
    assert modes[-1]["data"] == {"mode": "acceptEdits"}
    h.feed.send({"type": "set_mode", "mode": "bypass"})  # policy does not allow it
    assert h.out.wait("error")[-1]["code"] == "bad_mode"
    h.stop()


def test_permission_request_carries_the_diff_of_an_edit(run, project):
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    h = run()
    h.out.wait("ready")
    args = {"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"}
    t = threading.Thread(target=lambda: h.engine._approve("Edit", args))
    t.start()
    request = h.out.wait("permission_request")[0]
    assert "-x = 1" in request["diff"] and "+x = 2" in request["diff"]
    assert request["rule"] == "edit(app.py)"
    h.feed.send({"type": "permission_response", "id": request["id"], "decision": "deny"})
    t.join(5)
    assert (project / "app.py").read_text() == "x = 1\n"  # the request changed nothing
    h.stop()


def test_the_engine_command_continues_the_newest_session(chat, monkeypatch, capsys):
    """`laris -c` through the Ink front end starts the engine with --continue (T81)."""
    import io
    import json
    import sys

    from cli import client

    earlier = chat.conversations.create("earlier")
    chat.conversations.save({**earlier, "messages": [{"role": "user", "content": "hi"}]})
    newest = chat.conversations.list()[0]["id"]
    monkeypatch.setattr("cli.commands.engine.make_chat", lambda args, interactive=True: chat)
    monkeypatch.setattr("cli.bootstrap.ensure_global_home", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"type": "shutdown"}) + "\n"))
    assert client.main(["engine", "--stdio", "--continue"]) == 0
    ready = json.loads(capsys.readouterr().out.splitlines()[0])
    assert ready["type"] == "ready" and ready["session"] == newest


def test_the_recorded_scenarios_of_the_node_front_end_are_valid_e1():
    """packaging/npm/test/scenarios replay recorded engine output; they must stay valid E1."""
    import json
    from pathlib import Path

    folder = Path(__file__).resolve().parents[3] / "packaging" / "npm" / "test" / "scenarios"
    files = sorted(folder.glob("*.json"))
    assert len(files) >= 8
    for file in files:
        steps = json.loads(file.read_text(encoding="utf-8"))["steps"]
        for step in steps:
            for event in step.get("emit", []):
                if file.name == "mismatch.json":
                    continue  # the point of that scenario is an event from another version
                e1.parse_event(event)
            if "expect" in step:
                want = step["expect"]
                assert want["type"] in e1.COMMANDS, (file.name, want)


def test_continue_and_resume_take_an_id_or_a_unique_prefix(chat, monkeypatch, capsys):
    import io
    import json
    import sys

    from cli import client

    ids = []
    for title in ("one", "two"):
        made = chat.conversations.create(title)
        chat.conversations.save({**made, "messages": [{"role": "user", "content": title}]})
        ids.append(made["id"])
    monkeypatch.setattr("cli.commands.engine.make_chat", lambda args, interactive=True: chat)
    monkeypatch.setattr("cli.bootstrap.ensure_global_home", lambda: None)

    def session(*flags):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"type": "shutdown"}) + "\n"))
        code = client.main(["engine", "--stdio", *flags])
        out = capsys.readouterr()
        return code, (json.loads(out.out.splitlines()[0])["session"] if out.out else None), out.err

    assert session("--continue", ids[0])[1] == ids[0]
    assert session("--continue", ids[1][:8])[1] == ids[1]
    assert session("--resume", ids[0])[1] == ids[0]
    code, _, err = session("--continue", "zzzzzz")
    assert code == 2 and "no session zzzzzz" in err
