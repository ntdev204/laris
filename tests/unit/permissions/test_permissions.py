"""Permission modes, rules, precedence, persistence of answers (SR-C3, SR-C5)."""

import json

import pytest

from laris.client.permissions import PermissionEngine, next_mode, parse_rule, rule_matches
from laris.client.project_state import ProjectState
from laris.shared.config import settings

WRITE = {"path": "src/a.py", "content": "x"}


@pytest.fixture
def engine(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "proj"
    root.mkdir()
    return PermissionEngine(
        home / "settings.json",
        ProjectState(home, root),
        root,
        sandbox_bin=home / ".venv" / "bin",
        allow_bypass=False,
        always_ask=("ingest_path", "save_memory"),
    )


def put(engine, **permissions):
    settings.write(engine.settings_file, {"permissions": permissions})


@pytest.mark.parametrize(
    "rule,tool,args,expected",
    [
        ("Edit(src/**)", "Edit", {"path": "src/a/b.py"}, True),
        ("Edit(src/**)", "Edit", {"path": "tests/a.py"}, False),
        ("Edit(src/**)", "Write", {"path": "src/a.py"}, False),  # another tool
        ("Write(*.md)", "Write", {"path": "README.md"}, True),
        ("Write(*.md)", "Write", {"path": "docs/README.md"}, False),  # `*` stays in a folder
        ("Write(**/*.md)", "Write", {"path": "docs/README.md"}, True),
        ("Write(./notes.txt)", "Write", {"path": "notes.txt"}, True),
        ("Bash(git status:*)", "bash", {"command": "git status"}, True),
        ("Bash(git status:*)", "bash", {"command": "git status -s"}, True),
        ("Bash(git status:*)", "bash", {"command": "git statusx"}, False),
        ("Bash(git status:*)", "bash", {"command": "git push"}, False),
        ("Bash(ls)", "bash", {"command": "ls"}, True),
        ("Bash", "bash", {"command": "anything"}, True),
        ("*", "search_corpus", {"query": "x"}, True),
        ("read", "Read", {"path": "a"}, True),
        ("not a rule(", "bash", {"command": "ls"}, False),
    ],
)
def test_rule_matching(rule, tool, args, expected, tmp_path):
    assert rule_matches(rule, tool, args, tmp_path) is expected


def test_path_rules_follow_the_resolved_path(tmp_path):
    (tmp_path / "src").mkdir()
    assert rule_matches("Write(src/**)", "Write", {"path": "src/../src/a.py"}, tmp_path)
    assert not rule_matches("Write(src/**)", "Write", {"path": "src/../secret.py"}, tmp_path)
    assert parse_rule("Edit(src/**)") == ("edit", "src/**") and parse_rule("Bash") == (
        "bash",
        None,
    )
    assert parse_rule("((") is None


def test_default_mode_asks_for_writes_and_listed_tools_only(engine):
    assert engine.decide("Write", WRITE, True).action == "ask"
    assert engine.decide("ingest_path", {"path": "a"}, False).action == "ask"  # always-ask list
    assert engine.decide("search_corpus", {"query": "q"}, False).action == "allow"


def test_accept_edits_allows_edits_but_still_asks_for_the_rest(engine):
    engine.mode = "acceptEdits"
    assert engine.decide("Write", WRITE, True).action == "allow"
    assert engine.decide("Edit", WRITE, True).action == "allow"
    assert engine.decide("bash", {"command": "make"}, True).action == "ask"
    assert engine.decide("save_memory", {"text": "x"}, True).action == "ask"


def test_plan_mode_is_read_only(engine):
    engine.mode = "plan"
    assert engine.decide("Write", WRITE, True).action == "deny"
    assert engine.decide("bash", {"command": "ls"}, True).action == "deny"
    assert engine.decide("read_file", {"path": "a"}, False).action == "allow"
    put(engine, allow=["Write"])  # no rule makes a plan writable
    assert engine.decide("Write", WRITE, True).action == "deny"


def test_bypass_needs_policy_and_never_beats_deny_or_ask(engine, tmp_path):
    with pytest.raises(ValueError, match="not allowed"):
        engine.mode = "bypass"
    engine.allow_bypass = True
    engine.mode = "bypass"
    assert engine.decide("Write", WRITE, True).action == "allow"
    put(engine, deny=["Write(src/**)"], ask=["Bash(rm:*)"])
    assert engine.decide("Write", WRITE, True).action == "deny"
    assert engine.decide("bash", {"command": "rm -rf x"}, True).action == "ask"
    assert engine.decide("bash", {"command": "ls"}, True).action == "allow"


def test_deny_wins_over_allow_and_ask(engine):
    put(engine, allow=["Write"], ask=["Write(src/**)"], deny=["Write(src/secret/**)"])
    assert engine.decide("Write", {"path": "src/secret/k"}, True).action == "deny"
    assert engine.decide("Write", {"path": "src/a.py"}, True).action == "ask"
    assert engine.decide("Write", {"path": "docs/a.md"}, True).action == "allow"
    decision = engine.decide("Write", {"path": "src/secret/k"}, True)
    assert decision.rule == "Write(src/secret/**)" and "denied by rule" in decision.reason


def test_project_state_rules_apply_and_a_damaged_file_is_ignored(engine):
    engine.state.update(permissions={"allow": ["Write(docs/**)"], "deny": ["Write(docs/x/**)"]})
    assert engine.decide("Write", {"path": "docs/a.md"}, True).action == "allow"
    assert engine.decide("Write", {"path": "docs/x/a.md"}, True).action == "deny"
    engine.state.path.write_text("{not json", encoding="utf-8")
    assert engine.decide("Write", {"path": "docs/a.md"}, True).action == "ask"


def test_mode_follows_saved_settings_until_set(engine):
    assert engine.mode == "default"
    put(engine, defaultMode="acceptEdits")
    assert engine.mode == "acceptEdits"  # `/write on` and the settings panel take effect at once
    engine.mode = "plan"
    put(engine, defaultMode="default")
    assert engine.mode == "plan"  # an explicit choice for this session wins
    put(engine, defaultMode="bypass")
    fresh = PermissionEngine(engine.settings_file, engine.state, engine.project_root)
    assert fresh.mode == "default"  # bypass in the file is ignored without the policy flag


def test_cycling_modes(engine):
    assert [next_mode(m) for m in ("default", "acceptEdits", "plan")] == [
        "acceptEdits", "plan", "default",
    ]  # fmt: skip
    assert (
        next_mode("plan", allow_bypass=True) == "bypass" and next_mode("bypass", True) == "default"
    )
    assert [engine.cycle() for _ in range(4)] == ["acceptEdits", "plan", "default", "acceptEdits"]


def test_installs_outside_the_sandbox_are_denied_whatever_the_settings_say(engine):
    put(engine, allow=["Bash", "Bash(pip install:*)"])
    engine.allow_bypass = True
    engine.mode = "bypass"
    for command in ("pip install --user requests", "sudo apt-get install gcc", "pipx install x"):
        decision = engine.decide("bash", {"command": command}, True)
        assert decision.action == "deny" and decision.rule == "builtin:install", command


def test_sandbox_installs_run_without_a_prompt_and_a_user_rule_restores_it(engine):
    command = {"command": "pip install requests"}
    decision = engine.decide("bash", command, True)
    assert decision.action == "allow" and decision.rule == "builtin:sandbox-install"
    put(engine, ask=["Bash(pip install:*)"])
    assert engine.decide("bash", command, True).action == "ask"
    put(engine, deny=["Bash(pip install:*)"])
    assert engine.decide("bash", command, True).action == "deny"


def test_suggested_rules(engine):
    assert engine.suggest("bash", {"command": "git status -s"}) == "bash(git status:*)"
    assert engine.suggest("bash", {"command": "make"}) == "bash(make:*)"
    assert engine.suggest("Write", {"path": "a.txt"}) == "write(a.txt)"
    assert engine.suggest("save_memory", {"text": "x"}) == "save_memory"


def test_answers_are_kept_per_scope(engine):
    engine.remember("Write(a.txt)", "session")
    engine.remember("Write(b.txt)", "project")
    engine.remember("Write(b.txt)", "project")  # no duplicate
    engine.remember("Write(c.txt)", "everywhere")
    assert json.loads(engine.state.path.read_text())["permissions"]["allow"] == [
        "Write(b.txt)"
    ]
    assert settings.read_raw(engine.settings_file)["permissions"]["allow"] == ["Write(c.txt)"]
    for name in "abc":
        assert engine.decide("Write", {"path": f"{name}.txt"}, True).action == "allow"
    assert engine.decide("Write", {"path": "d.txt"}, True).action == "ask"
    fresh = PermissionEngine(engine.settings_file, engine.state, engine.project_root)
    assert fresh.decide("Write", {"path": "a.txt"}, True).action == "ask"  # session only
    assert fresh.decide("Write", {"path": "b.txt"}, True).action == "allow"
    with pytest.raises(ValueError):
        engine.remember("((", "project")
    with pytest.raises(ValueError):
        engine.remember("Write", "forever")


def test_a_broken_settings_file_means_no_rules_not_a_crash(engine):
    engine.settings_file.parent.mkdir(parents=True, exist_ok=True)
    engine.settings_file.write_text('{"permissions": {"allow": 5}}', encoding="utf-8")
    assert engine.decide("Write", WRITE, True).action == "ask"
    assert engine.mode == "default"


@pytest.mark.usefixtures("use_placeholder_model")
def test_the_agent_loop_obeys_the_engine(tmp_path, project):
    from laris.client.application.chat_app import ChatApp
    from laris.client.application.service import SearchService
    from laris.client.application.workspace import Workspace

    chat = ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")
    asked = []
    session = chat._session(
        {"id": "s1", "messages": []}, lambda name, args: asked.append(name) or True
    )
    chat.permissions.mode = "plan"
    denied = session._execute("Write", {"path": "a.txt", "content": "x"})
    assert denied["error"]["code"] == "approval_denied" and not asked
    chat.permissions.mode = "default"
    session._execute("Write", {"path": "a.txt", "content": "x"})
    assert asked == ["Write"]  # default mode asks
    chat.permissions.mode = "acceptEdits"
    session._execute("Write", {"path": "b.txt", "content": "x"})
    assert asked == ["Write"]  # acceptEdits does not
    settings.write(chat.permissions.settings_file, {"permissions": {"deny": ["Write(c.txt)"]}})
    refused = session._execute("Write", {"path": "c.txt", "content": "x"})
    assert refused["error"]["code"] == "approval_denied"
    assert not any(p.name == "c.txt" for p in tmp_path.rglob("c.txt"))
