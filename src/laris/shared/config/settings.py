"""`~/.laris/settings.json`: the one file of client settings (SR-C6), shaped like Claude Code's.

Validated by pydantic models whose JSON Schema ships as `settings.schema.json` beside this module.
Errors name the JSON path (`permissions.defaultMode`, `hooks.PreToolUse[0].hooks[0].timeout`). The
file holds no secrets (the API key is in `.credentials.json`). `layer_from` turns the keys a user
has set into a configuration layer; nothing here reads a project file.
"""

import hashlib
import json
import re
import ssl
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
MODES = ("default", "acceptEdits", "plan", "bypass")
MODE_TO_APPROVAL = {"default": "ask", "acceptEdits": "auto", "plan": "deny", "bypass": "auto"}
_FINGERPRINT = re.compile(r"^(|sha256:[0-9a-f]{64})$")


class SettingsError(ValueError):
    """The settings file (or a change to it) is invalid; the message names the JSON path."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Server(_Strict):
    url: str = ""
    caFingerprint: str = ""  # sha256:<hex> of the pinned private certificate
    timeoutSeconds: float = Field(default=120.0, gt=0)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("caFingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        if not _FINGERPRINT.match(value):
            raise ValueError("must be sha256: followed by 64 lowercase hex digits")
        return value


class Permissions(_Strict):
    defaultMode: Literal["default", "acceptEdits", "plan", "bypass"] = "default"
    allow: List[str] = Field(default_factory=list)
    ask: List[str] = Field(default_factory=list)
    deny: List[str] = Field(default_factory=list)
    additionalDirectories: List[str] = Field(default_factory=list)


class HookCommand(_Strict):
    type: Literal["command"] = "command"
    command: str = Field(min_length=1)
    timeout: float = Field(default=30.0, gt=0, le=600)


class HookMatcher(_Strict):
    matcher: str = ""
    hooks: List[HookCommand] = Field(default_factory=list)


class StatusLine(_Strict):
    type: Literal["command"] = "command"
    command: str = Field(min_length=1)


class Sandbox(_Strict):
    python: str = "3.12"
    packages: List[str] = Field(default_factory=list)
    inheritEnv: bool = False
    indexUrl: str = ""
    pythonSource: str = ""


class Ui(_Strict):
    theme: Literal["auto", "light", "dark"] = "auto"
    markdown: bool = True
    spinner: bool = True
    showStatusLine: bool = True


class Context(_Strict):
    autoCompact: bool = True
    windowTokens: int = Field(default=32768, ge=1024)
    compactThreshold: float = Field(default=0.8, gt=0.0, le=1.0)


class Vault(_Strict):
    autoRecord: bool = True


class Learning(_Strict):
    collect: bool = True


class Settings(_Strict):
    schema_: Optional[str] = Field(default=None, alias="$schema")
    server: Server = Field(default_factory=Server)
    model: str = ""
    ui: Ui = Field(default_factory=Ui)
    permissions: Permissions = Field(default_factory=Permissions)
    env: Dict[str, str] = Field(default_factory=dict)
    hooks: Dict[str, List[HookMatcher]] = Field(default_factory=dict)
    statusLine: Optional[StatusLine] = None
    sandbox: Sandbox = Field(default_factory=Sandbox)
    context: Context = Field(default_factory=Context)
    vault: Vault = Field(default_factory=Vault)
    learning: Learning = Field(default_factory=Learning)
    extraInstructions: str = ""
    cleanupPeriodDays: int = Field(default=30, ge=0)
    autoUpdates: bool = True

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("hooks")
    @classmethod
    def _events(cls, value: Dict[str, List[HookMatcher]]) -> Dict[str, List[HookMatcher]]:
        unknown = [k for k in value if k not in HOOK_EVENTS]
        if unknown:
            raise ValueError(f"unknown hook event {unknown[0]!r} (known: {', '.join(HOOK_EVENTS)})")
        return value


def json_schema() -> Dict[str, Any]:
    schema = Settings.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "LARIS client settings (~/.laris/settings.json)"
    return schema


def _path_of(loc: Any) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(root)"


def validate(data: Any) -> Settings:
    """The parsed settings, or a `SettingsError` that names the JSON path of the first problem."""
    if not isinstance(data, dict):
        raise SettingsError("(root): settings must be a JSON object")
    try:
        return Settings(**data)
    except ValidationError as exc:
        problem = exc.errors()[0]
        where = _path_of(problem["loc"])
        if problem["type"] == "extra_forbidden":
            raise SettingsError(f"{where}: unknown setting") from None
        raise SettingsError(f"{where}: {problem['msg']}") from None


# -- file -------------------------------------------------------------------------------------
LEGACY_KEYS = {
    "base_url", "model", "api_key", "api_key_env", "ca_file", "auto_compact", "context_window",
    "compact_threshold", "allow_write", "learning_enabled", "vault_record", "extra_instructions",
}  # fmt: skip


def from_legacy(flat: Dict[str, Any]) -> Dict[str, Any]:
    """A 1.x flat `settings.json` as the nested shape (the API key is not carried over)."""
    out: Dict[str, Any] = {}

    def put(path: str, value: Any) -> None:
        node = out
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    table = {
        "base_url": "server.url", "model": "model", "auto_compact": "context.autoCompact",
        "context_window": "context.windowTokens", "compact_threshold": "context.compactThreshold",
        "learning_enabled": "learning.collect", "vault_record": "vault.autoRecord",
        "extra_instructions": "extraInstructions",
    }  # fmt: skip
    for key, path in table.items():
        if key in flat:
            put(path, flat[key])
    if "allow_write" in flat:
        put("permissions.defaultMode", "acceptEdits" if flat["allow_write"] else "default")
    return out


def is_legacy(data: Dict[str, Any]) -> bool:
    return (
        bool(data) and bool(set(data) & LEGACY_KEYS) and not (set(data) - LEGACY_KEYS - {"$schema"})
    )


def read_raw(path: Path) -> Dict[str, Any]:
    """The nested settings as stored; an unreadable file is treated as empty, a 1.x flat file is
    converted in memory (the migration at first start rewrites it)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return from_legacy(data) if is_legacy(data) else data


def write(path: Path, data: Dict[str, Any]) -> None:
    validate(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_path(data: Dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def set_path(data: Dict[str, Any], dotted: str, value: Any) -> Dict[str, Any]:
    """A copy with `dotted` set; the whole result is validated before it is returned."""
    out: Dict[str, Any] = json.loads(json.dumps(data))
    node = out
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    node[parts[-1]] = value
    validate(out)
    return out


def parse_value(text: str) -> Any:
    """`true`, `12`, `["a"]`, `{"k": 1}` are JSON; anything else is a string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


# -- as configuration -------------------------------------------------------------------------
def server_address(url: str) -> str:
    """A server address as a person types it, made complete: `https://` when no scheme is given
    and the API prefix `/v1` when there is no path (`laris.example.com` -> `https://laris.example.com/v1`)."""
    url = url.strip().rstrip("/")
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    if urlparse(url).path in ("", "/"):
        url += "/v1"
    return url


def pinned_path(url: str, home: Optional[Path] = None) -> Optional[Path]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    base = Path(home) if home else Path.home() / ".laris"
    return base / "trusted" / f"{parsed.hostname}_{parsed.port or 443}.pem"


def fingerprint_of_file(path: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(Path(path).read_text(encoding="utf-8"))
    return "sha256:" + hashlib.sha256(der).hexdigest()


def layer_from(data: Dict[str, Any], home: Optional[Path] = None) -> Dict[str, Any]:
    """Configuration layer (`load_config(extra_layers=[...])`) from the keys the user has set."""
    out: Dict[str, Any] = {}

    def put(path: str, value: Any) -> None:
        node = out
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    from laris.shared.config import packaged

    data = packaged.under(data)  # the address packaged at build time, beneath the user's (D24)
    server = data.get("server") or {}
    if "url" in server:
        put("model_api.base_url", str(server["url"]).rstrip("/"))
    if "timeoutSeconds" in server:
        put("model_api.timeout_s", float(server["timeoutSeconds"]))
    fingerprint = server.get("caFingerprint")
    if fingerprint and server.get("url"):
        pem = pinned_path(str(server["url"]), home)
        try:
            if pem and pem.is_file() and fingerprint_of_file(pem) == fingerprint:
                put("model_api.ca_file", str(pem))  # only a certificate that matches the pin
        except (OSError, ValueError):
            pass
    if "model" in data:
        put("model_api.model", data["model"])
    mode = (data.get("permissions") or {}).get("defaultMode")
    if mode:
        put("agent.approval.mode", MODE_TO_APPROVAL[mode])
    context = data.get("context") or {}
    for key, path in (("autoCompact", "context.enabled"), ("windowTokens", "context.window_tokens"),
                      ("compactThreshold", "context.threshold")):  # fmt: skip
        if key in context:
            put(path, context[key])
    if "collect" in (data.get("learning") or {}):
        put("learning.enabled", data["learning"]["collect"])
    if "autoRecord" in (data.get("vault") or {}):
        put("vault.auto_record", data["vault"]["autoRecord"])
    return out
