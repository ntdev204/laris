"""The user's API key: where it comes from, how it is stored, and which private space it names.

The key is read from the environment variable `app.key_env`, else from the `api_key` field of
the global settings.json written by `laris login` (mode 0600), else typed at a hidden prompt. Each
key owns a separate conversation space: its folder name is a one-way fingerprint, so the key is
never written to state folders, logs or audit records.
"""

import getpass
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Callable, Mapping, Optional

from config.runtime_schemas import AppConfig, ModelApiConfig

FINGERPRINT_CHARS = 16
MIN_KEY_CHARS = 8


class CredentialError(Exception):
    """No usable API key."""


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def _path(cfg: AppConfig) -> Path:
    return Path(cfg.account_file).expanduser()


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _legacy(cfg: AppConfig) -> Path:
    return _path(cfg).with_name("credentials.json")


def load_saved(cfg: AppConfig) -> Optional[str]:
    """`api_key` in the global settings.json (older installs: ~/.laris/credentials.json)."""
    for path in (_path(cfg), _legacy(cfg)):
        value = _read(path).get("api_key")
        if isinstance(value, str) and value:
            return value
    return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # the file now holds a secret


def save(cfg: AppConfig, key: str) -> Path:
    """Store the key in settings.json next to the other settings (mode 0600)."""
    path = _path(cfg)
    data = _read(path)
    data["api_key"] = key
    _write(path, data)
    return path


def forget(cfg: AppConfig) -> bool:
    removed = False
    path = _path(cfg)
    data = _read(path)
    if data.pop("api_key", None) is not None:
        _write(path, data)
        removed = True
    legacy = _legacy(cfg)
    if legacy != path and legacy.exists():
        legacy.unlink()
        removed = True
    return removed


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


def verify_with_server(api: ModelApiConfig, key: str) -> str:
    """`ok`, `rejected`, `unreachable` or `local` (no model API configured: nothing to check)."""
    if not api.base_url:
        return "local"
    from agent.provider import check_key

    return check_key(api.base_url, key, min(api.timeout_s, 10.0))
