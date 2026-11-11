"""Chat application core shared by the web UI: conversations, settings, uploads, model calls."""

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from agent.builtin_tools import build_registry
from agent.conversations import (
    ConversationStore,
    SettingsStore,
    title_from,
)
from agent.loop import SYSTEM_PROMPT, AgentSession, Approver
from agent.provider import ChatProvider, HttpChatProvider, OfflinePlanner
from agent.tools import Sandbox
from application.service import SearchService
from application.workspace import IngestError, chunks_from_bytes

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ChatApp:
    def __init__(self, service: SearchService, root: Path) -> None:
        self.service = service
        self.root = Path(root)
        self.conversations = ConversationStore(self.root / "conversations")
        self.settings = SettingsStore(self.root / "settings.json")
        self.uploads = self.root / "uploads"
        self.output = self.root / "output"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.sandbox = Sandbox([Path.cwd(), self.uploads], self.output)

    # -- model -----------------------------------------------------------------------------
    def provider(self) -> ChatProvider:
        cfg = self.settings.load()
        if cfg["base_url"]:
            return HttpChatProvider(cfg["base_url"], cfg["model"], cfg["api_key_env"] or None)
        return OfflinePlanner(has_model=self.service.has_model)

    def model_health(self) -> Dict[str, Any]:
        cfg = self.settings.load()
        if not cfg["base_url"]:
            return {"mode": "offline", "ok": True, "detail": "built-in scripted planner (no model)"}
        try:
            with urllib.request.urlopen(cfg["base_url"].rstrip("/") + "/models", timeout=5) as r:
                names = [m["id"] for m in json.loads(r.read()).get("data", [])]
            return {"mode": "api", "ok": True, "detail": f"connected, models: {', '.join(names)}"}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            return {"mode": "api", "ok": False, "detail": f"cannot reach model API: {exc}"}

    # -- uploads ---------------------------------------------------------------------------
    def upload(self, name: str, data_base64: str, ingest: bool) -> Dict[str, Any]:
        safe = re.sub(r"[^\w.\- ]", "_", Path(name).name).strip() or "upload"
        data = base64.b64decode(data_base64)
        if len(data) > MAX_UPLOAD_BYTES:
            raise IngestError("file too large (25 MB limit)")
        path = self.uploads / safe
        path.write_bytes(data)
        result: Dict[str, Any] = {"name": safe, "path": str(path), "bytes": len(data)}
        if ingest:
            result["ingested"] = self.service.workspace.add(chunks_from_bytes(safe, data))
        return result

    # -- conversation turns ----------------------------------------------------------------
    def _session(
        self, conversation: Dict[str, Any], approve: Optional[Approver] = None
    ) -> AgentSession:
        cfg = self.settings.load()
        registry = build_registry(self.service, self.sandbox)
        prompt = cfg["system_prompt"] or SYSTEM_PROMPT
        return AgentSession(
            self.provider(),
            registry,
            approve=approve or (lambda name, arguments: bool(cfg["allow_write"])),
            log_dir=self.root / "sessions",
            messages=[{"role": "system", "content": prompt}, *conversation["messages"]],
            session_id=conversation["id"],
        )

    def send(
        self, conversation_id: str, text: str, approve: Optional[Approver] = None
    ) -> Generator[Dict[str, Any], None, None]:
        conversation = self.conversations.get(conversation_id)
        if not conversation["messages"]:
            conversation["title"] = title_from(text)
        session = self._session(conversation, approve)
        try:
            yield from session.send(text)
        finally:  # keep what happened even if the client disconnects mid-stream
            conversation["messages"] = session.messages[1:]
            self.conversations.save(conversation)
