"""System prompt assembly: base rules, LARIS.md instructions, skill index, memory, environment.

LARIS.md files are read on every turn so edits take effect immediately. Order (later wins on
conflict): user-level `~/.laris/LARIS.md`, project `LARIS.md`, `.laris/LARIS.md`, and the
git-ignored `LARIS.local.md`.
"""

import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from skills import SkillLibrary

INSTRUCTION_FILES = ("LARIS.md", ".laris/LARIS.md", "LARIS.local.md")
MAX_INSTRUCTION_CHARS = 14000
MAX_MEMORY_CHARS = 4000

BASE_PROMPT = (
    "You are LARIS, a local research assistant with tools. Use the tools to read files, "
    "search the corpus and extract evidence. Cite the source of every statement, say when "
    "evidence is missing, and never claim more than the quoted passages support. Follow the "
    "project instructions below."
)

SKILL_RULES = (
    "When a request matches a skill, call `use_skill` with its name before answering, then "
    "follow the returned instructions. Read reference files with `read_file` only when needed."
)


def instruction_files(project_root: Path) -> List[Path]:
    found = [Path.home() / ".laris" / "LARIS.md"]
    found += [project_root / rel for rel in INSTRUCTION_FILES]
    return [p for p in found if p.is_file()]


def load_instructions(project_root: Path) -> List[Tuple[str, str]]:
    """(label, text) per existing instruction file, truncated to the total budget."""
    out: List[Tuple[str, str]] = []
    budget = MAX_INSTRUCTION_CHARS
    for path in instruction_files(project_root):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        if len(text) > budget:
            text = text[:budget] + "\n…(truncated)"
        budget -= len(text)
        try:
            label = str(path.relative_to(project_root))
        except ValueError:
            label = str(path)
        out.append((label, text))
        if budget <= 0:
            break
    return out


def memory_section(memory_dir: Path) -> Optional[str]:
    if not memory_dir.is_dir():
        return None
    index = memory_dir / "MEMORY.md"
    names = sorted(p.name for p in memory_dir.glob("*.md") if p.name != "MEMORY.md")
    parts = []
    if index.is_file():
        parts.append(index.read_text(encoding="utf-8").strip()[:MAX_MEMORY_CHARS])
    if names:
        parts.append("Memory files (read with read_file): " + ", ".join(names))
    return "\n".join(parts) if parts else None


def build_system_prompt(
    project_root: Path,
    skills: Optional[SkillLibrary] = None,
    custom: str = "",
    today: Optional[datetime.date] = None,
) -> str:
    sections = [custom.strip() or BASE_PROMPT]
    for label, text in load_instructions(project_root):
        sections.append(f"# Project instructions ({label})\n{text}")
    if skills and skills.skills:
        sections.append(f"# Skills\n{SKILL_RULES}\n{skills.index_text()}")
    memory = memory_section(project_root / ".laris" / "memory")
    if memory:
        sections.append(f"# Memory (.laris/memory)\n{memory}")
    day = (today or datetime.date.today()).isoformat()
    sections.append(f"# Environment\nDate: {day}. Working folder: {project_root}.")
    return "\n\n".join(sections)
