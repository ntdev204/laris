"""Policies: what may be read, what needs approval, and where internal prompts may be sent."""

import ipaddress
import re
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from laris.shared.config.runtime_schemas import AgentConfig


def _glob_regex(pattern: str) -> "re.Pattern[str]":
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


class PathPolicy:
    """Deny-list of internal and secret files, matched on the path relative to the project."""

    def __init__(
        self, deny_globs: List[str], project_root: Path, extra_roots: Optional[List[Path]] = None
    ):
        self.root = project_root.resolve()
        self.extra_roots = [r.resolve() for r in (extra_roots or [])]
        self._regexes = [_glob_regex(g) for g in deny_globs]

    def _relative(self, path: Path) -> str:
        resolved = path.resolve()
        for base in [self.root, *self.extra_roots]:
            try:
                return resolved.relative_to(base).as_posix()
            except ValueError:
                continue
        return resolved.as_posix().lstrip("/")

    def add_deny(self, glob: str) -> None:
        self._regexes.append(_glob_regex(glob))

    def denied(self, path: Path) -> bool:
        rel = self._relative(path)
        return any(r.match(rel) for r in self._regexes)


class ApprovalPolicy:
    def __init__(self, cfg: AgentConfig) -> None:
        self.mode = cfg.approval.mode
        self.always_ask = set(cfg.approval.always_ask)

    def decide(self, tool: str, writes: bool) -> str:
        """allow, ask or deny for one tool call."""
        if not (writes or tool in self.always_ask):
            return "allow"
        if self.mode == "deny":
            return "deny"
        return "allow" if self.mode == "auto" else "ask"


LOOPBACK_NAMES = {"localhost"}


def is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def egress_allowed(base_url: str, allow_remote: bool) -> bool:
    """Internal prompts leave the machine only when the config explicitly allows a remote host."""
    return not base_url or allow_remote or is_loopback_url(base_url)


def describe(value: Any) -> str:
    return str(value)[:200]
