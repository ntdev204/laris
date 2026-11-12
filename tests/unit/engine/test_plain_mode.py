"""T80 (SR-C1): plain-text mode. A scripted `input` and a collecting `print` drive the real engine
through E1: a message, slash commands, approvals with a diff, interrupt, the exit paths and a
version mismatch. No dependency beyond the standard library."""

import ast
import json
import threading
from pathlib import Path

import pytest

from laris.client.engine import Engine
from laris.client.plain import EngineLink, PlainClient, run_plain
from laris.protocol import engine as e1


class Screen:
    """The terminal: `read` answers prompts from a script, `write` records what is printed."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts, self.lines, self._partial = [], [], ""

    def read(self, prompt=""):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            answer()
            return self.read(prompt)
        return answer

    def write(self, text="", end="\n", flush=False):
        self._partial += str(text) + end
        *done, self._partial = self._partial.split("\n")
        self.lines.extend(done)

    @property
    def text(self):
        return "\n".join(self.lines) + self._partial


def _client(chat, project, screen, **kw):
    link = EngineLink(lambda r, w: Engine(chat, r, w, "2.0.0-test", cwd=project))
    return PlainClient(link, read=screen.read, write=screen.write, **kw), link


def test_a_message_streams_with_its_tool_call_and_the_prompt_returns(chat, project):
    screen = Screen(["perovskite efficiency"])
    client, _ = _client(chat, project, screen)
    assert client.run() == 0
    assert "LARIS  session" in screen.text and "mode " in screen.text
    assert "● search_corpus" in screen.text and "⎿" in screen.text
    assert len(screen.prompts) == 2  # the prompt came back after the turn, then end of input


def test_slash_commands_go_through_the_engine_and_exit_ends_the_session(chat, project):
    screen = Screen(["/context", "/nope", "/", "/exit", "never read"])
    client, _ = _client(chat, project, screen)
    assert client.run() == 0
    assert "token" in screen.text  # /context
    assert "[error] unknown command" in screen.text  # an error ends its command, the prompt returns
    assert "Type /help" in screen.text  # a bare slash is answered locally
    assert screen.answers == ["never read"]  # /exit stopped the loop


def test_a_custom_command_runs_a_turn(chat, project, monkeypatch):
    seen = []

    def send(conversation_id, text, approve=None):
        seen.append(text)
        yield {"type": "text", "delta": "ok"}
        yield {"type": "done", "status": "completed", "answer": "ok"}

    monkeypatch.setattr(chat, "send", send)
    screen = Screen(["plain question"])
    client, _ = _client(chat, project, screen)
    client.run()
    assert seen == ["plain question"] and "ok" in screen.text


def _approval_chat(chat, monkeypatch, tool, arguments, outcome):
    def send(conversation_id, text, approve=None):
        allowed = approve(tool, arguments)
        outcome.append(allowed)
        yield {"type": "text", "delta": "allowed" if allowed else "refused"}
        yield {"type": "done", "status": "completed", "answer": ""}

    monkeypatch.setattr(chat, "send", send)


def test_an_approval_shows_the_diff_and_yes_allows_it(chat, project, monkeypatch):
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    outcome = []
    _approval_chat(
        chat,
        monkeypatch,
        "Edit",
        {"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"},
        outcome,
    )
    screen = Screen(["change it", "y"])
    client, _ = _client(chat, project, screen)
    client.run()
    assert "-x = 1" in screen.text and "+x = 2" in screen.text  # the diff, as text
    assert "Permission: Edit" in screen.text and "edit(app.py)" in screen.prompts[1]
    assert outcome == [True] and "allowed" in screen.text


@pytest.mark.parametrize("reply", ["", "n", "garbage-no"])
def test_anything_but_yes_refuses(chat, project, monkeypatch, reply):
    outcome = []
    _approval_chat(chat, monkeypatch, "write_file", {"path": "a.txt"}, outcome)
    screen = Screen(["go", reply])
    client, _ = _client(chat, project, screen)
    client.run()
    assert outcome == [False] and "refused" in screen.text


def test_always_in_this_project_is_saved_as_a_rule(chat, project, monkeypatch):
    outcome = []
    _approval_chat(chat, monkeypatch, "write_file", {"path": "a.txt"}, outcome)
    screen = Screen(["go", "p"])
    client, _ = _client(chat, project, screen)
    client.run()
    assert outcome == [True]
    rules = chat.permissions.state.read()["permissions"]["allow"]
    assert rules == [chat.permissions.suggest("write_file", {"path": "a.txt"})]


def test_ctrl_c_during_a_turn_interrupts_and_keeps_the_session(chat, project, monkeypatch):
    release = threading.Event()

    def slow(conversation_id, text, approve=None):
        yield {"type": "text", "delta": "start "}
        release.wait(10)
        yield {"type": "text", "delta": "never shown"}
        yield {"type": "done", "status": "completed", "answer": ""}

    monkeypatch.setattr(chat, "send", slow)
    screen = Screen(["long task", "/context"])
    client, link = _client(chat, project, screen)
    real_get = link.events.get
    state = {"raised": False}

    def get(*args, **kwargs):
        event = real_get(*args, **kwargs)
        if event and event.get("type") == "text" and not state["raised"]:
            state["raised"] = True
            threading.Timer(0.3, release.set).start()  # the model goes on after the interrupt
            raise KeyboardInterrupt  # Ctrl+C while the answer streams
        return event

    link.events.get = get
    monkeypatch.setattr(chat, "send", slow)
    assert client.run() == 0
    assert "[interrupted]" in screen.text and "never shown" not in screen.text
    assert len(screen.prompts) == 3  # the prompt returned after the interrupt: session kept


def test_ctrl_c_at_a_permission_prompt_refuses_and_interrupts(chat, project, monkeypatch):
    outcome = []
    _approval_chat(chat, monkeypatch, "write_file", {"path": "a.txt"}, outcome)
    screen = Screen(["go", KeyboardInterrupt()])
    client, _ = _client(chat, project, screen)
    client.run()
    assert outcome == [False] and "[interrupted]" in screen.text


def test_ctrl_c_or_ctrl_d_at_the_prompt_leaves_cleanly(chat, project):
    for leave in (KeyboardInterrupt(), EOFError()):
        screen = Screen([leave])
        client, _ = _client(chat, project, screen)
        assert client.run() == 0


def test_an_engine_of_another_protocol_version_is_refused(chat, project):
    class Old:
        def run(self):
            return 0

    class Link:
        events = __import__("queue").Queue()
        sent = []

        def send(self, command):
            self.sent.append(command)

        def close(self):
            return 0

    link = Link()
    link.events.put({"type": "ready", "version": "9", "session": "s", "cwd": ".", "mode": "ask"})
    screen = Screen([])
    assert PlainClient(link, read=screen.read, write=screen.write).run() == 2
    assert "E1 version" in screen.text and "'9'" in screen.text and screen.prompts == []


def test_the_client_sends_only_valid_e1_commands(chat, project):
    screen = Screen(["hello", "/context", "/exit"])
    client, link = _client(chat, project, screen)
    sent = []
    real = link.send
    link.send = lambda command: (sent.append(command), real(command))[1]
    client.run()
    assert sent and all(e1.parse_command(json.loads(json.dumps(c))) for c in sent)
    assert [c["type"] for c in sent][:3] == ["user_message", "command", "command"]


def test_run_plain_wires_the_engine_of_this_process(chat, project, monkeypatch):
    screen = Screen([])
    monkeypatch.setattr("builtins.input", screen.read)
    monkeypatch.setattr("builtins.print", screen.write)
    assert run_plain(chat, None, "2.0.0-test", project / "home", None, project) == 0
    assert "LARIS  session" in screen.text


def test_plain_mode_imports_only_the_standard_library_and_laris():
    tree = ast.parse(Path("src/laris/client/plain.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    import sys

    allowed = set(sys.stdlib_module_names) | {"laris"}
    assert names <= allowed, names - allowed
    assert (
        "input("
        not in Path("src/cli/commands/agent.py")
        .read_text(encoding="utf-8")
        .split("def _headless")[0]
        .split("class _Chat")[1]
    )  # the old REPL is gone from the chat command
