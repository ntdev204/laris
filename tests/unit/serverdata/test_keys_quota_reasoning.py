"""Keys with roles and token quotas, usage metering, and reasoning that stays on the server."""

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from laris.client.agent.provider import AssistantTurn, ChatProvider
from laris.server.gateway import PolicyGateway
from laris.server.gateway.reasoning import ThinkSplitter
from laris.server.serverdata import ServerData
from laris.server.serverdata.cache import TTLCache
from laris.server.serverdata.keys import KeyError_
from laris.server.serving.model_server import ModelService, build_server
from laris.shared.config.runtime_schemas import ServingConfig
from laris.shared.harness.runtime import HarnessRuntime

ROOT = Path(__file__).resolve().parents[3]
SECRET_THOUGHT = "PRIVATE-REASONING-7f3a: compare the abstracts, then pick the third"


class Thinker(ChatProvider):
    """A reasoning model: thoughts arrive inline in tags and as a separate field."""

    name = "thinker"

    def chat(self, messages, tools):
        return AssistantTurn("Perovskite is stable [nguồn #1].")

    def stream(self, messages, tools):
        yield {"type": "reasoning", "delta": SECRET_THOUGHT}
        for part in ("<thi", "nk>inline secret thought</thi", "nk>Perovskite ", "is stable."):
            yield {"type": "text", "delta": part}
        yield {"type": "turn", "turn": AssistantTurn("Perovskite is stable.")}


@pytest.fixture
def stack(tmp_path):
    cfg = ServingConfig(data_dir=str(tmp_path / "srv"), cache_ttl_s=0.0, reasoning_http=False)
    runtime = HarnessRuntime.load(ROOT)
    data = ServerData(cfg, tmp_path, lambda t: runtime.redactor.redact(t)[0])
    backend = Thinker()
    gateway = PolicyGateway(
        runtime,
        backend,
        "laris-test",
        meter=data.usage,
        traces=data.traces,
        think_tags=cfg.reasoning_tags,
        chars_per_token=cfg.chars_per_token,
    )
    service = ModelService(
        backend,
        "laris-test",
        None,
        None,
        gateway,
        auth=data.auth,
        meter=data.usage,
        admin=data,
        chars_per_token=cfg.chars_per_token,
        reasoning_http=cfg.reasoning_http,
    )
    server = build_server(service, "127.0.0.1", 0, cfg.max_body_bytes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    yield data, base, service
    server.shutdown()


def call(base, key, path="/laris/chat", body=None, method=None):
    data = None if body is None and method != "POST" else json.dumps(body or {}).encode()
    request = urllib.request.Request(
        base + path, data, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


CHAT = {
    "messages": [{"role": "user", "content": "Is perovskite stable?"}],
    "laris": {"kind": "turn", "session_id": "abc123", "task": "Is perovskite stable?"},
}


def test_a_new_key_is_accepted_at_once_and_only_its_digest_is_stored(stack, tmp_path):
    data, base, _ = stack
    assert call(base, "lk_deadbeef_nope", "/models")[0] == 401
    record, key = data.keys.create("Alice", "user", None)
    assert key.startswith("lk_") and call(base, key, "/models")[0] == 200  # no restart
    assert key.encode() not in (tmp_path / "srv/laris-server.db").read_bytes()
    stored = sqlite3.connect(tmp_path / "srv/laris-server.db").execute("SELECT digest FROM keys")
    assert key not in stored.fetchone()[0] and len(record.id) == 8
    assert call(base, key + "x", "/models")[0] == 401


def test_revoked_and_expired_keys_stop_working(stack):
    data, base, _ = stack
    _, key = data.keys.create("Bob", "user", None)
    assert call(base, key, "/models")[0] == 200
    data.keys.revoke(data.keys.verify(key).id)
    assert call(base, key, "/models")[0] == 401
    _, old = data.keys.create("Old", "user", None, expires_in_days=1, now=1.0)
    assert call(base, old, "/models")[0] == 401


def test_token_quota_is_enforced_and_unlimited_never_runs_out(stack):
    data, base, _ = stack
    record, limited = data.keys.create("Small", "user", 40)
    _, unlimited = data.keys.create("Big", "user", None)
    status, body = call(base, limited, body=CHAT)
    assert status == 200 and '"usage"' in body
    assert data.keys.get(record.id).tokens_used > 0
    # keep asking until the quota is gone: then HTTP 429
    codes = [call(base, limited, body=CHAT)[0] for _ in range(5)]
    assert 429 in codes
    assert all(call(base, unlimited, body=CHAT)[0] == 200 for _ in range(5))
    data.keys.set_limit(record.id, 10_000, add=False)
    assert call(base, limited, body=CHAT)[0] == 200
    info = json.loads(call(base, limited, "/laris/account")[1])
    assert info["token_limit"] == 10_000 and info["tokens_left"] < 10_000
    assert json.loads(call(base, unlimited, "/laris/account")[1])["tokens_left"] is None


def test_roles_and_permissions(stack):
    data, base, _ = stack
    _, user = data.keys.create("U", "user", None)
    _, readonly = data.keys.create("R", "readonly", None)
    _, admin = data.keys.create("A", "admin", None)
    assert call(base, readonly, body=CHAT)[0] == 403
    assert call(base, user, body=CHAT)[0] == 200
    assert call(base, user, "/admin/usage")[0] == 403
    assert call(base, admin, "/admin/usage")[0] == 200
    with pytest.raises(KeyError_):
        data.keys.create("X", "user", None, ["reasoning.read"])  # not for ordinary roles
    with pytest.raises(KeyError_):
        data.keys.create("X", "nobody", None)
    with pytest.raises(KeyError_):
        data.keys.create("X", "user", None, ["made.up"])


def test_reasoning_never_reaches_a_client_but_is_kept_for_the_operator(stack):
    data, base, service = stack
    _, admin = data.keys.create("A", "admin", None)
    status, body = call(base, admin, body=CHAT)  # even an admin key gets no reasoning in chat
    assert status == 200
    assert SECRET_THOUGHT not in body and "inline secret thought" not in body
    assert "<think>" not in body and "Perovskite is stable." in body.replace('"', "")
    traces = data.traces.list()
    assert traces and traces[0]["reasoning_chars"] > 0
    stored = data.traces.get(traces[0]["id"])
    assert SECRET_THOUGHT in stored["reasoning"] and "inline secret thought" in stored["reasoning"]
    assert stored["task"] == "Is perovskite stable?"
    # admin HTTP view is off by default: the reasoning has no network path
    assert call(base, admin, "/admin/reasoning")[0] == 404
    service.reasoning_http = True
    status, text = call(base, admin, "/admin/reasoning?limit=5")
    assert status == 200 and "reasoning_chars" in text and SECRET_THOUGHT not in text
    status, text = call(base, admin, f"/admin/reasoning?id={traces[0]['id']}")
    assert status == 200 and SECRET_THOUGHT in text
    _, user = data.keys.create("U", "user", None)
    assert call(base, user, "/admin/reasoning")[0] == 403


def test_secrets_are_redacted_before_a_trace_is_stored(stack):
    data, _, _ = stack
    principal = data.auth.authenticate(data.keys.create("S", "user", None)[1])
    data.traces.record(principal, {"reasoning": "token sk-ant-abcdefghijklmnop1234567890 used"})
    assert (
        "sk-ant-abcdefghijklmnop1234567890"
        not in data.traces.get(data.traces.list()[0]["id"])["reasoning"]
    )


def test_think_splitter_handles_tags_split_across_chunks():
    s = ThinkSplitter([["<think>", "</think>"]])
    out = (
        "".join(s.feed(p) for p in ["a <th", "ink>hid", "den</thi", "nk> b <", "x> c"]) + s.finish()
    )
    assert out == "a  b <x> c" and "".join(s.reasoning) == "hidden"
    open_ended = ThinkSplitter([["<think>", "</think>"]])
    assert open_ended.feed("x<think>never closed") + open_ended.finish() == "x"
    assert "never closed" in "".join(open_ended.reasoning)


def test_ttl_cache_expires_and_evicts():
    now = [0.0]
    cache = TTLCache(10, 2, clock=lambda: now[0])
    cache.put("a", 1)
    assert cache.get("a") == 1
    now[0] = 11
    assert cache.get("a") is None
    cache.put("a", 1), cache.put("b", 2), cache.put("c", 3)
    assert cache.get("a") is None and cache.get("c") == 3 and cache.hits >= 2


def test_key_commands_create_list_limit_revoke(tmp_path, monkeypatch, capsys):
    from cli.main import main

    monkeypatch.chdir(tmp_path)
    assert main(["keys", "create", "--label", "Carol", "--role", "user", "--tokens", "500"]) == 0
    out = capsys.readouterr().out
    key = out.split("shown once, give it to the user): ")[1].split()[0]
    key_id = key.split("_")[1]
    assert main(["keys", "list"]) == 0 and key_id in capsys.readouterr().out
    assert main(["keys", "limit", key_id, "--tokens", "100", "--add"]) == 0
    assert "600" in capsys.readouterr().out
    assert main(["keys", "limit", key_id, "--tokens", "unlimited"]) == 0
    assert "unlimited" in capsys.readouterr().out
    assert (
        main(["keys", "create", "--label", "x", "--role", "user", "--permission", "keys.manage"])
        == 2
    )
    assert main(["keys", "revoke", key_id]) == 0
    assert "revoked" in capsys.readouterr().out
    assert main(["usage", "summary"]) == 0
    assert main(["reasoning", "list"]) == 0


def test_whoami_shows_role_and_token_balance(stack, monkeypatch, capsys, tmp_path):
    from cli.main import main

    data, base, _ = stack
    _, key = data.keys.create("Dana", "user", 5000)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LARIS_API_KEY", key)
    monkeypatch.setenv("LARIS_MODEL_API__BASE_URL", base)
    assert main(["whoami"]) == 0
    out = capsys.readouterr().out
    assert "Vai trò: user" in out and "còn 5000" in out


def test_over_http_the_real_peer_address_decides(stack):
    data, base, _ = stack
    default = data.ensure_default_key()
    assert call(base, default, "/models")[0] == 200  # this test client runs on the server itself
    _, elsewhere = data.keys.create("Remote", "user", None, allowed_ips=["203.0.113.0/24"])
    assert call(base, elsewhere, "/models")[0] == 401  # peer is 127.0.0.1: not in its range
    _, here = data.keys.create("Local", "user", None, allowed_ips=["127.0.0.0/8"])
    assert call(base, here, "/models")[0] == 200
