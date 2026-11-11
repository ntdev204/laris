"""Skills: instruction packages (`SKILL.md` plus references) the assistant loads on demand."""

from skills.loader import Skill, SkillLibrary, default_skill_roots

__all__ = ["Skill", "SkillLibrary", "default_skill_roots"]
