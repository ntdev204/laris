"""Encryption of stored API keys.

Current format (version 2): AES-256-GCM from the `cryptography` library, a fresh 12-byte random
nonce per message, the version byte bound as associated data. Version 1 blobs (written before
AES-GCM was approved: encrypt-then-MAC, documented below) are still readable; `needs_upgrade`
tells the store to reseal them.

Legacy version 1 construction: encrypt-then-MAC. Sub-keys come from the master secret through
an HMAC-based HKDF.
The cipher is HMAC-SHA256 in counter mode (a PRF-based stream cipher) with a fresh 16-byte random
nonce per message. A 32-byte HMAC-SHA256 tag covers version, nonce and ciphertext and is checked in
constant time before anything is decrypted. Lookup digests are keyed (HMAC), so a stolen database
file cannot be used to test guesses of a key without the master secret.

This module is the only place that knows the scheme.
"""

import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path
from typing import Mapping, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"  # legacy
GCM_VERSION = b"\x02"
GCM_NONCE = 12
NONCE = 16
TAG = 32
MIN_MASTER_CHARS = 16


class SecretBoxError(ValueError):
    """The blob is corrupt, was tampered with, or was sealed with another master secret."""


def _hkdf(master: bytes, label: bytes) -> bytes:
    prk = hmac.new(b"laris-server-v1", master, hashlib.sha256).digest()
    return hmac.new(prk, label + b"\x01", hashlib.sha256).digest()


class SecretBox:
    def __init__(self, master: bytes) -> None:
        if len(master) < MIN_MASTER_CHARS:
            raise ValueError("master secret is too short")
        self._enc = _hkdf(master, b"encrypt")
        self._mac = _hkdf(master, b"authenticate")
        self._lookup = _hkdf(master, b"lookup")

    def _stream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out += hmac.new(self._enc, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
            counter += 1
        return bytes(out[:length])

    def seal(self, plaintext: str) -> bytes:
        nonce = os.urandom(GCM_NONCE)
        body = AESGCM(self._enc).encrypt(nonce, plaintext.encode("utf-8"), GCM_VERSION)
        return GCM_VERSION + nonce + body

    def needs_upgrade(self, blob: bytes) -> bool:
        return blob[:1] != GCM_VERSION

    def _seal_legacy(self, plaintext: str) -> bytes:  # kept for tests of the migration path
        data = plaintext.encode("utf-8")
        nonce = os.urandom(NONCE)
        body = bytes(a ^ b for a, b in zip(data, self._stream(nonce, len(data))))
        tag = hmac.new(self._mac, VERSION + nonce + body, hashlib.sha256).digest()
        return VERSION + nonce + body + tag

    def open(self, blob: bytes) -> str:
        if blob[:1] == GCM_VERSION:
            if len(blob) < 1 + GCM_NONCE + 16:
                raise SecretBoxError("unreadable secret")
            nonce, body = blob[1 : 1 + GCM_NONCE], blob[1 + GCM_NONCE :]
            try:
                return AESGCM(self._enc).decrypt(nonce, body, GCM_VERSION).decode("utf-8")
            except InvalidTag as exc:
                raise SecretBoxError(
                    "secret failed authentication (wrong master secret or tampering)"
                ) from exc
        if len(blob) < 1 + NONCE + TAG or blob[:1] != VERSION:
            raise SecretBoxError("unreadable secret")
        nonce, body, tag = blob[1 : 1 + NONCE], blob[1 + NONCE : -TAG], blob[-TAG:]
        expected = hmac.new(self._mac, VERSION + nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise SecretBoxError("secret failed authentication (wrong master secret or tampering)")
        return bytes(a ^ b for a, b in zip(body, self._stream(nonce, len(body)))).decode("utf-8")

    def lookup_digest(self, plaintext: str) -> str:
        return hmac.new(self._lookup, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


DOCKER_SECRETS = "/run/secrets"


def load_master(
    env_name: str, file_path: str, environ: Optional[Mapping[str, str]] = None
) -> bytes:
    """The master secret: the environment variable if set, else a 0600 file created on first run
    (outside the database folder, so the database alone never decrypts anything)."""
    env = os.environ if environ is None else environ
    if env_name and env.get(env_name):
        value = env[env_name].strip()
        if len(value) < MIN_MASTER_CHARS:
            raise ValueError(f"{env_name} must have at least {MIN_MASTER_CHARS} characters")
        return value.encode("utf-8")
    path = Path(file_path).expanduser()
    if path.is_file():
        mode = path.stat().st_mode
        # a Docker secret is a root-owned tmpfs file only this container can see: its mode is the
        # runtime's, not ours to demand
        docker_secret = path.resolve().parent == Path(DOCKER_SECRETS)
        if mode & (stat.S_IRWXG | stat.S_IRWXO) and not docker_secret:
            raise ValueError(f"{path} must not be readable by group or others (chmod 600)")
        return path.read_text(encoding="utf-8").strip().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(secret)
    return secret.encode("utf-8")
