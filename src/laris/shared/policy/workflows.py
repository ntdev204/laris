"""Workflows: declarative procedures that can only narrow what a session may do (rules W-1..W-4).

A workflow file in `.laris/workflows/<name>.yaml` lists ordered phases plus enforceable limits: the
tools the session may call, a step cap, a stricter approval mode, required citations and the output
sections the final answer must contain.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class WorkflowError(ValueError):
    pass


class Phase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")
    goal: str = Field(min_length=3)
    instructions: str = Field(default="")
    exit: str = Field(default="")


def _probe() -> None:
    """Its type is the function type of this module: plain Python, or compiled in the client."""


class WorkflowSpec(BaseModel):
    # methods of a compiled module are not `FunctionType`; tell pydantic they are not fields
    model_config = ConfigDict(ignored_types=(type(_probe),))

    name: str
    description: str = Field(min_length=10)
    version: str = Field(default="1.0.0")
    triggers: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(min_length=1)
    max_steps: int = Field(default=6, ge=1, le=10)
    require_citations: bool = Field(default=False)
    approval: Literal["inherit", "ask", "deny"] = Field(default="inherit")
    phases: List[Phase] = Field(min_length=1)
    output_sections: List[str] = Field(default_factory=list)
    stop_conditions: List[str] = Field(default_factory=list)

    def render(self, request: str, limit: int) -> str:
        lines = [
            f"Workflow: {self.name} (v{self.version}) — {self.description}",
            f"Allowed tools: {', '.join(self.allowed_tools)}. Step limit: {self.max_steps}.",
            "Follow the phases in order; do not call a tool outside the allowed list.",
        ]
        for number, phase in enumerate(self.phases, 1):
            lines.append(f"{number}. [{phase.id}] {phase.goal}")
            if phase.instructions:
                lines.append("   " + " ".join(phase.instructions.split()))
            if phase.exit:
                lines.append(f"   Done when: {phase.exit}")
        if self.stop_conditions:
            lines.append("Stop when: " + "; ".join(self.stop_conditions))
        if self.output_sections:
            lines.append(
                "The final answer MUST contain these sections: " + ", ".join(self.output_sections)
            )
        if request:
            lines.append(f"Task: {request}")
        return "\n".join(lines)[:limit]


class WorkflowLibrary:
    def __init__(self, folder: Optional[Path]) -> None:
        self.folder = Path(folder) if folder else None
        self.workflows: Dict[str, WorkflowSpec] = {}
        self.problems: List[str] = []
        self.reload()

    def reload(self) -> None:
        self.workflows, self.problems = {}, []
        if not self.folder or not self.folder.is_dir():
            return
        for path in sorted(self.folder.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                spec = WorkflowSpec(**data)
            except (yaml.YAMLError, ValidationError, TypeError) as exc:
                self.problems.append(f"{path.name}: {str(exc).splitlines()[0]}")
                continue
            if spec.name != path.stem or not NAME.match(spec.name):
                self.problems.append(f"{path.name}: name must equal the file name (lowercase-dash)")
                continue
            self.workflows[spec.name] = spec

    def names(self) -> List[str]:
        return sorted(self.workflows)

    def get(self, name: str) -> WorkflowSpec:
        key = name.strip().lstrip("/").lower()
        if key not in self.workflows:
            raise WorkflowError(f"unknown workflow: {name}")
        return self.workflows[key]

    def check(self, tools: Set[str], max_steps: int) -> List[str]:
        """Cross-check every workflow against the real tools and global limits (rule W-1)."""
        problems = list(self.problems)
        for spec in self.workflows.values():
            unknown = sorted(set(spec.allowed_tools) - tools)
            if unknown:
                problems.append(f"{spec.name}: unknown tools {unknown}")
            if spec.max_steps > max_steps:
                problems.append(f"{spec.name}: max_steps {spec.max_steps} exceeds {max_steps}")
        return problems

    def summary(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "tools": s.allowed_tools}
            for s in self.workflows.values()
        ]
