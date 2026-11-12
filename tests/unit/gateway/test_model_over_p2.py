"""T55: the server reaches the model only over P2; no model code lives in the server process."""

import json
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from laris.protocol import AssistantTurn, ChatProvider
from laris.server.gateway import PolicyGateway
from laris.server.serving.auth import KeyRing
from laris.server.serving.limits import LimitedProvider
from laris.server.serving.model_server import ModelService, build_server
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.http_provider import HttpChatProvider, HttpEmbedder

ROOT = Path(__file__).resolve().parents[3]
KEY = "p2-test-key-1"


class Stub(BaseHTTPRequestHandler):
    """Another OpenAI-compatible runtime: it knows nothing of LARIS."""

    seen = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append((self.path, body))
        if self.path == "/v1/embeddings":
            data = {
                "data": [
                    {"index": i, "embedding": [float(len(t))]} for i, t in enumerate(body["input"])
                ]
            }
        elif body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"choices": [{"index": 0, "delta": {"content": "Perovskite is stable."}}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n")
            return
        else:
            data = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        return


@pytest.fixture
def other_runtime():
    Stub.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_gateway_works_against_any_openai_compatible_url(other_runtime):
    runtime = HarnessRuntime.load(ROOT)
    backend = LimitedProvider(HttpChatProvider(other_runtime, "anything"), 2)
    gateway = PolicyGateway(runtime, backend, "laris-test")
    embedder = HttpEmbedder(other_runtime)
    service = ModelService(backend, "laris-test", embedder, KeyRing([KEY]), gateway)
    srv = build_server(service, "127.0.0.1", 0, runtime.config.serving.max_body_bytes)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        head = {
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "X-Laris-Protocol": "1",
        }
        body = {"messages": [{"role": "user", "content": "hi"}], "stream": True,
                "laris": {"kind": "turn", "session_id": "abc123"}}  # fmt: skip
        request = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_port}/v1/laris/chat", json.dumps(body).encode(), head
        )
        text = urllib.request.urlopen(request, timeout=20).read().decode()
        assert "Perovskite is stable." in text
        path, sent = Stub.seen[0]
        assert path == "/v1/chat/completions" and sent["messages"][0]["role"] == "system"
        assert embedder(["ab", "abcd"]) == [[2.0], [4.0]]
    finally:
        srv.shutdown()


def test_concurrency_towards_the_model_is_bounded():
    gate, running, peak = threading.Event(), [0], [0]
    lock = threading.Lock()

    class Slow(ChatProvider):
        def chat(self, messages, tools):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            gate.wait(5)
            with lock:
                running[0] -= 1
            return AssistantTurn("x")

    limited = LimitedProvider(Slow(), 2)
    threads = [threading.Thread(target=limited.chat, args=([], [])) for _ in range(6)]
    for th in threads:
        th.start()
    gate.wait(0.3)
    assert running[0] == 2  # the other four wait for a slot
    gate.set()
    for th in threads:
        th.join(timeout=5)
    assert peak[0] == 2 and limited.peak == 2 and limited.in_flight == 0


def test_the_server_process_loads_no_model_code():
    code = (
        "import sys, laris.server.gateway, laris.server.serving.model_server, "
        "laris.server.serverdata, cli.commands.model;"
        "bad = [m for m in sys.modules if m.startswith('laris.model')];"
        "print(bad)"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src")}, check=True,
    ).stdout.strip()  # fmt: skip
    assert out == "[]"
