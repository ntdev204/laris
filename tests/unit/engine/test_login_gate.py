"""The part of an engine session before `ready` (ADR-019 D24, D25): the packaged server address,
and asking for what is missing over E1 instead of stopping."""

import io
import json
from pathlib import Path

import pytest

from laris.client.engine.login import LoginGate
from laris.shared.config import packaged
from laris.shared.harness import credentials, trust
from laris.shared.harness.runtime import HarnessRuntime

GOOD = "lk_good_key_for_tests"
SERVER = "https://laris.test:8443/v1"


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "home"
    (root / ".laris").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: root)
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(root / ".laris" / ".credentials.json"))
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    monkeypatch.delenv(packaged.ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    return root / ".laris"


@pytest.fixture
def server(monkeypatch):
    """A server that is reachable, verifiable and accepts one key."""
    seen = []
    monkeypatch.setattr(trust, "decide", lambda url, *a, **k: trust.Decision("trusted"))

    def verify(api, key):
        seen.append(key)
        return "ok" if key == GOOD else "rejected"

    monkeypatch.setattr(credentials, "verify_with_server", verify)
    return seen


def run_gate(home: Path, commands, environ=None):
    reader = io.StringIO("".join(json.dumps(c) + "\n" for c in commands))
    writer = io.StringIO()
    env = {} if environ is None else environ
    gate = LoginGate(reader, writer, lambda: HarnessRuntime.load(Path.cwd()), home, env)
    passed = gate.run()
    events = [json.loads(line) for line in writer.getvalue().splitlines()]
    return passed, events, env, writer.getvalue()


def defaults(tmp_path, monkeypatch, url=SERVER, fingerprint=""):
    data = {"server": {"url": url, **({"caFingerprint": fingerprint} if fingerprint else {})}}
    path = tmp_path / "defaults.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(packaged.ENV, str(path))


def test_no_server_and_no_key_are_asked_in_turn_and_the_key_is_saved(home, server):
    passed, events, env, raw = run_gate(
        home,
        [{"type": "login", "server": "laris.test:8443"}, {"type": "login", "key": GOOD}],
    )
    assert passed and [e["reason"] for e in events] == ["no_server", "no_key"]
    assert events[1]["server"] == SERVER  # a bare host name becomes an https address
    assert json.loads((home / "settings.json").read_text())["server"]["url"] == SERVER
    assert json.loads((home / ".credentials.json").read_text())["api_key"] == GOOD
    assert env["LARIS_API_KEY"] == GOOD and GOOD not in raw  # the key is never echoed


def test_a_refused_key_is_asked_again_and_not_saved(home, server, tmp_path, monkeypatch):
    defaults(tmp_path, monkeypatch)
    passed, events, _, _ = run_gate(
        home, [{"type": "login", "key": "lk_wrong_key_value"}, {"type": "login", "key": GOOD}]
    )
    assert passed and [e["reason"] for e in events] == ["no_key", "rejected"]
    assert json.loads((home / ".credentials.json").read_text())["api_key"] == GOOD
    assert server == ["lk_wrong_key_value", GOOD]


def test_a_saved_key_and_a_packaged_server_start_without_a_question(
    home, server, tmp_path, monkeypatch
):
    defaults(tmp_path, monkeypatch)
    credentials.save(HarnessRuntime.load(Path.cwd()).config.app, GOOD)
    passed, events, env, _ = run_gate(home, [])
    assert passed and events == [] and env["LARIS_API_KEY"] == GOOD
    assert not (home / "settings.json").exists()  # the default is not copied into the settings


def test_a_saved_key_the_server_now_refuses_is_forgotten(home, server, tmp_path, monkeypatch):
    defaults(tmp_path, monkeypatch)
    app = HarnessRuntime.load(Path.cwd()).config.app
    credentials.save(app, "lk_revoked_key_value")
    passed, events, _, _ = run_gate(home, [{"type": "login", "key": GOOD}])
    assert passed and events[0]["reason"] == "rejected" and "saved key" in events[0]["message"]
    assert credentials.load_saved(app) == GOOD


def test_leaving_before_login_ends_quietly(home, server, tmp_path, monkeypatch):
    defaults(tmp_path, monkeypatch)
    assert run_gate(home, [{"type": "shutdown"}])[0] is False
    assert run_gate(home, [])[0] is False  # end of input: the front end is gone
    passed, events, _, _ = run_gate(home, [{"type": "user_message", "text": "hi"}])
    assert not passed and events[-1] == {
        "type": "error", "code": "login_required", "message": "answer `login_required` first",
    }  # fmt: skip


def test_a_key_that_is_too_short_is_explained(home, server, tmp_path, monkeypatch):
    defaults(tmp_path, monkeypatch)
    passed, events, _, _ = run_gate(
        home, [{"type": "login", "key": "short"}, {"type": "login", "key": GOOD}]
    )
    assert passed and [e["reason"] for e in events] == ["no_key", "invalid"]
    assert "at least" in events[1]["message"] and server == [GOOD]


def test_an_unknown_certificate_needs_a_person_and_the_package_can_vouch(
    home, tmp_path, monkeypatch
):
    fingerprint = "SHA256:" + ":".join(["AB"] * 32)
    calls = []

    def decide(url, ca_file="", expected="", accept="", home=None, timeout=5.0):
        calls.append({"expected": expected, "accept": accept})
        if expected or accept:
            return trust.Decision("trusted" if len(calls) > 2 else "pinned", fingerprint)
        return trust.Decision("unknown", fingerprint, "authority")

    monkeypatch.setattr(trust, "decide", decide)
    monkeypatch.setattr(credentials, "verify_with_server", lambda api, key: "ok")
    defaults(tmp_path, monkeypatch)  # no fingerprint packaged: a person has to confirm
    passed, events, _, _ = run_gate(
        home, [{"type": "login", "trust": True}, {"type": "login", "key": GOOD}]
    )
    assert passed and events[0]["reason"] == "untrusted_certificate"
    assert events[0]["fingerprint"] == fingerprint and calls[1]["accept"] == fingerprint

    calls.clear()
    defaults(tmp_path, monkeypatch, fingerprint=fingerprint)  # packaged: nobody is asked
    passed, events, _, _ = run_gate(home, [])
    assert passed and events == [] and calls[0]["expected"] == fingerprint


def test_a_packaged_fingerprint_that_does_not_match_cannot_be_overridden(
    home, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        trust, "decide", lambda *a, **k: trust.Decision("mismatch", "SHA256:00", "authority")
    )
    defaults(tmp_path, monkeypatch, fingerprint="SHA256:" + ":".join(["AB"] * 32))
    passed, events, _, _ = run_gate(home, [{"type": "login", "trust": True}])
    assert not passed and [e["reason"] for e in events] == ["certificate_mismatch"] * 2


def test_an_unreachable_server_keeps_the_key_and_says_so(home, tmp_path, monkeypatch):
    monkeypatch.setattr(trust, "decide", lambda *a, **k: trust.Decision("unreachable"))
    monkeypatch.setattr(credentials, "verify_with_server", lambda api, key: "unreachable")
    defaults(tmp_path, monkeypatch)
    passed, events, _, _ = run_gate(home, [{"type": "login", "key": GOOD}])
    assert passed and events[-1]["code"] == "server_unreachable"


# -- the packaged default as configuration (D24) ---------------------------------------------
def test_precedence_environment_then_settings_then_the_packaged_default(
    home, tmp_path, monkeypatch
):
    assert HarnessRuntime.load(Path.cwd()).config.model_api.base_url == ""
    defaults(tmp_path, monkeypatch)
    assert HarnessRuntime.load(Path.cwd()).config.model_api.base_url == SERVER
    (home / "settings.json").write_text(json.dumps({"server": {"url": "https://mine.test"}}))
    assert HarnessRuntime.load(Path.cwd()).config.model_api.base_url == "https://mine.test"
    monkeypatch.setenv("LARIS_MODEL_API__BASE_URL", "https://env.test")
    assert HarnessRuntime.load(Path.cwd()).config.model_api.base_url == "https://env.test"


def test_a_broken_or_hostile_defaults_file_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "defaults.json"
    monkeypatch.setenv(packaged.ENV, str(path))
    for text in ("{not json", "[]", '{"server": "x"}', '{"server": {"url": "ftp://x"}}'):
        path.write_text(text, encoding="utf-8")
        assert packaged.load() == {} and packaged.server_url() == ""
    path.write_text('{"server": {"url": "https://a.test/", "caFingerprint": " AB "}}')
    assert packaged.server_url() == "https://a.test/v1" and packaged.ca_fingerprint() == "AB"
    path.write_text("x" * (packaged.MAX_BYTES + 1))
    assert packaged.load() == {}


def test_the_source_tree_carries_no_default(monkeypatch):
    monkeypatch.delenv(packaged.ENV, raising=False)
    assert packaged.path() is None and packaged.load() == {}  # not a frozen program: no file
    repo = Path(__file__).resolve().parents[3]
    assert not list((repo / "src").rglob(packaged.FILE_NAME))
    assert not list((repo / "packaging").glob(packaged.FILE_NAME))


def test_a_frozen_program_finds_the_file_beside_its_folder(tmp_path, monkeypatch):
    monkeypatch.delenv(packaged.ENV, raising=False)
    (tmp_path / "pkg" / "laris").mkdir(parents=True)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(tmp_path / "pkg" / "laris" / "laris"))
    (tmp_path / "pkg" / "defaults.json").write_text(json.dumps({"server": {"url": SERVER}}))
    assert packaged.server_url() == SERVER
