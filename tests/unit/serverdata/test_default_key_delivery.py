"""T59: the default key reaches the operator by a 0600 file or `keys reveal`, never the output."""

import logging
import os
import stat
from pathlib import Path

from cli.main import main
from laris.server.serverdata import ServerData
from laris.shared.config.runtime_schemas import ServingConfig

ROOT = Path(__file__).resolve().parents[3]
ARGS = ["model", "serve", "--policy-root", str(ROOT), "--port", "8123"]
ARGS += ["--model-url", "http://127.0.0.1:9/v1"]


class _Stop:
    server_port = 0

    def serve_forever(self):
        return

    def server_close(self):
        return


def test_start_up_prints_and_logs_no_key(tmp_path, monkeypatch, capsys, caplog):
    import cli.commands.model as serve

    key_file = tmp_path / "secrets" / "default.key"
    monkeypatch.setenv("LARIS_SERVING__DATA_DIR", str(tmp_path / "srv"))
    monkeypatch.setenv("LARIS_SERVING__FIRST_ADMIN_FILE", str(key_file))
    monkeypatch.setenv("LARIS_SERVING__MASTER_FILE", str(tmp_path / "master.secret"))
    monkeypatch.setattr(serve, "build_server", lambda *a, **k: _Stop())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with caplog.at_level(logging.DEBUG):
        code = main(ARGS)
    assert code == 0
    out = capsys.readouterr()
    shown = out.out + out.err + caplog.text
    secret = key_file.read_text(encoding="utf-8").strip()
    assert secret.startswith("lk_") and secret not in shown and "lk_" not in shown
    assert str(key_file) in out.out and "keys reveal default" in out.out
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    # a second start creates nothing new and says nothing about a key
    main(ARGS)
    assert "Default key created" not in capsys.readouterr().out


def test_the_file_works_as_a_key_and_reveal_returns_the_same(tmp_path):
    cfg = ServingConfig(
        data_dir=str(tmp_path / "srv"), first_admin_file=str(tmp_path / "k" / "d.key")
    )
    data = ServerData(cfg, tmp_path, lambda t: t)
    plaintext = data.ensure_default_key()
    path = data.deliver_default_key(plaintext)
    assert open(path, encoding="utf-8").read().strip() == plaintext
    assert data.keys.reveal(data.keys.default_key().id) == plaintext
    assert data.auth.authenticate(plaintext, "127.0.0.1") is not None


def test_no_file_when_none_is_configured(tmp_path):
    cfg = ServingConfig(data_dir=str(tmp_path / "srv"), first_admin_file="")
    data = ServerData(cfg, tmp_path, lambda t: t)
    assert data.deliver_default_key(data.ensure_default_key()) == ""
