"""Chat application, conversation storage and the model API round trip (loopback only)."""

import json
import threading

import pytest

from agent.conversations import ConversationStore
from agent.provider import HttpChatProvider, OfflinePlanner
from application.chat_app import ChatApp
from application.service import SearchService
from application.workspace import Workspace, chunks_from_text
from harness.prefs import PrefsError
from harness.runtime import HarnessRuntime
from serving.model_server import ModelService, build_server, load_backend


@pytest.fixture
def chat(tmp_path, project):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(
        chunks_from_text("solar.txt", "Perovskite solar cells reach 25% efficiency.")
    )
    return ChatApp(service, project, project / "chat")


def test_conversation_ids_cannot_escape_the_store(tmp_path):
    store = ConversationStore(tmp_path)
    for bad in ("../x", "a/b", "", "ZZZ"):
        with pytest.raises(KeyError):
            store.get(bad)
    conversation = store.create()
    assert store.get(conversation["id"])["messages"] == []
    store.delete(conversation["id"])
    assert store.list() == []


def test_settings_reject_unknown_keys_and_wrong_types(chat):
    out = chat.update_settings({"base_url": "http://127.0.0.1:9/v1", "allow_write": True})
    assert out["base_url"] == "http://127.0.0.1:9/v1" and out["allow_write"] is True
    for bad in ({"evil": 1}, {"allow_write": "yes"}, {"context_window": 5}):
        with pytest.raises(PrefsError):
            chat.update_settings(bad)
    # security settings are not editable from the UI or the CLI
    with pytest.raises(PrefsError):
        chat.update_settings({"deny_read_globs": []})
    assert "evil" not in chat.settings()


def test_multi_turn_conversation_is_saved_and_titled(chat):
    conversation = chat.conversations.create()
    events = list(chat.send(conversation["id"], "perovskite efficiency"))
    assert [e["type"] for e in events][-1] == "done"
    list(chat.send(conversation["id"], "and what about silicon?"))
    saved = chat.conversations.get(conversation["id"])
    users = [m for m in saved["messages"] if m["role"] == "user"]
    assert len(users) == 2 and saved["title"].startswith("perovskite")
    assert saved["messages"][0]["role"] == "user"  # the system prompt is never persisted


def test_chat_settings_and_conversations(chat):
    created = chat.conversations.create()
    assert chat.conversations.get(created["id"])["id"] == created["id"]
    with pytest.raises(KeyError):
        chat.conversations.get("ffffffffffff")
    assert chat.update_settings({"model": "m"})["model"] == "m"
    with pytest.raises(PrefsError):
        chat.update_settings({"nope": 1})
    assert chat.model_health()["mode"] == "offline"
    chat.conversations.delete(created["id"])
    with pytest.raises(KeyError):
        chat.conversations.get(created["id"])


def test_upload_is_sandboxed_by_name_and_ingested(chat):
    import base64

    out = chat.upload("../../evil name.txt", base64.b64encode(b"graphene conducts").decode(), True)
    assert "evil" in out["path"] and ".." not in out["path"]
    assert out["ingested"]["passages"] == 1


def test_model_server_round_trip_with_streaming_and_auth():
    rt = HarnessRuntime()
    service = ModelService(OfflinePlanner(rt.strings), "laris-core", api_key="secret")
    server = build_server(service, "127.0.0.1", 0, rt.config.serving.max_body_bytes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        tools = [{"type": "function", "function": {"name": "search_corpus"}}]
        messages = [{"role": "user", "content": "graphene"}]
        from agent.provider import ProviderError

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
    strings = HarnessRuntime().strings
    assert isinstance(load_backend(None, strings), OfflinePlanner)
    with pytest.raises(ValueError):
        load_backend("no_class_given", strings)
    with pytest.raises(TypeError):
        load_backend("json:JSONDecoder", strings)


def test_embeddings_need_a_loaded_model():
    planner = OfflinePlanner(HarnessRuntime().strings)
    with pytest.raises(ValueError):
        ModelService(planner, "m").embeddings({"input": "x"})
    vectors = ModelService(planner, "m", embedder=lambda t: [[1.0, 0.0]] * len(t))
    assert len(vectors.embeddings({"input": ["a", "b"]})["data"]) == 2
