"""Shared fixtures: an isolated project folder carrying the real prompt modules and policy."""

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_url_opener():
    """No test may inherit (or leave behind) a process-wide pinned-certificate opener."""
    from laris.shared.harness import trust

    trust.reset()
    yield
    trust.reset()


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
