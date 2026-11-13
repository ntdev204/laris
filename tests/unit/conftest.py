"""Shared fixtures: an isolated project folder carrying the real prompt modules and policy."""

import shutil
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


@pytest.fixture
def project(tmp_path):
    """A throwaway project root with configs/ and LARIS.md copied from the repository."""
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    shutil.copy(REPO / "configs" / "default.yaml", root / "configs" / "default.yaml")
    for part in ("prompts", "rules", "workflows", "help", "brain", "vault"):
        shutil.copytree(REPO / ".laris" / part, root / ".laris" / part)
    shutil.copy(REPO / ".laris" / "integrity.lock", root / ".laris" / "integrity.lock")
    shutil.copy(REPO / "LARIS.md", root / "LARIS.md")
    return root


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """No test may read or write the owner's real `~/.laris`: HOME points at a throwaway folder."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LARIS_APP__SETTINGS_FILE", str(home / ".laris" / "settings.json"))
