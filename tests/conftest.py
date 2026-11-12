"""Shared test setup: server tests never touch the real home folder."""

import pytest


@pytest.fixture(autouse=True)
def _server_master_secret(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("LARIS_SERVER_MASTER", "test-master-secret-0123456789abcdef")


@pytest.fixture
def use_placeholder_model(monkeypatch):
    """The client has no offline mode (D16); tests of the chat flow stand in for the server with the
    scripted placeholder planner."""
    from laris.client.application.chat_app import ChatApp
    from laris.shared.offline import OfflinePlanner

    def provider(self, runtime):
        return OfflinePlanner(
            runtime.strings,
            self.service.has_model,
            runtime.config.app.search_default_top_k,
            runtime.config.agent.read_max_chars // 5,
        )

    monkeypatch.setattr(ChatApp, "provider", provider)
