"""The user's API key: where it comes from, how it is stored, and which private space it names.

The key is read from the environment variable `app.key_env`, else from the credentials file written
by `laris login` (mode 0600), else typed at a hidden prompt. Each key owns a separate conversation
space: its folder name is a one-way fingerprint, so the key is never written to state folders, logs
or audit records.
"""

import getpass
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Callable, Mapping, Optional

from config.runtime_schemas import AppConfig

FINGERPRINT_CHARS = 16
MIN_KEY_CHARS = 8


class CredentialError(Exception):
    """No usable API key."""


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def _path(cfg: AppConfig) -> Path:
    return Path(cfg.account_file).expanduser()


def load_saved(cfg: AppConfig) -> Optional[str]:
    path = _path(cfg)
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("api_key")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def save(cfg: AppConfig, key: str) -> Path:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps({"api_key": key}))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def forget(cfg: AppConfig) -> bool:
    path = _path(cfg)
    if path.exists():
        path.unlink()
        return True
    return False


def validate(key: str) -> str:
    key = key.strip()
    if len(key) < MIN_KEY_CHARS or any(c.isspace() for c in key):
        raise CredentialError(f"API key must be at least {MIN_KEY_CHARS} characters, no spaces")
    return key


def resolve(
    cfg: AppConfig,
    environ: Optional[Mapping[str, str]] = None,
    ask: Optional[Callable[[str], str]] = None,
    interactive: bool = True,
) -> str:
    """The key to use now; asks (hidden input) and saves it when none is known."""
    env = os.environ if environ is None else environ
    found = env.get(cfg.key_env) or load_saved(cfg)
    if found:
        return validate(found)
    if not interactive:
        raise CredentialError(f"no API key: set {cfg.key_env} or run `laris login`")
    key = validate((ask or getpass.getpass)("API key: "))
    save(cfg, key)
    return key
