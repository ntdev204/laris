"""T57: address rules behind a proxy: X-Forwarded-For counts only from trusted proxies."""

import threading
import urllib.error
import urllib.request

import pytest

from laris.protocol import AssistantTurn, ChatProvider
from laris.server.serverdata import ServerData, netcheck
from laris.server.serving.model_server import build_server
from laris.server.serving.service import ModelService
from laris.shared.config.runtime_schemas import ServingConfig

NETS = netcheck.networks(["10.0.0.0/8", "127.0.0.1"])


def test_real_address_rules():
    real = netcheck.real_address
    assert real("203.0.113.5", ["10.1.1.1"], NETS) == "203.0.113.5"  # untrusted peer
    assert real("10.0.0.2", ["198.51.100.7"], NETS) == "198.51.100.7"  # trusted peer: believed
    assert real("10.0.0.2", [], NETS) == "10.0.0.2"  # no header: the proxy itself
    # the client forged a first hop; the proxy appended the real address on the right
    assert real("10.0.0.2", ["10.9.9.9, 198.51.100.7"], NETS) == "198.51.100.7"
    assert real("10.0.0.2", ["198.51.100.7, 10.0.0.9"], NETS) == "198.51.100.7"  # chained
    assert real("10.0.0.2", ["198.51.100.7", "10.0.0.9"], NETS) == "198.51.100.7"  # 2 header lines
    assert real("10.0.0.2", ["garbage"], NETS) is None  # unparsable: no rule can match
    assert real("10.0.0.2", ["198.51.100.7"], []) == "10.0.0.2"  # no trusted proxies configured
    assert real("::ffff:127.0.0.1", ["198.51.100.7"], NETS) == "198.51.100.7"  # mapped IPv4
    assert real(None, ["1.2.3.4"], NETS) is None
    with pytest.raises(ValueError):
        netcheck.networks(["not-an-address"])


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


def status(base, key, forwarded=None):
    headers = {"Authorization": f"Bearer {key}"}
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    request = urllib.request.Request(base + "/models", headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_a_trusted_proxy_lets_the_real_client_address_decide(behind):
    data, base = behind(["127.0.0.1"])  # the test client plays the proxy
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    _, local = data.keys.create("local", "user", None, allowed_ips=["@server"])
    assert status(base, office, "198.51.100.7") == 200
    assert status(base, office, "203.0.113.9") == 401  # a client outside the allowed range
    assert status(base, office) == 401  # no header: the proxy's own (loopback) address
    assert status(base, local, "198.51.100.7") == 401  # a remote client is not "the server"
    assert status(base, local) == 200  # a request made by the machine itself


def test_forged_headers_do_not_help(behind):
    data, base = behind(["127.0.0.1"])
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    _, local = data.keys.create("local", "user", None, allowed_ips=["@server"])
    # the client wrote the first hop; the proxy added the true address after it
    assert status(base, office, "198.51.100.7, 203.0.113.9") == 401
    assert status(base, local, "127.0.0.1, 203.0.113.9") == 401
    assert status(base, office, "not-an-ip") == 401


def test_without_trusted_proxies_the_header_is_ignored(behind):
    data, base = behind([])
    _, office = data.keys.create("office", "user", None, allowed_ips=["198.51.100.0/24"])
    _, local = data.keys.create("local", "user", None, allowed_ips=["@server"])
    assert status(base, office, "198.51.100.7") == 401  # a forged header proves nothing
    assert status(base, local, "198.51.100.7") == 200  # the peer is loopback: it is the server
    assert status(base, local, "203.0.113.9") == 200
