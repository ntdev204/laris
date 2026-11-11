"""Persistent conversations (JSON files) and user settings for the chat front ends."""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_ID = re.compile(r"^[0-9a-f]{12}$")


class ConversationStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, conversation_id: str) -> Path:
        if not _ID.match(conversation_id):
            raise KeyError(conversation_id)
        return self.root / f"{conversation_id}.json"

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
        path = self._path(conversation_id)
        if not path.exists():
            raise KeyError(conversation_id)
        data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def save(self, conversation: Dict[str, Any]) -> None:
        conversation["updated"] = time.time()
        path = self._path(conversation["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(conversation, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def delete(self, conversation_id: str) -> None:
        self._path(conversation_id).unlink(missing_ok=True)

    def list(self) -> List[Dict[str, Any]]:
        rows = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rows.append(
                    {k: data[k] for k in ("id", "title", "created", "updated")}
                    | {"messages": len(data.get("messages", []))}
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(rows, key=lambda r: -r["updated"])


def title_from(text: str, limit: int = 48) -> str:
    line = " ".join(text.split())
    return (line[: limit - 1] + "…") if len(line) > limit else (line or "Cuộc trò chuyện mới")


def last_assistant(messages: List[Dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return None
