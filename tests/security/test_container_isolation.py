"""A compromised container and a hostile client against the Docker deployment (SR-S4, SR-S7).

Static checks of `docker/compose.yaml` and the Dockerfiles say what an attacker who owns one
container can and cannot reach (ports, mounts, privileges, network). The tests that need Docker
run the real `caddy:2` image with the repository's Caddyfile and skip when it is not local."""

import http.server
import json
import re
import socket
import ssl
import subprocess
import threading
import time
import uuid

import pytest
import yaml

from tests.security.conftest import ROOT, docker_ready

COMPOSE = yaml.safe_load((ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8"))
CADDYFILE = (ROOT / "docker" / "Caddyfile").read_text(encoding="utf-8")
SERVICES = COMPOSE["services"]
INNER = ("api", "model", "postgres")


def mounts(service):
    return [str(v) for v in SERVICES[service].get("volumes", [])]


# -- ports -----------------------------------------------------------------------------------
def test_only_caddy_is_reachable_from_outside_and_only_on_web_ports():
    for name in INNER:
        for forbidden in ("ports", "expose"):
            assert forbidden not in SERVICES[name], f"{name} must not set {forbidden}"
    published = [str(p) for p in SERVICES["caddy"]["ports"]]
    assert len(published) == 2
    assert {p.rsplit(":", 1)[1] for p in published} == {"80", "443"}
    # no service shares a network or process space with the host
    for name, spec in SERVICES.items():
        for key in ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup_parent"):
            assert spec.get(key) in (None, "private"), f"{name}: {key}={spec.get(key)}"


def test_the_inner_services_cannot_reach_the_internet_or_the_edge():
    assert COMPOSE["networks"]["backend"]["internal"] is True
    for name in INNER:
        assert SERVICES[name]["networks"] == ["backend"], name
    assert "edge" in SERVICES["caddy"]["networks"] and "backend" in SERVICES["caddy"]["networks"]
    assert not COMPOSE["networks"]["edge"].get("internal")


# -- privileges ------------------------------------------------------------------------------
def test_no_service_is_privileged_or_holds_a_dangerous_capability():
    dangerous = {"SYS_ADMIN", "SYS_PTRACE", "SYS_MODULE", "NET_ADMIN", "NET_RAW", "DAC_READ_SEARCH",
                 "SYS_RAWIO", "SYS_BOOT", "MKNOD", "ALL"}  # fmt: skip
    for name, spec in SERVICES.items():
        assert not spec.get("privileged"), name
        assert not dangerous & set(spec.get("cap_add", [])), name
        assert not spec.get("devices"), f"{name}: raw host devices"
        assert "no-new-privileges:true" in spec["security_opt"], name
        assert spec["cap_drop"] == ["ALL"], name
        assert not any("seccomp:unconfined" in o or "apparmor" in o for o in spec["security_opt"])


def test_the_three_application_containers_have_a_read_only_root_file_system():
    for name in ("caddy", "api", "model"):
        assert SERVICES[name]["read_only"] is True, name
    # the writable places are named: tmpfs, and volumes that hold data
    assert SERVICES["api"]["tmpfs"] == ["/tmp"]


@pytest.mark.parametrize("file", ["api.Dockerfile", "model.Dockerfile"])
def test_images_do_not_run_as_root(file):
    text = (ROOT / "docker" / file).read_text(encoding="utf-8")
    users = re.findall(r"^USER\s+(\S+)", text, re.M)
    assert users and users[-1] not in ("root", "0"), users


# -- mounts ----------------------------------------------------------------------------------
def test_no_container_mounts_the_docker_socket_the_host_root_or_a_home_folder():
    for name in SERVICES:
        for volume in mounts(name):
            source = volume.split(":")[0]
            assert "docker.sock" not in volume and "/var/run" not in source, (name, volume)
            assert source not in ("/", "/etc", "/home", "/root", "/proc", "/sys", "/dev", "~"), (
                name, volume,
            )  # fmt: skip
            assert not source.startswith(("/etc", "/root", "/home", "/proc", "/sys", "/dev")), (
                name, volume,
            )  # fmt: skip


def test_every_host_folder_mount_is_read_only():
    for name in SERVICES:
        for volume in mounts(name):
            source = volume.split(":")[0]
            if source.startswith((".", "/", "$")):  # a host path, not a named volume
                assert volume.endswith(":ro"), (name, volume)


def test_policy_weights_and_configuration_cannot_be_written_by_the_containers():
    assert "../.laris:/app/.laris:ro" in mounts("api")
    assert "../LARIS.md:/app/LARIS.md:ro" in mounts("api")
    assert any(v.endswith("/models:ro") for v in mounts("model"))
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in mounts("caddy")
    # nothing but the API sees the policy, and nothing sees the project, the vault or the brain
    for name in ("caddy", "model", "postgres"):
        assert not any(".laris" in v for v in mounts(name)), name
    for name in SERVICES:
        for volume in mounts(name):
            assert not re.search(r"vault|brain|\.git|\.env|\.claude|secrets", volume.split(":")[0])


def test_the_model_container_gets_no_database_and_no_secret_of_the_api():
    assert "secrets" not in SERVICES["model"]
    assert set(SERVICES["api"]["secrets"]) == {"laris_master", "laris_database_url"}
    assert SERVICES["postgres"]["secrets"] == ["laris_postgres_password"]
    assert "caddy" not in {s for s in SERVICES["api"].get("secrets", [])}
    assert "secrets" not in SERVICES["caddy"]


def test_no_secret_value_is_in_an_environment_variable_or_the_compose_file():
    text = (ROOT / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert not re.search(r"postgres(ql)?://\S+:\S+@", text)
    for name, spec in SERVICES.items():
        for key, value in (spec.get("environment") or {}).items():
            if re.search(r"SECRET|PASSWORD|_TOKEN$|API_KEY|DATABASE_URL$", key):
                assert key.endswith("_FILE") or "/run/secrets/" in str(value), (name, key)
    for path in (
        (ROOT / "docker" / "secrets").glob("*") if (ROOT / "docker" / "secrets").exists() else []
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(path)], cwd=ROOT, check=False
        ).returncode
        assert ignored == 0, f"{path.name} is not git-ignored"


# -- the proxy's own configuration -----------------------------------------------------------
def test_the_caddyfile_bounds_slow_clients_and_bodies():
    assert re.search(r"timeouts\s*\{[^}]*read_header\s+\d+s", CADDYFILE)
    assert re.search(r"timeouts\s*\{[^}]*read_body\s+\d+s", CADDYFILE)
    assert re.search(r"max_size\s+\d+MB", CADDYFILE)
    assert "write " not in CADDYFILE.split("servers", 1)[1].split("}", 1)[0]  # SSE must not be cut
    assert "request>headers>Authorization delete" in CADDYFILE


# -- the real Caddy ---------------------------------------------------------------------------
class Upstream(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        Upstream.seen.append(
            {
                "xff": self.headers.get_all("X-Forwarded-For"),
                "host": self.headers.get("Host"),
                "bytes": len(body),
            }  # fmt: skip
        )
        reply = json.dumps(Upstream.seen[-1]).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = do_POST

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def caddy(tmp_path_factory):
    """The repository's Caddyfile in front of a recording upstream, on loopback ports. Only the
    three timeouts are shortened (and the admin socket and redirects turned off) so tests are
    quick; the shipped values are checked above."""
    if not docker_ready("caddy:2"):
        pytest.skip("Docker or the caddy:2 image is not available")
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    port = free_port()
    text = CADDYFILE.replace("api:8000", f"127.0.0.1:{upstream.server_port}")
    text = re.sub(r"(read_body|read_header|idle)\s+\d+s", r"\1 2s", text)
    text = text.replace("servers {", "admin off\n\tauto_https disable_redirects\n\tservers {", 1)
    text = text.replace("health_uri /health", "").replace("health_interval 15s", "")
    folder = tmp_path_factory.mktemp("caddy")
    (folder / "Caddyfile").write_text(text, encoding="utf-8")
    name = f"laris-sec-{uuid.uuid4().hex[:8]}"
    started = subprocess.run(
        ["docker", "run", "-d", "--rm", "--network", "host", "--name", name,
         "-e", f"LARIS_DOMAIN=localhost:{port}",
         "-v", f"{folder}/Caddyfile:/etc/caddy/Caddyfile:ro",
         "caddy:2"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if started.returncode != 0:
        upstream.shutdown()
        pytest.skip(f"could not start caddy: {started.stderr.strip()[:200]}")
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.skip("caddy did not start listening")
        time.sleep(1.5)  # the local CA and certificate are made on the first start
        yield port
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        upstream.shutdown()


def tls_request(port, request: bytes, wait=10.0) -> bytes:
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", port), timeout=wait) as raw:
        with context.wrap_socket(raw, server_hostname="localhost") as sock:
            sock.sendall(request)
            data = b""
            try:
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                    top, sep, body = data.partition(b"\r\n\r\n")
                    if sep and b"content-length" in top.lower():
                        size = int(re.search(rb"(?i)content-length:\s*(\d+)", top).group(1))
                        if len(body) >= size:
                            break
            except (socket.timeout, ConnectionError, ssl.SSLError):
                pass
            return data


def test_caddy_closes_a_connection_that_never_starts_the_handshake(caddy):
    started = time.monotonic()
    with socket.create_connection(("127.0.0.1", caddy), timeout=15) as sock:
        sock.settimeout(15)
        closed = sock.recv(1) == b""  # the server gave up: end of stream
    assert closed and time.monotonic() - started < 8


def test_caddy_closes_a_handshake_that_stalls_half_way(caddy):
    started = time.monotonic()
    with socket.create_connection(("127.0.0.1", caddy), timeout=15) as sock:
        sock.sendall(b"\x16\x03\x01\x02\x00\x01\x00")  # a TLS record header and one byte of it
        sock.settimeout(15)
        try:
            data = sock.recv(1024)
        except ConnectionError:
            data = b""
    assert time.monotonic() - started < 8 and not data.startswith(b"HTTP/")


def test_caddy_drops_a_request_whose_headers_never_finish(caddy):
    started = time.monotonic()
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", caddy), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname="localhost") as sock:
            sock.sendall(b"POST /v1/x HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")  # never ends
            sock.settimeout(15)
            try:
                data = sock.recv(1024)
            except (ConnectionError, ssl.SSLError):
                data = b""
    assert time.monotonic() - started < 8
    assert not data or data.startswith(b"HTTP/1.1 408") or b" 400 " in data[:20]


def test_caddy_replaces_a_forged_x_forwarded_for_with_the_real_peer(caddy):
    Upstream.seen.clear()
    request = (
        "POST /v1/x HTTP/1.1\r\nHost: localhost\r\nContent-Length: 2\r\n"
        "X-Forwarded-For: 198.51.100.7\r\nConnection: close\r\n\r\n{}"
    )
    answer = tls_request(caddy, request.encode())
    assert b" 200 " in answer.split(b"\r\n", 1)[0], answer[:200]
    forwarded = Upstream.seen[-1]["xff"]
    assert forwarded == ["127.0.0.1"], forwarded  # the client's own word is gone


def test_caddy_stops_an_oversized_body_at_the_edge(caddy):
    Upstream.seen.clear()
    request = (
        f"POST /v1/x HTTP/1.1\r\nHost: localhost\r\nContent-Length: {40 * 1024 * 1024}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    answer = tls_request(caddy, request)  # promises 40 MB, sends none
    assert b" 413 " in answer.split(b"\r\n", 1)[0], answer[:200]
    assert not Upstream.seen  # the API was never asked
