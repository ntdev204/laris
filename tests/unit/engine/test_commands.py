"""The slash-command registry: built-ins, custom commands with $ARGUMENTS, trust, completion."""

import json

import pytest

from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace
from laris.client.engine.commands import BUILTIN, Context, expand
from laris.client.sandbox import SandboxManager

pytestmark = pytest.mark.usefixtures("use_placeholder_model")


@pytest.fixture
def ctx(tmp_path, project):
    service = SearchService(Workspace(tmp_path / "ws"))
    chat = ChatApp(service, project, project / "chat")
    home = tmp_path / "home"
    (home / "commands").mkdir(parents=True)
    sandbox = SandboxManager(home, uv=None, environ={"PATH": ""})
    return Context(chat, dict(chat.conversations.create()), home, project, sandbox, BUILTIN)


def run(ctx, line):
    ctx.registry = BUILTIN
    return BUILTIN.dispatch(line, ctx)


def test_every_spec_command_is_registered():
    required = (
        "help clear compact resume continue model status cost context config permissions memory "
        "init login logout doctor vault skills workflows hooks sandbox rewind exit"
    ).split()
    assert not [n for n in required if n not in BUILTIN.commands]


def test_help_lists_commands_and_unknown_is_an_error(ctx):
    text = run(ctx, "/help").text
    assert "/sandbox" in text and "/config" in text
    bad = run(ctx, "/nope")
    assert bad.error and "unknown command" in bad.text


def test_sessions_clear_resume_continue(ctx):
    first = ctx.conversation["id"]
    ctx.chat.conversations.save({**ctx.chat.conversations.get(first), "title": "first one"})
    cleared = run(ctx, "/clear")
    assert cleared.conversation and cleared.conversation["id"] != first
    ctx.conversation = cleared.conversation
    assert first in run(ctx, "/sessions").text
    back = run(ctx, f"/resume {first[:6]}")
    assert back.conversation["id"] == first
    assert run(ctx, "/resume zzzz").error
    assert run(ctx, "/continue").conversation["id"] == first


def test_config_get_set_and_validation_errors(ctx):
    assert run(ctx, "/config set server.timeoutSeconds 45").text.endswith("45")
    assert run(ctx, "/config get server.timeoutSeconds").text == "45"
    assert json.loads(run(ctx, "/config").text)["server"]["timeoutSeconds"] == 45
    bad = run(ctx, "/config set server.timeoutSeconds banana")
    assert bad.error and "server.timeoutSeconds" in bad.text
    assert run(ctx, "/config set nonsense.key 1").error
    assert run(ctx, "/config get server.url").error or run(ctx, "/config get server.url").text == ""
    assert run(ctx, "/config frobnicate").error


def test_status_cost_context_model_and_permissions(ctx):
    assert json.loads(run(ctx, "/status").text)["session"] == ctx.conversation["id"]
    assert "tokens" in run(ctx, "/cost").text and "auto-compact" in run(ctx, "/context").text
    assert run(ctx, "/model").text
    run(ctx, '/config set permissions.deny ["Bash(rm:*)"]')
    perms = run(ctx, "/permissions").text
    assert "mode:" in perms and "Bash(rm:*)" in perms


def test_memory_init_trust_doctor_vault_skills_workflows_hooks_tools(ctx):
    assert "no memory" in run(ctx, "/memory").text
    (ctx.home / "memory").mkdir()
    (ctx.home / "memory" / "pref.md").write_text("x", encoding="utf-8")
    assert "[user] pref.md" in run(ctx, "/memory").text
    out = run(ctx, "/init").text
    assert "created" in out and "nothing overwritten" in run(ctx, "/init").text
    assert (
        "not trusted" in run(ctx, "/trust off").text or "no longer" in run(ctx, "/trust off").text
    )
    assert "trusted" in run(ctx, "/trust").text and ctx.state.trusted
    doctor = run(ctx, "/doctor").text
    assert "settings: ok" in doctor and "sandbox:" in doctor and "folder trusted: yes" in doctor
    assert run(ctx, "/vault").text
    assert run(ctx, "/skills").text and run(ctx, "/workflows").text is not None
    assert run(ctx, "/hooks").text == "no hooks configured"
    hook = '{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"echo hi"}]}]}'
    run(ctx, "/config set hooks " + hook)
    assert "PreToolUse [Bash] echo hi" in run(ctx, "/hooks").text
    assert "search_corpus" in run(ctx, "/tools").text


def test_login_logout_sandbox_write_learn_exit(ctx, monkeypatch):
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(ctx.home / ".credentials.json"))
    assert "not signed in" in run(ctx, "/login").text
    assert "no saved key" in run(ctx, "/logout").text
    assert "sandbox: missing" in run(ctx, "/sandbox").text
    assert "failed" in run(ctx, "/sandbox reset").text
    assert "auto-approved" in run(ctx, "/write on").text and "ask" in run(ctx, "/write off").text
    assert "on" in run(ctx, "/learn on").text
    assert run(ctx, "/exit").exit and run(ctx, "/quit").exit
    ctx.sandbox = None
    assert run(ctx, "/sandbox").error


def test_custom_commands_expand_arguments(ctx):
    (ctx.home / "commands" / "review.md").write_text(
        "---\ndescription: Review a file\nargument-hint: FILE\n---\nReview $ARGUMENTS carefully.\n",
        encoding="utf-8",
    )
    (ctx.home / "commands" / "plain.md").write_text("Summarise the repo.", encoding="utf-8")
    result = run(ctx, "/review src/a.py")
    assert result.turn == "Review src/a.py carefully."
    assert run(ctx, "/plain more detail").turn == "Summarise the repo.\n\nmore detail"
    assert expand("no marker", "") == "no marker"
    shown = [c.name for c in BUILTIN.complete("re", ctx)]
    assert "review" in shown and "resume" in shown
    assert "Review a file" in [c.summary for c in BUILTIN.complete("review", ctx)]
    assert "(user)" in run(ctx, "/help").text


def test_project_commands_need_trust_and_cannot_shadow_builtins(ctx):
    folder = ctx.chat.project_root / ".laris" / "commands"
    folder.mkdir(parents=True)
    (folder / "deploy.md").write_text("Deploy $ARGUMENTS", encoding="utf-8")
    (folder / "help.md").write_text("pwned", encoding="utf-8")
    assert run(ctx, "/deploy now").error  # untrusted folder: not used
    assert "not used until you trust" in run(ctx, "/help").text
    run(ctx, "/trust")
    assert run(ctx, "/deploy now").turn == "Deploy now"
    assert "pwned" not in run(ctx, "/help").text and run(ctx, "/help").turn is None
    (ctx.home / "commands" / "deploy.md").write_text("User deploy", encoding="utf-8")
    assert run(ctx, "/deploy").turn == "User deploy"  # the user's own command wins


def test_bad_custom_files_are_skipped(ctx):
    (ctx.home / "commands" / "Bad Name.md").write_text("x", encoding="utf-8")
    (ctx.home / "commands" / "empty.md").write_text("---\ndescription: d\n---\n", encoding="utf-8")
    assert run(ctx, "/empty").error and run(ctx, "/Bad Name").error


def test_rewind_lists_and_restores_what_the_coding_tools_changed(ctx):
    project = ctx.chat.project_root
    assert "nothing to rewind" in run(ctx, "/rewind").text
    session = ctx.chat._session(ctx.conversation)
    assert {"Read", "Write", "Edit", "Glob", "Grep", "Bash"} <= set(session.registry.tools)
    (project / "f.py").write_text("old\n", encoding="utf-8")
    session.registry.call("Edit", {"path": "f.py", "old_string": "old", "new_string": "new"})
    session.registry.call("Write", {"path": "g.py", "content": "g\n"})
    listing = run(ctx, "/rewind").text
    assert "Edit" in listing and "f.py" in listing and "g.py" in listing and "(new file)" in listing
    assert "removed: g.py" in run(ctx, "/rewind 1").text and not (project / "g.py").exists()
    assert "restored: f.py" in run(ctx, "/rewind all").text
    assert (project / "f.py").read_text() == "old\n"
    assert run(ctx, "/rewind banana").error
