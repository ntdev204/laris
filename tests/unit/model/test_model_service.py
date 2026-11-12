"""T53: the model block over HTTP (protocol P2) with scripted backends. No model is trained."""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

import uvicorn  # noqa: E402

from laris.client.agent.builtin_tools import build_registry  # noqa: E402
from laris.client.agent.loop import AgentSession  # noqa: E402
from laris.client.agent.provider import HttpChatProvider  # noqa: E402
from laris.client.agent.tools import Sandbox  # noqa: E402
from laris.client.application.service import SearchService  # noqa: E402
from laris.client.application.workspace import Workspace, chunks_from_text  # noqa: E402
from laris.model.app import create_app  # noqa: E402
from laris.model.service import ModelService  # noqa: E402
from laris.protocol import (  # noqa: E402
    AssistantTurn,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatProvider,
    EmbedResponse,
    ProviderError,
    StreamError,
    ToolCall,
    decode_events,
)
from laris.shared.harness.runtime import HarnessRuntime  # noqa: E402
from laris.shared.plan import PLAN_TOOL  # noqa: E402

QA = "Assumptions: none. Uncertainties: none. Next step: none. Sources: solar.txt."


class Scripted(ChatProvider):
    name = "scripted"

    def __init__(self, turns, reasoning=False, fail_after=None):
        self.turns, self.reasoning, self.fail_after = list(turns), reasoning, fail_after
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append((list(messages), list(tools)))
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        if isinstance(turn, Exception):
            raise turn
        return turn

    def stream(self, messages, tools):
        if self.reasoning:
            yield {"type": "reasoning", "delta": "private thoughts"}
        if self.fail_after is not None:
            yield {"type": "text", "delta": "partial"}
            raise ProviderError("backend died mid-stream")
        yield from super().stream(messages, tools)


class Live:
    def __init__(self, backend, embedder=None, max_body=1_000_000):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        app = create_app(ModelService(backend, "scripted-model", embedder), max_body)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="critical")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def call(self, path, body=None, method=None):
        data = (
            None
            if body is None
            else (body if isinstance(body, bytes) else json.dumps(body).encode())
        )
        request = urllib.request.Request(self.base + path, data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def live():
    made = []

    def start(backend, embedder=None, max_body=1_000_000):
        item = Live(backend, embedder, max_body)
        made.append(item)
        return item

    yield start
    for item in made:
        item.stop()


def embed(texts):
    return [[float(len(t)), 1.0, 0.0] for t in texts]


HELLO = {"messages": [{"role": "user", "content": "hi"}]}


def test_health_and_models_reveal_nothing_but_the_model(live):
    server = live(Scripted([AssistantTurn("x")]), embed)
    status, body = server.call("/health")
    assert status == 200 and json.loads(body) == {
        "status": "ok", "model": "scripted-model", "backend": "scripted", "embeddings": True,
    }  # fmt: skip
    assert json.loads(server.call("/v1/models")[1])["data"][0]["id"] == "scripted-model"
    assert server.call("/openapi.json")[0] == 404  # no interactive docs on the internal service
    assert server.call("/nothing")[0] == 404


def test_completion_matches_the_p2_schema_for_text_and_tool_calls(live):
    call = ToolCall("c1", "search_corpus", {"query": "x"})
    server = live(Scripted([AssistantTurn(None, [call]), AssistantTurn("done")]))
    first = ChatCompletionResponse(**json.loads(server.call("/v1/chat/completions", HELLO)[1]))
    assert first.choices[0].finish_reason == "tool_calls"
    function = first.choices[0].message.tool_calls[0].function
    assert function.name == "search_corpus" and json.loads(function.arguments) == {"query": "x"}
    second = ChatCompletionResponse(**json.loads(server.call("/v1/chat/completions", HELLO)[1]))
    assert second.choices[0].message.content == "done" and second.choices[0].finish_reason == "stop"


def test_stream_chunks_match_the_schema_and_end_with_done(live):
    call = ToolCall("c1", "search_corpus", {"query": "x"})
    server = live(Scripted([AssistantTurn("hello", [call])], reasoning=True))
    status, raw = server.call("/v1/chat/completions", {**HELLO, "stream": True})
    assert status == 200 and raw.decode().rstrip().endswith("data: [DONE]")
    chunks = [ChatCompletionChunk(**c) for c in decode_events(raw.decode().splitlines())]
    deltas = [c.choices[0].delta for c in chunks if c.choices]
    assert any(d.reasoning_content == "private thoughts" for d in deltas)
    assert "".join(d.content or "" for d in deltas) == "hello"
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
    assert any(d.tool_calls and d.tool_calls[0].function.name == "search_corpus" for d in deltas)


def test_a_failure_before_the_stream_is_an_http_error_after_it_an_error_event(live):
    before = live(Scripted([ProviderError("model unavailable")]))
    status, body = before.call("/v1/chat/completions", {**HELLO, "stream": True})
    assert status == 502 and "model unavailable" in json.loads(body)["error"]
    assert before.call("/v1/chat/completions", HELLO)[0] == 502
    mid = live(Scripted([AssistantTurn("x")], fail_after=1))
    status, raw = mid.call("/v1/chat/completions", {**HELLO, "stream": True})
    assert status == 200  # the response had started: the error travels inside the stream
    events = list(decode_events(raw.decode().splitlines()))
    assert events[0]["choices"][0]["delta"]["content"] == "partial"
    assert "backend died" in StreamError(**events[-1]).error["message"]
    assert raw.decode().rstrip().endswith("data: [DONE]")


def test_embeddings_follow_the_openai_shape(live):
    server = live(Scripted([AssistantTurn("x")]), embed)
    reply = EmbedResponse(**json.loads(server.call("/v1/embeddings", {"input": ["ab", "abcd"]})[1]))
    assert [d.index for d in reply.data] == [0, 1] and reply.data[1].embedding[0] == 4.0
    one = json.loads(server.call("/v1/embeddings", {"input": "abc"})[1])
    assert len(one["data"]) == 1
    none = live(Scripted([AssistantTurn("x")]))
    status, body = none.call("/v1/embeddings", {"input": ["a"]})
    assert status == 400 and "no embedding model" in json.loads(body)["error"]


def test_bad_requests_are_refused(live):
    server = live(Scripted([AssistantTurn("x")]), max_body=2000)
    assert server.call("/v1/chat/completions", b"{not json")[0] == 400
    assert server.call("/v1/chat/completions", b"[1, 2]")[0] == 400
    assert server.call("/v1/chat/completions", {"messages": "no"})[0] == 400
    big = {"messages": [{"role": "user", "content": "x" * 5000}]}
    assert server.call("/v1/chat/completions", big)[0] == 413


def test_the_service_keeps_no_state_and_knows_no_keys(live):
    backend = Scripted([AssistantTurn("x")])
    server = live(backend)
    server.call("/v1/chat/completions", HELLO)
    server.call("/v1/chat/completions", HELLO)
    assert len(backend.seen) == 2  # each request stands alone
    request = urllib.request.Request(server.base + "/v1/models")
    request.add_header("Authorization", "Bearer anything")
    assert urllib.request.urlopen(request, timeout=5).status == 200  # no auth on the internal net


# SR-H6: the model boundary holds when the model is reached over HTTP -------------------------
def _session(project, tmp_path, backend, live):
    rt = HarnessRuntime.load(project)
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(chunks_from_text("solar.txt", "Perovskite cells reach 25% efficiency."))
    registry = build_registry(service, Sandbox([project], tmp_path / "o", policy=rt.paths), rt)
    provider = HttpChatProvider(live(backend).base + "/v1", "scripted-model")
    return rt, registry, provider


def test_tool_calls_over_http_are_validated_by_the_loop(project, tmp_path, live):
    backend = Scripted([
        AssistantTurn(None, [ToolCall("a", "no_such_tool", {})]),
        AssistantTurn(None, [ToolCall("b", "search_corpus", {"bad": 1})]),
        AssistantTurn(QA),
    ])  # fmt: skip
    rt, registry, provider = _session(project, tmp_path, backend, live)
    events = list(AgentSession(provider, registry, rt).send("find cells"))
    errors = [e["result"]["error"]["code"] for e in events if e["type"] == "tool_result"]
    assert len(errors) == 2 and all(errors)
    assert events[-1]["status"] in {"completed", "unverified", "max_steps"}


def test_plan_tool_and_wire_keys_over_http(project, tmp_path, live):
    steps = [{"text": "search", "status": "in_progress"}, {"text": "answer", "status": "pending"}]
    backend = Scripted([AssistantTurn(None, [ToolCall("p", PLAN_TOOL, {"steps": steps})]),
                        AssistantTurn(QA)], reasoning=True)  # fmt: skip
    rt, registry, provider = _session(project, tmp_path, backend, live)
    session = AgentSession(provider, registry, rt)
    events = list(session.send("compare two things step by step"))
    assert any(e["type"] == "plan" for e in events)
    assert PLAN_TOOL in [t["function"]["name"] for t in backend.seen[0][1]]
    allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
    assert all(set(m) <= allowed for m in backend.seen[0][0])
    assert "private thoughts" not in json.dumps(session.messages)  # reasoning never persists


# T54: the service runs its model calls through the GPU queue ----------------------------------
def _queue(backend, embedder=None, **overrides):
    from laris.model.service import build_queue
    from laris.shared.config.runtime_schemas import ModelServiceConfig

    cfg = ModelServiceConfig(**overrides)
    return build_queue(backend, embedder, cfg)


class Live2(Live):
    def __init__(self, service, max_body=1_000_000):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server = uvicorn.Server(
            uvicorn.Config(
                create_app(service, max_body),
                host="127.0.0.1",
                port=self.port,
                log_level="critical",
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started


def test_health_reports_the_gpu_budget_and_resident_models(live):
    backend = Scripted([AssistantTurn("x")])
    queue = _queue(backend, embed, chat_vram_bytes=4096, embed_vram_bytes=2048)
    item = Live2(ModelService(backend, "scripted-model", embed, queue))
    try:
        item.call("/v1/chat/completions", HELLO)
        item.call("/v1/embeddings", {"input": ["a"]})
        gpu = json.loads(item.call("/health")[1])["gpu"]
        assert gpu["resident"] == ["chat", "embed"] and gpu["resident_bytes"] == 4096 + 2048
        assert gpu["peak_bytes"] <= gpu["budget_bytes"]
    finally:
        item.stop()
        queue.close()


def test_a_full_queue_answers_503(live):
    gate = threading.Event()

    class Slow(Scripted):
        def chat(self, messages, tools):
            gate.wait(5)
            return super().chat(messages, tools)

    backend = Slow([AssistantTurn("x")])
    queue = _queue(backend, queue_max_waiting=1)
    item = Live2(ModelService(backend, "scripted-model", None, queue))
    statuses = []
    try:
        threads = [
            threading.Thread(
                target=lambda: statuses.append(item.call("/v1/chat/completions", HELLO)[0])
            )
            for _ in range(4)
        ]
        for th in threads:
            th.start()
            time.sleep(0.2)
        gate.set()
        for th in threads:
            th.join(timeout=10)
        assert 503 in statuses and 200 in statuses
    finally:
        gate.set()
        item.stop()
        queue.close()
