"""Client acceptance suite (T82): fixtures shared by the scripted sessions.

A scripted provider stands in for the model. Nothing here says anything about model quality."""

import pytest

from laris.client.agent.provider import AssistantTurn, ChatProvider, ProviderError, ToolCall
from laris.client.application.chat_app import ChatApp
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from tests.unit.conftest import *  # noqa: F401,F403  (isolated project, autouse guards)

CITED = "Perovskite cells reach 25% efficiency [nguồn #1]."


class Scripted(ChatProvider):
    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append(messages)
        if not self.turns:
            raise ProviderError("the scripted model has nothing left to say")
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn


def golden_turns():
    """The reference session: search, write a note (needs approval), cited answer."""
    return [
        AssistantTurn(None, [ToolCall("s1", "search_corpus", {"query": "perovskite", "top_k": 2})]),
        AssistantTurn(None, [ToolCall("w1", "Write", {"path": "note.txt", "content": "hi\n"})]),
        AssistantTurn(CITED),
    ]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """The global home (`~/.laris`: settings, hooks, per-project state) is a throwaway folder."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    return home


@pytest.fixture
def make_chat(tmp_path, project, use_placeholder_model, monkeypatch):
    """A fresh ChatApp over a one-document workspace, answering with the given scripted turns."""

    def make(turns, name="ws"):
        service = SearchService(Workspace(tmp_path / name))
        service.workspace.add(
            chunks_from_text("solar.txt", "Perovskite solar cells reach 25% efficiency in labs.")
        )
        chat = ChatApp(service, project, project / f"chat-{name}")
        provider = Scripted(turns)
        monkeypatch.setattr(chat, "provider", lambda runtime: provider)
        chat.scripted = provider
        return chat

    return make
