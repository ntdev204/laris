"""System prompt composition from versioned modules, instruction files and runtime state.

Modules live under `prompts.dir` (default `.laris/prompts`), are listed in `manifest.yaml` and use
`{{variable}}` placeholders; unknown placeholders are an error so a typo can never ship silently.
The composed prompt is hashed so every session can record *which* prompt ran without storing it.
"""

import datetime
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from laris.shared.config.schemas import LarisConfig
from laris.shared.skills import SkillLibrary

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
POLICY_SECTION = "internal_policy"


class PromptError(ValueError):
    """Raised when the manifest, a module or a placeholder is invalid."""


@dataclass
class ComposedPrompt:
    text: str
    sha256: str
    version: str
    sections: List[str]
    canary: str
    confidential_sources: List[str] = field(default_factory=list)
    remote: Optional[Dict[str, Any]] = None  # client side: what the policy server composes from


def expand(path: Path) -> Path:
    return Path(str(path)).expanduser()


class PromptComposer:
    def __init__(self, config: LarisConfig, project_root: Path) -> None:
        self.cfg = config.prompts
        self.vault_cfg = config.vault
        self.canary_enabled = config.security.canary_enabled
        self.root = Path(project_root)
        folder = Path(self.cfg.dir)
        self.dir = folder if folder.is_absolute() else self.root / folder
        manifest_path = self.dir / self.cfg.manifest
        if not manifest_path.is_file():
            raise PromptError(f"prompt manifest not found: {manifest_path}")
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        self.version = str(manifest.get("version", ""))
        self.allowed = set(manifest.get("variables", []))
        self.order: List[str] = list(manifest.get("order", []))
        self.modules: Dict[str, str] = {}
        for name, relative in (manifest.get("modules") or {}).items():
            file = self.dir / relative
            if not file.is_file():
                raise PromptError(f"prompt module '{name}' missing: {file}")
            self.modules[name] = file.read_text(encoding="utf-8").strip()
        unknown = [n for n in self.order if n not in self.modules and n != POLICY_SECTION]
        if unknown or not self.version:
            raise PromptError(f"manifest invalid (version/order): {unknown}")
        for name, text in self.modules.items():
            for var in _PLACEHOLDER.findall(text):
                if var not in self.allowed:
                    raise PromptError(f"module '{name}' uses undeclared variable '{var}'")

    # -- instruction files -----------------------------------------------------------------
    def rule_files(self) -> List[Path]:
        folder = Path(self.cfg.rules_dir)
        folder = folder if folder.is_absolute() else self.root / folder
        return sorted(folder.glob("*.md")) if folder.is_dir() else []

    def instruction_files(self) -> List[Path]:
        """User file, then `LARIS.md`, then every rules file, then the remaining local files."""
        listed = [self.root / rel for rel in self.cfg.instruction_files]
        files = [expand(Path(self.cfg.user_instruction_file)), *listed[:1], *self.rule_files()]
        files += listed[1:]
        return [p for p in files if p.is_file()]

    def load_policy(self) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        budget = self.cfg.max_instruction_chars
        for path in self.instruction_files():
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            budget -= len(text)
            if budget < 0:  # a truncated rule would silently weaken the policy: fail closed
                raise PromptError("instruction files exceed prompts.max_instruction_chars")
            try:
                label = str(path.relative_to(self.root))
            except ValueError:
                label = path.name
            out.append((label, text))
        return out

    def _memory(self) -> str:
        from laris.shared.vault.memory import read_memory
        from laris.shared.vault.project import ProjectVault

        legacy = self.root / self.cfg.memory_dir
        if not self.vault_cfg.enabled:
            if not legacy.is_dir():
                return ""
            parts = []
            index = legacy / "MEMORY.md"
            if index.is_file():
                parts.append(index.read_text(encoding="utf-8").strip())
            names = sorted(p.name for p in legacy.glob("*.md") if p.name != "MEMORY.md")
            if names:
                parts.append("Files: " + ", ".join(names))
            return "\n".join(parts)[: self.cfg.max_memory_chars]
        return read_memory(
            ProjectVault(self.root, self.vault_cfg), legacy, self.cfg.max_memory_chars
        )

    # -- composition -----------------------------------------------------------------------
    def compose(
        self,
        session_id: str,
        skills: Optional[SkillLibrary] = None,
        extra_instructions: str = "",
        today: Optional[datetime.date] = None,
        extra_variables: Optional[Dict[str, Any]] = None,
        workflow_text: str = "",
        extra_policy: Optional[List[Tuple[str, str]]] = None,
        canary_token: str = "",
    ) -> ComposedPrompt:
        """`extra_policy` are the caller's own instruction files (policy server: the client's);
        they come before the protected rules so a rule is always the later, stronger text."""
        canary = canary_token or f"LARIS-CANARY-{secrets.token_hex(8)}"
        canary = canary if self.canary_enabled else "disabled"
        own = list(extra_policy or [])
        policy = self.load_policy()
        if own:
            budget = self.cfg.max_instruction_chars
            own = [(label, text[:budget]) for label, text in own]
            policy = own + policy
        variables: Dict[str, str] = {
            "assistant_name": self.cfg.assistant_name,
            "reply_language": self.cfg.reply_language,
            "date": (today or datetime.date.today()).isoformat(),
            "skills_index": skills.index_text(self.cfg.skills_index_chars) if skills else "",
            "memory": self._memory(),
            "extra_instructions": extra_instructions.strip()[: self.cfg.user_preferences_max_chars],
            "workflow": workflow_text,
            "session_id": session_id,
            "integrity_token": canary,
        }
        variables.update({k: str(v) for k, v in (extra_variables or {}).items()})
        sections: List[str] = []
        used: List[str] = []
        confidential: List[str] = []
        for name in self.order:
            if name == POLICY_SECTION:
                if not policy:
                    continue
                body = "\n\n".join(f"<!-- {label} -->\n{text}" for label, text in policy)
                sections.append(
                    f'<{name} classification="internal" disclose="never">\n{body}\n</{name}>'
                )
                confidential += [text for _, text in policy[len(own) :]]
            else:
                needs = _PLACEHOLDER.findall(self.modules[name])
                if name in ("skills", "memory", "workflow", "user_preferences") and not all(
                    variables.get(v) for v in needs
                ):
                    continue
                body = _PLACEHOLDER.sub(lambda m: variables[m.group(1)], self.modules[name])
                sections.append(f"<{name}>\n{body}\n</{name}>")
                if name in (
                    "identity",
                    "principles",
                    "confidentiality",
                    "untrusted_content",
                    "tools_protocol",
                    "output_format",
                ):
                    confidential.append(body)
            used.append(name)
        text = "\n\n".join(sections)
        return ComposedPrompt(
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            version=self.version,
            sections=used,
            canary=canary if self.canary_enabled else "",
            confidential_sources=confidential,
        )
