"""User preferences: the few settings a user may change at runtime (web settings panel, /model).

Preferences are saved as JSON and applied as a configuration layer above the YAML files and below
environment variables, so deployers can still pin any value with `LARIS_*`. Security settings are
not editable here. Anything invalid is rejected before it is saved.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import laris.shared.config.settings as settings
from laris.shared.config.schemas import LarisConfig
from laris.shared.config.user_layer import EDITABLE, layer_from, read_settings

EXTRA_KEY = "extra_instructions"


class PrefsError(ValueError):
    """Raised when a preference is unknown, mistyped or violates the configuration schema."""


class UserPrefs:
    """The settings panel's view of `settings.json`: flat keys in, the nested file out."""

    def __init__(self, path: Path, extra_max_chars: int = 1200) -> None:
        self.path = Path(path)
        self.extra_max_chars = extra_max_chars

    def raw(self) -> Dict[str, Any]:
        """The nested settings as stored."""
        return read_settings(self.path)

    @property
    def extra_instructions(self) -> str:
        return str(self.raw().get("extraInstructions", ""))[: self.extra_max_chars]

    def layer(self, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Nested configuration dict for `load_config(extra_layers=[...])`."""
        return layer_from(self.raw() if raw is None else raw)

    def update(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        data = self.raw()
        for key, value in changes.items():
            if key == EXTRA_KEY:
                if not isinstance(value, str):
                    raise PrefsError(f"{key} must be text")
                data["extraInstructions"] = value[: self.extra_max_chars]
                continue
            if key not in EDITABLE:
                raise PrefsError(f"setting '{key}' cannot be changed here")
            dotted, expected = EDITABLE[key]
            ok = isinstance(value, expected) and not (
                expected is not bool and isinstance(value, bool)
            )
            if expected is float and isinstance(value, int) and not isinstance(value, bool):
                ok, value = True, float(value)
            if not ok:
                raise PrefsError(f"{key} must be {expected.__name__}")
            if key == "allow_write":
                value = "acceptEdits" if value else "default"
            try:
                data = settings.set_path(data, dotted, value)
            except settings.SettingsError as exc:
                raise PrefsError(str(exc)) from exc
        try:
            LarisConfig(**self.layer(data))  # reject values the configuration schema refuses
            settings.write(self.path, data)
        except settings.SettingsError as exc:
            raise PrefsError(str(exc)) from exc
        except Exception as exc:
            raise PrefsError(str(exc).splitlines()[0]) from exc
        return data


def effective(config: LarisConfig, extra_instructions: str = "") -> Dict[str, Any]:
    """Editable settings as the UI shows them, read from the resolved configuration."""
    return {
        "base_url": config.model_api.base_url,
        "model": config.model_api.model,
        "ca_file": config.model_api.ca_file,
        "auto_compact": config.context.enabled,
        "context_window": config.context.window_tokens,
        "compact_threshold": config.context.threshold,
        "allow_write": config.agent.approval.mode == "auto",
        "learning_enabled": config.learning.enabled,
        "vault_record": config.vault.auto_record,
        EXTRA_KEY: extra_instructions,
    }
