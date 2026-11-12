"""`laris model serve`: OpenAI-compatible model API (placeholder backend until the core exists).

Host, port, model name, body limit and API-key variable come from the `serving` configuration.
"""

import argparse
import ssl
from pathlib import Path
from typing import Any

from cli.common import cli_overrides
from laris.server.gateway import PolicyGateway
from laris.server.serverdata import ServerData, tls
from laris.server.serving.auth import KeyRing
from laris.server.serving.limits import LimitedProvider
from laris.server.serving.model_server import ModelService, build_server, enable_tls
from laris.shared.harness.runtime import HarnessRuntime
from laris.shared.http_provider import HttpChatProvider, HttpEmbedder


class _Serve:
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", default=None, help="Bind address (config: serving.host)")
        parser.add_argument("--port", type=int, default=None, help="Port (config: serving.port)")
        parser.add_argument("--model-name", default=None, help="Name reported by /v1/models")
        parser.add_argument(
            "--model-url", default=None, help="Model block URL (config: model_api.internal_url)"
        )
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
        api = runtime.config.model_api
        model_url = args.model_url or api.internal_url
        if not model_url:
            print("[ERROR] no model block: set model_api.internal_url or pass --model-url")
            return 2
        name = args.model_name or cfg.model_name
        backend = LimitedProvider(
            HttpChatProvider(model_url, name, None, api.timeout_s, api.temperature),
            cfg.model_concurrency,
        )
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
            where = data.deliver_default_key(created)
            print(
                "Default key created (every permission, no limit, usable from this machine only)."
            )
            if where:
                print(f"It was written to {where} (mode 0600).")
            print("Print it with `laris-server keys reveal default`; it is never shown here.")
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
            HttpEmbedder(model_url, name, None, api.timeout_s),
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
        server = build_server(service, host, port, cfg.max_body_bytes, cfg.trusted_proxies)
        retention = None
        if cfg.database_engine == "postgres":  # partitions, daily summary, expiry (T62)
            from laris.server.storage.maintenance import Maintenance, RetentionWorker

            retention = RetentionWorker(
                Maintenance(data.db, cfg.usage_retention_days, cfg.trace_retention_days),
                cfg.retention_interval_s,
            ).start()
        if cert:
            try:
                enable_tls(server, cert, identity)
            except (OSError, ssl.SSLError) as exc:
                print(f"[ERROR] cannot load the TLS certificate or key: {exc}")
                server.server_close()
                return 2
        kind = f"model block {model_url}"
        scheme = "https" if cert else "http"
        if cert:
            print(f"certificate fingerprint {tls.fingerprint(cert)}")
        print(f"LARIS model API on {scheme}://{host}:{port}/v1  model={name}  [{kind}]")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            if retention is not None:
                retention.stop()
            server.server_close()
        return 0


COMMANDS: dict[str, Any] = {"serve": _Serve()}
