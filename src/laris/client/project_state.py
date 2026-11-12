"""Per-project state in `~/.laris/projects/<slug>/state.json` (SR-C3, SR-C5, SR-C6).

Holds what the user decided about one folder: whether it is trusted (its custom commands and skills
may then be used) and, from T74, the tool approvals. Reads never raise; a damaged file is ignored.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

from laris.client.store.store import slug_of


class ProjectState:
    def __init__(self, home: Path, project_root: Path) -> None:
        self.path = Path(home).expanduser() / "projects" / slug_of(project_root) / "state.json"

    def read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)

    def update(self, **changes: Any) -> Dict[str, Any]:
        data = {**self.read(), **changes}
        self.write(data)
        return data

    @property
    def trusted(self) -> bool:
        return self.read().get("trusted") is True

    def trust(self, value: bool = True) -> None:
        self.update(trusted=value)
