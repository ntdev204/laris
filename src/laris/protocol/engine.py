"""Engine protocol E1 (SR-C7): JSON lines between a front end and `laris engine --stdio`.

The engine writes *events* and reads *commands*, one JSON object per line, each with a `type`.
The front end holds no tool, permission or storage logic; it only draws events and sends commands.
The version in the `ready` event is `E1_VERSION`; a front end that does not know it refuses with a
clear message. `json_schema()` is the machine-readable description (also shipped as
`e1.schema.json` beside this module, and checked against it by the tests).

Events out: ready, text, tool_call, tool_result, plan, permission_request, status, usage, compact,
goal, completion, error, done. Commands in: user_message, permission_response, interrupt, command,
set_mode, complete, shutdown.
"""

from typing import Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

E1_VERSION = "1"
MODES = ("ask", "auto", "deny")


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- events (engine -> front end) --------------------------------------------------------------
class Ready(_Message):
    type: Literal["ready"] = "ready"
    version: str = E1_VERSION
    engine: str  # the laris version
    session: str  # conversation id
    cwd: str
    mode: str
    server: str = ""  # server address, empty when none is configured


class Text(_Message):
    type: Literal["text"] = "text"
    delta: str


class ToolCall(_Message):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(_Message):
    type: Literal["tool_result"] = "tool_result"
    id: str
    name: str
    result: Any = None


class PlanEvent(_Message):
    type: Literal["plan"] = "plan"
    source: str = ""
    steps: List[Dict[str, str]] = Field(default_factory=list)


class PermissionRequest(_Message):
    type: Literal["permission_request"] = "permission_request"
    id: str
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    rule: str = ""  # the rule an "always allow" answer would save
    scopes: List[str] = Field(default_factory=lambda: ["once", "session", "project", "everywhere"])


class Status(_Message):
    """Progress that is not text: `kind` is verify, reflect, brain, learning, mode, notice ..."""

    type: Literal["status"] = "status"
    kind: str
    data: Dict[str, Any] = Field(default_factory=dict)


class Usage(_Message):
    type: Literal["usage"] = "usage"
    tokens: int = Field(ge=0)
    window: int = Field(ge=0)


class Compact(_Message):
    type: Literal["compact"] = "compact"
    before: int = Field(ge=0)
    after: int = Field(ge=0)
    summarized: int = Field(default=0, ge=0)
    method: str = ""


class Goal(_Message):
    type: Literal["goal"] = "goal"
    complete: bool
    open: List[Any] = Field(default_factory=list)
    failed: List[Any] = Field(default_factory=list)
    retry: bool = False


class CompletionItem(_Message):
    value: str
    description: str = ""


class Completion(_Message):
    """The answer to a `complete` command."""

    type: Literal["completion"] = "completion"
    id: str
    items: List[CompletionItem] = Field(default_factory=list)


class ErrorEvent(_Message):
    type: Literal["error"] = "error"
    code: str
    message: str


class Done(_Message):
    type: Literal["done"] = "done"
    status: str
    answer: str = ""


# -- commands (front end -> engine) ------------------------------------------------------------
class UserMessage(_Message):
    type: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)


class PermissionResponse(_Message):
    type: Literal["permission_response"] = "permission_response"
    id: str
    decision: Literal["allow", "deny"]
    remember: bool = False  # for this session (same as scope "session")
    scope: Literal["once", "session", "project", "everywhere"] = "once"


class Interrupt(_Message):
    type: Literal["interrupt"] = "interrupt"


class Command(_Message):
    """A slash command: `name` without the slash, `args` the rest of the line."""

    type: Literal["command"] = "command"
    name: str = Field(min_length=1)
    args: str = ""


class SetMode(_Message):
    type: Literal["set_mode"] = "set_mode"
    mode: Literal["default", "acceptEdits", "plan", "bypass", "next"]  # `next` is Shift+Tab


class Complete(_Message):
    """Ask for completions of `text` typed after `/` (commands) or `@` (files, skills)."""

    type: Literal["complete"] = "complete"
    id: str
    trigger: Literal["/", "@"]
    text: str = ""


class Shutdown(_Message):
    type: Literal["shutdown"] = "shutdown"


EVENTS: Dict[str, Type[_Message]] = {
    m.model_fields["type"].default: m
    for m in (
        Ready,
        Text,
        ToolCall,
        ToolResult,
        PlanEvent,
        PermissionRequest,
        Status,
        Usage,
        Compact,
        Goal,
        Completion,
        ErrorEvent,
        Done,
    )  # fmt: skip
}
COMMANDS: Dict[str, Type[_Message]] = {
    m.model_fields["type"].default: m
    for m in (UserMessage, PermissionResponse, Interrupt, Command, SetMode, Complete, Shutdown)
}


class ProtocolError(ValueError):
    """A line that is not a valid E1 event or command."""


def _parse(table: Dict[str, Type[_Message]], what: str, data: Any) -> _Message:
    if not isinstance(data, dict):
        raise ProtocolError(f"{what} must be a JSON object")
    kind = data.get("type")
    model = table.get(kind) if isinstance(kind, str) else None
    if model is None:
        raise ProtocolError(f"unknown {what} type {kind!r} (known: {', '.join(sorted(table))})")
    try:
        return model(**data)
    except (ValidationError, TypeError) as exc:
        where, message = "?", str(exc)
        if isinstance(exc, ValidationError):
            problem = exc.errors()[0]
            where = ".".join(str(p) for p in problem["loc"]) or "?"
            message = problem["msg"]
        raise ProtocolError(f"invalid {kind} {what}: {where}: {message}") from None


def parse_event(data: Any) -> _Message:
    return _parse(EVENTS, "event", data)


def parse_command(data: Any) -> _Message:
    return _parse(COMMANDS, "command", data)


def json_schema() -> Dict[str, Any]:
    """The E1 JSON Schema: every event and every command, versioned."""
    events = TypeAdapter(Union[tuple(EVENTS.values())]).json_schema()  # type: ignore[arg-type]
    commands = TypeAdapter(Union[tuple(COMMANDS.values())]).json_schema()  # type: ignore[arg-type]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LARIS engine protocol E1",
        "version": E1_VERSION,
        "events": events,
        "commands": commands,
    }


def check_version(ready: Dict[str, Any], supported: Optional[str] = None) -> Optional[str]:
    """None when the engine speaks `supported` (default: this module's version), else a message
    a front end can show."""
    wanted = supported or E1_VERSION
    found = ready.get("version")
    if found == wanted:
        return None
    return (
        f"this front end speaks engine protocol E1 version {wanted} but the engine reports "
        f"{found!r}; update the laris program and the front end together"
    )
