"""`laris vault` (project vault) and `laris brain` (system brain) commands."""

import argparse
from pathlib import Path
from typing import Any, List

from config.loader import load_runtime_config
from harness.runtime import HarnessRuntime
from vault.brain import Brain
from vault.index import VaultIndex
from vault.lint import Problem, lint_content, lint_format, lint_hierarchy
from vault.project import FOLDERS, ProjectVault
from vault.schema import Schema, lint_schema


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
        index = VaultIndex.build(folder, cache_file=root / config.vault.cache_dir / "index.json")
        schema = Schema.load(root / config.prompts.vault_dir / "schema.yaml")
        runtime = HarnessRuntime(config, root)
        problems = (
            lint_format(index)
            + lint_schema(index, schema)
            + lint_content(
                index,
                config.vault.max_note_lint_chars,
                config.vault.max_property_chars,
                runtime.redactor.redact,
            )
        )
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


class _MigrateMemory:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("--undo", action="store_true", help="Remove the notes it created")

    def run(self, args: argparse.Namespace) -> int:
        from vault.memory import migrate, undo_migration

        root, config = Path(args.project_root).resolve(), _config(args)
        vault = ProjectVault(root, config.vault)
        legacy = root / config.prompts.memory_dir
        if args.undo:
            print(f"removed {undo_migration(vault, legacy)} migrated note(s); originals untouched")
            return 0
        done = migrate(vault, legacy)
        vault.refresh_index()
        print(f"{len(done)} memory file(s) are in {config.vault.dir}/Memory (originals kept)")
        return 0


class _Sync:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("--accept", action="store_true", help="Adopt hand edits in blocks")

    def run(self, args: argparse.Namespace) -> int:
        from vault.repair import accept_edits, find_conflicts

        root, config = Path(args.project_root).resolve(), _config(args)
        vault = ProjectVault(root, config.vault)
        if not vault.root.is_dir():
            print("no project vault yet; run `laris vault init`")
            return 0
        if args.accept:
            print(f"adopted hand edits in {accept_edits(vault)} note(s)")
        conflicts = find_conflicts(vault.root)
        for item in conflicts:
            print(f"[EDITED] {item.path}: block '{item.block}' was edited by hand; left alone")
        if conflicts:
            print("run `laris vault sync --accept` to let LARIS update those blocks again")
        vault.refresh_index()
        return 1 if conflicts else 0


class _Repair:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument(
            "--restore", metavar="NOTE", help="Restore a note from its newest backup"
        )

    def run(self, args: argparse.Namespace) -> int:
        from vault.repair import repair, restore

        root, config = Path(args.project_root).resolve(), _config(args)
        vault = ProjectVault(root, config.vault)
        if args.restore:
            name = restore(vault, args.restore)
            print(f"restored from {name}" if name else "no backup for that note")
            return 0 if name else 1
        report = repair(vault)
        print(
            f"closed {report.closed_blocks} block(s), removed {report.temp_files} temp file(s)"
            + (", rebuilt the skeleton" if report.skeleton else "")
        )
        return 0


def _index(args: argparse.Namespace) -> tuple:
    root, config = Path(args.project_root).resolve(), _config(args)
    folder = root / config.vault.dir
    if not folder.is_dir():
        return None, config
    return VaultIndex.build(folder, cache_file=root / config.vault.cache_dir / "index.json"), config


class _Search:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("query")
        parser.add_argument("--limit", type=int, default=8)

    def run(self, args: argparse.Namespace) -> int:
        from vault.search import NoteSearch

        index, _ = _index(args)
        if index is None:
            print("no project vault yet; run `laris vault init`")
            return 0
        hits = NoteSearch(index).search(args.query, args.limit)
        for hit in hits:
            note = index.notes[hit.path]
            print(f"{hit.score:7.3f}  {hit.path}  [{note.props.get('type', '')}]")
        print(f"{len(hits)} note(s)")
        return 0


class _Show:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("note", help="Note name or path")

    def run(self, args: argparse.Namespace) -> int:
        index, _ = _index(args)
        note = index.find(args.note) if index else None
        if note is None:
            print(f"no such note: {args.note}")
            return 1
        print(f"# {note.title}  ({note.path})")
        print(note.body.strip())
        print("\nLinks to: " + (", ".join(t for t, _ in index.outgoing(note.path)) or "-"))
        print("Linked from: " + (", ".join(index.backlinks(note.path)) or "-"))
        return 0


class _Graph:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument(
            "--format",
            choices=["json", "stats", "graphml", "canvas"],
            default="stats",
            help="graphml and canvas export the scholarly knowledge graph (with provenance)",
        )
        parser.add_argument("--out", default="", help="Write the export to this file")
        parser.add_argument("--note", default="", help="Only the neighbourhood of this note")
        parser.add_argument("--depth", type=int, default=1)

    def run(self, args: argparse.Namespace) -> int:
        import json

        from vault.graph import VaultGraph

        index, _ = _index(args)
        if index is None:
            print("no project vault yet; run `laris vault init`")
            return 0
        if args.format in ("graphml", "canvas"):
            from scholarly import kg

            graph_kg = kg.build(index)
            text = graph_kg.to_graphml() if args.format == "graphml" else graph_kg.to_canvas()
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(f"wrote {args.out}: {len(graph_kg.nodes)} nodes, {len(graph_kg.edges)} edges")
            else:
                print(text)
            return 0
        graph = VaultGraph(index)
        if args.note:
            found = index.find(args.note)
            if found is None:
                print(f"no such note: {args.note}")
                return 1
            data = graph.local_graph(found.path, args.depth)
        else:
            data = {
                "nodes": graph.nodes,
                "edges": [[p, t, k] for p in graph.nodes for t, k in graph.out[p]],
            }
        if args.format == "json":
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        print(f"{len(data['nodes'])} notes, {len(data['edges'])} links")
        for path, count in graph.top_by_degree(5):
            print(f"  {count:>3}  {path}")
        print(f"components: {len(graph.components())}")
        return 0


class _Propose:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("title")
        parser.add_argument("text")

    def run(self, args: argparse.Namespace) -> int:
        from vault.proposals import propose

        root, config = Path(args.project_root).resolve(), _config(args)
        result = propose(ProjectVault(root, config.vault), args.title, args.text, "user")
        print(f"{result.status}: {result.note} {result.reason}".strip())
        return 0 if result.status != "skipped" else 1


class _Review:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)

    def run(self, args: argparse.Namespace) -> int:
        from vault.proposals import pending

        root, config = Path(args.project_root).resolve(), _config(args)
        items = pending(ProjectVault(root, config.vault))
        for item in items:
            print(f"- {item.title}  [{item.origin}, {item.created}]\n    {item.text[:200]}")
        print(f"{len(items)} pending proposal(s); not used for answers until accepted")
        return 0


class _Accept:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("title")
        parser.add_argument("--into", default="memory", choices=["memory", "decision", "concept"])

    def run(self, args: argparse.Namespace) -> int:
        from vault.proposals import accept

        root, config = Path(args.project_root).resolve(), _config(args)
        try:
            result = accept(ProjectVault(root, config.vault), args.title, args.into)
        except KeyError as exc:
            print(f"[ERROR] {exc.args[0]}")
            return 1
        print(f"{result.status}: {result.note}")
        return 0 if result.status != "skipped" else 1


class _Reject:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _root(parser)
        parser.add_argument("title")

    def run(self, args: argparse.Namespace) -> int:
        from vault.proposals import reject

        root, config = Path(args.project_root).resolve(), _config(args)
        ok = reject(ProjectVault(root, config.vault), args.title)
        print("rejected" if ok else "no such pending proposal")
        return 0 if ok else 1


VAULT_COMMANDS: dict[str, Any] = {
    "search": _Search(),
    "show": _Show(),
    "graph": _Graph(),
    "sync": _Sync(),
    "repair": _Repair(),
    "init": _Init(),
    "check": _Check(),
    "status": _Status(),
    "migrate-memory": _MigrateMemory(),
}
PROPOSAL_COMMANDS: dict[str, Any] = {
    "propose": _Propose(),
    "review": _Review(),
    "accept": _Accept(),
    "reject": _Reject(),
}
BRAIN_COMMANDS: dict[str, Any] = {
    "check": _BrainCheck(),
    "tree": _BrainTree(),
    "route": _BrainRoute(),
}
