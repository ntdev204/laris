import json
import threading

import pytest

from cli.commands import account
from cli.main import main
from laris.client.agent.provider import check_key
from laris.server.serverdata import tls as server_tls
from laris.server.serving.auth import KeyRing
from laris.server.serving.model_server import ModelService, build_server, enable_tls, load_backend
from laris.shared.harness import trust
from laris.shared.harness.runtime import HarnessRuntime

KEY = "lk_test_trust_key_value"


@pytest.fixture
def https_server(tmp_path):
    cert, key = server_tls.create_self_signed(str(tmp_path / "tls"), ["localhost", "127.0.0.1"])
    rt = HarnessRuntime()
    service = ModelService(load_backend(None, rt.strings), "m", keys=KeyRing([KEY]))
    srv = build_server(service, "127.0.0.1", 0, rt.config.serving.max_body_bytes)
    enable_tls(srv, str(cert), str(key))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_port}/v1", cert
    srv.shutdown()
    trust.reset()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(account, "GLOBAL_DIR", tmp_path / "home" / ".laris")
    monkeypatch.setattr(trust, "TRUST_DIR", str(tmp_path / "home" / ".laris" / "trusted"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    monkeypatch.setattr("getpass.getpass", lambda _="": KEY)
    monkeypatch.setenv(
        "LARIS_APP__ACCOUNT_FILE", str(tmp_path / "home" / ".laris" / "settings.json")
    )
    return tmp_path / "home" / ".laris"


def test_fingerprint_formats_agree(https_server):
    url, cert = https_server
    pem = cert.read_text()
    assert server_tls.fingerprint(str(cert)) == trust.fingerprint_pem(pem)
    fp = trust.fingerprint_pem(pem)
    assert fp.startswith("SHA256:") and trust.normalise(fp.lower().replace(":", "")) == fp
    assert trust.normalise(fp) == fp


def test_an_untrusted_certificate_is_refused_until_the_fingerprint_matches(
    https_server, home, monkeypatch, capsys
):
    url, cert = https_server
    host_port = url.split("//")[1].split("/")[0]
    host, port = host_port.split(":")
    assert check_key(url, KEY, 3) == "unreachable"  # never trusted silently
    assert not trust.is_trusted(host, int(port))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["login", "--server", url]) == 2  # no terminal, no flag: refused
    assert "Không tin cậy" in capsys.readouterr().out
    wrong = "SHA256:" + ":".join(["00"] * 32)
    assert main(["login", "--server", url, "--trust-fingerprint", wrong]) == 2
    assert "KHÔNG khớp" in capsys.readouterr().out
    assert check_key(url, KEY, 3) == "unreachable"
    right = server_tls.fingerprint(str(cert))
    assert main(["login", "--server", url, "--trust-fingerprint", right]) == 0
    settings = json.loads((home / "settings.json").read_text())
    assert settings["base_url"] == url and settings["ca_file"].endswith(f"{host}_{port}.pem")
    assert settings["api_key"] == KEY
    assert check_key(url, KEY, 3) == "ok"  # pinned: verified from now on
    trust.reset()
    assert check_key(url, KEY, 3) == "unreachable"  # a fresh process installs the pin itself
    HarnessRuntime.load()  # reads settings.json and installs the pinned certificate
    assert check_key(url, KEY, 3) == "ok"


def test_interactive_confirmation_pins_the_certificate(https_server, home, monkeypatch):
    url, _ = https_server
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _="": "y")
    assert main(["login", "--server", url]) == 0
    assert json.loads((home / "settings.json").read_text())["ca_file"]


def test_a_changed_certificate_is_not_accepted_by_the_pin(https_server, home, tmp_path):
    url, cert = https_server
    assert (
        main(["login", "--server", url, "--trust-fingerprint", server_tls.fingerprint(str(cert))])
        == 0
    )
    other, _ = server_tls.create_self_signed(str(tmp_path / "other"), ["localhost", "127.0.0.1"])
    pinned = json.loads((home / "settings.json").read_text())["ca_file"]
    assert trust.fingerprint_pem(open(pinned).read()) != server_tls.fingerprint(str(other))
