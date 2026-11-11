"""`laris harness verify|lock` and `laris workflows list|show|check` (protected policy)."""

import argparse
from pathlib import Path
from typing import Any

from agent.builtin_tools import build_registry
from agent.tools import Sandbox
from application.service import SearchService
from application.workspace import Workspace
from config.loader import load_runtime_config
from harness import integrity
from harness.prompts import PromptComposer
from harness.runtime import HarnessRuntime
from harness.workflows import WorkflowError, WorkflowLibrary


def _root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=".", help="Folder that contains .laris/")


def _config(args: argparse.Namespace) -> Any:
    return load_runtime_config(Path(args.project_root).resolve())


def _library(args: argparse.Namespace) -> WorkflowLibrary:
    root = Path(args.project_root).resolve()
    folder = Path(_config(args).prompts.workflows_dir)
    return WorkflowLibrary(folder if folder.is_absolute() else root / folder)


class _Verify:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        problems = integrity.verify(root, config.prompts)
        if not problems:  # only compose and cross-check a policy that is intact
            PromptComposer(config, root).compose("verify")
            runtime = HarnessRuntime(config, root)
            registry = build_registry(
                SearchService(Workspace(root / config.app.workspace)),
                Sandbox([root], root / config.app.chat_dir / "output"),
                runtime,
            )
            problems += runtime.workflows().check(set(registry.tools), config.agent.max_steps)
        for problem in problems:
            print(f"[FAIL] {problem}")
        files = len(integrity.protected_files(root, config.prompts))
        print(f"{files} protected files, {len(problems)} problems")
        return 1 if problems else 0


class _Lock:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        lock = integrity.write_lock(root, config.prompts)
        count = len(integrity.protected_files(root, config.prompts))
        print(f"wrote {lock.relative_to(root)} ({count} files)")
        print("Commit it with the owner-approved change (rule G-1).")
        return 0


class _List:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        library = _library(args)
        for item in library.summary():
            print(f"{item['name']:<18} {', '.join(item['tools'])}\n    {item['description']}")
        for problem in library.problems:
            print(f"[problem] {problem}")
        return 0


class _Show:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("name")

    def run(self, args: argparse.Namespace) -> int:
        try:
            spec = _library(args).get(args.name)
        except WorkflowError as exc:
            print(f"[ERROR] {exc}")
            return 2
        print(spec.render("", _config(args).prompts.workflow_max_chars))
        return 0


class _Check:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        config = _config(args)
        root = Path(args.project_root).resolve()
        runtime = HarnessRuntime(config, root)
        registry = build_registry(
            SearchService(Workspace(root / config.app.workspace)),
            Sandbox([root], root / config.app.chat_dir / "output"),
            runtime,
        )
        library = _library(args)
        problems = library.check(set(registry.tools), config.agent.max_steps)
        for problem in problems:
            print(f"[FAIL] {problem}")
        print(f"{len(library.workflows)} valid workflows, {len(problems)} problems")
        return 1 if problems else 0


HARNESS_COMMANDS: dict[str, Any] = {"verify": _Verify(), "lock": _Lock()}
WORKFLOW_COMMANDS: dict[str, Any] = {"list": _List(), "show": _Show(), "check": _Check()}
