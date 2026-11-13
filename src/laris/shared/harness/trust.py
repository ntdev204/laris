"""Trusting a server whose certificate no public authority signed (a private or self-signed one).

The client verifies every server certificate. A server run by its owner usually has a private
certificate authority, so the client can show a SHA-256 fingerprint and, when it matches the one
the owner published (typed by the user, confirmed by the user, or packaged with the program, D24),
keep that certificate as trusted for this server only (pinned). Nothing is trusted silently.

What is pinned matters. A reverse proxy with its own authority (Caddy) renews the server's own
certificate every few hours, so pinning that one stops working at the next renewal. The server
therefore publishes its *authority* at `CA_PATH`; the client prefers it and falls back to the
server's own certificate only for a server that publishes none (a self-signed one).
"""

import hashlib
import http.client
import socket
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

TRUST_DIR = "~/.laris/trusted"
CA_PATH = "/.well-known/laris/ca.crt"  # where a server publishes its private authority
CA_MAX_BYTES = 65536
_installed: Optional[str] = None
# The pinned file may hold a server's own (leaf) certificate, as when the owner's reverse proxy
# issues one from a private CA. A certificate in the trust store is then enough to anchor the
# chain; the host name is still checked.
_PINNED = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)


def fingerprint_der(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return "SHA256:" + ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def fingerprint_pem(pem: str) -> str:
    return fingerprint_der(ssl.PEM_cert_to_DER_cert(pem))


def normalise(value: str) -> str:
    """Accepts `SHA256:AA:BB..`, `aa:bb..` or plain hex, any case."""
    hex_only = "".join(c for c in value.upper().replace("SHA256", "") if c in "0123456789ABCDEF")
    return "SHA256:" + ":".join(hex_only[i : i + 2] for i in range(0, len(hex_only), 2))


def fetch_certificate(host: str, port: int, timeout: float = 5.0) -> str:
    """The certificate the server presents, without verifying it (to be shown, not trusted)."""
    return ssl.get_server_certificate((host, port), timeout=timeout)


def is_trusted(host: str, port: int, ca_file: str = "", timeout: float = 5.0) -> bool:
    """True when a verified TLS handshake succeeds (system authorities plus `ca_file`)."""
    context = ssl.create_default_context()
    if ca_file and Path(ca_file).expanduser().is_file():
        context.load_verify_locations(cafile=str(Path(ca_file).expanduser()))
        context.verify_flags |= _PINNED
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                return True
    except ssl.SSLError:
        return False
    except OSError:
        return True  # unreachable is a different problem; do not offer to trust anything


def save(pem: str, host: str, port: int, folder: Optional[str] = None) -> Path:
    target = Path(folder or TRUST_DIR).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{host}_{port}.pem".replace("/", "_")
    path.write_text(pem, encoding="utf-8")
    path.chmod(0o600)
    return path


def install(ca_file: str) -> None:
    """Use the system authorities plus the pinned certificate for this process's HTTPS calls."""
    global _installed
    path = Path(ca_file).expanduser()
    if not ca_file or not path.is_file() or _installed == str(path):
        return
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(path))
    context.verify_flags |= _PINNED
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    )
    _installed = str(path)


def reset() -> None:
    """Forget the installed opener (tests)."""
    global _installed
    urllib.request._opener = None  # type: ignore[attr-defined]
    _installed = None


# -- deciding whom to trust ----------------------------------------------------------------------
@dataclass
class Candidate:
    """A certificate that could be pinned for a server, with the fingerprint a person compares."""

    pem: str
    fingerprint: str
    kind: str  # "authority" (published at CA_PATH) or "certificate" (the server's own)


@dataclass
class Decision:
    """`trusted`: nothing to do. `pinned`: a certificate was verified and kept. `unknown`: a person
    has to compare `fingerprint`. `mismatch`: the expected fingerprint names none of the server's
    certificates. `unreachable`: the server did not answer."""

    status: str
    fingerprint: str = ""
    kind: str = ""
    path: Optional[Path] = None


def fetch_authority(host: str, port: int, timeout: float = 5.0) -> Optional[str]:
    """The authority certificate the server publishes at `CA_PATH`, or None. It is read without
    verification on purpose: it is only compared by fingerprint, never trusted as it arrives."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
    try:
        connection.request("GET", CA_PATH, headers={"Accept": "application/x-pem-file"})
        response = connection.getresponse()
        if response.status != 200:
            return None
        body = response.read(CA_MAX_BYTES + 1)
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()
    if len(body) > CA_MAX_BYTES:
        return None
    text = body.decode("ascii", errors="replace")
    start, end = text.find("-----BEGIN CERTIFICATE-----"), text.find("-----END CERTIFICATE-----")
    if start < 0 or end < start:
        return None
    pem = text[start : end + len("-----END CERTIFICATE-----")] + "\n"
    try:
        ssl.PEM_cert_to_DER_cert(pem)
    except ValueError:
        return None
    return pem


def candidates(host: str, port: int, timeout: float = 5.0) -> List[Candidate]:
    """What could be pinned, best first: the published authority, then the server's certificate."""
    found: List[Candidate] = []
    authority = fetch_authority(host, port, timeout)
    if authority:
        found.append(Candidate(authority, fingerprint_pem(authority), "authority"))
    try:
        own = fetch_certificate(host, port, timeout)
        found.append(Candidate(own, fingerprint_pem(own), "certificate"))
    except (OSError, ValueError):
        pass
    return found


def _record(path: Path, settings_file: Path) -> None:
    from laris.shared.config import settings

    pinned = settings.set_path(
        settings.read_raw(settings_file), "server.caFingerprint", settings.fingerprint_of_file(path)
    )
    settings.write(settings_file, pinned)


def decide(
    url: str,
    ca_file: str = "",
    expected: str = "",
    accept: str = "",
    home: Optional[Path] = None,
    timeout: float = 5.0,
) -> Decision:
    """Make the server at `url` verifiable, pinning a certificate when one is vouched for.

    `expected` is a fingerprint from a trusted source (the package, a flag): the candidate that
    carries it is pinned without a question. `accept` is the fingerprint a person just confirmed.
    A pinned certificate is kept only if a verified handshake then succeeds, so a published
    "authority" that did not sign the server's certificate is never kept.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return Decision("trusted")
    host, port = parsed.hostname, parsed.port or 443
    if is_trusted(host, port, ca_file, timeout):
        return Decision("trusted")
    found = candidates(host, port, timeout)
    if not found:
        return Decision("unreachable")
    base = Path(home) if home else Path("~/.laris").expanduser()
    wanted = {normalise(v) for v in (expected, accept) if v}
    for candidate in found:
        if candidate.fingerprint not in wanted:
            continue
        path = save(candidate.pem, host, port, str(base / "trusted"))
        if is_trusted(host, port, str(path), timeout):
            _record(path, base / "settings.json")
            reset()  # the same file name may hold a new certificate
            install(str(path))
            return Decision("pinned", candidate.fingerprint, candidate.kind, path)
        path.unlink(missing_ok=True)
    if wanted:
        return Decision("mismatch", found[0].fingerprint, found[0].kind)
    return Decision("unknown", found[0].fingerprint, found[0].kind)
