"""TLS material for the model server: locate the certificate and create a self-signed one."""

import datetime
import ipaddress
import os
import socket
from pathlib import Path
from typing import List, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from harness.trust import fingerprint_pem

CERT_NAME = "cert.pem"
KEY_NAME = "key.pem"


def default_paths(tls_dir: str) -> Tuple[Path, Path]:
    folder = Path(tls_dir).expanduser()
    return folder / CERT_NAME, folder / KEY_NAME


def discover(tls_dir: str) -> Tuple[str, str]:
    """The certificate and key under the TLS folder, or two empty strings if not both present."""
    cert, key = default_paths(tls_dir)
    return (str(cert), str(key)) if cert.is_file() and key.is_file() else ("", "")


def _alt_names(hosts: List[str]) -> List[x509.GeneralName]:
    names: List[x509.GeneralName] = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    return names


def create_self_signed(
    tls_dir: str, hosts: List[str], days: int = 365, force: bool = False
) -> Tuple[Path, Path]:
    """Write a self-signed certificate (ECDSA P-256) and a 0600 private key under `tls_dir`.
    Clients pin it on first login (`laris login --server`, trust on first use), or use a real CA."""
    cert_path, key_path = default_paths(tls_dir)
    if (cert_path.exists() or key_path.exists()) and not force:
        raise FileExistsError(f"{cert_path.parent} already holds a certificate (use --force)")
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    hosts = hosts or [socket.gethostname(), "localhost", "127.0.0.1"]
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(_alt_names(hosts)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem_key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def fingerprint(cert_file: str) -> str:
    """SHA-256 fingerprint of a certificate file: what a user compares at `laris login`."""
    return fingerprint_pem(Path(cert_file).read_text(encoding="utf-8"))
