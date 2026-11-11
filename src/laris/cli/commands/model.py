"""`laris model serve`: OpenAI-compatible model API (placeholder backend until the core exists)."""

import argparse
from pathlib import Path
from typing import Any, Callable, List, Optional

from laris.serving.model_server import (
    ModelService,
    api_key_from_env,
    build_server,
    load_backend,
)


def _embedder(args: argparse.Namespace) -> Optional[Callable[[List[str]], List[List[float]]]]:
    if not (args.checkpoint and args.tokenizer_model):
        return None
    from laris.language.inference.loader import load_encoder
    from laris.language.inference.predictor import LanguageEncoderPredictor

    predictor = LanguageEncoderPredictor(
        load_encoder(Path(args.checkpoint), Path(args.tokenizer_model), device=args.device)
    )
    return lambda texts: [[float(x) for x in row] for row in predictor.embed(texts)]


class _Serve:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default="127.0.0.1", help="Bind address (local by default)")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--model-name", default=None, help="Name reported by /v1/models")
        parser.add_argument("--backend", default=None, help="package.module:ClassName ChatProvider")
        parser.add_argument("--checkpoint", help="Encoder checkpoint for /v1/embeddings")
        parser.add_argument("--tokenizer-model")
        parser.add_argument("--device", default=None)
        parser.add_argument("--api-key-env", default=None, help="Env var holding the required key")

    def run(self, args: argparse.Namespace) -> int:
        backend = load_backend(args.backend)
        name = args.model_name or ("laris-core" if args.backend else "laris-placeholder")
        service = ModelService(backend, name, _embedder(args), api_key_from_env(args.api_key_env))
        server = build_server(service, args.host, args.port)
        kind = "custom backend" if args.backend else "PLACEHOLDER backend (no trained core model)"
        print(f"LARIS model API on http://{args.host}:{args.port}/v1  model={name}  [{kind}]")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            server.server_close()
        return 0


COMMANDS: dict[str, Any] = {"serve": _Serve()}
