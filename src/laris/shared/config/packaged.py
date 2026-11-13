"""Defaults written into the package at build time (ADR-019 D24).

The release workflow writes `defaults.json` beside the frozen program from repository variables;
nothing of it is in the source tree. It may hold the server address and, for a server with a
private certificate authority, the SHA-256 fingerprint of that authority:

    {"server": {"url": "https://laris.example.com", "caFingerprint": "SHA256:AA:BB:..."}}

It is the lowest layer: `~/.laris/settings.json` and the `LARIS_*` environment both override it.
`LARIS_PACKAGED_DEFAULTS` names another file (tests, a development checkout).
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ENV = "LARIS_PACKAGED_DEFAULTS"
FILE_NAME = "defaults.json"
MAX_BYTES = 65536


def path() -> Optional[Path]:
    """Where the defaults of this installation are, or None when there are none."""
    named = os.environ.get(ENV)
    if named:
        return Path(named).expanduser()
    if getattr(sys, "frozen", False):  # <package>/laris/laris(.exe): the file sits beside `laris/`
        return Path(sys.executable).resolve().parent.parent / FILE_NAME
    return None


def load() -> Dict[str, Any]:
    """The packaged defaults, `{}` when absent or unreadable (a broken file never stops a start)."""
    where = path()
    if where is None:
        return {}
    try:
        if not where.is_file() or where.stat().st_size > MAX_BYTES:
            return {}
        data = json.loads(where.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    server = data.get("server") if isinstance(data, dict) else None
    if not isinstance(server, dict):
        return {}
    out: Dict[str, str] = {}
    url = server.get("url")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        from laris.shared.config.settings import server_address

        out["url"] = server_address(url)
    fingerprint = server.get("caFingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        out["caFingerprint"] = fingerprint.strip()
    return {"server": out} if "url" in out else {}


def server_url() -> str:
    return str(load().get("server", {}).get("url", ""))


def ca_fingerprint() -> str:
    """The fingerprint of the server's certificate authority the package vouches for, or ''."""
    return str(load().get("server", {}).get("caFingerprint", ""))


def under(settings: Dict[str, Any]) -> Dict[str, Any]:
    """`settings` with the packaged server address beneath it: the user's own address wins, and
    the packaged fingerprint is never copied (the pin in settings records what was verified)."""
    url = server_url()
    if not url or (settings.get("server") or {}).get("url"):
        return settings
    merged = dict(settings)
    merged["server"] = {**(settings.get("server") or {}), "url": url}
    return merged
