"""Chat application core shared by the web UI and the terminal: conversations, preferences,
uploads and model calls. Every limit and policy comes from the harness runtime (configuration)."""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from laris.client.agent.builtin_tools import build_registry
from laris.client.agent.coding_tools import (
    Checkpoints,
    CodingContext,
    preview_change,
)
from laris.client.agent.context import CompactionResult, ContextManager, Summarizer
from laris.client.agent.conversations import ConversationStore, title_from
from laris.client.agent.loop import AgentSession, Approver
from laris.client.agent.provider import (
    ChatProvider,
    HttpChatProvider,
    OfflinePlanner,
    PolicyServerProvider,
)
from laris.client.agent.tools import Sandbox, ToolSpec
from laris.client.application.service import SearchService
from laris.client.application.workspace import IngestError, chunks_from_bytes
from laris.client.hooks import HookOutcome, HookRunner
from laris.client.learning.collector import Collector
from laris.client.learning.hooks import make_ingest_hook
from laris.client.permissions import PermissionEngine
from laris.client.project_state import ProjectState
from laris.shared.config import settings as settings_mod
from laris.shared.harness.prefs import UserPrefs, effective
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.policy.policy import egress_allowed
from laris.shared.policy.workflows import WorkflowError, WorkflowSpec
from laris.shared.skills import SkillLibrary


def _egress_ok(runtime: HarnessRuntime) -> bool:
    """Plain http to a non-local host needs `allow_remote`; https to the policy server is fine
    (a client holds no internal prompts, so the only data sent is the user's own work)."""
    api = runtime.config.model_api
    secure = runtime.remote and api.base_url.startswith("https://")
    return secure or egress_allowed(api.base_url, api.allow_remote)


class PolicyError(RuntimeError):
    """A configuration policy blocks the action (for example a non-local model API)."""


class ChatApp:
    def __init__(
        self,
        service: SearchService,
        project_root: Optional[Path] = None,
        chat_dir: Optional[Path] = None,
        overrides: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
    ) -> None:
        self.service = service
        self.user = user
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.overrides = overrides
        base = HarnessRuntime.load(self.project_root, overrides)
        chosen = Path(chat_dir) if chat_dir else Path(base.config.app.chat_dir)
        self.root = chosen if chosen.is_absolute() else self.project_root / chosen
        if user:  # one private conversation space per API key
            self.root = self.root / base.config.app.users_dir / user
        self.conversations = ConversationStore(self.root / "conversations")
        settings = (
            Path(base.config.app.settings_file).expanduser()
            if base.config.app.settings_file
            else self.root / "settings.json"
        )
        self.prefs = UserPrefs(settings, base.config.prompts.user_preferences_max_chars)
        self.uploads = self.root / "uploads"
        self.output = self.root / "output"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.memory_dir = self.project_root / base.config.prompts.memory_dir
        self.service.on_ingest = make_ingest_hook(lambda: self.runtime)
        home = settings.parent
        self.sandbox_manager: Optional[Any] = None  # set by the front end that owns the sandbox
        self.hook_context: List[str] = []  # what SessionStart hooks asked the model to know
        self.hooks = HookRunner(settings, self.project_root)
        self.permissions = PermissionEngine(
            settings,
            ProjectState(home, self.project_root),
            self.project_root,
            sandbox_bin=home / ".venv" / "bin",
            allow_bypass=base.config.agent.approval.allow_bypass,
            always_ask=tuple(base.config.agent.approval.always_ask),
        )

    # -- runtime ---------------------------------------------------------------------------
    @property
    def runtime(self) -> HarnessRuntime:
        """Configuration resolved now, so saved preferences and file edits apply immediately."""
        return HarnessRuntime.load(self.project_root, self.overrides, self.prefs.layer())

    def skills_for(self, runtime: HarnessRuntime) -> SkillLibrary:
        roots = []
        trusted = ProjectState(Path(self.prefs.path).parent, self.project_root).trusted
        for entry in runtime.config.prompts.skill_roots:
            path = Path(entry).expanduser()
            kind = "user" if entry.startswith("~") else "project"
            if kind == "project" and not trusted:
                continue  # an untrusted folder's skills are not used (SR-C5)
            roots.append((path if path.is_absolute() else self.project_root / path, kind))
        return SkillLibrary(roots)

    def settings(self) -> Dict[str, Any]:
        return effective(self.runtime.config, self.prefs.extra_instructions)

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        self.prefs.update(changes)
        return self.settings()

    # -- model -----------------------------------------------------------------------------
    def provider(self, runtime: HarnessRuntime) -> ChatProvider:
        api = runtime.config.model_api
        if runtime.remote:  # the system policy is on the server: there is no offline mode
            if not api.base_url:
                raise PolicyError(runtime.strings.get("server.not_configured"))
            if not _egress_ok(runtime):
                raise PolicyError(runtime.strings.get("guard.remote_denied"))
            return PolicyServerProvider(
                api.base_url, api.model, api.api_key_env or None, api.timeout_s, api.temperature
            )
        if api.base_url:
            if not egress_allowed(api.base_url, api.allow_remote):
                raise PolicyError(runtime.strings.get("guard.remote_denied"))
            return HttpChatProvider(
                api.base_url, api.model, api.api_key_env or None, api.timeout_s, api.temperature
            )
        raise PolicyError(runtime.strings.get("server.not_configured"))  # no offline mode (D16)

    def model_health(self) -> Dict[str, Any]:
        runtime = self.runtime
        api = runtime.config.model_api
        if not api.base_url:
            detail = runtime.strings.get("server.not_configured")
            return {"mode": "api", "ok": False, "detail": detail}
        if not _egress_ok(runtime):
            return {
                "mode": "api",
                "ok": False,
                "detail": runtime.strings.get("guard.remote_denied"),
            }
        try:
            headers = {}
            key = os.environ.get(api.api_key_env) if api.api_key_env else None
            if key:
                headers["Authorization"] = f"Bearer {key}"
            request = urllib.request.Request(api.base_url.rstrip("/") + "/models", headers=headers)
            with urllib.request.urlopen(request, timeout=5) as r:
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
            result["ingested"] = self.service.ingest(chunks_from_bytes(safe, data, cfg))
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
            if isinstance(provider, PolicyServerProvider):  # the server owns the instruction
                return (
                    provider.summarizer()
                    .chat(
                        [
                            {"role": "system", "content": "", "laris": {"focus": instructions}},
                            {"role": "user", "content": transcript},
                        ],
                        [],
                    )
                    .content
                )
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
        coding = self.coding(conversation["id"], runtime)
        registry = build_registry(
            self.service, sandbox, runtime, skills, self.memory_dir, coding=coding
        )
        return AgentSession(
            provider,
            registry,
            runtime,
            approve=approve,
            messages=list(conversation["messages"]),
            session_id=conversation["id"],
            skills=skills,
            extra_instructions="\n".join(
                [t for t in (self.prefs.extra_instructions, *self.hook_context) if t]
            ),
            context=ContextManager(
                runtime.config.context, runtime.strings, self._summarizer(provider, runtime)
            ),
            on_compact=self._archive(conversation["id"]),
            log_dir=self.root / "sessions",
            audit_dir=self.root / "audit",
            plan=conversation.get("plan"),
            permissions=self.permissions,
            hooks=self.hooks,
        )

    def coding(self, session_id: str, runtime: Optional[HarnessRuntime] = None) -> CodingContext:
        """What the coding tools of one session may touch, and where their checkpoints go."""
        rt = runtime or self.runtime
        home = Path(self.prefs.path).parent
        try:
            saved = settings_mod.validate(settings_mod.read_raw(self.prefs.path))
            extra = [Path(p).expanduser() for p in saved.permissions.additionalDirectories]
            env, inherit = dict(saved.env), saved.sandbox.inheritEnv
        except settings_mod.SettingsError:
            extra, env, inherit = [], {}, False
        cfg = rt.config.agent.coding
        folder = ProjectState(home, self.project_root).path.parent / "checkpoints" / session_id
        return CodingContext(
            root=self.project_root,
            cfg=cfg,
            policy=rt.paths,
            redact=lambda text: rt.redactor.redact(text)[0],
            checkpoints=Checkpoints(folder, cfg.checkpoint_keep),
            extra_roots=extra,
            sandbox=self.sandbox_manager,
            env=env,
            inherit_env=inherit,
        )

    def session_start(self, conversation_id: str) -> HookOutcome:
        """Run the `SessionStart` hooks once when a front end opens a session."""
        self.hooks.session_id = conversation_id
        self.hooks.sandbox = self.sandbox_manager
        outcome = self.hooks.run("SessionStart", {"source": "startup"})
        self.hook_context = list(outcome.context)
        return outcome

    def preview(self, tool: str, arguments: Dict[str, Any]) -> str:
        """The diff shown with an approval request for `Write` and `Edit`."""
        return preview_change(self.coding("preview"), tool, arguments)

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

    def how_to_use(self, runtime: Optional[HarnessRuntime] = None) -> str:
        """The prepared user guide, printed as written (no model call, no inference)."""
        rt = runtime or self.runtime
        if rt.remote:
            try:
                text = str(rt.server_client().get("/laris/help").get("text", "")).strip()
            except Exception:  # offline or rejected key: fall through to the short notice
                text = ""
            return text or rt.strings.get("help.missing")
        path = Path(rt.config.prompts.help_file).expanduser()
        path = path if path.is_absolute() else self.project_root / path
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        return rt.strings.get("help.missing")

    def is_help_command(self, text: str, runtime: HarnessRuntime) -> bool:
        return text.strip().lower() in {c.lower() for c in runtime.config.prompts.help_commands}

    def send(
        self, conversation_id: str, text: str, approve: Optional[Approver] = None
    ) -> Generator[Dict[str, Any], None, None]:
        conversation = self.conversations.get(conversation_id)
        runtime = self.runtime
        text = runtime.redactor.redact_secrets(text)[0]  # a typed key is never stored
        if not conversation["messages"]:
            conversation["title"] = title_from(text)
        if self.is_help_command(text, runtime):
            guide = self.how_to_use(runtime)
            conversation["messages"] += [
                {"role": "user", "content": text.strip(), "ui_only": True},
                {"role": "assistant", "content": guide, "ui_only": True},
            ]
            self.conversations.save(conversation)
            yield {"type": "text", "delta": guide}
            yield {"type": "done", "status": "completed", "answer": guide}
            return
        self.hooks.session_id = conversation_id
        submitted = self.hooks.run("UserPromptSubmit", {"prompt": text})
        for note in self.hooks.drain():
            yield {"type": "hook", **note}
        if submitted.blocked:
            yield {"type": "done", "status": "blocked", "answer": submitted.reason}
            return
        if submitted.context:
            text = text + "\n\n[Context from a hook]\n" + "\n".join(submitted.context)
        try:
            session = self._session(conversation, approve)
        except PolicyError as exc:
            yield {"type": "done", "status": "blocked", "answer": str(exc)}
            return
        try:
            message = text
            skill = self.parse_skill_command(text, session.skills or SkillLibrary([]))
            workflow = self.parse_workflow_command(text, self.runtime)
            stop_rounds = 0
            while True:
                final: Optional[Dict[str, Any]] = None
                for event in session.send(message, skill, workflow):
                    for note in self.hooks.drain():
                        yield {"type": "hook", **note}
                    if event["type"] == "done":
                        final = event
                    else:
                        yield event
                for note in self.hooks.drain():
                    yield {"type": "hook", **note}
                if final is None:
                    break
                if final["status"] == "completed" and stop_rounds < 1 and self.hooks.has("Stop"):
                    stop = self.hooks.run("Stop", {"answer": final.get("answer", "")})
                    for note in self.hooks.drain():
                        yield {"type": "hook", **note}
                    if stop.blocked:  # a Stop hook may ask for one more round of work
                        stop_rounds += 1
                        message, skill, workflow = stop.reason, None, None
                        continue
                yield self._learn(conversation_id, session)
                yield final
                break
        finally:  # keep what happened even if the client disconnects mid-stream
            session.seal_interrupted()  # a call without a result would make the history invalid
            conversation["messages"] = session.history
            conversation["plan"] = session.plan.to_list()  # an unfinished goal survives --resume
            self.conversations.save(conversation)

    # -- learning --------------------------------------------------------------------------
    def collector(self, runtime: Optional[HarnessRuntime] = None) -> Collector:
        rt = runtime or self.runtime
        folder = Path(rt.config.learning.dir)
        return Collector(
            rt.config.learning, folder if folder.is_absolute() else self.project_root / folder
        )

    def _learn(self, conversation_id: str, session: AgentSession) -> Dict[str, Any]:
        """Keep the finished turn for later fine-tuning when it passes the quality gate."""
        runtime = self.runtime
        history = session.history
        start = max(
            (
                i
                for i, m in enumerate(history)
                if m.get("role") == "user" and not m.get("compacted") and not m.get("harness")
            ),
            default=0,
        )
        if session.sh is None:
            return {"type": "learning", "stored": False, "reason": "no_session"}
        outcome = self.collector(runtime).record(
            conversation_id, history[start:], session.last_turn, session.sh.guard
        )
        try:
            from laris.client.vault.hooks import record_turn

            outcome.update(
                record_turn(
                    runtime,
                    conversation_id,
                    history[start:],
                    session.last_turn,
                    session.plan.summary_lines(),
                )
            )
        except Exception:  # keeping a note must never break a finished turn
            outcome["vault_status"] = "failed"
        outcome["type"] = "learning"
        return outcome

    def rate(self, example_id: str, rating: str) -> Dict[str, Any]:
        return self.collector().rate(example_id, rating)

    def learning_stats(self) -> Dict[str, Any]:
        return self.collector().stats()

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
