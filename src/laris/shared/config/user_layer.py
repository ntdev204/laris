"""The user's saved settings (`~/.laris/settings.json`) as a configuration layer.

Lives in `config` so that configuration loading needs nothing from `harness`. The file format is in
`laris.shared.config.settings`; this module keeps the names the loader and the panel use.
"""

from pathlib import Path
from typing import Any, Dict, Tuple

import laris.shared.config.settings as settings
from laris.shared.config.settings import layer_from, read_raw

# flat key shown in the chat settings panel -> (dotted path in settings.json, python type)
EDITABLE: Dict[str, Tuple[str, type]] = {
    "base_url": ("server.url", str),
    "model": ("model", str),
    "auto_compact": ("context.autoCompact", bool),
    "context_window": ("context.windowTokens", int),
    "compact_threshold": ("context.compactThreshold", float),
    "allow_write": ("permissions.defaultMode", bool),  # True = acceptEdits, False = default
    "learning_enabled": ("learning.collect", bool),
    "vault_record": ("vault.autoRecord", bool),
}


def read_settings(path: Path) -> Dict[str, Any]:
    return read_raw(path)


def flat_view(data: Dict[str, Any]) -> Dict[str, Any]:
    """The settings panel's flat keys, for the values the file sets."""
    out: Dict[str, Any] = {}
    for key, (dotted, _) in EDITABLE.items():
        try:
            value = settings.get_path(data, dotted)
        except KeyError:
            continue
        out[key] = value == "acceptEdits" if key == "allow_write" else value
    if "extraInstructions" in data:
        out["extra_instructions"] = data["extraInstructions"]
    return out


__all__ = ["EDITABLE", "flat_view", "layer_from", "read_settings"]
