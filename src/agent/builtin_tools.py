"""Built-in tools: files, OCR, corpus search, extractive QA, skills, memory, discourse.

Limits, timeouts and policies come from the harness runtime (configuration); results never carry
absolute paths and file reads honour the deny-list of internal and secret files.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional

from agent.tools import Sandbox, ToolExecutionError, ToolRegistry, ToolSpec, schema
from application.service import SearchService, ServiceError
from application.workspace import (
    IMAGE_SUFFIXES,
    IngestError,
    chunks_from_path,
    read_text_from_bytes,
)
from harness.runtime import HarnessRuntime
from skills.loader import SkillError, SkillLibrary

_PATH = {"type": "string", "description": "File or folder path (project-relative)"}
_MEMORY_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


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
        return service.workspace.add(chunks)

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
        from scientific.extractor import ScientificDiscourseExtractor

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
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / f"{name}.md"
        mode = "a" if args.get("append", True) and path.exists() else "w"
        content = rt.redactor.redact(args["content"].strip())[0]
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(("\n" if mode == "a" else "") + content + "\n")
        return {"path": rel(path), "mode": "appended" if mode == "a" else "created"}

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
        ToolSpec("corpus_status", "Show corpus size and model availability.", schema({}), status),
    )
    for spec in specs:
        registry.register(spec)
    return registry
