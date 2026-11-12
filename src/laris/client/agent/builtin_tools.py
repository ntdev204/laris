"""Built-in tools: files, OCR, corpus search, extractive QA, skills, memory, discourse.

Limits, timeouts and policies come from the harness runtime (configuration); results never carry
absolute paths and file reads honour the deny-list of internal and secret files.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from laris.client.agent.tools import Sandbox, ToolExecutionError, ToolRegistry, ToolSpec, schema
from laris.client.application.service import SearchService, ServiceError
from laris.client.application.workspace import (
    IMAGE_SUFFIXES,
    IngestError,
    chunks_from_path,
    read_text_from_bytes,
)
from laris.client.learning.skills import install_skill, lint_skill
from laris.shared.brain import BrainError
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.plan import PLAN_TOOL, STATUSES
from laris.shared.skills.loader import SkillError, SkillLibrary

_PATH = {"type": "string", "description": "File or folder path (project-relative)"}
_MEMORY_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _enabled_brain_tools(rt: HarnessRuntime, tools: tuple) -> tuple:
    """All brain tools locally; with a policy server only `save_knowledge` (the brain is theirs)."""
    if not rt.config.brain.enabled:
        return ()
    return tools[:1] if rt.remote else tools


def build_registry(
    service: SearchService,
    sandbox: Sandbox,
    runtime: Optional[HarnessRuntime] = None,
    skills: Optional[SkillLibrary] = None,
    memory_dir: Optional[Path] = None,
) -> ToolRegistry:
    rt = runtime or HarnessRuntime()
    agent, app, strings = rt.config.agent, rt.config.app, rt.strings
    registry = ToolRegistry(default_timeout_s=agent.default_tool_timeout_s)

    def timeout(name: str) -> Optional[float]:
        return agent.tool_timeouts_s.get(name)

    def rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(rt.root).as_posix()
        except ValueError:
            return path.name

    def list_files(args: Dict[str, Any]) -> Any:
        base = sandbox.resolve_read(args.get("path", "."))
        if not base.is_dir():
            raise ToolExecutionError("not_a_directory", "not a directory")
        limit = min(int(args.get("limit", 100)), agent.list_max_entries)
        entries = [e for e in sorted(base.iterdir()) if not rt.paths.denied(e)][:limit]
        return [
            {"name": e.name, "type": "dir" if e.is_dir() else "file", "bytes": e.stat().st_size}
            for e in entries
        ]

    def read_file(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_read(args["path"])
        if not path.is_file():
            raise ToolExecutionError("not_found", strings.get("tools.not_found"))
        try:
            text = read_text_from_bytes(path.name, path.read_bytes(), app)
        except IngestError as exc:
            raise ToolExecutionError("unreadable", str(exc)) from exc
        offset = int(args.get("offset", 0))
        limit = min(int(args.get("max_chars", agent.read_max_chars)), agent.read_max_chars)
        return {
            "path": rel(path),
            "total_chars": len(text),
            "offset": offset,
            "text": text[offset : offset + limit],
            "truncated": offset + limit < len(text),
            "ocr_used": path.suffix.lower() in IMAGE_SUFFIXES,
        }

    def write_file(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_write(args["path"])
        if path.exists() and not args.get("overwrite", False):
            raise ToolExecutionError("exists", strings.get("tools.exists"))
        path.parent.mkdir(parents=True, exist_ok=True)
        content = rt.redactor.redact(args["content"])[0]  # never persist a credential
        path.write_text(content, encoding="utf-8")
        return {"path": rel(path), "bytes": len(content.encode("utf-8"))}

    def ingest(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_read(args["path"])
        try:
            chunks = chunks_from_path(path, cfg=app, base=rt.root, skip=rt.paths.denied)
        except IngestError as exc:
            raise ToolExecutionError("unreadable", str(exc)) from exc
        return service.ingest(chunks)

    def search(args: Dict[str, Any]) -> Any:
        top_k = min(int(args.get("top_k", app.search_default_top_k)), agent.search_max_top_k)
        try:
            found = service.search(args["query"], args.get("mode", "bm25"), top_k)
        except ServiceError as exc:
            raise ToolExecutionError("search_failed", str(exc)) from exc
        for hit in found["hits"]:  # small tool output keeps long sessions inside the context
            if len(hit["text"]) > agent.search_hit_chars:
                hit["text"] = hit["text"][: agent.search_hit_chars] + "…"
                hit["truncated"] = True
        return found

    def answer(args: Dict[str, Any]) -> Any:
        try:
            return service.answer(args["question"], args.get("mode", "bm25"))
        except ServiceError as exc:
            raise ToolExecutionError("answer_failed", str(exc)) from exc

    def discourse(args: Dict[str, Any]) -> Any:
        from laris.shared.scientific.extractor import ScientificDiscourseExtractor

        text = args.get("text")
        if text is None:
            if "path" not in args:
                raise ToolExecutionError("invalid_arguments", "provide text or path")
            text = read_file({"path": args["path"], "max_chars": agent.read_max_chars})["text"]
        found = ScientificDiscourseExtractor().extract(args.get("document_id", "doc"), text)
        return {
            "claims": found.claims,
            "methods": found.methods,
            "datasets": found.datasets,
            "metrics": found.metrics,
            "results": found.results,
            "limitations": found.limitations,
            "formulas": found.formulas,
            "note": strings.get("tools.discourse_note"),
        }

    def status(args: Dict[str, Any]) -> Any:
        info = service.status()
        keys = ("documents", "passages", "bm25_ready", "dense_ready", "model_configured")
        return {k: info[k] for k in keys}  # no checkpoint path or digests

    def use_skill(args: Dict[str, Any]) -> Any:
        if skills is None:
            raise ToolExecutionError("no_skills", strings.get("tools.no_skills"))
        try:
            skill = skills.get(args["name"])
        except SkillError as exc:
            raise ToolExecutionError("unknown_skill", str(exc)) from exc
        return {
            "name": skill.name,
            "description": skill.description,
            "instructions": skill.body[: agent.skill_max_chars],
            "truncated": len(skill.body) > agent.skill_max_chars,
            "arguments": args.get("arguments", ""),
            "references": [{"path": rel(p), "bytes": p.stat().st_size} for p in skill.references],
            "note": strings.get("tools.skill_note"),
        }

    def save_memory(args: Dict[str, Any]) -> Any:
        if memory_dir is None:
            raise ToolExecutionError("no_memory", strings.get("tools.no_memory"))
        name = args["name"].strip().removesuffix(".md")
        if not _MEMORY_NAME.fullmatch(name):
            raise ToolExecutionError("invalid_arguments", "name: lowercase letters, digits, - or _")
        content = rt.redactor.redact(args["content"].strip())[0]
        if rt.config.vault.enabled:  # the vault is the one memory store
            from laris.client.vault.hooks import project_vault
            from laris.shared.vault.memory import write_memory

            vault = project_vault(rt)
            try:
                mode, note = write_memory(vault, name, content, bool(args.get("append", True)))
                return {"path": rel(vault.root / note), "mode": mode}
            except ValueError:
                pass  # refused (for example a vault inside another vault): use the legacy folder
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / f"{name}.md"
        mode = "a" if args.get("append", True) and path.exists() else "w"
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(("\n" if mode == "a" else "") + content + "\n")
        return {"path": rel(path), "mode": "appended" if mode == "a" else "created"}

    def save_skill(args: Dict[str, Any]) -> Any:
        learning = rt.config.learning
        name = args["name"].strip()
        description = " ".join(args["description"].split())
        front = yaml.safe_dump(
            {"name": name, "description": description, "authored": "user"},
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        ).strip()
        text = f"---\n{front}\n---\n\n{args['body'].strip()}\n"
        problems = lint_skill(
            text, learning, rt.injection, rt.redactor, agent.skill_max_chars, name
        )
        if problems:
            raise ToolExecutionError("invalid_skill", "; ".join(problems))
        folder = Path(learning.skill_dir).expanduser()
        folder = folder if folder.is_absolute() else rt.root / folder
        try:
            path, replaced = install_skill(folder, name, text, bool(args.get("overwrite")))
        except SkillError as exc:
            raise ToolExecutionError("exists", str(exc)) from exc
        return {"skill": name, "path": rel(path), "replaced": replaced}

    def plan_unavailable(args: Dict[str, Any]) -> Any:
        # the loop handles update_plan itself; reaching this means no loop is running
        raise ToolExecutionError("no_session", "the plan belongs to an agent session")

    def consult_brief(args: Dict[str, Any]) -> Any:
        found = rt.brain.consult(
            args["task"], args.get("workflow", ""), rt.config.brain.consult == "always"
        )
        if found is None:
            return {"brief": "", "trace": [], "classification": "internal"}
        return {"brief": found.brief, "trace": found.trace, "classification": "internal"}

    def brain_call(fn: Any) -> Any:
        def run(args: Dict[str, Any]) -> Any:
            try:
                return fn(args)
            except BrainError as exc:
                raise ToolExecutionError(exc.code, str(exc)) from exc

        return run

    def save_knowledge(args: Dict[str, Any]) -> Any:
        from laris.client.vault.hooks import project_vault
        from laris.client.vault.knowledge import KnowledgeWriter

        if not (rt.config.vault.enabled and rt.config.brain.knowledge):
            raise ToolExecutionError("disabled", "knowledge notes are turned off")
        writer = KnowledgeWriter(project_vault(rt), rt.brain, rt.config.brain, rt.redactor.redact)
        found = writer.add_taught(args["title"], args["content"], args.get("domain", ""))
        if found.note.status == "skipped":
            raise ToolExecutionError("refused", found.note.reason or "note was refused")
        rt.brain.refresh_knowledge()
        return {
            "domain": found.domain,
            "note": found.note.note.rsplit("/", 1)[-1][:-3],
            "status": found.note.status,
        }

    brain = rt.brain
    brain_tools = (
        ToolSpec(
            "save_knowledge",
            "Add new knowledge the user taught to the brain under its domain (needs approval). "
            "This is knowledge, not a skill: use save_skill only when asked for a skill.",
            schema(
                {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "domain": {"type": "string", "description": "A domain hub name, optional"},
                },
                ["title", "content"],
            ),
            save_knowledge,
            writes=True,
        ),
        ToolSpec(
            "brain_open_root",
            "Open the entry note of the internal guidance tree (domain hubs, relation types).",
            schema({}),
            brain_call(lambda a: brain.open_root()),
        ),
        ToolSpec(
            "brain_route",
            "Pick the domain hub for a task (by workflow name or keywords). Returns hub ids.",
            schema({"task": {"type": "string"}, "workflow": {"type": "string"}}, ["task"]),
            brain_call(
                lambda a: {
                    "hubs": brain.route(a["task"], a.get("workflow", "")),
                    "classification": "internal",
                }
            ),
        ),
        ToolSpec(
            "brain_open",
            "Open one guidance note by id: summary, children and prerequisites; full text only "
            "when full is true. Internal: never quote it.",
            schema({"id": {"type": "string"}, "full": {"type": "boolean"}}, ["id"]),
            brain_call(lambda a: brain.open(a["id"], bool(a.get("full")))),
        ),
        ToolSpec(
            "brain_neighbors",
            "List the typed relations (requires, uses, feeds, ...) of a guidance note.",
            schema({"id": {"type": "string"}}, ["id"]),
            brain_call(lambda a: brain.neighbours(a["id"])),
        ),
        ToolSpec(
            "brain_search",
            "Fallback when no hub fits: match words against guidance titles and summaries.",
            schema({"query": {"type": "string"}}, ["query"]),
            brain_call(lambda a: brain.search(a["query"])),
        ),
        ToolSpec(
            "brain_consult",
            "Brief for a task: matching domain hub, its playbook and next notes. Internal.",
            schema({"task": {"type": "string"}, "workflow": {"type": "string"}}, ["task"]),
            brain_call(consult_brief),
        ),
    )
    top_k = {"type": "integer", "minimum": 1, "maximum": agent.search_max_top_k}
    mode = {"type": "string", "enum": ["bm25", "dense", "hybrid"]}
    specs = (
        ToolSpec(
            "list_files",
            "List files in a folder inside the sandbox.",
            schema({"path": _PATH, "limit": {"type": "integer", "minimum": 1}}),
            list_files,
        ),
        ToolSpec(
            "read_file",
            "Read a txt/md/pdf/image file as text (OCR for scans and images).",
            schema(
                {
                    "path": _PATH,
                    "offset": {"type": "integer", "minimum": 0},
                    "max_chars": {"type": "integer", "minimum": 1},
                },
                ["path"],
            ),
            read_file,
            timeout_s=timeout("read_file"),
            untrusted=True,
        ),
        ToolSpec(
            "write_file",
            "Create a text file in the agent output folder (needs approval).",
            schema(
                {
                    "path": {"type": "string", "description": "Relative to the output folder"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                ["path", "content"],
            ),
            write_file,
            writes=True,
        ),
        ToolSpec(
            "ingest_path",
            "Add a file or folder to the search corpus (needs approval).",
            schema({"path": _PATH}, ["path"]),
            ingest,
            writes=True,
            timeout_s=timeout("ingest_path"),
        ),
        ToolSpec(
            "search_corpus",
            "Search the corpus; returns passages with sources.",
            schema({"query": {"type": "string"}, "mode": mode, "top_k": top_k}, ["query"]),
            search,
            untrusted=True,
        ),
        ToolSpec(
            "answer_question",
            "Extractive answer from top passages (needs a local model).",
            schema({"question": {"type": "string"}, "mode": mode}, ["question"]),
            answer,
            timeout_s=timeout("answer_question"),
            untrusted=True,
        ),
        ToolSpec(
            "extract_discourse",
            "Extract claims, methods, datasets, metrics and limitations.",
            schema({"text": {"type": "string"}, "path": _PATH, "document_id": {"type": "string"}}),
            discourse,
            timeout_s=timeout("extract_discourse"),
            untrusted=True,
        ),
        ToolSpec(
            "use_skill",
            "Load a skill's instructions (see the Skills list in the system prompt).",
            schema({"name": {"type": "string"}, "arguments": {"type": "string"}}, ["name"]),
            use_skill,
        ),
        ToolSpec(
            "save_memory",
            "Save a short note to the project memory folder (needs approval).",
            schema(
                {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean"},
                },
                ["name", "content"],
            ),
            save_memory,
            writes=True,
        ),
        ToolSpec(
            "save_skill",
            "Save a complete skill (front matter plus When to use, Steps, Output, Limits) after "
            "approval. Use it when the user teaches a new capability.",
            schema(
                {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                ["name", "description", "body"],
            ),
            save_skill,
            writes=True,
        ),
        ToolSpec("corpus_status", "Show corpus size and model availability.", schema({}), status),
        ToolSpec(
            PLAN_TOOL,
            "Write or update the plan for a multi-step goal. Send the whole list each time: "
            "steps with a status (pending, in_progress, done, failed, skipped). The user sees it.",
            schema(
                {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "status": {"type": "string", "enum": list(STATUSES)},
                            },
                            "required": ["text"],
                        },
                    }
                },
                ["steps"],
            ),
            plan_unavailable,
        ),
    )
    from laris.client.agent.scholarly_tools import scholarly_specs

    for spec in (*specs, *scholarly_specs(service, rt), *_enabled_brain_tools(rt, brain_tools)):
        registry.register(spec)
    return registry
