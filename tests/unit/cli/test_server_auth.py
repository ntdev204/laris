"""Server-side key authentication and the stateless-server contract (user disk = database)."""

import ast
import threading
from pathlib import Path

import pytest

from agent.provider import AuthError, HttpChatProvider, OfflinePlanner, check_key
from cli.main import main
from harness.runtime import HarnessRuntime
from serving.auth import KeyRing
from serving.model_server import ModelService, build_server

SRC = Path(__file__).resolve().parents[3] / "src"
GOOD, OTHER = "test-key-user-one", "test-key-user-two"


def test_keyring_accepts_only_known_keys(tmp_path):
    f = tmp_path / "keys.txt"
    f.write_text(f"# test keys\n{GOOD}\n\n{OTHER}  # second\n", encoding="utf-8")
    ring = KeyRing.load("KEYS", str(f), {"KEYS": "env-key-aaaa1111, env-key-bbbb2222"})
    assert len(ring) == 4
    for key in (GOOD, OTHER, "env-key-aaaa1111", "  env-key-bbbb2222 "):
        assert ring.check(key)
    for bad in ("", None, "test-key-user", GOOD + "x", "TEST-KEY-USER-ONE"):
        assert not ring.check(bad)
    with pytest.raises(ValueError):
        KeyRing(["short"])
    assert not KeyRing().check(GOOD)  # an empty ring accepts nothing


@pytest.fixture
def server():
    rt = HarnessRuntime()
    service = ModelService(OfflinePlanner(rt.strings), "laris-core", keys=KeyRing([GOOD, OTHER]))
    srv = build_server(service, "127.0.0.1", 0, rt.config.serving.max_body_bytes)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_server_rejects_missing_and_wrong_keys_and_accepts_each_valid_key(server, monkeypatch):
    assert check_key(server, GOOD) == "ok" and check_key(server, OTHER) == "ok"
    assert check_key(server, "wrong-key-123456") == "rejected"
    assert check_key(server, "") == "rejected"
    messages = [{"role": "user", "content": "graphene"}]
    monkeypatch.setenv("T_KEY", "wrong-key-123456")
    with pytest.raises(AuthError):
        HttpChatProvider(server, "m", "T_KEY", timeout_s=3).chat(messages, [])
    with pytest.raises(AuthError):
        list(HttpChatProvider(server, "m", "T_KEY", timeout_s=3).stream(messages, []))
    monkeypatch.setenv("T_KEY", GOOD)
    assert HttpChatProvider(server, "m", "T_KEY", timeout_s=3).chat(messages, []).tool_calls
    assert check_key("http://127.0.0.1:9/v1", GOOD, 1) == "unreachable"


def test_health_reveals_nothing_and_models_need_a_key(server):
    import json
    import urllib.request

    with urllib.request.urlopen(server.removesuffix("/v1") + "/health") as r:
        assert json.loads(r.read()) == {"status": "ok"}


def test_serve_refuses_to_start_without_keys(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.delenv("LARIS_SERVER_KEYS", raising=False)
    assert main(["model", "serve", "--port", "0"]) == 2
    assert "no API keys" in capsys.readouterr().out


def test_chat_stops_when_the_server_rejects_the_key(server, project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv("LARIS_API_KEY", "wrong-key-123456")
    monkeypatch.setenv("LARIS_MODEL_API__BASE_URL", server)
    monkeypatch.setenv("LARIS_MODEL_API__ALLOW_REMOTE", "false")
    assert main(["-p", "xin chào"]) == 2
    assert "từ chối" in capsys.readouterr().out
    monkeypatch.setenv("LARIS_API_KEY", GOOD)
    assert main(["-p", "xin chào"]) == 0


def test_login_does_not_save_a_rejected_key(server, project, tmp_path, monkeypatch):
    monkeypatch.chdir(project)
    cred = tmp_path / "cred.json"
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(cred))
    monkeypatch.setenv("LARIS_MODEL_API__BASE_URL", server)
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda _="": "wrong-key-123456")
    assert main(["login"]) == 2 and not cred.exists()
    monkeypatch.setattr("getpass.getpass", lambda _="": OTHER)
    assert main(["login"]) == 0 and cred.exists()


# -- the server is stateless: user data lives on the user's machine only ------------------------
FORBIDDEN = {"application", "vault", "learning", "harness", "skills", "scientific", "retrieval"}


def _imports(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_model_server_cannot_touch_user_data_or_tools():
    for path in (SRC / "serving").glob("*.py"):
        assert not (_imports(path) & FORBIDDEN), path.name


def test_model_server_writes_no_files_and_logs_nothing():
    text = "".join(p.read_text(encoding="utf-8") for p in (SRC / "serving").glob("*.py"))
    for needle in ("write_text", "write_bytes", "open(", "logging", "print("):
        assert needle not in text, needle
