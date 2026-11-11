"""`laris skills list|show|check`: inspect and validate the skills in `.laris/skills`."""

import argparse
from pathlib import Path
from typing import Any

from cli.common import load_runtime
from skills import SkillLibrary
from skills.loader import SkillError


def _library(args: argparse.Namespace) -> SkillLibrary:
    root = Path(args.project_root).resolve()
    runtime = load_runtime(args)
    roots = []
    for entry in runtime.config.prompts.skill_roots:
        path = Path(entry).expanduser()
        roots.append(
            (
                path if path.is_absolute() else root / path,
                "user" if entry.startswith("~") else "project",
            )
        )
    return SkillLibrary(roots)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=".", help="Folder that contains .laris/")


class _List:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)

    def run(self, args: argparse.Namespace) -> int:
        library = _library(args)
        for name in library.names():
            skill = library.skills[name]
            print(f"{name:<24} {skill.scope:<8} {len(skill.references)} refs  {skill.summary(90)}")
        for problem in library.problems:
            print(f"[problem] {problem}")
        return 0


class _Show:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("name")

    def run(self, args: argparse.Namespace) -> int:
        try:
            skill = _library(args).get(args.name)
        except SkillError as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(f"# {skill.name} ({skill.scope})\n{skill.description}\n\n{skill.body}")
        return 0


class _Check:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)

    def run(self, args: argparse.Namespace) -> int:
        library = _library(args)
        for problem in library.problems:
            print(f"[FAIL] {problem}")
        print(f"{len(library.skills)} valid skills, {len(library.problems)} problems")
        return 1 if library.problems else 0


COMMANDS: dict[str, Any] = {"list": _List(), "show": _Show(), "check": _Check()}
