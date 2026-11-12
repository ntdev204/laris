"""API keys accepted by the model server. Only SHA-256 digests are kept in memory.

Keys come from an environment variable (comma, space or newline separated) and/or a file (one key
per line, `#` comments). The server holds no other state about users: no conversations, documents or
logs. Each request is checked against every digest, with no early exit.
"""

import hashlib
import hmac
import re
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Mapping, Optional

if TYPE_CHECKING:
    from laris.server.serving.ports import Principal

MIN_KEY_CHARS = 8
_SPLIT = re.compile(r"[,\s]+")


def _digest(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


class KeyRing:
    def __init__(self, keys: Iterable[str] = ()) -> None:
        self._digests: List[bytes] = []
        for key in keys:
            key = key.strip()
            if len(key) < MIN_KEY_CHARS:
                raise ValueError(f"API keys must have at least {MIN_KEY_CHARS} characters")
            self._digests.append(_digest(key))

    def __len__(self) -> int:
        return len(self._digests)

    def check(self, supplied: Optional[str]) -> bool:
        if not supplied:
            return False
        probe = _digest(supplied.strip())
        matched = False
        for known in self._digests:  # no early exit: timing does not reveal which entry matched
            matched |= hmac.compare_digest(probe, known)
        return matched

    @classmethod
    def load(
        cls, env_name: str = "", file_path: str = "", environ: Optional[Mapping[str, str]] = None
    ) -> "KeyRing":
        keys: List[str] = []
        if env_name and environ is not None and environ.get(env_name):
            keys += [k for k in _SPLIT.split(environ[env_name]) if k]
        if file_path:
            path = Path(file_path).expanduser()
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line:
                        keys.append(line)
        return cls(keys)


class StaticAuthenticator:
    """Fixed keys from `KeyRing` (testing): role `user`, no token limit, never revoked."""

    def __init__(self, ring: "KeyRing", permissions: Iterable[str]) -> None:
        from laris.server.serving.ports import Principal

        self._ring = ring
        self._principal = Principal("static", "user", frozenset(permissions))

    def authenticate(
        self, supplied: Optional[str], client_ip: Optional[str] = None
    ) -> "Optional[Principal]":
        return self._principal if self._ring.check(supplied) else None
