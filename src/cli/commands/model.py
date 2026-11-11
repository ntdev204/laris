"""`laris model serve`: OpenAI-compatible model API (placeholder backend until the core exists).

Host, port, model name, body limit and API-key variable come from the `serving` configuration.
"""

import argparse
import ssl
from pathlib import Path
from typing import Any, Callable, List, Optional

from cli.common import cli_overrides, model_flags
from gateway import PolicyGateway
from harness.runtime import HarnessRuntime
from serverdata import ServerData, tls
from serving.auth import KeyRing
from serving.model_server import ModelService, build_server, enable_tls, load_backend


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
        parser.add_argument(
            "--policy-root", default=None, help="Folder holding the system .laris/ (default: cwd)"
        )
        parser.add_argument("--tls-cert", default=None, help="PEM certificate chain (HTTPS)")
        parser.add_argument("--tls-identity", default=None, help="PEM private key (HTTPS)")
        parser.add_argument(
            "--api-key-env", default=None, help="Env var with the accepted keys (comma separated)"
        )
        parser.add_argument(
            "--allowed-file", default=None, help="File with accepted keys, one per line"
        )

    def run(self, args: argparse.Namespace) -> int:
        root = Path(args.policy_root or Path.cwd())
        runtime = HarnessRuntime.load(root, cli_overrides(args))
        if runtime.remote:
            print(f"[ERROR] no system policy under {root}/.laris/prompts: the server needs it")
            return 2
        cfg = runtime.config.serving
        host, port = args.host or cfg.host, args.port or cfg.port
        backend = load_backend(args.backend, runtime.strings)
        name = args.model_name or (cfg.model_name if args.backend else cfg.placeholder_name)
        key_env = args.api_key_env or cfg.api_key_env
        ring = KeyRing.load(key_env, args.allowed_file or cfg.allowed_file, runtime.environ)
        cert, identity = (
            args.tls_cert or cfg.tls_cert_file,
            args.tls_identity or cfg.tls_identity_file,
        )
        if not cert and not identity:  # certificate and key in the TLS folder: HTTPS is on
            cert, identity = tls.discover(cfg.tls_dir)
        if bool(cert) != bool(identity):
            print("[ERROR] HTTPS needs both a certificate and its private key")
            return 2
        if not cert and not cfg.allow_plain_http and host not in ("127.0.0.1", "localhost", "::1"):
            print(
                f"[ERROR] refusing plain HTTP on {host}: run `laris-server tls init` "
                "or pass --tls-cert and --tls-identity "
                "(or terminate TLS in front and set serving.allow_plain_http)"
            )
            return 2
        extra = [] if host in ("0.0.0.0", "::", "") else [host]  # a specific bind address is ours
        redact = lambda t: runtime.redactor.redact(t)[0]  # noqa: E731
        try:
            data = ServerData(
                cfg, root, redact, ring if cfg.require_auth else None, runtime.environ, extra
            )
        except ValueError as exc:  # e.g. a master secret file other users can read
            print(f"[ERROR] {exc}")
            return 2
        created = data.ensure_default_key() if cfg.require_auth else None
        if created:
            print(
                "Default key created (every permission, no limit, usable from this machine only):"
            )
            print(f"  {created}", flush=True)
            print("It is stored encrypted; print it again with `laris-server keys reveal default`.")
        gateway = PolicyGateway(
            runtime,
            backend,
            name,
            meter=data.usage,
            traces=data.traces,
            think_tags=cfg.reasoning_tags,
            chars_per_token=cfg.chars_per_token,
        )
        service = ModelService(
            backend,
            name,
            _embedder(args),
            None,
            gateway,
            auth=data.auth if cfg.require_auth else None,
            meter=data.usage,
            admin=data,
            chars_per_token=cfg.chars_per_token,
            reasoning_http=cfg.reasoning_http,
        )
        purged = data.traces.purge(cfg.trace_retention_days)
        count = len(data.keys.list())
        print(
            f"{count} database key(s), {len(ring)} fixed key(s); {purged} old trace(s) purged"
            if cfg.require_auth
            else "AUTHENTICATION IS OFF"
        )
        server = build_server(service, host, port, cfg.max_body_bytes)
        if cert:
            try:
                enable_tls(server, cert, identity)
            except (OSError, ssl.SSLError) as exc:
                print(f"[ERROR] cannot load the TLS certificate or key: {exc}")
                server.server_close()
                return 2
        kind = "custom backend" if args.backend else "PLACEHOLDER backend (no trained core model)"
        scheme = "https" if cert else "http"
        if cert:
            print(f"certificate fingerprint {tls.fingerprint(cert)}")
        print(f"LARIS model API on {scheme}://{host}:{port}/v1  model={name}  [{kind}]")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            server.server_close()
        return 0


COMMANDS: dict[str, Any] = {"serve": _Serve()}
