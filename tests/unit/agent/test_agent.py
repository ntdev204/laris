"""Agent runtime: tool validation, sandbox, loop invariants, offline planner, HTTP provider."""

import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.loop import AgentSession
from laris.client.agent.provider import (
    AssistantTurn,
    ChatProvider,
    HttpChatProvider,
    OfflinePlanner,
    ProviderError,
    ToolCall,
)
from laris.client.agent.tools import Sandbox, ToolExecutionError, ToolRegistry, ToolSpec, schema
from laris.client.application.service import SearchService
from laris.client.application.workspace import Workspace, chunks_from_text
from laris.shared.harness.runtime import HarnessRuntime

RT = HarnessRuntime()
MAX_STEPS = RT.config.agent.max_steps


@pytest.fixture
def env(tmp_path):
    service = SearchService(Workspace(tmp_path / "ws"))
    service.workspace.add(
        chunks_from_text("solar.txt", "Perovskite solar cells reach 25% efficiency.")
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("hello from a file", encoding="utf-8")
    sandbox = Sandbox([tmp_path / "docs"], tmp_path / "out")
    return service, sandbox, tmp_path


class Scripted(ChatProvider):
    def __init__(self, turns):
        self.turns = list(turns)

    def chat(self, messages, tools):
        return self.turns.pop(0)


def test_argument_validation_and_unknown_tool(env):
    registry = build_registry(env[0], env[1], RT)
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("read_file", {})
    assert exc.value.code == "invalid_arguments"
    with pytest.raises(ToolExecutionError):
        registry.call("search_corpus", {"query": "x", "top_k": True})
    with pytest.raises(ToolExecutionError):
        registry.call("search_corpus", {"query": "x", "extra": 1})
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("nope", {})
    assert exc.value.code == "unknown_tool"


def test_sandbox_blocks_reads_and_writes_outside(env):
    service, sandbox, tmp = env
    registry = build_registry(service, sandbox, RT)
    assert (
        registry.call("read_file", {"path": str(tmp / "docs" / "note.txt")})["text"]
        == "hello from a file"
    )
    for bad in ("/etc/passwd", str(tmp / "ws" / "chunks.jsonl"), str(tmp / "docs" / ".." / "ws")):
        with pytest.raises(ToolExecutionError) as exc:
            registry.call("read_file", {"path": bad})
        assert exc.value.code == "outside_sandbox"
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("write_file", {"path": "../escape.txt", "content": "x"})
    assert exc.value.code == "outside_sandbox"
    registry.call("write_file", {"path": "a/report.md", "content": "ok"})
    assert (tmp / "out" / "a" / "report.md").read_text() == "ok"
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("write_file", {"path": "a/report.md", "content": "again"})
    assert exc.value.code == "exists"


def test_tool_timeout_and_exception_mapping():
    registry = ToolRegistry()
    registry.register(ToolSpec("slow", "d", schema({}), lambda a: time.sleep(2), timeout_s=0.1))
    registry.register(ToolSpec("boom", "d", schema({}), lambda a: 1 / 0))
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("slow", {})
    assert exc.value.code == "timeout"
    with pytest.raises(ToolExecutionError) as exc:
        registry.call("boom", {})
    assert exc.value.code == "tool_failed"


def test_loop_denies_writes_without_approval_and_allows_with(env):
    service, sandbox, tmp = env
    write = ToolCall("c1", "write_file", {"path": "x.txt", "content": "hi"})
    denied = AgentSession(
        Scripted([AssistantTurn(None, [write]), AssistantTurn("done")]),
        build_registry(service, sandbox, RT),
        RT,
    ).run("write")
    assert "approval_denied" in json.dumps(denied.steps[0]["result"])
    assert not (tmp / "out" / "x.txt").exists()
    allowed = AgentSession(
        Scripted([AssistantTurn(None, [write]), AssistantTurn("done")]),
        build_registry(service, sandbox, RT),
        RT,
        approve=lambda name, args: True,
    ).run("write")
    assert allowed.status == "completed" and (tmp / "out" / "x.txt").exists()


def test_identical_call_twice_halts(env):
    call = ToolCall("c", "corpus_status", {})
    result = AgentSession(
        Scripted([AssistantTurn(None, [call]), AssistantTurn(None, [call])]),
        build_registry(env[0], env[1], RT),
        RT,
    ).run("loop")
    assert result.status == "cyclic"


def test_step_ceiling_is_ten(env):
    calls = [
        AssistantTurn(None, [ToolCall(f"c{i}", "list_files", {"limit": i + 1})]) for i in range(30)
    ]
    result = AgentSession(Scripted(calls), build_registry(env[0], env[1], RT), RT).run("go")
    assert result.status == "max_steps" and len(result.steps) == MAX_STEPS


def test_offline_planner_reads_searches_and_quotes(env):
    service, sandbox, tmp = env
    planner = OfflinePlanner(RT.strings)
    session = AgentSession(planner, build_registry(service, sandbox, RT), RT, log_dir=tmp / "log")
    result = session.run(f"perovskite efficiency, see {tmp / 'docs' / 'note.txt'}")
    assert result.status == "completed"
    assert [s["tool"] for s in result.steps] == ["read_file", "search_corpus"]
    assert "solar.txt" in result.answer and "hello from a file" in result.answer
    assert (
        result.log_path and json.loads(open(result.log_path).readlines()[-1])["role"] == "assistant"
    )


def test_http_provider_speaks_openai_chat_contract():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "type": "function",
                                    "function": {"name": "corpus_status", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        provider = HttpChatProvider(f"http://127.0.0.1:{server.server_port}/v1", "core")
        turn = provider.chat([{"role": "user", "content": "hi"}], [{"type": "function"}])
        assert turn.tool_calls[0].name == "corpus_status" and seen["body"]["model"] == "core"
    finally:
        server.shutdown()
    with pytest.raises(ProviderError):
        HttpChatProvider("http://127.0.0.1:1/v1", "core", timeout_s=1).chat([], [])


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_ocr_reads_rendered_text():
    import io

    from PIL import Image, ImageDraw, ImageFont

    from laris.client.application.ocr import ocr_image_bytes

    image = Image.new("RGB", (700, 90), "white")
    ImageDraw.Draw(image).text(
        (10, 20),
        "Accuracy reached 76.3 percent",
        font=ImageFont.load_default(size=32),
        fill="black",
    )
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    assert "Accuracy" in ocr_image_bytes(buffer.getvalue(), RT.config.app.ocr_lang)
