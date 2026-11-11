"""/how-to-use prints the prepared guide verbatim: no model call, no inference."""

import json

import pytest

from agent.provider import ChatProvider, wire_messages
from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace
from config.loader import load_runtime_config
from harness.integrity import protected_files, verify


class Exploding(ChatProvider):
    """Fails the test if the model is ever called."""

    calls = 0

    def chat(self, messages, tools):
        Exploding.calls += 1
        raise AssertionError("the model must not be called for /how-to-use")


@pytest.fixture
def chat(project, tmp_path):
    return ChatApp(SearchService(Workspace(tmp_path / "ws")), project, project / "chat")


def guide_text(project):
    return (project / ".laris" / "help" / "how-to-use.md").read_text(encoding="utf-8").strip()


def test_command_prints_the_file_verbatim_without_the_model(chat, project, monkeypatch):
    monkeypatch.setattr(chat, "provider", lambda runtime: Exploding())
    conv = chat.conversations.create()
    events = list(chat.send(conv["id"], "/how-to-use"))
    assert [e["type"] for e in events] == ["text", "done"]
    assert events[0]["delta"] == guide_text(project) == events[1]["answer"]
    assert events[1]["status"] == "completed" and Exploding.calls == 0
    assert list(chat.send(conv["id"], "  /HOW-TO-USE  "))[0]["delta"] == guide_text(project)


def test_help_turns_are_stored_for_display_but_hidden_from_the_model(chat, project):
    conv = chat.conversations.create()
    list(chat.send(conv["id"], "/how-to-use"))
    saved = chat.conversations.get(conv["id"])["messages"]
    assert [m["role"] for m in saved] == ["user", "assistant"] and all(m["ui_only"] for m in saved)
    assert wire_messages(saved + [{"role": "user", "content": "real"}]) == [
        {"role": "user", "content": "real"}
    ]
    # a later real turn keeps the help messages in history but never counts or summarises them
    events = list(chat.send(conv["id"], "corpus_status"))
    assert events[-1]["status"] == "completed"
    history = chat.conversations.get(conv["id"])["messages"]
    assert history[0]["ui_only"] and history[1]["content"] == guide_text(project)
    assert chat.usage(conv["id"])["tokens"] < 20000


def test_help_turn_is_not_collected_as_training_data(chat):
    conv = chat.conversations.create()
    list(chat.send(conv["id"], "/how-to-use"))
    assert chat.learning_stats()["examples"]["sft"] == 0


def test_missing_file(chat, project, tmp_path):
    assert chat.how_to_use() == guide_text(project)
    (project / ".laris" / "help" / "how-to-use.md").unlink()
    relaxed = ChatApp(chat.service, project, project / "chat", {"prompts.integrity": "off"})
    assert "Chưa có" in relaxed.how_to_use()


def test_guide_is_integrity_protected_and_covers_the_commands(project):
    cfg = load_runtime_config(project).prompts
    assert any(p.name == "how-to-use.md" for p in protected_files(project, cfg))
    path = project / ".laris" / "help" / "how-to-use.md"
    path.write_text(path.read_text() + "\nextra", encoding="utf-8")
    assert any("how-to-use.md" in p for p in verify(project, cfg))


def test_guide_mentions_every_user_command():
    from tests.unit.harness.test_harness import REPO

    text = (REPO / ".laris" / "help" / "how-to-use.md").read_text(encoding="utf-8")
    for needle in (
        "/how-to-use", "/workflow", "/compact", "/context", "/rate", "/learn", "/skills",
        "laris --resume", "/sessions", "laris login",
        "grounded-qa", "document-intake", "evidence-review", "research-brief", "save_skill",
        "vault/",
    ):  # fmt: skip
        assert needle in text, needle
    assert json.dumps(text)  # valid text


def test_guide_is_for_users_not_operators():
    from tests.unit.harness.test_harness import REPO

    text = (REPO / ".laris" / "help" / "how-to-use.md").read_text(encoding="utf-8")
    for forbidden in ("model serve", "app serve", "harness verify", "harness lock", "brain check"):
        assert forbidden not in text, forbidden


def test_bare_laris_and_resume_open_the_chat_and_commands_are_unchanged():
    from cli.main import build_parser, interactive_default

    assert interactive_default([]) == ["agent", "chat"]
    assert interactive_default(["--resume"]) == ["agent", "chat", "--resume"]
    assert interactive_default(["--resume", "ab12"]) == ["agent", "chat", "--resume", "ab12"]
    assert interactive_default(["skills", "list"]) == ["skills", "list"]
    assert interactive_default(["--help"]) == ["--help"]
    args = build_parser().parse_args(interactive_default(["--resume"]))
    assert args.resume == "pick"
    assert build_parser().parse_args(interactive_default(["--resume", "ab"])).resume == "ab"


def test_resume_picker_prefix_and_new(chat, monkeypatch):
    from cli.commands.agent import _Chat

    first = chat.conversations.create("Một")
    second = chat.conversations.create("Hai")
    monkeypatch.setattr("builtins.input", lambda _="": "")
    assert _Chat._start(chat, "pick")["id"] in (first["id"], second["id"])
    assert _Chat._start(chat, second["id"][:6])["id"] == second["id"]
    monkeypatch.setattr("builtins.input", lambda _="": "n")
    fresh = _Chat._start(chat, "pick")
    assert fresh["id"] not in (first["id"], second["id"])
    monkeypatch.setattr("builtins.input", lambda _="": "2")
    rows = chat.conversations.list()
    assert _Chat._start(chat, "pick")["id"] == rows[1]["id"]
    assert _Chat._start(chat, "nonexistent")["messages"] == []


def test_web_is_removed():
    from tests.unit.harness.test_harness import REPO

    assert not (REPO / "src" / "application" / "server.py").exists()
    assert not (REPO / "src" / "application" / "web_ui.py").exists()
    text = (REPO / ".laris" / "help" / "how-to-use.md").read_text(encoding="utf-8").lower()
    assert "web" not in text.split() and "trình duyệt" not in text
