"""Token metering per key. `None` as limit means unlimited."""

import time
from typing import Any, Dict, List, Optional

from laris.server.serverdata.db import Database
from laris.server.serving.ports import Principal, QuotaExceeded


class UsageStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _limits(self, key_id: str) -> Optional[Any]:
        return (
            self.db.connection()
            .execute("SELECT token_limit, tokens_used FROM keys WHERE id=?", (key_id,))
            .fetchone()
        )

    def check(self, principal: Principal, estimated_tokens: int) -> None:
        if principal.key_id == "static":
            return
        row = self._limits(principal.key_id)  # fresh: the limit may have changed since login
        if row is None:
            raise QuotaExceeded("key no longer exists")
        limit = row["token_limit"]
        if limit is not None and row["tokens_used"] + max(0, estimated_tokens) > limit:
            raise QuotaExceeded("token quota used up")

    def record(self, principal: Principal, usage: Dict[str, Any]) -> None:
        if principal.key_id == "static":
            return
        prompt = int(usage.get("prompt_tokens", 0))
        completion = int(usage.get("completion_tokens", 0))
        now = time.time()
        conn = self.db.connection()
        conn.execute(
            "INSERT INTO usage (key_id, ts, session_id, kind, prompt_tokens, completion_tokens)"
            " VALUES (?,?,?,?,?,?)",
            (principal.key_id, now, str(usage.get("session_id", ""))[:64],
             str(usage.get("kind", "chat")), prompt, completion),
        )  # fmt: skip
        conn.execute(
            "UPDATE keys SET tokens_used = tokens_used + ?, last_used_at = ? WHERE id = ?",
            (prompt + completion, now, principal.key_id),
        )

    def account(self, principal: Principal) -> Dict[str, Any]:
        row = self._limits(principal.key_id) if principal.key_id != "static" else None
        limit = row["token_limit"] if row else None
        used = row["tokens_used"] if row else 0
        return {
            "role": principal.role,
            "permissions": sorted(principal.permissions),
            "token_limit": limit,  # null = unlimited
            "tokens_used": used,
            "tokens_left": None if limit is None else max(0, limit - used),
        }

    def summary(self, since: float = 0.0) -> List[Dict[str, Any]]:
        rows = (
            self.db.connection()
            .execute(
                "SELECT key_id, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt,"
                " SUM(completion_tokens) AS completion FROM usage WHERE ts >= ?"
                " GROUP BY key_id ORDER BY key_id",
                (since,),
            )
            .fetchall()
        )
        return [dict(r) for r in rows]
