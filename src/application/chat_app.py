"""Chat application core shared by the web UI and the terminal: conversations, preferences,
uploads and model calls. Every limit and policy comes from the harness runtime (configuration)."""

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from agent.builtin_tools import build_registry
from agent.context import CompactionResult, ContextManager, Summarizer
from agent.conversations import ConversationStore, title_from
from agent.loop import AgentSession, Approver
from agent.provider import ChatProvider, HttpChatProvider, OfflinePlanner
from agent.tools import Sandbox, ToolSpec
from application.service import SearchService
from application.workspace import IngestError, chunks_from_bytes
from harness.policy import egress_allowed
from harness.prefs import UserPrefs, effective
from harness.runtime import HarnessRuntime
from harness.workflows import WorkflowError, WorkflowSpec
from skills import SkillLibrary


class PolicyError(RuntimeError):
    """A configuration policy blocks the action (for example a non-local model API)."""


class ChatApp:
    def __init__(
        self,
        service: SearchService,
        project_root: Optional[Path] = None,
        chat_dir: Optional[Path] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.service = service
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.overrides = overrides
        base = HarnessRuntime.load(self.project_root, overrides)
        chosen = Path(chat_dir) if chat_dir else Path(base.config.app.chat_dir)
        self.root = chosen if chosen.is_absolute() else self.project_root / chosen
        self.conversations = ConversationStore(self.root / "conversations")
        self.prefs = UserPrefs(
            self.root / "settings.json", base.config.prompts.user_preferences_max_chars
        )
        self.uploads = self.root / "uploads"
        self.output = self.root / "output"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.memory_dir = self.project_root / base.config.prompts.memory_dir

    # -- runtime ---------------------------------------------------------------------------
    @property
    def runtime(self) -> HarnessRuntime:
        """Configuration resolved now, so saved preferences and file edits apply immediately."""
        return HarnessRuntime.load(self.project_root, self.overrides, self.prefs.layer())

    def skills_for(self, runtime: HarnessRuntime) -> SkillLibrary:
        roots = []
        for entry in runtime.config.prompts.skill_roots:
            path = Path(entry).expanduser()
            roots.append(
                (
                    path if path.is_absolute() else self.project_root / path,
                    "user" if entry.startswith("~") else "project",
                )
            )
        return SkillLibrary(roots)

    def settings(self) -> Dict[str, Any]:
        return effective(self.runtime.config, self.prefs.extra_instructions)

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        self.prefs.update(changes)
        return self.settings()

    # -- model -----------------------------------------------------------------------------
    def provider(self, runtime: HarnessRuntime) -> ChatProvider:
        api = runtime.config.model_api
        if api.base_url:
            if not egress_allowed(api.base_url, api.allow_remote):
                raise PolicyError(runtime.strings.get("guard.remote_denied"))
            return HttpChatProvider(
                api.base_url, api.model, api.api_key_env or None, api.timeout_s, api.temperature
            )
        agent = runtime.config.agent
        return OfflinePlanner(
            runtime.strings,
            self.service.has_model,
            runtime.config.app.search_default_top_k,
            agent.read_max_chars // 5,
        )

    def model_health(self) -> Dict[str, Any]:
        runtime = self.runtime
        api = runtime.config.model_api
        if not api.base_url:
            return {"mode": "offline", "ok": True, "detail": "built-in scripted planner (no model)"}
        if not egress_allowed(api.base_url, api.allow_remote):
            return {
                "mode": "api",
                "ok": False,
                "detail": runtime.strings.get("guard.remote_denied"),
            }
        try:
            with urllib.request.urlopen(api.base_url.rstrip("/") + "/models", timeout=5) as r:
                names = [m["id"] for m in json.loads(r.read()).get("data", [])]
            return {"mode": "api", "ok": True, "detail": f"connected, models: {', '.join(names)}"}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            return {"mode": "api", "ok": False, "detail": "cannot reach the model API"}

    # -- uploads ---------------------------------------------------------------------------
    def _display(self, path: Path) -> str:
        """Project-relative path; absolute only when chat state lives outside the project."""
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path)

    def upload(self, name: str, data_base64: str, ingest: bool) -> Dict[str, Any]:
        cfg = self.runtime.config.app
        safe = re.sub(r"[^\w.\- ]", "_", Path(name).name).strip() or "upload"
        data = base64.b64decode(data_base64)
        if len(data) > cfg.upload_max_bytes:
            raise IngestError(f"file too large ({cfg.upload_max_bytes // (1024 * 1024)} MB limit)")
        path = self.uploads / safe
        path.write_bytes(data)
        result: Dict[str, Any] = {
            "name": safe,
            "path": self._display(path),
            "bytes": len(data),
        }
        if ingest:
            result["ingested"] = self.service.workspace.add(chunks_from_bytes(safe, data, cfg))
        return result

    # -- context ---------------------------------------------------------------------------
    def _summarizer(self, provider: ChatProvider, runtime: HarnessRuntime) -> Optional[Summarizer]:
        if isinstance(provider, OfflinePlanner):
            return None  # no model: compaction falls back to a deterministic summary
        strings = runtime.strings

        def summarize(transcript: str, instructions: str) -> Optional[str]:
            ask = strings.get("compaction.summarizer_instruction")
            if instructions:
                ask += "\n" + strings.get("compaction.summarizer_focus", focus=instructions)
            turn = provider.chat(
                [{"role": "system", "content": ask}, {"role": "user", "content": transcript}], []
            )
            return turn.content

        return summarize

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
        runtime = self.runtime
        skills = self.skills_for(runtime)
        provider = self.provider(runtime)
        skill_roots = [r for r, _ in skills.roots]
        sandbox = Sandbox(
            [self.project_root, self.uploads, *skill_roots],
            self.output,
            policy=runtime.paths,
            denied_message=runtime.strings.get("guard.read_denied"),
            base=self.project_root,
        )
        registry = build_registry(self.service, sandbox, runtime, skills, self.memory_dir)
        return AgentSession(
            provider,
            registry,
            runtime,
            approve=approve,
            messages=list(conversation["messages"]),
            session_id=conversation["id"],
            skills=skills,
            extra_instructions=self.prefs.extra_instructions,
            context=ContextManager(
                runtime.config.context, runtime.strings, self._summarizer(provider, runtime)
            ),
            on_compact=self._archive(conversation["id"]),
            log_dir=self.root / "sessions",
            audit_dir=self.root / "audit",
        )

    def parse_workflow_command(
        self, text: str, runtime: HarnessRuntime
    ) -> Optional[Tuple[WorkflowSpec, str]]:
        """`/workflow name request` -> (spec, request) for a known workflow."""
        if not text.startswith("/workflow "):
            return None
        name, _, rest = text[len("/workflow ") :].strip().partition(" ")
        library = runtime.workflows()
        try:
            return library.get(name), rest.strip()
        except WorkflowError:
            return None

    def tool_specs(self) -> List[ToolSpec]:
        """Tools the agent has right now (for listings); nothing is executed."""
        session = self._session({"id": "tools", "messages": []})
        return list(session.registry.tools.values())

    def parse_skill_command(self, text: str, skills: SkillLibrary) -> Optional[Tuple[str, str]]:
        """`/name rest` -> (name, rest) when name is a known skill."""
        if not text.startswith("/"):
            return None
        name, _, rest = text[1:].partition(" ")
        return (name.lower(), rest.strip()) if name.lower() in skills.skills else None

    def send(
        self, conversation_id: str, text: str, approve: Optional[Approver] = None
    ) -> Generator[Dict[str, Any], None, None]:
        conversation = self.conversations.get(conversation_id)
        if not conversation["messages"]:
            conversation["title"] = title_from(text)
        try:
            session = self._session(conversation, approve)
        except PolicyError as exc:
            yield {"type": "done", "status": "blocked", "answer": str(exc)}
            return
        try:
            yield from session.send(
                text,
                self.parse_skill_command(text, session.skills or SkillLibrary([])),
                self.parse_workflow_command(text, self.runtime),
            )
        finally:  # keep what happened even if the client disconnects mid-stream
            conversation["messages"] = session.history
            self.conversations.save(conversation)

    def compact(
        self, conversation_id: str, instructions: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """Manual /compact: shrink the stored conversation now (same method as autocompact)."""
        conversation = self.conversations.get(conversation_id)
        session = self._session(conversation)
        yield from session.compact(instructions)
        conversation["messages"] = session.history
        self.conversations.save(conversation)

    def usage(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.conversations.get(conversation_id)
        event = self._session(conversation).usage_event()
        return {"tokens": event["tokens"], "window": event["window"]}

    def instruction_summary(self) -> Dict[str, Any]:
        """Internal files are only listed when `security.expose_internal_info` is true."""
        runtime = self.runtime
        files = runtime.composer.load_policy()
        if runtime.config.security.expose_internal_info:
            return {"count": len(files), "files": [{"file": f, "chars": len(t)} for f, t in files]}
        return {"count": len(files)}
