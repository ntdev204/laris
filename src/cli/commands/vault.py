"""`laris vault` (project vault) and `laris brain` (system brain) commands."""

import argparse
from pathlib import Path
from typing import Any, List

from config.loader import load_runtime_config
from vault.brain import Brain
from vault.index import VaultIndex
from vault.lint import Problem, lint_format, lint_hierarchy
from vault.project import FOLDERS, ProjectVault


def _root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default=".", help="Project folder (holds the vault)")


def _config(args: argparse.Namespace) -> Any:
    return load_runtime_config(Path(args.project_root).resolve())


def _brain_folder(root: Path, config: Any) -> Path:
    folder = Path(config.prompts.brain_dir)
    return folder if folder.is_absolute() else root / folder


def brain_problems(root: Path, config: Any) -> List[Problem]:
    folder = _brain_folder(root, config)
    if not folder.is_dir():
        return [Problem(config.prompts.brain_dir, "brain", "brain folder is missing")]
    index = VaultIndex.build(folder)
    cfg = config.brain
    root_note = index.find(cfg.root_note)
    relations = root_note.prop_list("relations") if root_note else []
    return lint_format(index) + lint_hierarchy(
        index,
        cfg.root_note,
        cfg.max_depth,
        cfg.max_children,
        cfg.required_properties,
        cfg.summary_max_chars,
        relations,
    )


class _Init:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        vault = ProjectVault(root, config.vault)
        created = vault.ensure()
        vault.refresh_index()
        print(("created " if created else "already exists: ") + config.vault.dir)
        print("Open the folder in Obsidian, or keep using it as plain Markdown.")
        return 0


class _Check:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        folder = root / config.vault.dir
        if not folder.is_dir():
            print("no project vault yet; run `laris vault init`")
            return 0
        index = VaultIndex.build(folder)
        problems = lint_format(index)
        for problem in problems:
            print(f"[FAIL] {problem}")
        print(f"{len(index.notes)} notes, {len(problems)} problems")
        return 1 if problems else 0


class _Status:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        folder = root / config.vault.dir
        if not folder.is_dir():
            print("no project vault yet; run `laris vault init`")
            return 0
        index = VaultIndex.build(folder)
        print(f"{config.vault.dir}: {len(index.notes)} notes")
        for name in FOLDERS:
            print(f"  {name:<10} {sum(1 for p in index.notes if p.startswith(name + '/'))}")
        inbox = sum(1 for p in index.notes if p.startswith(config.vault.inbox_dir + "/"))
        print(f"  inbox      {inbox} (not used for answers until accepted)")
        print(f"  unresolved links: {len(index.unresolved)}")
        print(f"  notes nothing links to: {len(index.unlinked())}")
        return 0


class _BrainCheck:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        problems = brain_problems(root, config)
        for problem in problems:
            print(f"[FAIL] {problem}")
        count = len(VaultIndex.build(_brain_folder(root, config)).notes)
        print(f"{count} brain notes, {len(problems)} problems")
        return 1 if problems else 0


class _BrainTree:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        brain = Brain(_brain_folder(root, config), config.brain)
        if not brain.available:
            print("no brain")
            return 1

        def show(title: str, depth: int) -> None:
            note = brain.index.find(title)
            if note is None:
                return
            print("  " * depth + f"{note.title} [{note.props.get('type', '')}]")
            for child in brain.index.targets(note.path, "children"):
                show(brain.index.notes[child].title, depth + 1)

        show(config.brain.root_note, 0)
        return 0


class _BrainRoute:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("task", help="Task text")
        parser.add_argument("--workflow", default="")

    def run(self, args: argparse.Namespace) -> int:
        root, config = Path(args.project_root).resolve(), _config(args)
        brain = Brain(_brain_folder(root, config), config.brain)
        hubs = brain.route(args.task, args.workflow)
        print(", ".join(hubs) if hubs else "(no hub matches)")
        return 0


VAULT_COMMANDS: dict[str, Any] = {"init": _Init(), "check": _Check(), "status": _Status()}
BRAIN_COMMANDS: dict[str, Any] = {
    "check": _BrainCheck(),
    "tree": _BrainTree(),
    "route": _BrainRoute(),
}
