"""`laris-model`: the model block. `laris-model serve` runs the model service (protocol P2).

Host, port and backend come from the `model_service` configuration; flags override it. The
self-trained encoder and its training, evaluation and data tooling were removed in T233 (D48).
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from cli.parser import Table

COMMANDS: Table = {}


def _serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laris-model serve", description="Serve the model API (OpenAI-compatible, internal)"
    )
    parser.add_argument("--host", default=None, help="Bind address (config: model_service.host)")
    parser.add_argument("--port", type=int, default=None, help="Port (config: model_service.port)")
    parser.add_argument("--model-name", default=None, help="Name reported by /v1/models")
    parser.add_argument("--backend", default=None, help="package.module:ClassName ChatProvider")
    return parser


def serve(argv: Sequence[str]) -> int:
    args = _serve_parser().parse_args(list(argv))
    import uvicorn

    from laris.model.app import create_app
    from laris.model.service import ModelService, build_queue
    from laris.model.tools import Limits, ToolBox
    from laris.shared.backend import load_backend
    from laris.shared.config.loader import load_runtime_config

    cfg = load_runtime_config(Path.cwd()).model_service
    spec = args.backend or cfg.backend
    backend = load_backend(spec or None)
    name = args.model_name or (cfg.model_name if spec else cfg.placeholder_name)
    queue = build_queue(backend, cfg)
    app = create_app(
        ModelService(
            backend,
            name,
            None,
            queue,
            ToolBox(Limits(cfg.tool_max_chars, cfg.tool_max_documents)),
        ),
        cfg.max_body_bytes,
    )
    host, port = args.host or cfg.host, args.port or cfg.port
    kind = "custom backend" if spec else "PLACEHOLDER backend (no chat model configured)"
    print(f"LARIS model service on http://{host}:{port}/v1  model={name}  [{kind}]", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    items = list(sys.argv[1:] if argv is None else argv)
    if items[:1] == ["serve"]:
        return serve(items[1:])
    print("usage: laris-model serve [--host H] [--port P] [--model-name N] [--backend M:C]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
