"""Compatibility surface of the former `http.server` implementation: `ModelService`,
`build_server` and `enable_tls` now come from the FastAPI server in `laris.server.api`."""

from typing import Any, Sequence

from laris.server.serving.service import ModelService
from laris.shared.backend import load_backend

__all__ = ["ModelService", "build_server", "enable_tls", "load_backend"]


def build_server(
    service: ModelService,
    host: str,
    port: int,
    max_body_bytes: int,
    trusted_proxies: Sequence[str] = (),
) -> Any:
    """The P1 server (FastAPI on uvicorn) bound to `host:port`; call `serve_forever()`."""
    from laris.server.api import ApiServer, create_app

    return ApiServer(
        create_app(service, max_body_bytes, trusted_proxies=trusted_proxies), host, port
    )


def enable_tls(server: Any, cert_file: str, identity_file: str) -> None:
    """Serve HTTPS: certificate chain and private key loaded from PEM files."""
    server.enable_tls(cert_file, identity_file)
