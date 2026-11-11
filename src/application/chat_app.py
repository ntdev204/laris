"""Chat application core shared by the web UI: conversations, settings, uploads, model calls."""

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from agent.builtin_tools import build_registry
from agent.context import CompactionResult, ContextManager, Summarizer
from agent.conversations import (
    ConversationStore,
    SettingsStore,
    title_from,
)
from agent.loop import AgentSession, Approver
from agent.prompt import build_system_prompt
from agent.provider import ChatProvider, HttpChatProvider, OfflinePlanner
from agent.tools import Sandbox
from application.service import SearchService
from application.workspace import IngestError, chunks_from_bytes
from skills import SkillLibrary, default_skill_roots

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ChatApp:
    def __init__(
        self, service: SearchService, root: Path, project_root: Optional[Path] = None
    ) -> None:
        self.service = service
        self.root = Path(root)
        self.project_root = Path(project_root or Path.cwd())
        self.skills = SkillLibrary(default_skill_roots(self.project_root))
        self.memory_dir = self.project_root / ".laris" / "memory"
        self.conversations = ConversationStore(self.root / "conversations")
        self.settings = SettingsStore(self.root / "settings.json")
        self.uploads = self.root / "uploads"
        self.output = self.root / "output"
        self.uploads.mkdir(parents=True, exist_ok=True)
        skill_roots = [r for r, _ in self.skills.roots]
        self.sandbox = Sandbox([self.project_root, self.uploads, *skill_roots], self.output)

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

    # -- context ---------------------------------------------------------------------------
    def _summarizer(self) -> Optional[Summarizer]:
        provider = self.provider()
        if isinstance(provider, OfflinePlanner):
            return None  # no model: compaction falls back to a deterministic summary

        def summarize(transcript: str, instructions: str) -> Optional[str]:
            ask = (
                "Tóm tắt cuộc trò chuyện dưới đây để người trợ lý có thể tiếp tục công việc: "
                "mục tiêu của người dùng, quyết định đã chốt, tệp và nguồn đã dùng (giữ nguyên "
                "đường dẫn, tên nguồn, số liệu), việc còn dở. Viết ngắn gọn bằng tiếng Việt."
            )
            if instructions:
                ask += f"\nƯu tiên: {instructions}"
            turn = provider.chat(
                [{"role": "system", "content": ask}, {"role": "user", "content": transcript}], []
            )
            return turn.content

        return summarize

    def context_manager(self) -> ContextManager:
        cfg = self.settings.load()
        return ContextManager(
            window=cfg["context_window"],
            threshold=cfg["compact_threshold"],
            enabled=cfg["auto_compact"],
            summarizer=self._summarizer(),
        )

    def _archive(self, conversation_id: str) -> Any:
        def keep(result: CompactionResult) -> None:
            if not result.archived:
                return
            folder = self.root / "archive"
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{conversation_id}-{int(time.time())}.json"
            (folder / name).write_text(
                json.dumps(result.archived, ensure_ascii=False), encoding="utf-8"
            )

        return keep

    # -- conversation turns ----------------------------------------------------------------
    def _session(
        self, conversation: Dict[str, Any], approve: Optional[Approver] = None
    ) -> AgentSession:
        cfg = self.settings.load()
        self.skills.reload()  # skills and LARIS.md are re-read so edits apply immediately
        registry = build_registry(self.service, self.sandbox, self.skills, self.memory_dir)
        prompt = build_system_prompt(self.project_root, self.skills, cfg["system_prompt"])
        return AgentSession(
            self.provider(),
            registry,
            approve=approve or (lambda name, arguments: bool(cfg["allow_write"])),
            log_dir=self.root / "sessions",
            messages=[{"role": "system", "content": prompt}, *conversation["messages"]],
            session_id=conversation["id"],
            context=self.context_manager(),
            on_compact=self._archive(conversation["id"]),
        )

    def parse_skill_command(self, text: str) -> Optional[Tuple[str, str]]:
        """`/name rest` -> (name, rest) when name is a known skill."""
        if not text.startswith("/"):
            return None
        name, _, rest = text[1:].partition(" ")
        return (name.lower(), rest.strip()) if name.lower() in self.skills.skills else None

    def send(
        self, conversation_id: str, text: str, approve: Optional[Approver] = None
    ) -> Generator[Dict[str, Any], None, None]:
        conversation = self.conversations.get(conversation_id)
        if not conversation["messages"]:
            conversation["title"] = title_from(text)
        session = self._session(conversation, approve)
        try:
            yield from session.send(text, self.parse_skill_command(text))
        finally:  # keep what happened even if the client disconnects mid-stream
            conversation["messages"] = session.messages[1:]
            self.conversations.save(conversation)

    def compact(
        self, conversation_id: str, instructions: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """Manual /compact: shrink the stored conversation now (same method as autocompact)."""
        conversation = self.conversations.get(conversation_id)
        session = self._session(conversation)
        yield from session.compact(instructions)
        conversation["messages"] = session.messages[1:]
        self.conversations.save(conversation)

    def instruction_files(self) -> Any:
        from agent.prompt import load_instructions

        return load_instructions(self.project_root)

    def usage(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.conversations.get(conversation_id)
        event = self._session(conversation).usage_event()
        return {"tokens": event["tokens"], "window": event["window"]}
