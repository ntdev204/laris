"""`laris skills list|show|check`: inspect and validate the skills in `.laris/skills`."""

import argparse
from pathlib import Path
from typing import Any

from cli.common import load_runtime
from laris.client.application.workspace import Workspace
from laris.client.learning.hooks import knowledge_skill_for
from laris.client.learning.skills import install_skill, lint_skill, skill_meta, sync_chunks
from laris.shared.skills import SkillLibrary
from laris.shared.skills.loader import SkillError


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


class _Lint:
    """Completeness and safety lint of one skill or of a SKILL.md file outside the library."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("target", help="Skill name or path to a SKILL.md file")

    def run(self, args: argparse.Namespace) -> int:
        runtime = load_runtime(args)
        path = Path(args.target)
        if not path.is_file():
            try:
                path = _library(args).get(args.target).directory / "SKILL.md"
            except SkillError as exc:
                print(f"[ERROR] {exc}")
                return 2
        problems = lint_skill(
            path.read_text(encoding="utf-8"),
            runtime.config.learning,
            runtime.injection,
            runtime.redactor,
            runtime.config.agent.skill_max_chars,
        )
        for problem in problems:
            print(f"[FAIL] {problem}")
        print("complete" if not problems else f"{len(problems)} problems")
        return 1 if problems else 0


class _Add:
    """Install a hand-written skill after the same lint `save_skill` applies."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("--file", required=True, help="SKILL.md to install")
        parser.add_argument("--overwrite", action="store_true")

    def run(self, args: argparse.Namespace) -> int:
        runtime = load_runtime(args)
        text = Path(args.file).read_text(encoding="utf-8")
        name = skill_meta(text).get("name", "")
        problems = lint_skill(
            text,
            runtime.config.learning,
            runtime.injection,
            runtime.redactor,
            runtime.config.agent.skill_max_chars,
            str(name),
        )
        if problems:
            for problem in problems:
                print(f"[FAIL] {problem}")
            return 1
        folder = Path(runtime.config.learning.skill_dir).expanduser()
        folder = folder if folder.is_absolute() else runtime.root / folder
        try:
            path, replaced = install_skill(folder, str(name), text, args.overwrite)
        except SkillError as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(f"{'replaced' if replaced else 'installed'} {path.relative_to(runtime.root)}")
        return 0


class _Sync:
    """Build or refresh the generated knowledge skills for the whole workspace corpus."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser)
        parser.add_argument("--workspace", default=None)

    def run(self, args: argparse.Namespace) -> int:
        runtime = load_runtime(args)
        everything = Workspace(Path(runtime.config.app.workspace)).load()
        made = 0
        for group in sync_chunks(everything).values():
            outcome = knowledge_skill_for(runtime, group, everything)
            if outcome.get("skill"):
                made += 1
                print(f"{'updated' if outcome['skill_updated'] else 'created'} {outcome['skill']}")
            elif outcome.get("skill_skipped"):
                print(f"[skipped] {'; '.join(outcome['skill_skipped'])}")
        print(f"{made} knowledge skills written")
        return 0


COMMANDS: dict[str, Any] = {
    "list": _List(),
    "show": _Show(),
    "check": _Check(),
    "lint": _Lint(),
    "add": _Add(),
    "sync": _Sync(),
}
