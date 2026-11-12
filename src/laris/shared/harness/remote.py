"""Client side of the policy server: the pieces `laris` needs when `.laris/` policy is not local.

The system policy (prompt modules, rules, workflows, brain) lives on the server. This module holds
only what is the user's: instruction files, skills index and memory from the two client folders
(`~/.laris` global and `./.laris` project), the public message catalogue and workflow *limits*.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from laris.protocol import AuthError, ProviderError
from laris.protocol import http_failure as _http_failure
from laris.shared.config.schemas import LarisConfig
from laris.shared.policy.prompts import ComposedPrompt, expand
from laris.shared.policy.workflows import NAME, Phase, WorkflowError, WorkflowSpec
from laris.shared.skills import SkillLibrary

PUBLIC_STRINGS = Path(__file__).with_name("public_strings.yaml")


def use_server_policy(config: LarisConfig, root: Path) -> bool:
    """`app.policy_source`: `server`, `local`, or `auto` (server when no local prompts exist)."""
    choice = config.app.policy_source
    if choice != "auto":
        return choice == "server"
    folder = Path(config.prompts.dir)
    folder = folder if folder.is_absolute() else root / folder
    return not (folder / config.prompts.manifest).is_file()


class NoBrain:
    """Stands in for the brain on the client: it lives on the server and is never copied."""

    available = False
    routes: Dict[str, str] = {}

    def route(self, *_: Any, **__: Any) -> List[str]:
        return []

    def begin_turn(self) -> None:
        return None

    def refresh_knowledge(self) -> None:
        return None

    def texts(self) -> List[str]:
        return []


class ClientLayers:
    """Collects the user's own instruction layers, global first then project."""

    def __init__(self, config: LarisConfig, root: Path) -> None:
        self.cfg = config.prompts
        self.vault_cfg = config.vault
        self.root = root

    def instructions(self) -> List[Dict[str, str]]:
        user_file = expand(Path(self.cfg.user_instruction_file))
        listed = [user_file] + [self.root / rel for rel in self.cfg.instruction_files]
        out: List[Dict[str, str]] = []
        budget = self.cfg.max_instruction_chars
        for path in listed:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            budget -= len(text)
            if budget < 0:
                raise ValueError("instruction files exceed prompts.max_instruction_chars")
            label = "global" if path == user_file else "project"
            out.append({"label": f"{label}:{path.name}", "text": text})
        return out

    def memory(self) -> str:
        from laris.shared.vault.memory import read_memory
        from laris.shared.vault.project import ProjectVault

        parts: List[str] = []
        if self.vault_cfg.enabled:
            legacy = self.root / self.cfg.memory_dir
            parts.append(read_memory(ProjectVault(self.root, self.vault_cfg), legacy, 10**6))
        for folder in (expand(Path("~/.laris/memory")),):
            index = folder / "MEMORY.md"
            if index.is_file():
                parts.append(index.read_text(encoding="utf-8").strip()[: self.cfg.max_memory_chars])
        return "\n".join(parts)[: self.cfg.max_memory_chars]


class RemoteComposer:
    """Replaces the local prompt composer: returns an empty prompt plus the client's layers."""

    version = "server"

    def __init__(self, config: LarisConfig, root: Path) -> None:
        self.layers = ClientLayers(config, root)

    def compose(
        self,
        session_id: str,
        skills: Optional[SkillLibrary] = None,
        extra_instructions: str = "",
        workflow_text: str = "",
        **_: Any,
    ) -> ComposedPrompt:
        cap = self.layers.cfg.skills_index_chars
        remote = {
            "session_id": session_id,
            "layers": {
                "instructions": self.layers.instructions(),
                "skills_index": skills.index_text(cap) if skills else "",
                "memory": self.layers.memory(),
                "extra": extra_instructions,
            },
        }
        return ComposedPrompt("", "", self.version, [], "", [], remote)


class ServerClient:
    """Small authenticated GET helper for the policy endpoints (workflows, help)."""

    def __init__(self, base_url: str, key: Optional[str], timeout_s: float = 10.0) -> None:
        self.base = base_url.rstrip("/")
        self.key = key
        self.timeout_s = timeout_s

    def get(self, path: str) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        request = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return dict(json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            raise _http_failure(exc) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ProviderError(f"policy server unreachable: {exc}") from exc


class RemoteWorkflows:
    """Workflow limits from the server (tools, steps, approval); the phases never leave it."""

    def __init__(self, server: Optional[ServerClient]) -> None:
        self.server = server
        self.workflows: Dict[str, WorkflowSpec] = {}
        self.problems: List[str] = []
        self.reload()

    def reload(self) -> None:
        self.workflows, self.problems = {}, []
        if self.server is None:
            return
        try:
            items = self.server.get("/laris/workflows").get("workflows", [])
        except (ProviderError, AuthError) as exc:
            self.problems.append(str(exc))
            return
        for item in items:
            try:
                spec = WorkflowSpec(
                    **{**item, "phases": [Phase(id="remote", goal="runs on the policy server")]}
                )
            except (TypeError, ValueError):
                continue
            if NAME.match(spec.name):
                self.workflows[spec.name] = spec

    def names(self) -> List[str]:
        return sorted(self.workflows)

    def get(self, name: str) -> WorkflowSpec:
        key = name.strip().lstrip("/").lower()
        if key not in self.workflows:
            raise WorkflowError(f"unknown workflow: {name}")
        return self.workflows[key]

    def check(self, tools: Set[str], max_steps: int) -> List[str]:
        return list(self.problems)

    def summary(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "tools": s.allowed_tools}
            for s in self.workflows.values()
        ]
