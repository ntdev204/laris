"""The user's saved preferences (`~/.laris/settings.json`) as a configuration layer.

Lives in `config` so that configuration loading needs nothing from `harness`.
"""

import json
from pathlib import Path
from typing import Any, Dict, Tuple

# flat key -> (config path, python type)
EDITABLE: Dict[str, Tuple[Tuple[str, ...], type]] = {
    "base_url": (("model_api", "base_url"), str),
    "model": (("model_api", "model"), str),
    "api_key_env": (("model_api", "api_key_env"), str),
    "ca_file": (("model_api", "ca_file"), str),
    "auto_compact": (("context", "enabled"), bool),
    "context_window": (("context", "window_tokens"), int),
    "compact_threshold": (("context", "threshold"), float),
    "allow_write": (("agent", "approval", "mode"), bool),
    "learning_enabled": (("learning", "enabled"), bool),
    "vault_record": (("vault", "auto_record"), bool),
}


def read_settings(path: Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def layer_from(data: Dict[str, Any]) -> Dict[str, Any]:
    """Nested configuration dict for `load_config(extra_layers=[...])`."""
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
