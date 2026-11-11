"""Chat application, conversation storage and the model API round trip (loopback only)."""

import json
import threading

import pytest

from laris.agent.conversations import ConversationStore, SettingsStore
from laris.agent.provider import HttpChatProvider, OfflinePlanner
from laris.application.chat_app import ChatApp
from laris.application.server import handle_api
from laris.application.service import SearchService
from laris.application.workspace import Workspace, chunks_from_text
from laris.serving.model_server import ModelService, build_server, load_backend


@pytest.fixture
def chat(tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(
        chunks_from_text("solar.txt", "Perovskite solar cells reach 25% efficiency.")
    )
    return ChatApp(service, tmp_path / "chat")


def test_conversation_ids_cannot_escape_the_store(tmp_path):
    store = ConversationStore(tmp_path)
    for bad in ("../x", "a/b", "", "ZZZ"):
        with pytest.raises(KeyError):
            store.get(bad)
    conversation = store.create()
    assert store.get(conversation["id"])["messages"] == []
    store.delete(conversation["id"])
    assert store.list() == []


def test_settings_ignore_unknown_keys_and_wrong_types(tmp_path):
    settings = SettingsStore(tmp_path / "s.json")
    out = settings.update({"base_url": "http://x/v1", "allow_write": "yes", "evil": 1})
    assert out["base_url"] == "http://x/v1" and out["allow_write"] is False and "evil" not in out


def test_multi_turn_conversation_is_saved_and_titled(chat):
    conversation = chat.conversations.create()
    events = list(chat.send(conversation["id"], "perovskite efficiency"))
    assert [e["type"] for e in events][-1] == "done"
    list(chat.send(conversation["id"], "and what about silicon?"))
    saved = chat.conversations.get(conversation["id"])
    users = [m for m in saved["messages"] if m["role"] == "user"]
    assert len(users) == 2 and saved["title"].startswith("perovskite")
    assert saved["messages"][0]["role"] == "user"  # the system prompt is never persisted


def test_chat_routes_through_handle_api(chat):
    service = chat.service
    code, created = handle_api(service, "POST", "/api/conversations", {}, chat)
    assert code == 200
    assert handle_api(service, "GET", f"/api/conversations/{created['id']}", {}, chat)[0] == 200
    assert handle_api(service, "GET", "/api/conversations/ffffffffffff", {}, chat)[0] == 404
    assert handle_api(service, "POST", "/api/settings", {"model": "m"}, chat)[1]["model"] == "m"
    assert handle_api(service, "GET", "/api/model-health", {}, chat)[1]["mode"] == "offline"
    assert handle_api(service, "DELETE", f"/api/conversations/{created['id']}", {}, chat)[0] == 200


def test_upload_is_sandboxed_by_name_and_ingested(chat):
    import base64

    out = chat.upload("../../evil name.txt", base64.b64encode(b"graphene conducts").decode(), True)
    assert out["path"].startswith(str(chat.uploads)) and out["ingested"]["passages"] == 1


def test_model_server_round_trip_with_streaming_and_auth():
    service = ModelService(OfflinePlanner(), api_key="secret")
    server = build_server(service, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        tools = [{"type": "function", "function": {"name": "search_corpus"}}]
        messages = [{"role": "user", "content": "graphene"}]
        from laris.agent.provider import ProviderError

        with pytest.raises(ProviderError):  # wrong key is rejected
            HttpChatProvider(base, "m", timeout_s=3).chat(messages, tools)
        import os

        os.environ["LARIS_TEST_KEY"] = "secret"
        provider = HttpChatProvider(base, "m", "LARIS_TEST_KEY", timeout_s=5)
        assert provider.chat(messages, tools).tool_calls[0].name == "search_corpus"
        events = list(provider.stream(messages, tools))
        assert (
            events[-1]["type"] == "turn"
            and events[-1]["turn"].tool_calls[0].name == "search_corpus"
        )
        final = [
            {"role": "user", "content": "graphene"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {
                            "name": "search_corpus",
                            "arguments": json.dumps({"query": "graphene"}),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_0", "content": json.dumps({"hits": []})},
        ]
        streamed = list(provider.stream(final, tools))
        assert any(e["type"] == "text" for e in streamed)
    finally:
        server.shutdown()


def test_backend_loader_validates_spec():
    assert isinstance(load_backend(None), OfflinePlanner)
    with pytest.raises(ValueError):
        load_backend("no_class_given")
    with pytest.raises(TypeError):
        load_backend("json:JSONDecoder")


def test_embeddings_need_a_loaded_model():
    with pytest.raises(ValueError):
        ModelService(OfflinePlanner()).embeddings({"input": "x"})
    vectors = ModelService(OfflinePlanner(), embedder=lambda t: [[1.0, 0.0]] * len(t))
    assert len(vectors.embeddings({"input": ["a", "b"]})["data"]) == 2
