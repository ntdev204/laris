"""Audit trail: metadata only (event type, tool name, status, sizes, timing), never content."""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from laris.shared.harness.guard import SecretRedactor

MAX_FIELD_CHARS = 200


class AuditLog:
    def __init__(
        self,
        directory: Optional[Path],
        session_id: str,
        redactor: SecretRedactor,
        enabled: bool = True,
    ) -> None:
        self.path = Path(directory) / f"{session_id}.jsonl" if directory and enabled else None
        self.redactor = redactor
        self.seq = 0
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **fields: Any) -> None:
        if self.path is None:
            return
        self.seq += 1
        row: Dict[str, Any] = {"seq": self.seq, "ts": round(time.time(), 3), "event": kind}
        for key, value in fields.items():
            if isinstance(value, str):
                value = self.redactor.redact(value[:MAX_FIELD_CHARS])[0]
            elif not isinstance(value, (int, float, bool, type(None))):
                value = str(value)[:MAX_FIELD_CHARS]
            row[key] = value
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
