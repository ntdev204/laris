"""Trusting a server whose certificate no public authority signed (a private or self-signed one).

The client verifies every server certificate. A server run by its owner usually has a private
certificate, so `laris login` can show the certificate's SHA-256 fingerprint and, when the user
confirms it matches the one the owner published, keep that certificate as trusted for this server
only (trust on first use, pinned). Nothing is trusted silently, and the fingerprint is the only
thing a person has to compare.
"""

import hashlib
import socket
import ssl
import urllib.request
from pathlib import Path
from typing import Optional

TRUST_DIR = "~/.laris/trusted"
_installed: Optional[str] = None


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
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                return True
    except ssl.SSLError:
        return False
    except OSError:
        return True  # unreachable is a different problem; do not offer to trust anything


def save(pem: str, host: str, port: int, folder: str = TRUST_DIR) -> Path:
    target = Path(folder).expanduser()
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
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    )
    _installed = str(path)


def reset() -> None:
    """Forget the installed opener (tests)."""
    global _installed
    urllib.request._opener = None  # type: ignore[attr-defined]
    _installed = None
