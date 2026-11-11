"""Built-in tools: files, OCR, corpus search, extractive QA and scientific discourse extraction."""

from pathlib import Path
from typing import Any, Dict, Optional

from laris.agent.tools import (
    MAX_READ_CHARS,
    Sandbox,
    ToolExecutionError,
    ToolRegistry,
    ToolSpec,
    schema,
)
from laris.application.service import SearchService, ServiceError
from laris.application.workspace import (
    IMAGE_SUFFIXES,
    IngestError,
    chunks_from_path,
    read_text_from_bytes,
)

_PATH = {"type": "string", "description": "File or folder path"}


def build_registry(service: SearchService, sandbox: Sandbox) -> ToolRegistry:
    registry = ToolRegistry()

    def list_files(args: Dict[str, Any]) -> Any:
        base = sandbox.resolve_read(args.get("path", "."))
        if not base.is_dir():
            raise ToolExecutionError("not_a_directory", f"{base} is not a directory")
        entries = sorted(base.iterdir())[: int(args.get("limit", 100))]
        return [
            {"name": e.name, "type": "dir" if e.is_dir() else "file", "bytes": e.stat().st_size}
            for e in entries
        ]

    def read_file(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_read(args["path"])
        if not path.is_file():
            raise ToolExecutionError("not_found", f"no such file: {args['path']}")
        try:
            text = read_text_from_bytes(path.name, path.read_bytes())
        except IngestError as exc:
            raise ToolExecutionError("unreadable", str(exc)) from exc
        offset = int(args.get("offset", 0))
        limit = min(int(args.get("max_chars", MAX_READ_CHARS)), MAX_READ_CHARS)
        return {
            "path": str(path),
            "total_chars": len(text),
            "offset": offset,
            "text": text[offset : offset + limit],
            "truncated": offset + limit < len(text),
            "ocr_used": path.suffix.lower() in IMAGE_SUFFIXES,
        }

    def write_file(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_write(args["path"])
        if path.exists() and not args.get("overwrite", False):
            raise ToolExecutionError("exists", f"{path.name} exists; pass overwrite=true")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return {"path": str(path), "bytes": len(args["content"].encode("utf-8"))}

    def ingest(args: Dict[str, Any]) -> Any:
        path = sandbox.resolve_read(args["path"])
        try:
            chunks = chunks_from_path(path)
        except IngestError as exc:
            raise ToolExecutionError("unreadable", str(exc)) from exc
        return service.workspace.add(chunks)

    def search(args: Dict[str, Any]) -> Any:
        try:
            return service.search(
                args["query"], args.get("mode", "bm25"), int(args.get("top_k", 5))
            )
        except ServiceError as exc:
            raise ToolExecutionError("search_failed", str(exc)) from exc

    def answer(args: Dict[str, Any]) -> Any:
        try:
            return service.answer(args["question"], args.get("mode", "bm25"))
        except ServiceError as exc:
            raise ToolExecutionError("answer_failed", str(exc)) from exc

    def discourse(args: Dict[str, Any]) -> Any:
        from laris.scientific.extractor import ScientificDiscourseExtractor

        text = args.get("text")
        if text is None:
            if "path" not in args:
                raise ToolExecutionError("invalid_arguments", "provide text or path")
            text = read_file({"path": args["path"], "max_chars": MAX_READ_CHARS})["text"]
        found = ScientificDiscourseExtractor().extract(args.get("document_id", "doc"), text)
        return {
            "claims": found.claims,
            "methods": found.methods,
            "datasets": found.datasets,
            "metrics": found.metrics,
            "results": found.results,
            "limitations": found.limitations,
            "formulas": found.formulas,
            "note": "heuristic extraction; spans refer to the supplied text, not verified support",
        }

    def status(args: Dict[str, Any]) -> Any:
        return service.status()

    for spec in (
        ToolSpec(
            "list_files",
            "List files in a folder inside the sandbox.",
            schema({"path": _PATH, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
            list_files,
        ),
        ToolSpec(
            "read_file",
            "Read a txt/md/pdf/image file as text (OCR for scans and images).",
            schema(
                {
                    "path": _PATH,
                    "offset": {"type": "integer", "minimum": 0},
                    "max_chars": {"type": "integer", "minimum": 1, "maximum": MAX_READ_CHARS},
                },
                ["path"],
            ),
            read_file,
            timeout_s=120.0,
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
            timeout_s=300.0,
        ),
        ToolSpec(
            "search_corpus",
            "Search the corpus; returns passages with sources.",
            schema(
                {
                    "query": {"type": "string"},
                    "mode": {"type": "string", "enum": ["bm25", "dense", "hybrid"]},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["query"],
            ),
            search,
        ),
        ToolSpec(
            "answer_question",
            "Extractive answer from top passages (needs a local model).",
            schema(
                {
                    "question": {"type": "string"},
                    "mode": {"type": "string", "enum": ["bm25", "dense", "hybrid"]},
                },
                ["question"],
            ),
            answer,
            timeout_s=120.0,
        ),
        ToolSpec(
            "extract_discourse",
            "Extract claims, methods, datasets, metrics and limitations.",
            schema({"text": {"type": "string"}, "path": _PATH, "document_id": {"type": "string"}}),
            discourse,
            timeout_s=60.0,
        ),
        ToolSpec("corpus_status", "Show corpus size and model availability.", schema({}), status),
    ):
        registry.register(spec)
    return registry


def default_sandbox(
    read_roots: Optional[list] = None, output_dir: Optional[Path] = None
) -> Sandbox:
    roots = [Path(r) for r in (read_roots or [Path.cwd()])]
    return Sandbox(roots, Path(output_dir or Path("artifacts/agent/output")).resolve())
