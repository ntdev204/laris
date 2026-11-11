"""`laris model serve`: OpenAI-compatible model API (placeholder backend until the core exists).

Host, port, model name, body limit and API-key variable come from the `serving` configuration.
"""

import argparse
from pathlib import Path
from typing import Any, Callable, List, Optional

from cli.common import load_runtime, model_flags
from serving.model_server import ModelService, api_key_from_env, build_server, load_backend


def _embedder(args: argparse.Namespace) -> Optional[Callable[[List[str]], List[List[float]]]]:
    if not (args.checkpoint and args.tokenizer_model):
        return None
    from language.inference.loader import load_encoder
    from language.inference.predictor import LanguageEncoderPredictor

    predictor = LanguageEncoderPredictor(
        load_encoder(Path(args.checkpoint), Path(args.tokenizer_model), device=args.device)
    )
    return lambda texts: [[float(x) for x in row] for row in predictor.embed(texts)]


class _Serve:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default=None, help="Bind address (config: serving.host)")
        parser.add_argument("--port", type=int, default=None, help="Port (config: serving.port)")
        parser.add_argument("--model-name", default=None, help="Name reported by /v1/models")
        parser.add_argument("--backend", default=None, help="package.module:ClassName ChatProvider")
        model_flags(parser)
        parser.add_argument("--api-key-env", default=None, help="Env var holding the required key")

    def run(self, args: argparse.Namespace) -> int:
        runtime = load_runtime(args)
        cfg = runtime.config.serving
        host, port = args.host or cfg.host, args.port or cfg.port
        backend = load_backend(args.backend, runtime.strings)
        name = args.model_name or (cfg.model_name if args.backend else cfg.placeholder_name)
        key_env = args.api_key_env or cfg.api_key_env
        service = ModelService(
            backend, name, _embedder(args), api_key_from_env(key_env, runtime.environ)
        )
        server = build_server(service, host, port, cfg.max_body_bytes)
        kind = "custom backend" if args.backend else "PLACEHOLDER backend (no trained core model)"
        print(f"LARIS model API on http://{host}:{port}/v1  model={name}  [{kind}]")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            server.server_close()
        return 0


COMMANDS: dict[str, Any] = {"serve": _Serve()}
