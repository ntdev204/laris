"""Shared fixtures: configuration and the home folder are isolated for every test."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_config_enabled():
    """`laris` switches project configuration off for its process; a test must not inherit that."""
    from laris.shared.config.loader import ignore_project_config

    ignore_project_config(False)
    yield
    ignore_project_config(False)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """No test may read or write the owner's real `~/.laris`: HOME points at a throwaway folder."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LARIS_APP__SETTINGS_FILE", str(home / ".laris" / "settings.json"))
