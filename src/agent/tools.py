"""Typed tool layer: JSON-schema validated arguments, hard timeouts, a read/write sandbox.

Matches the orchestration specification (section 3): strict types, wall-clock timeouts and typed
failures. Write tools can only create files below the sandbox output directory.
"""

import dataclasses
import enum
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


class ToolExecutionError(Exception):
    """Typed tool failure with a machine-readable code and payload."""

    def __init__(self, code: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": str(self), **self.payload}}


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses, enums and tuples into plain JSON data."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


_TYPES: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_arguments(schema: Dict[str, Any], args: Any) -> None:
    """Validate against the JSON-schema subset used by tool specs (object of typed fields)."""
    if not isinstance(args, dict):
        raise ToolExecutionError("invalid_arguments", "arguments must be an object")
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            raise ToolExecutionError("invalid_arguments", f"missing required argument: {name}")
    for name, value in args.items():
        if name not in props:
            raise ToolExecutionError("invalid_arguments", f"unexpected argument: {name}")
        spec = props[name]
        expected = _TYPES[spec["type"]]
        bad_bool = spec["type"] in ("integer", "number") and isinstance(value, bool)
        if bad_bool or not isinstance(value, expected):
            raise ToolExecutionError("invalid_arguments", f"{name} must be {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolExecutionError("invalid_arguments", f"{name} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"]:
            raise ToolExecutionError("invalid_arguments", f"{name} must be >= {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise ToolExecutionError("invalid_arguments", f"{name} must be <= {spec['maximum']}")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Any]
    writes: bool = False
    timeout_s: Optional[float] = None  # None: the registry default from configuration
    untrusted: bool = False  # output carries third-party content (documents, passages)

    def as_function(self) -> Dict[str, Any]:
        """OpenAI-compatible function descriptor (the format model APIs expect)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def schema(properties: Dict[str, Dict[str, Any]], required: Sequence[str] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required)}


@dataclass
class ToolRegistry:
    tools: Dict[str, ToolSpec] = field(default_factory=dict)
    default_timeout_s: float = 30.0  # overridden from `agent.default_tool_timeout_s`

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self.tools:
            raise ValueError(f"duplicate tool: {spec.name}")
        self.tools[spec.name] = spec

    def functions(self) -> List[Dict[str, Any]]:
        return [t.as_function() for t in self.tools.values()]

    def call(self, name: str, args: Any) -> Any:
        """Validate, execute under a wall-clock timeout, and return JSON-able data."""
        spec = self.tools.get(name)
        if spec is None:
            raise ToolExecutionError("unknown_tool", f"unknown tool: {name}")
        validate_arguments(spec.parameters, args)
        box: Dict[str, Any] = {}

        def run() -> None:
            try:
                box["value"] = spec.handler(args)
            except ToolExecutionError as exc:
                box["error"] = exc
            except Exception as exc:  # no unchecked exceptions cross the tool boundary
                box["error"] = ToolExecutionError("tool_failed", f"{type(exc).__name__}: {exc}")

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        limit = spec.timeout_s or self.default_timeout_s
        worker.join(limit)
        if worker.is_alive():
            raise ToolExecutionError("timeout", f"{name} exceeded {limit:.0f}s")
        if "error" in box:
            raise box["error"]
        return to_jsonable(box["value"])


@dataclass(frozen=True)
class Sandbox:
    """Reads are limited to `read_roots`; writes only create files under `output_dir`."""

    read_roots: Sequence[Path]
    output_dir: Path
    policy: Optional[Any] = None  # PathPolicy: deny-list of internal and secret files
    denied_message: str = "this file is internal or secret and cannot be read"
    base: Optional[Path] = None  # relative paths resolve against the project root

    def resolve_read(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        anchor = self.base or Path.cwd()
        path = (path if path.is_absolute() else anchor / path).resolve()
        for root in [*self.read_roots, self.output_dir]:
            if path == root.resolve() or root.resolve() in path.parents:
                if self.policy is not None and self.policy.denied(path):
                    raise ToolExecutionError("denied", self.denied_message)
                return path
        raise ToolExecutionError("outside_sandbox", "read not allowed outside the sandbox")

    def resolve_write(self, raw: str) -> Path:
        out = self.output_dir.resolve()
        path = (out / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if out not in path.parents:
            raise ToolExecutionError("outside_sandbox", "writes are limited to the output folder")
        return path


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
