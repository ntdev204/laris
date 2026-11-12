"""Hostile network clients against the API: slow, oversized, malformed and forged requests.

The API sits behind Caddy (TLS, limits, timeouts), but every test here talks to the API directly:
each control must also hold when the proxy is not in the way (SR-S4)."""

import json
import select
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from laris.protocol import AssistantTurn, ChatProvider
from laris.server.serverdata import ServerData
from laris.server.serving.model_server import build_server
from laris.server.serving.service import ModelService
from laris.shared.config.runtime_schemas import ServingConfig
from tests.security.conftest import BODY, KEY


def raw(port, request: bytes, wait=5.0) -> bytes:
    """Send bytes as they are and read the answer, returning as soon as one response is complete
    (or the server closes or resets the connection, which counts as a refusal)."""
    data = b""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=wait) as sock:
            sock.sendall(request)
            while True:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                data += chunk
                top, sep, body = data.partition(b"\r\n\r\n")
                if sep:
                    lowered = top.lower()
                    at = lowered.find(b"content-length:")
                    if at >= 0:
                        size = int(lowered[at + 15 :].split(b"\r\n", 1)[0])
                        if len(body) >= size:
                            break
    except (ConnectionError, socket.timeout):
        pass
    return data


def status_of(answer: bytes) -> int:
    return int(answer.split(b" ", 2)[1]) if answer.startswith(b"HTTP/") else 0


def head(length, extra="") -> str:
    return (
        "POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\n"
        f"Authorization: Bearer {KEY}\r\nX-Laris-Protocol: 1\r\n{extra}"
        f"Content-Length: {length}\r\n\r\n"
    )


def post(port, body: bytes):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/laris/chat",
        body,
        {"Content-Type": "application/json", "X-Laris-Protocol": "1",
         "Authorization": f"Bearer {KEY}"},
    )  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def still_serves(port):
    assert post(port, json.dumps(BODY).encode()) == 200


# -- slow clients ------------------------------------------------------------------------------
def test_many_stalled_connections_do_not_starve_a_real_request(api):
    port = api(body_timeout=30.0).server_port
    stalled = []
    try:
        for i in range(
            40
        ):  # half a request line, a header that never ends, a body that never comes
            sock = socket.create_connection(("127.0.0.1", port))
            sock.sendall([b"POST /v1/laris/ch", b"POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\nX-A: ",
                          head(500).encode() + b"{"][i % 3])  # fmt: skip
            stalled.append(sock)
        started = time.monotonic()
        still_serves(port)
        assert time.monotonic() - started < 5
    finally:
        for sock in stalled:
            sock.close()


def test_a_body_sent_one_byte_at_a_time_hits_the_deadline(api):
    """Each byte arrives in time, the body as a whole does not: the deadline is for the body."""
    port = api(body_timeout=1.0).server_port
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    answer, started = b"", time.monotonic()
    try:
        sock.sendall(head(400).encode())
        while time.monotonic() - started < 6 and not answer:
            sock.sendall(b" ")
            readable, _, _ = select.select([sock], [], [], 0.1)
            if readable:
                answer = sock.recv(65536)
    except OSError:
        pass  # closed on us: the server gave up
    finally:
        sock.close()
    assert time.monotonic() - started < 5, "the server let a trickling body run on"
    assert not answer or status_of(answer) == 408
    still_serves(port)


# -- oversized bodies -------------------------------------------------------------------------
def test_an_oversized_declared_body_is_refused_before_it_is_read(api):
    port = api(max_body=2_000).server_port
    started = time.monotonic()
    answer = raw(port, head(10**12).encode())  # promises a terabyte, sends nothing
    assert status_of(answer) == 413 and time.monotonic() - started < 3
    still_serves(port)


def test_a_body_larger_than_it_declared_is_not_taken_whole(api):
    port = api(max_body=2_000).server_port
    body = json.dumps({"messages": [], "pad": "x" * 50_000}).encode()
    answer = raw(port, head(1_900).encode() + body)  # says 1900 bytes, sends 50 000
    assert status_of(answer) in (400, 413, 0)  # refused or cut off; never a 200 or a 500
    still_serves(port)


def test_a_body_just_over_the_limit_is_refused_and_one_at_it_is_not_a_413(api):
    port = api(max_body=2_000).server_port
    assert post(port, b'{"x":"' + b"a" * 2_100 + b'"}') == 413
    assert post(port, b'{"x":"' + b"a" * 100 + b'"}') != 413


@pytest.mark.parametrize(
    "length,expected",
    [
        ("-1", 400),
        ("abc", 400),
        ("1e3", 400),
        ("0x10", 400),
        ("", 400),
        ("99999999999999999999", 413),
    ],
)
def test_a_hostile_content_length_is_a_clean_4xx(api, length, expected):
    port = api(max_body=2_000).server_port
    answer = raw(port, head(length).encode() + b"{}")
    assert status_of(answer) in (expected, 400, 0)
    still_serves(port)


def test_a_chunked_body_without_a_length_is_refused(api):
    port = api().server_port
    request = (
        "POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\n"
        f"Authorization: Bearer {KEY}\r\nX-Laris-Protocol: 1\r\n"
        'Transfer-Encoding: chunked\r\n\r\n5\r\n{"a":\r\n0\r\n\r\n'
    ).encode()
    assert status_of(raw(port, request)) in (400, 411)
    still_serves(port)


def test_conflicting_lengths_and_chunking_cannot_smuggle_a_second_request(api):
    """A request that carries both headers, or two lengths, must not be read as two requests."""
    port = api().server_port
    smuggled = b"POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\n\r\n"
    both = head(0, "Transfer-Encoding: chunked\r\n").encode() + b"0\r\n\r\n" + smuggled
    twice = head(2, "Content-Length: 40\r\n").encode() + b"{}" + smuggled
    for request in (both, twice):
        answer = raw(port, request)
        assert answer.count(b"HTTP/1.1 ") <= 1 or status_of(answer) in (400, 411)
    still_serves(port)


def test_a_huge_header_is_refused(api):
    port = api().server_port
    answer = raw(port, head(2, "X-Big: " + "a" * 200_000 + "\r\n").encode() + b"{}")
    assert status_of(answer) in (400, 431, 0)
    still_serves(port)


# -- malformed bodies -------------------------------------------------------------------------
HOSTILE_BODIES = {
    "not json": b"{not json",
    "array": b"[1, 2, 3]",
    "scalar": b"42",
    "null": b"null",
    "nul bytes": b'{"a":"\x00\x00"}',
    "invalid utf-8": b'{"a":"\xff\xfe\xfd"}',
    "lone surrogate": b'{"a":"\\ud800"}',
    "deep nesting": b"[" * 200_000 + b"]" * 200_000,
    "deep objects": b'{"a":' * 50_000 + b"1" + b"}" * 50_000,
    "huge exponent": b'{"a":1e999999999}',
    "huge integer": b'{"a":' + b"9" * 6_000 + b"}",
    "nan": b'{"a":NaN}',
    "duplicate keys": b'{"messages":[],"messages":"x"}',
    "messages not a list": b'{"messages":"x"}',
    "messages hold junk": b'{"messages":[1,null,"x",{"role":5}]}',
    "empty": b"",
}


@pytest.mark.parametrize("name", sorted(HOSTILE_BODIES))
def test_malformed_bodies_get_a_4xx_never_a_crash(api, name):
    port = api(max_body=2_000_000).server_port
    code = post(port, HOSTILE_BODIES[name])
    assert 400 <= code < 500 or (name == "empty" and code < 500), (name, code)
    still_serves(port)


def test_the_key_is_not_taken_from_the_query_string_or_a_second_header(api):
    port = api().server_port
    lines = (
        f"POST /v1/laris/chat?key={KEY} HTTP/1.1\r\nHost: x\r\n",
        f"POST /v1/laris/chat?api_key={KEY} HTTP/1.1\r\nHost: x\r\nX-Api-Key: {KEY}\r\n",
    )
    for line in lines:
        request = line + "X-Laris-Protocol: 1\r\nContent-Length: 2\r\n\r\n{}"
        assert status_of(raw(port, request.encode())) == 401


def test_header_injection_through_the_key_is_refused(api):
    port = api().server_port
    request = (
        "POST /v1/laris/chat HTTP/1.1\r\nHost: x\r\nX-Laris-Protocol: 1\r\n"
        "Authorization: Bearer wrong\r\n\r\n"
        f"Authorization: Bearer {KEY}\r\nContent-Length: 2\r\n\r\n{{}}"
    )
    assert status_of(raw(port, request.encode())) in (400, 401, 411)


# -- forged forwarding headers ---------------------------------------------------------------
class Quiet(ChatProvider):
    name = "quiet"

    def chat(self, messages, tools):
        return AssistantTurn("x")


@pytest.fixture
def behind(tmp_path):
    made = []

    def start(trusted):
        cfg = ServingConfig(data_dir=str(tmp_path / f"s{len(made)}"), cache_ttl_s=0.0)
        data = ServerData(cfg, tmp_path, lambda t: t)
        service = ModelService(Quiet(), "m", None, None, None, auth=data.auth, meter=data.usage)
        server = build_server(service, "127.0.0.1", 0, 1_000_000, trusted)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append(server)
        return data, f"http://127.0.0.1:{server.server_port}/v1"

    yield start
    for server in made:
        server.shutdown()


def models_status(base, key, headers=None):
    request = urllib.request.Request(
        base + "/models", headers={"Authorization": f"Bearer {key}", **(headers or {})}
    )
    try:
        return urllib.request.urlopen(request, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


FORGERIES = [
    {"X-Forwarded-For": "198.51.100.7"},
    {"X-Forwarded-For": "198.51.100.7, 198.51.100.8, 198.51.100.9"},
    {"X-Forwarded-For": "[::ffff:198.51.100.7]"},
    {"X-Forwarded-For": "198.51.100.7:443"},
    {"X-Forwarded-For": "198.51.100.7\t"},
    {"Forwarded": "for=198.51.100.7"},
    {"X-Real-IP": "198.51.100.7"},
    {"X-Client-IP": "198.51.100.7"},
    {"True-Client-IP": "198.51.100.7"},
    {"CF-Connecting-IP": "198.51.100.7"},
    {"X-Originating-IP": "198.51.100.7"},
    {"X-Forwarded-For": "198.51.100.7", "X-Forwarded-Host": "198.51.100.7"},
]


@pytest.mark.parametrize(
    "forged", FORGERIES, ids=lambda h: next(iter(h)) + "=" + next(iter(h.values()))
)
def test_no_forwarding_header_moves_a_client_into_an_allowed_range(behind, forged):
    """Without a trusted proxy a key limited to an office range never accepts a header's word."""
    data, base = behind([])
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    assert models_status(base, office, forged) == 401


@pytest.mark.parametrize(
    "forged", FORGERIES, ids=lambda h: next(iter(h)) + "=" + next(iter(h.values()))
)
def test_a_trusted_proxy_still_believes_only_x_forwarded_for_from_the_right(behind, forged):
    """Even behind a trusted proxy, only a hop the proxy itself wrote counts, and only in X-F-F."""
    data, base = behind(["127.0.0.1"])
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    # the proxy appends the true peer (203.0.113.9) after whatever the client wrote
    named = {k: v + ", 203.0.113.9" if k == "X-Forwarded-For" else v for k, v in forged.items()}
    assert models_status(base, office, named) == 401


def test_a_hundred_forged_hops_do_not_hide_the_real_client(behind):
    data, base = behind(["127.0.0.1"])
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    forged = ", ".join(["198.51.100.7"] * 100) + ", 203.0.113.9"
    assert models_status(base, office, {"X-Forwarded-For": forged}) == 401
    assert models_status(base, office, {"X-Forwarded-For": "198.51.100.7"}) == 200
