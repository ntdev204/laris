"""Message catalogue: runtime text loaded from `.laris/prompts/strings.yaml`."""

from pathlib import Path
from typing import Any, Dict

import yaml


class StringCatalogue:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: Path) -> "StringCatalogue":
        if not path.is_file():
            raise FileNotFoundError(f"string catalogue missing: {path}")
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: expected a mapping")
        return cls(loaded)

    def merged_over(self, base: "StringCatalogue") -> "StringCatalogue":
        """This catalogue's entries win; anything missing comes from `base` (packaged defaults)."""
        data: Dict[str, Any] = {
            k: dict(v) if isinstance(v, dict) else v for k, v in base._data.items()
        }
        for group, items in self._data.items():
            if isinstance(items, dict) and isinstance(data.get(group), dict):
                data[group].update(items)
            else:
                data[group] = items
        return StringCatalogue(data)

    def get(self, key: str, **values: Any) -> str:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"missing string: {key}")
            node = node[part]
        text = " ".join(str(node).split()) if "\n" in str(node) else str(node)
        return text.format(**values) if values else text

    def keys(self) -> list:
        out = []
        for group, items in self._data.items():
            if isinstance(items, dict):
                out += [f"{group}.{name}" for name in items]
        return out
