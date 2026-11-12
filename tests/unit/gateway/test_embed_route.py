"""T58: the client embeds through POST /v1/laris/embed; no encoder runs on the client and no text is
stored on the server."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from laris.client.application.service import SearchService, ServiceError
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.protocol import AssistantTurn, ChatProvider, EmbedResponse
from laris.server.serverdata import ServerData
from laris.server.serving.model_server import build_server
from laris.server.serving.service import ModelService
from laris.shared.config.runtime_schemas import ServingConfig
from laris.shared.http_provider import ServerEmbedder

VOCAB = ["perovskite", "solar", "silicon", "battery", "quantum", "protein", "neural", "graph"]


def scripted_encoder(texts):
    """A tiny bag-of-words encoder: the same words give the same direction."""
    return [[float(t.lower().count(w)) for w in VOCAB] for t in texts]


class Quiet(ChatProvider):
    name = "quiet"

    def chat(self, messages, tools):
        return AssistantTurn("x")


@pytest.fixture
def stack(tmp_path, monkeypatch):
    cfg = ServingConfig(data_dir=str(tmp_path / "srv"), cache_ttl_s=0.0)
    data = ServerData(cfg, tmp_path, lambda t: t)
    service = ModelService(
        Quiet(), "m", scripted_encoder, None, None, auth=data.auth, meter=data.usage
    )
    server = build_server(service, "127.0.0.1", 0, 1_000_000)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    _, key = data.keys.create("alice", "user", 100000)
    _, readonly = data.keys.create("ro", "readonly", None)
    monkeypatch.setenv("LARIS_TEST_KEY", key)
    yield data, base, key, readonly, tmp_path
    server.shutdown()


def post(base, key, body, protocol="1"):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if protocol:
        headers["X-Laris-Protocol"] = protocol
    request = urllib.request.Request(base + "/laris/embed", json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_the_route_follows_the_p1_rules(stack):
    _, base, key, readonly, _ = stack
    status, text = post(base, key, {"input": ["perovskite solar", "battery"]})
    reply = EmbedResponse(**json.loads(text))
    assert status == 200 and [d.index for d in reply.data] == [0, 1]
    assert reply.data[0].embedding[0] == 1.0 and reply.data[0].embedding[1] == 1.0
    assert post(base, key, {"input": "one text"})[0] == 200
    assert post(base, key, {"input": ["a"]}, protocol="")[0] == 426
    assert post(base, "wrong", {"input": ["a"]})[0] == 401
    assert post(base, readonly, {"input": ["a"]})[0] == 403  # a role without `embed`
    assert post(base, key, {"input": 5})[0] == 400
    assert post(base, key, {})[0] == 400


def left(base, key):
    request = urllib.request.Request(
        base + "/laris/account", headers={"Authorization": f"Bearer {key}", "X-Laris-Protocol": "1"}
    )
    return json.loads(urllib.request.urlopen(request, timeout=10).read())["tokens_left"]


def test_embedding_is_metered_and_no_text_is_stored(stack):
    data, base, key, _, tmp_path = stack
    before = left(base, key)
    secret = "ZEBRA-9931-confidential-passage about perovskite"
    assert post(base, key, {"input": [secret]})[0] == 200
    assert left(base, key) < before  # the request counted against the quota
    for path in Path(tmp_path / "srv").rglob("*"):
        if path.is_file():
            assert b"ZEBRA-9931" not in path.read_bytes(), path.name  # database, WAL and logs


def test_dense_and_hybrid_search_work_through_the_server(stack, tmp_path):
    _, base, _, _, _ = stack
    embedder = ServerEmbedder(base, "m", "LARIS_TEST_KEY")
    service = SearchService(Workspace(tmp_path / "ws"), embedder)
    service.ingest(
        chunks_from_text("solar.txt", "Perovskite solar cells reach high efficiency over silicon.")
        + chunks_from_text("bat.txt", "Battery electrodes and lithium cycling stability.")
        + chunks_from_text("quant.txt", "Quantum error correction and quantum gates.")
    )
    meta = service.build_dense_index()
    assert meta["count"] == 3 and meta["embedder"] == "server"
    dense = service.search("perovskite solar", mode="dense", top_k=1)
    assert dense["hits"][0]["source"] == "solar.txt"
    hybrid = service.search("quantum", mode="hybrid", top_k=1)
    assert hybrid["hits"][0]["source"] == "quant.txt"
    assert service.status()["model_configured"] is True


def test_the_client_has_no_encoder_of_its_own(tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.ingest(chunks_from_text("a.txt", "perovskite solar"))
    with pytest.raises(ServiceError, match="server"):
        service.build_dense_index()
    with pytest.raises(ServiceError, match="QA model"):
        service.answer("what?")
    assert not hasattr(service, "checkpoint")


def test_the_embedder_uses_the_key_that_login_saved(tmp_path, monkeypatch):
    import argparse
    import json

    from cli.common import load_runtime, make_service

    account = tmp_path / "settings.json"
    account.write_text(json.dumps({"api_key": "lk_saved_by_login"}), encoding="utf-8")
    monkeypatch.setenv("LARIS_APP__ACCOUNT_FILE", str(account))
    monkeypatch.setenv("LARIS_MODEL_API__BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("LARIS_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    runtime = load_runtime()
    service = make_service(argparse.Namespace(), runtime)
    assert service.embedder.api_key == "lk_saved_by_login"
    monkeypatch.setenv("LARIS_API_KEY", "lk_from_environment")
    assert make_service(argparse.Namespace(), load_runtime()).embedder.api_key == (
        "lk_from_environment"
    )


def test_http_failures_carry_the_servers_message():
    import io
    import urllib.error

    from laris.protocol.types import http_failure

    def failure(code, body):
        return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body))

    flat = http_failure(failure(400, b'{"error": "no embedding model loaded"}'))
    assert str(flat) == "model API returned HTTP 400: no embedding model loaded"
    nested = http_failure(failure(502, b'{"error": {"message": "a\\nb  c"}}'))
    assert str(nested) == "model API returned HTTP 502: a b c"
    assert str(http_failure(failure(500, b"<html>"))) == "model API returned HTTP 500"
    assert "quota" in str(http_failure(failure(429, b"{}")))
