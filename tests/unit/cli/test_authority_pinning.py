"""Pinning a server's certificate *authority* (published at `trust.CA_PATH`) instead of its own
certificate, so a renewed server certificate keeps working (a proxy with a private authority
renews it every few hours)."""

import datetime
import http.server
import json
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from laris.shared.harness import trust

NOW = datetime.datetime.now(datetime.timezone.utc)


def _name(text):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def make_authority(label="Test Authority"):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(label))
        .issuer_name(_name(label))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(minutes=5))
        .not_valid_after(NOW + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_leaf(folder: Path, authority, name="leaf"):
    import ipaddress

    ca_key, ca_cert = authority
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("server"))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(minutes=5))
        .not_valid_after(NOW + datetime.timedelta(hours=12))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    folder.mkdir(parents=True, exist_ok=True)
    cert_file, key_file = folder / f"{name}.crt", folder / f"{name}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


def pem_of(cert) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


class Server:
    """An HTTPS server that publishes `published` at the authority path (or 404 when None)."""

    def __init__(self, folder: Path, authority, published):
        self.folder, self.authority = folder, authority
        outer = self
        self.published = published

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = outer.published.encode() if outer.published else b""
                found = self.path == trust.CA_PATH and bool(body)
                self.send_response(200 if found else 404)
                self.send_header("Content-Length", str(len(body) if found else 0))
                self.end_headers()
                if found:
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.renew("first")
        self.httpd.socket = self.context.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]
        self.url = f"https://127.0.0.1:{self.port}"

    def renew(self, name):
        """A new server certificate from the same authority, as a proxy does every few hours."""
        cert, key = make_leaf(self.folder, self.authority, name)
        self.context.load_cert_chain(str(cert), str(key))
        self.leaf = cert.read_text()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def authority():
    return make_authority()


@pytest.fixture
def serve(tmp_path):
    made = []

    def start(authority, published="own"):
        text = pem_of(authority[1]) if published == "own" else published
        server = Server(tmp_path / f"tls{len(made)}", authority, text)
        made.append(server)
        return server

    yield start
    for server in made:
        server.close()


def test_the_published_authority_is_pinned_and_survives_a_renewal(tmp_path, authority, serve):
    server = serve(authority)
    home = tmp_path / "home"
    root = trust.fingerprint_pem(pem_of(authority[1]))
    assert trust.decide(server.url, home=home).status == "unknown"  # nothing vouches for it yet
    assert not (home / "trusted").exists()
    done = trust.decide(server.url, expected=root, home=home)
    assert done.status == "pinned" and done.kind == "authority" and done.fingerprint == root
    pinned = str(done.path)
    saved = json.loads((home / "settings.json").read_text())["server"]["caFingerprint"]
    assert saved == "sha256:" + root[7:].replace(":", "").lower()
    assert trust.is_trusted("127.0.0.1", server.port, pinned)
    server.renew("second")  # the server certificate changes, the authority does not
    assert trust.is_trusted("127.0.0.1", server.port, pinned)
    assert trust.decide(server.url, pinned, home=home).status == "trusted"


def test_pinning_the_server_certificate_itself_breaks_at_the_next_renewal(
    tmp_path, authority, serve
):
    """Why the authority is preferred: this is what release 2.0.0 did."""
    server = serve(authority, published=None)  # publishes no authority: only its own certificate
    home = tmp_path / "home"
    own = trust.fingerprint_pem(server.leaf)
    done = trust.decide(server.url, expected=own, home=home)
    assert done.status == "pinned" and done.kind == "certificate"
    assert trust.is_trusted("127.0.0.1", server.port, str(done.path))
    server.renew("second")
    assert not trust.is_trusted("127.0.0.1", server.port, str(done.path))


def test_a_wrong_fingerprint_pins_nothing(tmp_path, authority, serve):
    server = serve(authority)
    home = tmp_path / "home"
    wrong = "SHA256:" + ":".join(["00"] * 32)
    done = trust.decide(server.url, expected=wrong, home=home)
    assert done.status == "mismatch" and done.fingerprint != trust.normalise(wrong)
    assert not (home / "settings.json").exists()
    assert not list((home / "trusted").glob("*")) if (home / "trusted").exists() else True


def test_a_published_authority_that_did_not_sign_the_server_is_never_kept(
    tmp_path, authority, serve
):
    stranger = pem_of(make_authority("Somebody Else")[1])
    server = serve(authority, published=stranger)
    home = tmp_path / "home"
    done = trust.decide(server.url, expected=trust.fingerprint_pem(stranger), home=home)
    assert done.status == "mismatch"  # the handshake with it fails, so it is removed again
    assert not list((home / "trusted").glob("*.pem"))
    assert not (home / "settings.json").exists()


def test_what_the_authority_path_serves_is_bounded_and_must_be_a_certificate(
    tmp_path, authority, serve
):
    for published in ("not a certificate", "-----BEGIN CERTIFICATE-----\nAAAA\n", "x" * 70000):
        server = serve(authority, published=published)
        assert trust.fetch_authority("127.0.0.1", server.port) is None
    assert trust.fetch_authority("127.0.0.1", 1) is None  # nothing listens there


def test_a_plain_http_or_unreachable_server_asks_nothing(tmp_path):
    assert trust.decide("http://127.0.0.1:9", home=tmp_path).status == "trusted"
    assert trust.decide("https://127.0.0.1:1", home=tmp_path).status == "trusted"
