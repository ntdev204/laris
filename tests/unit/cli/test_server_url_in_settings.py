import json
import stat

import pytest

from cli.commands.account import _set_server
from laris.shared.config import settings
from laris.shared.config.loader import load_runtime_config


def test_server_address_comes_from_global_settings_json(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.delenv("LARIS_MODEL_API__BASE_URL", raising=False)
    assert load_runtime_config(tmp_path / "proj").model_api.base_url == ""
    (tmp_path / ".laris").mkdir()
    (tmp_path / ".laris" / "settings.json").write_text(
        json.dumps({"server": {"url": "https://laris.example.com/v1"}, "extraInstructions": "x"})
    )
    assert load_runtime_config(tmp_path / "proj").model_api.base_url == (
        "https://laris.example.com/v1"
    )


def test_a_1x_flat_settings_file_is_still_understood(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.delenv("LARIS_MODEL_API__BASE_URL", raising=False)
    (tmp_path / ".laris").mkdir()
    (tmp_path / ".laris" / "settings.json").write_text(
        json.dumps({"base_url": "https://old.example.com/v1", "allow_write": True})
    )
    config = load_runtime_config(tmp_path / "proj")
    assert config.model_api.base_url == "https://old.example.com/v1"
    assert config.agent.approval.mode == "auto"


def test_login_server_writes_settings_json_and_keeps_other_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.commands.account.GLOBAL_DIR", tmp_path / ".laris")
    path = tmp_path / ".laris" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"extraInstructions": "keep"}))
    assert _set_server("https://h:8000/v1/") == path
    assert json.loads(path.read_text()) == {
        "extraInstructions": "keep",
        "server": {"url": "https://h:8000/v1"},
    }


def test_login_saves_the_key_in_credentials_json_and_not_in_settings(tmp_path):
    from laris.shared.config.runtime_schemas import AppConfig
    from laris.shared.harness import credentials

    cfg = AppConfig(account_file=str(tmp_path / ".credentials.json"))
    credentials.save(cfg, "lk_abc_secretvalue")
    path = tmp_path / ".credentials.json"
    assert json.loads(path.read_text()) == {"api_key": "lk_abc_secretvalue"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert credentials.load_saved(cfg) == "lk_abc_secretvalue"
    assert credentials.forget(cfg) and credentials.load_saved(cfg) is None
    with pytest.raises(settings.SettingsError, match="api_key: unknown setting"):
        settings.validate({"api_key": "x"})  # a key can never live in settings.json
