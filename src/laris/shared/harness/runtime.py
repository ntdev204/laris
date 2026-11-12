"""HarnessRuntime: resolved configuration plus every component the loop needs."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import laris.shared.harness.integrity as integrity
import laris.shared.harness.trust as trust
from laris.shared.brain import Brain
from laris.shared.config.loader import load_runtime_config
from laris.shared.config.schemas import LarisConfig
from laris.shared.harness.audit import AuditLog
from laris.shared.harness.guard import Guard, InjectionScanner, LeakDetector, SecretRedactor
from laris.shared.harness.remote import (
    PUBLIC_STRINGS,
    NoBrain,
    RemoteComposer,
    RemoteWorkflows,
    ServerClient,
    use_server_policy,
)
from laris.shared.harness.strings import StringCatalogue
from laris.shared.policy.policy import ApprovalPolicy, PathPolicy
from laris.shared.policy.prompts import ComposedPrompt, PromptComposer
from laris.shared.policy.verifier import AnswerVerifier
from laris.shared.policy.workflows import WorkflowLibrary
from laris.shared.skills import SkillLibrary


@dataclass
class SessionHarness:
    """Per-session state: the composed prompt, a guard primed with it, and the audit log."""

    prompt: ComposedPrompt
    guard: Guard
    audit: AuditLog


class HarnessRuntime:
    def __init__(
        self,
        config: Optional[LarisConfig] = None,
        project_root: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.config = config or LarisConfig()
        self.root = Path(project_root or Path.cwd()).resolve()
        trust.install(self.config.model_api.ca_file)  # a pinned private certificate, if any
        self.environ = os.environ if environ is None else environ
        # remote: the system policy lives on the model server; nothing of it is read here
        self.remote = use_server_policy(self.config, self.root)
        self.integrity_problems = [] if self.remote else self._check_integrity()
        prompts_dir = Path(self.config.prompts.dir)
        folder = prompts_dir if prompts_dir.is_absolute() else self.root / prompts_dir
        self.strings = StringCatalogue.load(
            PUBLIC_STRINGS if self.remote else folder / "strings.yaml"
        )
        if not self.remote:  # newer built-in messages fill any gap in the locked policy catalogue
            self.strings = self.strings.merged_over(StringCatalogue.load(PUBLIC_STRINGS))
        self.redactor = SecretRedactor(self.config.security, self.strings, self.root, self.environ)
        self.injection = InjectionScanner(self.config.security)
        self.composer: Any = (
            RemoteComposer(self.config, self.root)
            if self.remote
            else PromptComposer(self.config, self.root)
        )
        self.approval = ApprovalPolicy(self.config.agent)
        self.paths = PathPolicy(self.config.security.deny_read_globs, self.root)
        chat_dir = self.config.app.chat_dir.strip("/")
        for private in ("conversations", "archive", "sessions", "audit", "users"):  # user data
            self.paths.add_deny(f"{chat_dir}/{private}/**")
        self.paths.add_deny(f"{chat_dir}/settings.json")
        self.paths.add_deny(f"{self.config.learning.dir.strip('/')}/**")  # collected training data
        brain_dir = self.config.prompts.brain_dir.strip("/")
        self.paths.add_deny(brain_dir)  # the system brain, folder and contents
        self.paths.add_deny(f"{brain_dir}/**")
        self.verifier = AnswerVerifier(self.config.agent.verify)
        self._brain: Optional[Brain] = None
        self._no_brain = NoBrain()

    def _check_integrity(self) -> list:
        mode = self.config.prompts.integrity
        if mode == "off":
            return []
        problems = integrity.verify(self.root, self.config.prompts)
        if problems and mode == "enforce":
            raise integrity.IntegrityError(
                "protected policy files do not match the integrity lock: " + "; ".join(problems[:5])
            )
        return problems

    def _vault_root(self) -> Path:
        folder = Path(self.config.vault.dir)
        return folder if folder.is_absolute() else self.root / folder

    @property
    def brain(self) -> Brain:
        """The system brain (read-only, protected). Built on first use; remote: server only."""
        if self.remote:
            return self._no_brain  # type: ignore[return-value]
        if self._brain is None:
            folder = Path(self.config.prompts.brain_dir)
            self._brain = Brain(
                folder if folder.is_absolute() else self.root / folder,
                self.config.brain,
                self.redactor.redact,
                knowledge_dir=self._vault_root() / self.config.vault.knowledge_dir,
                scan=self.injection.flagged,
            )
        return self._brain

    def server_client(self) -> ServerClient:
        from laris.shared.harness.credentials import load_saved

        api = self.config.model_api
        key = self.environ.get(self.config.app.key_env) or load_saved(self.config.app)
        return ServerClient(api.base_url, key)

    def workflows(self) -> Any:
        if self.remote:
            return RemoteWorkflows(self.server_client() if self.config.model_api.base_url else None)
        folder = Path(self.config.prompts.workflows_dir)
        return WorkflowLibrary(folder if folder.is_absolute() else self.root / folder)

    @classmethod
    def load(
        cls,
        project_root: Optional[Path] = None,
        overrides: Optional[Dict[str, Any]] = None,
        user_layer: Optional[Dict[str, Any]] = None,
    ) -> "HarnessRuntime":
        root = Path(project_root or Path.cwd())
        config = load_runtime_config(root, overrides=overrides, user_layer=user_layer)
        return cls(config, root)

    def begin(
        self,
        session_id: str,
        skills: Optional[SkillLibrary] = None,
        extra_instructions: str = "",
        audit_dir: Optional[Path] = None,
        workflow_text: str = "",
    ) -> SessionHarness:
        prompt = self.composer.compose(
            session_id, skills, extra_instructions, workflow_text=workflow_text
        )
        sources = list(prompt.confidential_sources)
        if self.config.brain.enabled and not self.remote:
            sources += self.brain.texts()  # brain text counts as confidential for leak detection
        leak = LeakDetector(self.config.security, sources, prompt.canary)
        guard = Guard(self.config.security, self.strings, self.redactor, leak, self.injection)
        audit = AuditLog(audit_dir, session_id, self.redactor, enabled=audit_dir is not None)
        return SessionHarness(prompt, guard, audit)
