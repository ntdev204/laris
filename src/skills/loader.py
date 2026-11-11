"""Discover, validate and load skills from `.laris/skills/<name>/SKILL.md`.

A skill is a folder with a `SKILL.md` (YAML front matter with `name` and `description`, then
Markdown instructions) and optional `references/` files. Only the name and description are put in
the system prompt; the body is loaded when the skill is used (progressive disclosure).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_BODY_CHARS = 24000
MAX_DESCRIPTION_CHARS = 1500


class SkillError(ValueError):
    """Raised for an unknown or invalid skill."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    directory: Path
    metadata: Dict[str, Any] = field(default_factory=dict)
    scope: str = "project"

    @property
    def references(self) -> List[Path]:
        folder = self.directory / "references"
        return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []

    def summary(self, limit: int = 240) -> str:
        text = " ".join(self.description.split())
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_skill_file(path: Path) -> Tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not match:
        raise SkillError(f"{path}: missing YAML front matter")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{path}: invalid front matter ({exc})") from exc
    if not isinstance(meta, dict):
        raise SkillError(f"{path}: front matter must be a mapping")
    return meta, match.group(2).strip()


def default_skill_roots(project_root: Optional[Path] = None) -> List[Tuple[Path, str]]:
    """Project skills first (they win name clashes), then the user's global skills."""
    base = Path(project_root or Path.cwd())
    return [(base / ".laris" / "skills", "project"), (Path.home() / ".laris" / "skills", "user")]


class SkillLibrary:
    def __init__(self, roots: Sequence[Tuple[Path, str]]) -> None:
        self.roots = [(Path(r), scope) for r, scope in roots]
        self.skills: Dict[str, Skill] = {}
        self.problems: List[str] = []
        self.reload()

    def reload(self) -> None:
        self.skills, self.problems = {}, []
        for root, scope in self.roots:
            if not root.is_dir():
                continue
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                skill_file = folder / "SKILL.md"
                if not skill_file.is_file():
                    continue
                try:
                    skill = self._load(folder, skill_file, scope)
                except SkillError as exc:
                    self.problems.append(str(exc))
                    continue
                if skill.name in self.skills:
                    self.problems.append(
                        f"{skill_file}: duplicate skill name '{skill.name}' ignored"
                    )
                    continue
                self.skills[skill.name] = skill

    @staticmethod
    def _load(folder: Path, skill_file: Path, scope: str) -> Skill:
        meta, body = parse_skill_file(skill_file)
        name = str(meta.get("name") or "").strip()
        description = " ".join(str(meta.get("description") or "").split())
        if not NAME_RE.match(name):
            raise SkillError(f"{skill_file}: invalid name {name!r} (lowercase letters, digits, -)")
        if name != folder.name:
            raise SkillError(f"{skill_file}: name '{name}' must match folder '{folder.name}'")
        if not description or len(description) > MAX_DESCRIPTION_CHARS:
            raise SkillError(
                f"{skill_file}: description missing or over {MAX_DESCRIPTION_CHARS} chars"
            )
        if not body:
            raise SkillError(f"{skill_file}: empty instructions")
        extra = {k: v for k, v in meta.items() if k not in ("name", "description")}
        return Skill(name, description, body, folder, extra, scope)

    def get(self, name: str) -> Skill:
        key = name.strip().lstrip("/").lower()
        if key not in self.skills:
            known = ", ".join(sorted(self.skills)) or "none"
            raise SkillError(f"unknown skill '{name}' (available: {known})")
        return self.skills[key]

    def names(self) -> List[str]:
        return sorted(self.skills)

    def index_text(self, limit_chars: int = 8000) -> str:
        lines, used = [], 0
        for name in self.names():
            line = f"- {name}: {self.skills[name].summary()}"
            if used + len(line) > limit_chars:
                lines.append("- …(more skills omitted; ask for /skills)")
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def read_reference(self, name: str, relative: str) -> str:
        skill = self.get(name)
        target = (skill.directory / relative).resolve()
        if skill.directory.resolve() not in target.parents or not target.is_file():
            raise SkillError(f"reference not found in skill '{name}': {relative}")
        return target.read_text(encoding="utf-8")
