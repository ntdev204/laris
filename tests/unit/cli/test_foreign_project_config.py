"""A research project's own `configs/default.yaml` (another schema) must not break the client."""

from laris.shared.config.loader import ignore_project_config, load_runtime_config


def test_client_ignores_the_folders_default_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "default.yaml").write_text(
        "environment:\n  gravity: 9.81\n  air: {density: 1.2}\n", encoding="utf-8"
    )
    ignore_project_config(True)
    assert load_runtime_config(tmp_path).environment == "development"
