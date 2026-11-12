import json

from cli.commands.account import _set_server
from laris.shared.config.loader import load_runtime_config


def test_server_address_comes_from_global_settings_json(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.delenv("LARIS_MODEL_API__BASE_URL", raising=False)
    assert load_runtime_config(tmp_path / "proj").model_api.base_url == ""
    (tmp_path / ".laris").mkdir()
    (tmp_path / ".laris" / "settings.json").write_text(
        json.dumps({"base_url": "https://laris.example.com/v1", "extra_instructions": "x"})
    )
    assert load_runtime_config(tmp_path / "proj").model_api.base_url == (
        "https://laris.example.com/v1"
    )


def test_login_server_writes_settings_json_and_keeps_other_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.commands.account.GLOBAL_DIR", tmp_path / ".laris")
    settings = tmp_path / ".laris" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"extra_instructions": "keep"}))
    assert _set_server("https://h:8000/v1/") == settings
    data = json.loads(settings.read_text())
    assert data == {"extra_instructions": "keep", "base_url": "https://h:8000/v1"}


def test_login_saves_key_into_settings_json_with_model_and_url(tmp_path):
    import stat

    from laris.shared.config.runtime_schemas import AppConfig
    from laris.shared.harness import credentials

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"base_url": "https://h/v1", "model": "laris-core"}))
    cfg = AppConfig(account_file=str(settings))
    credentials.save(cfg, "lk_abc_secretvalue")
    data = json.loads(settings.read_text())
    assert data == {
        "base_url": "https://h/v1",
        "model": "laris-core",
        "api_key": "lk_abc_secretvalue",
    }
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    assert credentials.load_saved(cfg) == "lk_abc_secretvalue"
    assert credentials.forget(cfg) and "api_key" not in json.loads(settings.read_text())
    assert json.loads(settings.read_text())["model"] == "laris-core"
