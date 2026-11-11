"""User preferences: the few settings a user may change at runtime (web settings panel, /model).

Preferences are saved as JSON and applied as a configuration layer above the YAML files and below
environment variables, so deployers can still pin any value with `LARIS_*`. Security settings are
not editable here. Anything invalid is rejected before it is saved.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config.schemas import LarisConfig

ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
# flat key -> (config path, python type)
EDITABLE: Dict[str, Tuple[Tuple[str, ...], type]] = {
    "base_url": (("model_api", "base_url"), str),
    "model": (("model_api", "model"), str),
    "api_key_env": (("model_api", "api_key_env"), str),
    "auto_compact": (("context", "enabled"), bool),
    "context_window": (("context", "window_tokens"), int),
    "compact_threshold": (("context", "threshold"), float),
    "allow_write": (("agent", "approval", "mode"), bool),
}
EXTRA_KEY = "extra_instructions"


class PrefsError(ValueError):
    """Raised when a preference is unknown, mistyped or violates the configuration schema."""


class UserPrefs:
    def __init__(self, path: Path, extra_max_chars: int = 1200) -> None:
        self.path = Path(path)
        self.extra_max_chars = extra_max_chars

    def raw(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def extra_instructions(self) -> str:
        return str(self.raw().get(EXTRA_KEY, ""))[: self.extra_max_chars]

    def layer(self, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Nested configuration dict for `load_config(extra_layers=[...])`."""
        data = self.raw() if raw is None else raw
        out: Dict[str, Any] = {}
        for key, (path, _) in EDITABLE.items():
            if key not in data:
                continue
            value: Any = data[key]
            if key == "allow_write":
                value = "auto" if value else "ask"
            node = out
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value
        return out

    def update(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        data = self.raw()
        for key, value in changes.items():
            if key == EXTRA_KEY:
                if not isinstance(value, str):
                    raise PrefsError(f"{key} must be text")
                data[key] = value[: self.extra_max_chars]
                continue
            if key not in EDITABLE:
                raise PrefsError(f"setting '{key}' cannot be changed here")
            expected = EDITABLE[key][1]
            ok = isinstance(value, expected) and not (
                expected is not bool and isinstance(value, bool)
            )
            if expected is float and isinstance(value, int) and not isinstance(value, bool):
                ok, value = True, float(value)
            if not ok:
                raise PrefsError(f"{key} must be {expected.__name__}")
            if key == "api_key_env" and value and not ENV_NAME.match(value):
                raise PrefsError("api_key_env must be an environment variable name")
            data[key] = value
        try:
            LarisConfig(**self.layer(data))  # reject values the schema refuses
        except Exception as exc:
            raise PrefsError(str(exc).splitlines()[0]) from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data


def effective(config: LarisConfig, extra_instructions: str = "") -> Dict[str, Any]:
    """Editable settings as the UI shows them, read from the resolved configuration."""
    return {
        "base_url": config.model_api.base_url,
        "model": config.model_api.model,
        "api_key_env": config.model_api.api_key_env,
        "auto_compact": config.context.enabled,
        "context_window": config.context.window_tokens,
        "compact_threshold": config.context.threshold,
        "allow_write": config.agent.approval.mode == "auto",
        EXTRA_KEY: extra_instructions,
    }
