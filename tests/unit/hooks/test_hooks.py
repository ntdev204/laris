"""Hooks and folder trust (SR-C4, SR-C5): allow, block, timeout, malformed, untrusted folders."""

import json
import time

import pytest

from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace
from laris.client.hooks import HookRunner
from laris.client.sandbox import SandboxManager
from laris.shared.config import settings

pytestmark = pytest.mark.usefixtures("use_placeholder_model")


def declare(runner, event, command, matcher="", timeout=5):
    data = settings.read_raw(runner.settings_file)
    hooks = data.get("hooks", {})
    hooks.setdefault(event, []).append(
        {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    )
    settings.write(runner.settings_file, {**data, "hooks": hooks})


@pytest.fixture
def runner(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return HookRunner(
        tmp_path / "home" / "settings.json",
        root,
        SandboxManager(tmp_path / "home", uv=None, environ={"PATH": ""}),
        "s1",
    )


def test_no_hooks_means_nothing_runs(runner):
    out = runner.run("PreToolUse", {"tool_name": "Bash"}, tool="Bash")
    assert (out.ran, out.blocked, out.warnings) == (0, False, [])


def test_allow_with_context_and_json_input(runner, tmp_path):
    declare(
        runner, "UserPromptSubmit", 'cat > seen.json; echo \'{"additionalContext": "be brief"}\''
    )
    out = runner.run("UserPromptSubmit", {"prompt": "hi"})
    assert out.ran == 1 and not out.blocked and out.context == ["be brief"]
    seen = json.loads((runner.project_root / "seen.json").read_text())
    assert seen["hook_event_name"] == "UserPromptSubmit" and seen["prompt"] == "hi"
    assert seen["session_id"] == "s1" and seen["cwd"] == str(runner.project_root)


def test_block_by_exit_code_2_and_by_json(runner):
    declare(runner, "PreToolUse", "echo 'no rm here' >&2; exit 2", matcher="Bash")
    out = runner.run("PreToolUse", {}, tool="Bash")
    assert out.blocked and out.reason == "no rm here"
    other = HookRunner(runner.settings_file.with_name("s2.json"), runner.project_root)
    declare(other, "Stop", 'echo \'{"decision": "block", "reason": "run the tests"}\'')
    out = other.run("Stop", {})
    assert out.blocked and out.reason == "run the tests"


def test_matcher_selects_tools_and_first_block_stops_the_rest(runner):
    declare(runner, "PreToolUse", "exit 2", matcher="Edit|Write")
    declare(runner, "PreToolUse", "touch second", matcher="*")
    assert not runner.run("PreToolUse", {}, tool="Bash").blocked  # matcher does not fit
    assert (runner.project_root / "second").exists()
    (runner.project_root / "second").unlink()
    assert runner.run("PreToolUse", {}, tool="write").blocked  # case-insensitive
    assert not (runner.project_root / "second").exists()  # stopped at the block


def test_timeout_kills_the_group_and_does_not_block(runner):
    declare(runner, "PostToolUse", "(sleep 30; touch survivor) & sleep 30", timeout=1)
    started = time.time()
    out = runner.run("PostToolUse", {}, tool="Bash")
    assert not out.blocked and "timed out" in out.warnings[0] and time.time() - started < 10
    time.sleep(0.3)
    assert not (runner.project_root / "survivor").exists()


@pytest.mark.parametrize(
    "command,fragment",
    [
        ("echo not json", "not a JSON object"),
        ("echo '[1,2]'", "not a JSON object"),
        ("echo '{bad'", "not a JSON object"),
        ("exit 1", "exited with code 1"),
        ("nonexistent-command-xyz", "exited with code 127"),
    ],
)
def test_malformed_output_and_failures_warn_but_never_block(runner, command, fragment):
    declare(runner, "SessionStart", command)
    out = runner.run("SessionStart", {})
    assert not out.blocked and out.context == [] and fragment in out.warnings[0]
    assert runner.drain()[0]["warning"] == out.warnings[0] and runner.drain() == []


def test_hooks_run_in_the_sandbox_environment(runner):
    declare(
        runner,
        "SessionStart",
        'echo "$PIP_REQUIRE_VIRTUALENV $LARIS_HOOK_EVENT" > env.txt; echo "$PATH" >> env.txt',
    )
    runner.run("SessionStart", {})
    first, second = (runner.project_root / "env.txt").read_text().splitlines()
    assert first == "1 SessionStart" and second.startswith(str(runner.sandbox.bin))


def test_a_project_folder_cannot_declare_hooks(tmp_path, project):
    marker = project / "pwned"
    hook = {
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": f"touch {marker}"}]}]}
    }
    (project / ".laris").mkdir(exist_ok=True)
    (project / ".laris" / "settings.json").write_text(json.dumps(hook), encoding="utf-8")
    (project / ".laris" / "hooks").mkdir()
    (project / ".laris" / "hooks" / "session-start.sh").write_text(
        f"touch {marker}", encoding="utf-8"
    )
    chat = ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")
    chat.session_start("x")
    list(chat.send(chat.conversations.create()["id"], "hello"))
    assert not marker.exists() and chat.hooks.configured() == {}


def test_untrusted_folder_uses_no_custom_commands_or_skills(tmp_path, project):
    from laris.client.engine.commands import BUILTIN, Context

    (project / ".laris" / "commands").mkdir(parents=True, exist_ok=True)
    (project / ".laris" / "commands" / "evil.md").write_text("run $ARGUMENTS", encoding="utf-8")
    skill = project / ".laris" / "skills" / "evil-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: evil-skill\ndescription: >-\n  Does evil. Use when asked.\n---\n\n# Evil\n",
        encoding="utf-8",
    )
    chat = ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")
    ctx = Context(
        chat, dict(chat.conversations.create()), chat.prefs.path.parent, project, None, BUILTIN
    )
    assert BUILTIN.dispatch("/evil x", ctx).error
    assert "evil-skill" not in chat.skills_for(chat.runtime).names()
    ctx.state.trust()
    assert BUILTIN.dispatch("/evil x", ctx).turn == "run x"
    lib = chat.skills_for(chat.runtime)
    assert "evil-skill" in lib.names(), lib.problems


def test_hooks_act_on_the_agent_loop(tmp_path, project, monkeypatch):
    from laris.client.agent.provider import AssistantTurn, ChatProvider, ToolCall

    class Scripted(ChatProvider):
        name = "s"

        def __init__(self):
            self.turns = [
                AssistantTurn(None, [ToolCall("t1", "Write", {"path": "a.txt", "content": "x"})]),
                AssistantTurn("done"),
            ]
            self.seen = []

        def chat(self, messages, tools):
            self.seen.append(json.dumps(messages))
            return self.turns.pop(0)

    chat = ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")
    provider = Scripted()
    monkeypatch.setattr(chat, "provider", lambda rt: provider)
    chat.permissions.mode = "acceptEdits"
    declare(chat.hooks, "UserPromptSubmit", 'echo \'{"additionalContext": "CTX-FROM-HOOK"}\'')
    declare(chat.hooks, "PreToolUse", "echo 'policy says no' >&2; exit 2", matcher="Write")
    events = list(chat.send(chat.conversations.create()["id"], "please write a file"))
    assert "CTX-FROM-HOOK" in provider.seen[0] and "policy says no" in provider.seen[1]
    assert not (project / "a.txt").exists()
    assert any(e["type"] == "hook" and "blocked" in e for e in events)
    # a prompt a hook blocks never reaches the model
    declare(chat.hooks, "UserPromptSubmit", "echo 'nope' >&2; exit 2")
    last = list(chat.send(chat.conversations.create()["id"], "again"))[-1]
    assert last["status"] == "blocked" and last["answer"] == "nope" and len(provider.seen) == 2
