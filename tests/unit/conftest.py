"""Shared fixtures: an isolated project folder carrying the real prompt modules and policy."""

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    """A throwaway project root with configs/ and LARIS.md copied from the repository."""
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    shutil.copy(REPO / "configs" / "default.yaml", root / "configs" / "default.yaml")
    shutil.copytree(REPO / "configs" / "prompts", root / "configs" / "prompts")
    shutil.copy(REPO / "LARIS.md", root / "LARIS.md")
    return root
