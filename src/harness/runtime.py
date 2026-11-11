"""HarnessRuntime: resolved configuration plus every component the loop needs."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from config.loader import load_runtime_config
from config.schemas import LarisConfig
from harness.audit import AuditLog
from harness.guard import Guard, InjectionScanner, LeakDetector, SecretRedactor
from harness.policy import ApprovalPolicy, PathPolicy
from harness.prompts import ComposedPrompt, PromptComposer
from harness.strings import StringCatalogue
from harness.verifier import AnswerVerifier
from skills import SkillLibrary


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
        self.environ = os.environ if environ is None else environ
        prompts_dir = Path(self.config.prompts.dir)
        folder = prompts_dir if prompts_dir.is_absolute() else self.root / prompts_dir
        self.strings = StringCatalogue.load(folder / "strings.yaml")
        self.redactor = SecretRedactor(self.config.security, self.strings, self.root, self.environ)
        self.injection = InjectionScanner(self.config.security)
        self.composer = PromptComposer(self.config, self.root)
        self.approval = ApprovalPolicy(self.config.agent)
        self.paths = PathPolicy(self.config.security.deny_read_globs, self.root)
        chat_dir = self.config.app.chat_dir.strip("/")
        for private in ("conversations", "archive", "sessions", "audit"):  # other users' data
            self.paths.add_deny(f"{chat_dir}/{private}/**")
        self.paths.add_deny(f"{chat_dir}/settings.json")
        self.verifier = AnswerVerifier(self.config.agent.verify)

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
    ) -> SessionHarness:
        prompt = self.composer.compose(session_id, skills, extra_instructions)
        leak = LeakDetector(self.config.security, prompt.confidential_sources, prompt.canary)
        guard = Guard(self.config.security, self.strings, self.redactor, leak, self.injection)
        audit = AuditLog(audit_dir, session_id, self.redactor, enabled=audit_dir is not None)
        return SessionHarness(prompt, guard, audit)
