"""`laris app ...`: local end-to-end application (ingest, index, search, ask, serve)."""

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from laris.application.server import serve
from laris.application.service import SearchService, ServiceError
from laris.application.workspace import IngestError, Workspace, chunks_from_path

DEFAULT_WORKSPACE = "artifacts/app/workspace"


def _common(parser: argparse.ArgumentParser, model: bool = True) -> None:
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="Workspace directory")
    if model:
        parser.add_argument(
            "--checkpoint", help="Checkpoint dir (e.g. <run>/best); enables dense/QA"
        )
        parser.add_argument("--tokenizer-model", help="SentencePiece .model file")
        parser.add_argument("--device", default=None, help="cuda or cpu (default: auto)")


def _service(args: argparse.Namespace) -> SearchService:
    return SearchService(
        Workspace(Path(args.workspace)),
        Path(args.checkpoint) if getattr(args, "checkpoint", None) else None,
        Path(args.tokenizer_model) if getattr(args, "tokenizer_model", None) else None,
        getattr(args, "device", None),
    )


class _Command:
    def __init__(
        self,
        flags: Dict[str, Dict[str, Any]],
        call: Callable[[SearchService, argparse.Namespace], Any],
        model: bool = True,
    ) -> None:
        self.flags, self.call, self.model = flags, call, model

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        _common(parser, self.model)
        for name, kwargs in self.flags.items():
            parser.add_argument(name, **kwargs)

    def run(self, args: argparse.Namespace) -> int:
        try:
            result = self.call(_service(args), args)
        except (ServiceError, IngestError, FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0


def _ingest(service: SearchService, args: argparse.Namespace) -> Optional[Dict[str, int]]:
    total = {"documents": 0, "passages": 0}
    for raw in args.paths:
        counts = service.workspace.add(chunks_from_path(Path(raw), args.limit))
        total["documents"] += counts["documents"]
        total["passages"] += counts["passages"]
    total["total_passages"] = len(service.workspace.load())
    return total


def _index(service: SearchService, args: argparse.Namespace) -> Dict[str, Any]:
    return service.build_dense_index(
        lambda done, n: print(f"embedding {done}/{n}") if done % 640 == 0 or done == n else None
    )


def _search(service: SearchService, args: argparse.Namespace) -> Dict[str, Any]:
    result = service.search(args.query, args.mode, args.top_k)
    for hit in result["hits"]:
        snippet = " ".join(hit["text"].split())[:200]
        print(f"{hit['rank']}. [{hit['source']}] {hit['title']}\n   {snippet}")
    print(f"\n{result['notice']}")
    return None  # type: ignore[return-value]


def _ask(service: SearchService, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    result = service.answer(args.query, args.mode, args.top_k)
    primary = result["primary"]
    print(
        f"Answer: {primary['answer']} (source: {primary['source']})"
        if primary
        else "No verbatim answer found."
    )
    for hit in result["hits"]:
        print(f"  - [{hit['source']}] {' '.join(hit['text'].split())[:160]}")
    print(f"\n{result['notice']}")
    return None


def _status(service: SearchService, args: argparse.Namespace) -> Dict[str, Any]:
    return service.status()


def _serve(service: SearchService, args: argparse.Namespace) -> None:
    from laris.application.chat_app import ChatApp

    chat = ChatApp(service, Path(args.chat_dir))
    changes: Dict[str, Any] = {}
    if args.model_api_url:
        changes.update(base_url=args.model_api_url, model=args.model_name)
    if args.allow_write:
        changes["allow_write"] = True
    if changes:
        chat.settings.update(changes)
    server = serve(service, args.host, args.port, chat)
    print(
        f"LARIS chat on http://{args.host}:{args.port}  (workspace {args.workspace}). Ctrl+C stops."
    )
    health = chat.model_health()
    print(f"Model: {health['detail']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


_Q = {"help": "Question or keywords"}
_SEARCH_FLAGS: Dict[str, Dict[str, Any]] = {
    "--query": {"required": True, **_Q},
    "--mode": {"choices": ["bm25", "dense", "hybrid"], "default": "bm25"},
    "--top-k": {"type": int, "default": 5},
}

COMMANDS = {
    "ingest": _Command(
        {
            "paths": {"nargs": "+", "help": "Files or folders (txt, md, pdf, BEIR corpus .jsonl)"},
            "--limit": {"type": int, "default": None, "help": "Max records per .jsonl file"},
        },
        _ingest,
        model=False,
    ),
    "index": _Command({}, _index),
    "search": _Command(_SEARCH_FLAGS, _search),
    "ask": _Command(_SEARCH_FLAGS, _ask),
    "status": _Command({}, _status, model=False),
    "serve": _Command(
        {
            "--host": {"default": "127.0.0.1", "help": "Bind address (local by default)"},
            "--port": {"type": int, "default": 8765},
            "--model-api-url": {
                "default": None,
                "help": "OpenAI-compatible model API for the agent",
            },
            "--model-name": {"default": "laris-core"},
            "--allow-write": {"action": "store_true", "help": "Let the web agent use write tools"},
            "--chat-dir": {"default": "artifacts/chat", "help": "Conversations, settings, uploads"},
        },
        _serve,
    ),
}
