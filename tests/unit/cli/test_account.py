"""API key: stored privately, names a private conversation space, never written to state."""

import json
import os
import stat

import pytest

from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace
from cli import credentials
from cli.main import build_parser, interactive_default, main
from config.loader import load_runtime_config

KEY_A = "key-alice-0123456789"
KEY_B = "key-bob-9876543210"


@pytest.fixture
def cfg(project, tmp_path, monkeypatch):
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    config = load_runtime_config(project).app
    return config.model_copy(update={"account_file": str(tmp_path / "home" / "cred.json")})


def test_key_is_saved_privately_and_resolved_in_order(cfg):
    path = credentials.save(cfg, KEY_A)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert credentials.resolve(cfg, environ={}, interactive=False) == KEY_A
    assert credentials.resolve(cfg, environ={cfg.key_env: KEY_B}, interactive=False) == KEY_B
    assert credentials.forget(cfg) and not credentials.forget(cfg)


def test_prompt_when_unknown_and_error_when_not_interactive(cfg):
    with pytest.raises(credentials.CredentialError):
        credentials.resolve(cfg, environ={}, interactive=False)
    asked = []
    key = credentials.resolve(cfg, environ={}, ask=lambda p: asked.append(p) or KEY_A)
    assert key == KEY_A and asked and credentials.load_saved(cfg) == KEY_A
    with pytest.raises(credentials.CredentialError):
        credentials.validate("short")
    with pytest.raises(credentials.CredentialError):
        credentials.validate("has a space in it")


def test_fingerprint_is_one_way_and_distinct():
    assert credentials.fingerprint(KEY_A) != credentials.fingerprint(KEY_B)
    assert KEY_A not in credentials.fingerprint(KEY_A) and len(credentials.fingerprint(KEY_A)) == 16


def _chat(project, tmp_path, key):
    service = SearchService(Workspace(tmp_path / "ws"))
    return ChatApp(service, project, user=credentials.fingerprint(key))


def test_each_key_has_its_own_conversations_settings_and_folder(project, tmp_path):
    alice, bob = _chat(project, tmp_path, KEY_A), _chat(project, tmp_path, KEY_B)
    mine = alice.conversations.create("Của Alice")
    list(alice.send(mine["id"], "perovskite"))
    alice.update_settings({"model": "alice-model"})
    assert [r["title"] for r in alice.conversations.list()] == ["perovskite"]
    assert bob.conversations.list() == []
    with pytest.raises(KeyError):
        bob.conversations.get(mine["id"])
    assert bob.settings().get("model") != "alice-model"
    assert alice.root != bob.root and credentials.fingerprint(KEY_A) in alice.root.parts
    again = _chat(project, tmp_path, KEY_A)  # the same key later sees its own history
    assert again.conversations.get(mine["id"])["id"] == mine["id"]


def test_key_never_reaches_state_files_and_user_folders_are_denied_to_tools(project, tmp_path):
    chat = _chat(project, tmp_path, KEY_A)
    os.environ["LARIS_API_KEY"] = KEY_A
    try:
        conv = chat.conversations.create()
        list(chat.send(conv["id"], f"my key is {KEY_A}"))
    finally:
        del os.environ["LARIS_API_KEY"]
    blob = "".join(p.read_text(errors="ignore") for p in chat.root.rglob("*") if p.is_file())
    assert KEY_A not in blob
    rt = chat.runtime
    assert rt.paths.denied(chat.root / "conversations" / f"{conv['id']}.json")


def test_login_commands_and_bare_laris_routes(project, tmp_path, monkeypatch, capsys):
    assert interactive_default(["login"]) == ["account", "login"]
    assert interactive_default(["whoami"]) == ["account", "whoami"]
    assert build_parser().parse_args(["account", "whoami"]).command == "whoami"
    monkeypatch.chdir(project)
    cred = tmp_path / "cred.json"
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(cred))
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    assert main(["whoami"]) == 1
    monkeypatch.setattr("getpass.getpass", lambda _="": KEY_A)
    assert main(["login"]) == 0 and json.loads(cred.read_text())["api_key"] == KEY_A
    capsys.readouterr()
    assert main(["whoami"]) == 0
    out = capsys.readouterr().out
    assert credentials.fingerprint(KEY_A) in out and KEY_A not in out
    assert main(["logout"]) == 0 and not cred.exists()


def test_chat_without_a_key_stops_with_a_clear_message(project, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(tmp_path / "none.json"))
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    assert main(["-p", "xin chào"]) == 2
    assert "LARIS_API_KEY" in capsys.readouterr().out
