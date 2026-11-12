"""T56: the FastAPI server for P1 validates bodies, checks the protocol, survives slow clients."""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from laris.protocol import AssistantTurn, ChatProvider, ProviderError, decode_events
from laris.server.api import ApiServer, create_app
from laris.server.gateway import PolicyGateway
from laris.server.serving.auth import KeyRing
from laris.server.serving.service import ModelService
from laris.shared.harness.runtime import HarnessRuntime

ROOT = Path(__file__).resolve().parents[3]
KEY = "p1-test-key-1"
BODY = {
    "messages": [{"role": "user", "content": "Is perovskite stable?"}],
    "laris": {"kind": "turn", "session_id": "abc123", "task": "perovskite"},
}


class Model(ChatProvider):
    name = "scripted"

    def __init__(self):
        self.delay = 0.0
        self.fail = False
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def chat(self, messages, tools):
        return AssistantTurn("Perovskite is stable [nguồn #1].")

    def stream(self, messages, tools):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            yield {"type": "text", "delta": "Perovskite "}
            if self.fail:
                raise ProviderError("model died")
            time.sleep(self.delay)
            yield from super().stream(messages, tools)
        finally:
            with self.lock:
                self.active -= 1


@pytest.fixture
def api():
    runtime = HarnessRuntime.load(ROOT)
    model = Model()
    gateway = PolicyGateway(runtime, model, "laris-test")
    service = ModelService(model, "laris-test", None, KeyRing([KEY]), gateway)
    made = []

    def start(max_body=1_000_000, body_timeout=30.0):
        app = create_app(service, max_body, body_timeout)
        server = ApiServer(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append(server)
        return server

    yield start, model
    for server in made:
        server.shutdown()


def raw(port, request: bytes, wait=5.0) -> bytes:
    """Send bytes as they are and read the whole answer."""
    with socket.create_connection(("127.0.0.1", port), timeout=wait) as sock:
        sock.sendall(request)
        data = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        return data


def status_of(answer: bytes) -> int:
    return int(answer.split(b" ", 2)[1])


def post(port, path, body, headers=None, key=KEY):
    head = {"Content-Type": "application/json", "X-Laris-Protocol": "1"}
    if key:
        head["Authorization"] = f"Bearer {key}"
    head.update(headers or {})
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data, head)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_missing_wrong_and_unknown_keys_and_routes(api):
    start, _ = api
    port = start().server_port
    assert post(port, "/v1/laris/chat", BODY, key=None)[0] == 401
    assert post(port, "/v1/laris/chat", BODY, key="wrong")[0] == 401
    assert post(port, "/v1/nothing", BODY, key=None)[0] == 401  # unknown route reveals nothing
    assert post(port, "/v1/nothing", BODY)[0] == 404
    assert post(port, "/v1/laris/chat", BODY)[0] == 200


def test_bodies_are_validated_before_any_work(api):
    start, model = api
    port = start(max_body=2000).server_port
    assert post(port, "/v1/laris/chat", b"{not json")[0] == 400
    assert post(port, "/v1/laris/chat", b"[1]")[0] == 400
    assert post(port, "/v1/laris/chat", {"messages": "no"})[0] == 400
    assert post(port, "/v1/laris/chat", {"messages": [], "tools": "x"})[0] == 400
    big = {"messages": [{"role": "user", "content": "x" * 5000}]}
    assert post(port, "/v1/laris/chat", big)[0] == 413
    assert model.peak == 0  # no request reached the model


def test_content_length_must_be_present_and_sane(api):
    start, _ = api
    port = start(max_body=2000).server_port
    head = (
        f"POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {KEY}\r\n"
        "X-Laris-Protocol: 1\r\nContent-Type: application/json\r\n"
    )
    chunked = head + "Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
    assert status_of(raw(port, chunked.encode())) == 411
    negative = head + "Content-Length: -5\r\n\r\n{}"
    assert status_of(raw(port, negative.encode())) == 400
    junk = head + "Content-Length: abc\r\n\r\n{}"
    assert status_of(raw(port, junk.encode())) in (400, 413)
    huge = head + "Content-Length: 99999999\r\n\r\n"
    assert status_of(raw(port, huge.encode())) == 413  # refused before the body is read


def test_protocol_version_mismatch_is_refused_clearly(api):
    start, _ = api
    port = start().server_port
    status, text = post(port, "/v1/laris/chat", BODY, {"X-Laris-Protocol": "99"})
    assert status == 426 and "99" in text and "Update the laris client" in text
    no_header = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/laris/account", headers={"Authorization": f"Bearer {KEY}"}
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(no_header, timeout=5)
    assert err.value.code == 426
    ok = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/laris/account",
        headers={"Authorization": f"Bearer {KEY}", "X-Laris-Protocol": "1"},
    )
    assert urllib.request.urlopen(ok, timeout=5).status == 200


def test_a_failure_mid_stream_is_an_error_event_then_done(api):
    start, model = api
    model.fail = True
    # before anything is sent the failure is an ordinary HTTP error (the gateway holds text back)
    assert post(start().server_port, "/v1/laris/chat", {**BODY, "stream": True})[0] == 502
    # without a gateway the first chunk goes out at once, so the failure arrives inside the stream
    bare = ModelService(model, "laris-test", None, KeyRing([KEY]))
    server = ApiServer(create_app(bare, 1_000_000), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = {"messages": [{"role": "user", "content": "hi"}], "stream": True}
        status, text = post(server.server_port, "/v1/chat/completions", body)
        assert status == 200 and text.rstrip().endswith("data: [DONE]")
        events = list(decode_events(text.splitlines()))
        assert events[0]["choices"][0]["delta"]["content"] == "Perovskite "
        assert "model died" in events[-1]["error"]["message"]
    finally:
        server.shutdown()


def test_a_slow_client_does_not_block_others(api):
    start, _ = api
    port = start(body_timeout=30.0).server_port
    stalled = socket.create_connection(("127.0.0.1", port))
    stalled.sendall(
        (
            f"POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {KEY}\r\n"
            "X-Laris-Protocol: 1\r\nContent-Length: 500\r\n\r\n{"
        ).encode()
    )  # promises 500 bytes, sends one, then stalls
    try:
        started = time.monotonic()
        assert post(port, "/v1/laris/chat", BODY)[0] == 200
        assert time.monotonic() - started < 5
    finally:
        stalled.close()


def test_a_body_that_never_finishes_times_out(api):
    start, _ = api
    port = start(body_timeout=0.5).server_port
    request = (
        f"POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {KEY}\r\n"
        "X-Laris-Protocol: 1\r\nContent-Length: 500\r\n\r\n{"
    ).encode()
    assert status_of(raw(port, request, wait=5.0)) == 408


def test_the_brain_lock_is_not_held_during_a_model_call(api):
    start, model = api
    port = start().server_port
    model.delay = 1.0
    started = time.monotonic()
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(post(port, "/v1/laris/chat", BODY)[0]))
        for _ in range(3)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    assert results == [200, 200, 200]
    assert time.monotonic() - started < 2.5  # three slow model calls overlapped
    assert model.peak >= 2
