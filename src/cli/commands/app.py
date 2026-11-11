"""`laris app ...`: local end-to-end application (ingest, index, search, ask, serve).

Every default (workspace, host, port, limits) comes from configuration; flags only override.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from application.server import serve
from application.service import SearchService, ServiceError
from application.workspace import IngestError, chunks_from_path
from cli.common import load_runtime, make_service, model_flags


class _Command:
    def __init__(
        self,
        flags: Dict[str, Dict[str, Any]],
        call: Callable[[SearchService, argparse.Namespace, Any], Any],
        model: bool = True,
    ) -> None:
        self.flags, self.call, self.model = flags, call, model

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--workspace", default=None, help="Workspace directory (config: app.workspace)"
        )
        if self.model:
            model_flags(parser)
        for name, kwargs in self.flags.items():
            parser.add_argument(name, **kwargs)

    def run(self, args: argparse.Namespace) -> int:
        try:
            runtime = load_runtime(args)
            result = self.call(make_service(args, runtime), args, runtime)
        except (ServiceError, IngestError, FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0


def _ingest(service: SearchService, args: argparse.Namespace, rt: Any) -> Optional[Dict[str, int]]:
    total = {"documents": 0, "passages": 0}
    for raw in args.paths:
        chunks = chunks_from_path(
            Path(raw), args.limit, rt.config.app, rt.root, skip=rt.paths.denied
        )
        counts = service.workspace.add(chunks)
        total["documents"] += counts["documents"]
        total["passages"] += counts["passages"]
    total["total_passages"] = len(service.workspace.load())
    return total


def _index(service: SearchService, args: argparse.Namespace, rt: Any) -> Dict[str, Any]:
    return service.build_dense_index(
        lambda done, n: print(f"embedding {done}/{n}") if done % 640 == 0 or done == n else None
    )


def _top_k(args: argparse.Namespace, rt: Any) -> int:
    return int(args.top_k or rt.config.app.search_default_top_k)


def _search(service: SearchService, args: argparse.Namespace, rt: Any) -> None:
    result = service.search(args.query, args.mode, _top_k(args, rt))
    for hit in result["hits"]:
        snippet = " ".join(hit["text"].split())[:200]
        print(f"{hit['rank']}. [{hit['source']}] {hit['title']}\n   {snippet}")
    print(f"\n{result['notice']}")


def _ask(service: SearchService, args: argparse.Namespace, rt: Any) -> None:
    result = service.answer(args.query, args.mode, _top_k(args, rt))
    primary = result["primary"]
    print(
        f"Answer: {primary['answer']} (source: {primary['source']})"
        if primary
        else "No verbatim answer found."
    )
    for hit in result["hits"]:
        print(f"  - [{hit['source']}] {' '.join(hit['text'].split())[:160]}")
    print(f"\n{result['notice']}")


def _status(service: SearchService, args: argparse.Namespace, rt: Any) -> Dict[str, Any]:
    info = service.status()
    if not rt.config.security.expose_internal_info:
        info.pop("checkpoint", None)
        info.pop("model_sha256", None)
    return info


def _serve(service: SearchService, args: argparse.Namespace, rt: Any) -> None:
    from application.chat_app import ChatApp

    chat = ChatApp(service, Path.cwd(), overrides=_overrides(args))
    cfg = chat.runtime.config.app
    host, port = args.host or cfg.host, args.port or cfg.port
    server = serve(service, host, port, chat)
    print(f"LARIS chat on http://{host}:{port}. Ctrl+C stops.")
    print(f"Model: {chat.model_health()['detail']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def _overrides(args: argparse.Namespace) -> Dict[str, Any]:
    from cli.common import cli_overrides

    return cli_overrides(args)


_SEARCH_FLAGS: Dict[str, Dict[str, Any]] = {
    "--query": {"required": True, "help": "Question or keywords"},
    "--mode": {"choices": ["bm25", "dense", "hybrid"], "default": "bm25"},
    "--top-k": {
        "type": int,
        "default": None,
        "help": "Passages (config: app.search_default_top_k)",
    },
}


class _Serve(_Command):
    def run(self, args: argparse.Namespace) -> int:
        try:
            runtime = load_runtime(args)
            _serve(make_service(args, runtime), args, runtime)
        except (ServiceError, FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"[ERROR] {exc}")
            return 2
        return 0


COMMANDS = {
    "ingest": _Command(
        {
            "paths": {"nargs": "+", "help": "Files or folders (txt, md, pdf, images, BEIR corpus)"},
            "--limit": {"type": int, "default": None, "help": "Max records per .jsonl file"},
        },
        _ingest,
        model=False,
    ),
    "index": _Command({}, _index),
    "search": _Command(_SEARCH_FLAGS, lambda s, a, r: _search(s, a, r)),
    "ask": _Command(_SEARCH_FLAGS, lambda s, a, r: _ask(s, a, r)),
    "status": _Command({}, _status, model=False),
    "serve": _Serve(
        {
            "--host": {"default": None, "help": "Bind address (config: app.host)"},
            "--port": {"type": int, "default": None, "help": "Port (config: app.port)"},
            "--model-api-url": {
                "default": None,
                "help": "Model API base URL (config: model_api.base_url)",
            },
            "--model-name": {"default": None, "help": "Model name (config: model_api.model)"},
            "--allow-write": {"action": "store_true", "help": "Auto-approve write tools"},
            "--chat-dir": {"default": None, "help": "Conversations folder (config: app.chat_dir)"},
        },
        lambda s, a, r: None,
    ),
}
