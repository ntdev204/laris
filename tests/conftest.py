"""Shared test setup: server tests never touch the real home folder."""

import pytest


@pytest.fixture(autouse=True)
def _server_master_secret(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("LARIS_SERVER_MASTER", "test-master-secret-0123456789abcdef")
