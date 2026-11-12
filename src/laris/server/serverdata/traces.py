"""The model's private reasoning, kept on the server for the operator only.

Nothing stored here is returned by any chat route. Secrets are redacted before storing and old
traces are purged by retention. Reading goes through the local `laris-server reasoning` commands.
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional

from laris.server.serverdata.db import Database
from laris.server.serving.ports import Principal

Redactor = Callable[[str], str]


class TraceStore:
    def __init__(self, db: Database, redact: Redactor = lambda text: text) -> None:
        self.db = db
        self.redact = redact

    def record(self, principal: Principal, trace: Dict[str, Any]) -> None:
        self.db.connection().execute(
            "INSERT INTO traces (key_id, ts, session_id, model, prompt_sha256, task, reasoning,"
            " tool_calls, brain, answer_chars) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                principal.key_id,
                time.time(),
                str(trace.get("session_id", ""))[:64],
                str(trace.get("model", ""))[:80],
                str(trace.get("prompt_sha256", "")),
                self.redact(str(trace.get("task", "")))[:2000],
                self.redact(str(trace.get("reasoning", ""))),
                self.redact(json.dumps(trace.get("tool_calls", []), ensure_ascii=False)),
                json.dumps(trace.get("brain", []), ensure_ascii=False),
                int(trace.get("answer_chars", 0)),
            ),
        )  # fmt: skip

    def list(self, key_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT id, key_id, ts, session_id, model, task, length(reasoning) AS reasoning_chars"
        sql += " FROM traces" + (" WHERE key_id=?" if key_id else "") + " ORDER BY id DESC LIMIT ?"
        args = ([key_id] if key_id else []) + [limit]
        return [dict(r) for r in self.db.connection().execute(sql, args).fetchall()]

    def get(self, trace_id: int) -> Optional[Dict[str, Any]]:
        row = (
            self.db.connection().execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone()
        )
        return dict(row) if row else None

    def purge(self, older_than_days: float) -> int:
        cutoff = time.time() - older_than_days * 86400
        cursor = self.db.connection().execute("DELETE FROM traces WHERE ts < ?", (cutoff,))
        return int(cursor.rowcount)
