"""User preferences: the few settings a user may change at runtime (web settings panel, /model).

Preferences are saved as JSON and applied as a configuration layer above the YAML files and below
environment variables, so deployers can still pin any value with `LARIS_*`. Security settings are
not editable here. Anything invalid is rejected before it is saved.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from laris.shared.config.schemas import LarisConfig
from laris.shared.config.user_layer import EDITABLE, layer_from, read_settings

ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
EXTRA_KEY = "extra_instructions"


class PrefsError(ValueError):
    """Raised when a preference is unknown, mistyped or violates the configuration schema."""


class UserPrefs:
    def __init__(self, path: Path, extra_max_chars: int = 1200) -> None:
        self.path = Path(path)
        self.extra_max_chars = extra_max_chars

    def raw(self) -> Dict[str, Any]:
        return read_settings(self.path)

    @property
    def extra_instructions(self) -> str:
        return str(self.raw().get(EXTRA_KEY, ""))[: self.extra_max_chars]

    def layer(self, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Nested configuration dict for `load_config(extra_layers=[...])`."""
        return layer_from(self.raw() if raw is None else raw)

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
        if "api_key" in data:  # the settings file may hold the API key: owner-only
            self.path.chmod(0o600)
        return data


def effective(config: LarisConfig, extra_instructions: str = "") -> Dict[str, Any]:
    """Editable settings as the UI shows them, read from the resolved configuration."""
    return {
        "base_url": config.model_api.base_url,
        "model": config.model_api.model,
        "api_key_env": config.model_api.api_key_env,
        "ca_file": config.model_api.ca_file,
        "auto_compact": config.context.enabled,
        "context_window": config.context.window_tokens,
        "compact_threshold": config.context.threshold,
        "allow_write": config.agent.approval.mode == "auto",
        "learning_enabled": config.learning.enabled,
        "vault_record": config.vault.auto_record,
        EXTRA_KEY: extra_instructions,
    }
