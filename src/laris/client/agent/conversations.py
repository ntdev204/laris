"""Persistent conversations (SQLite) and user settings for the chat front ends."""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from laris.client.store import Store, migrate_legacy

_ID = re.compile(r"^[0-9a-f]{12}$")


class ConversationStore:
    """Conversations in SQLite: `store` (a private space) or `<root>/conversations.sqlite`. Earlier
    `<root>/<id>.json` files are imported once, with a backup."""

    def __init__(self, root: Path, store: Optional[Store] = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store or Store(self.root / "conversations.sqlite")
        migrate_legacy(self.store, conversations=self.root)

    @staticmethod
    def _check(conversation_id: str) -> str:
        if not _ID.match(conversation_id):
            raise KeyError(conversation_id)
        return conversation_id

    def create(self, title: str = "Cuộc trò chuyện mới") -> Dict[str, Any]:
        now = time.time()
        conversation = {
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "created": now,
            "updated": now,
            "messages": [],
        }
        self.save(conversation)
        return conversation

    def get(self, conversation_id: str) -> Dict[str, Any]:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT data FROM conversations WHERE id = ?", (self._check(conversation_id),)
            ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        data: Dict[str, Any] = json.loads(row[0])
        return data

    def save(self, conversation: Dict[str, Any]) -> None:
        conversation["updated"] = time.time()
        self._check(conversation["id"])
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?)",
                (
                    conversation["id"],
                    conversation["title"],
                    conversation["created"],
                    conversation["updated"],
                    json.dumps(conversation, ensure_ascii=False),
                ),
            )

    def delete(self, conversation_id: str) -> None:
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (self._check(conversation_id),))

    def list(self) -> List[Dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, created, updated, "
                "json_array_length(data, '$.messages') FROM conversations ORDER BY updated DESC"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created": r[2], "updated": r[3], "messages": r[4] or 0}
            for r in rows
        ]


def title_from(text: str, limit: int = 48) -> str:
    line = " ".join(text.split())
    return (line[: limit - 1] + "…") if len(line) > limit else (line or "Cuộc trò chuyện mới")


def last_assistant(messages: List[Dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return None
