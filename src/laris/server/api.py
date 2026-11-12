"""The server API (protocol P1) on FastAPI.

Routes: `GET /health`, `GET /v1/models`, `GET /v1/laris/{workflows,help,account}`,
`GET /v1/admin/{usage,reasoning}`, `POST /v1/laris/chat` (SSE through the policy gateway) and the
bare `POST /v1/embeddings`. Every route checks the key and its permission; bodies are validated
(`Content-Length` present, not negative, within the limit, a JSON object of the right shape) before
any work; `/v1/laris/*` also needs a supported `X-Laris-Protocol`. A failure after a stream has
started becomes an `error` event followed by `[DONE]`.
"""

import json
import socket
import threading
from typing import Any, Callable, Dict, Iterator, Optional, Sequence, Tuple

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from laris.protocol import (
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    ChatRequest,
    EmbedRequest,
    ProviderError,
    encode_done,
    encode_event,
)
from laris.server.serverdata import netcheck
from laris.server.serving.ports import (
    ACCOUNT,
    CHAT,
    EMBED,
    HELP,
    MODELS,
    WORKFLOWS,
    Principal,
    QuotaExceeded,
)
from laris.server.serving.service import ModelService

_END = object()


def create_app(
    service: ModelService,
    max_body_bytes: int,
    body_timeout_s: float = 30.0,
    trusted_proxies: Sequence[str] = (),
) -> FastAPI:
    trusted = netcheck.networks(trusted_proxies)

    def client_address(request: Request) -> Optional[str]:
        """The address key rules are checked against: the TCP peer, or the client a trusted
        proxy forwarded (`serving.trusted_proxies`)."""
        peer = request.client.host if request.client else None
        return netcheck.real_address(peer, request.headers.getlist("x-forwarded-for"), trusted)

    app = FastAPI(title="laris-server", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    # -- helpers ---------------------------------------------------------------------------
    def principal_of(request: Request) -> Optional[Principal]:
        """Who is calling; None means the key is missing, unknown, revoked or expired."""
        if service.auth is None:  # tests only: `laris-server model serve` refuses to run open
            return Principal(
                "open", "user", frozenset((CHAT, EMBED, MODELS, WORKFLOWS, HELP, ACCOUNT))
            )
        supplied = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        return service.auth.authenticate(supplied, client_address(request))

    def allow(request: Request, permission: str) -> Principal:
        principal = principal_of(request)
        if principal is None:
            raise HTTPException(401, "invalid API key")
        if not principal.can(permission):
            raise HTTPException(403, f"this key lacks the '{permission}' permission")
        return principal

    def check_protocol(request: Request) -> None:
        sent = request.headers.get(PROTOCOL_HEADER.lower())
        if sent != PROTOCOL_VERSION:
            shown = "missing" if sent is None else repr(sent)
            raise HTTPException(
                426,
                f"unsupported protocol version ({shown}); this server speaks "
                f"{PROTOCOL_HEADER}: {PROTOCOL_VERSION}. Update the laris client.",
            )

    async def read_json(request: Request) -> Tuple[Dict[str, Any], int]:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            raise HTTPException(411, "Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError:
            raise HTTPException(400, "invalid Content-Length") from None
        if length < 0:
            raise HTTPException(400, "invalid Content-Length")
        if length > max_body_bytes:
            raise HTTPException(413, "request too large")
        chunks, total = [], 0
        try:
            with anyio.fail_after(body_timeout_s):
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > max_body_bytes:
                        raise HTTPException(413, "request too large")
                    chunks.append(chunk)
        except TimeoutError:
            raise HTTPException(408, "the request body arrived too slowly") from None
        try:
            body = json.loads(b"".join(chunks) or b"{}")
        except ValueError:
            raise HTTPException(400, "invalid JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "the body must be a JSON object")
        return body, length

    async def event_stream(chunks: Iterator[Dict[str, Any]], first: Any) -> Any:
        """SSE bytes; the generator is closed even when the reader leaves, so usage is recorded."""
        pending = [first] if first is not None else []
        try:
            while True:
                if pending:
                    item: Any = pending.pop()
                else:
                    item = await run_in_threadpool(next, chunks, _END)
                if item is _END:
                    break
                yield encode_event(item)
        except Exception as exc:  # after the first byte: an error event, then the end marker
            yield encode_event({"error": {"message": str(exc), "type": type(exc).__name__}})
        finally:
            close: Optional[Callable[[], None]] = getattr(chunks, "close", None)
            if close:
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(close)
        yield encode_done()

    async def sse(chunks: Any) -> StreamingResponse:
        iterator = iter(chunks)
        try:
            first = await run_in_threadpool(next, iterator, None)  # refusals raise here: HTTP error
        except BaseException:
            close = getattr(iterator, "close", None)
            if close:
                await run_in_threadpool(close)
            raise
        return StreamingResponse(
            event_stream(iterator, first),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    # -- GET -------------------------------------------------------------------------------
    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    def reasoning(query: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Admin-only and off by default: reasoning never travels to ordinary clients."""
        if not (service.reasoning_http and service.admin):
            return None
        if query.get("id", "").isdigit():
            return {"trace": service.admin.reasoning_get(int(query["id"]))}
        limit = int(query["limit"]) if query.get("limit", "").isdigit() else 20
        return {"traces": service.admin.reasoning_list(min(limit, 200))}

    @app.get("/{path:path}")
    def get(path: str, request: Request) -> Any:
        full = "/" + path
        gateway = service.gateway
        routes: Dict[str, Tuple[str, Callable[[Principal], Any]]] = {
            "/v1/models": (MODELS, lambda p: service.models()),
            "/v1/laris/workflows": (
                WORKFLOWS,
                lambda p: {"workflows": gateway.workflows()} if gateway else None,
            ),
            "/v1/laris/help": (HELP, lambda p: {"text": gateway.help_text()} if gateway else None),
            "/v1/laris/account": (
                ACCOUNT,
                lambda p: service.meter.account(p) if service.meter else {"role": p.role},
            ),
            "/v1/admin/usage": (
                "usage.read",
                lambda p: {"usage": service.admin.usage_summary()} if service.admin else None,
            ),
            "/v1/admin/reasoning": (
                "reasoning.read",
                lambda p: reasoning(dict(request.query_params)),
            ),
        }
        if full not in routes:
            raise HTTPException(401 if principal_of(request) is None else 404, "not found")
        if full.startswith("/v1/laris/"):
            check_protocol(request)
        permission, produce = routes[full]
        payload = produce(allow(request, permission))
        if payload is None:
            raise HTTPException(404, "not found")
        return payload

    # -- POST ------------------------------------------------------------------------------
    @app.post("/{path:path}", response_model=None)
    async def post(path: str, request: Request) -> Any:
        full = "/" + path
        known = {"/v1/laris/chat", "/v1/chat/completions", "/v1/embeddings", "/v1/laris/embed"}
        if full not in known:
            raise HTTPException(401 if principal_of(request) is None else 404, "not found")
        if full.startswith("/v1/laris/"):
            check_protocol(request)
        embedding = full in ("/v1/embeddings", "/v1/laris/embed")
        permission = EMBED if embedding else CHAT
        principal = await run_in_threadpool(allow, request, permission)
        body, length = await read_json(request)
        reservation: Any = None
        try:
            if full in ("/v1/laris/chat", "/v1/chat/completions"):
                try:
                    ChatRequest(**body)
                except (ValidationError, TypeError) as exc:
                    raise HTTPException(400, f"invalid request: {_first_error(exc)}") from None
            elif embedding:
                try:
                    EmbedRequest(**body)
                except (ValidationError, TypeError) as exc:
                    raise HTTPException(400, f"invalid request: {_first_error(exc)}") from None
            if service.meter is not None:
                reservation = await run_in_threadpool(
                    service.meter.reserve, principal, service.estimate_tokens(length)
                )
            if full == "/v1/laris/chat" and service.gateway:
                handed, reservation = reservation, None  # the stream settles it, even on a drop
                return await sse(service.gateway.stream(body, principal, handed))
            if full == "/v1/laris/chat" or (service.gateway and full == "/v1/chat/completions"):
                raise HTTPException(404, "not found")
            if full == "/v1/chat/completions" and body.get("stream"):
                response = await sse(service.stream_chunks(body))
                handed, reservation = reservation, None
                await run_in_threadpool(service.bill, principal, length, 0, "chat", handed)
                return response
            if full == "/v1/chat/completions":
                reply = await run_in_threadpool(service.complete, body)
                handed, reservation = reservation, None
                await run_in_threadpool(
                    service.bill, principal, length, len(json.dumps(reply)), "chat", handed
                )
                return reply
            reply = await run_in_threadpool(service.embeddings, body)
            handed, reservation = reservation, None
            await run_in_threadpool(service.bill, principal, length, 0, "embed", handed)
            return reply
        except QuotaExceeded as exc:
            raise HTTPException(429, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:  # includes the gateway's refusals
            raise HTTPException(400, str(exc)) from exc
        finally:
            if reservation is not None:  # an error before the work was handed on: give it back
                await run_in_threadpool(reservation.release)

    return app


def _first_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        return f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
    return str(exc)


class ApiServer:
    """What `build_server` returns: a bound socket and a uvicorn server that serves it.

    The port is bound at construction (`server_port` is known, port 0 picks a free one) and the
    interface mirrors the standard-library server the tests and the CLI already use.
    """

    def __init__(self, app: FastAPI, host: str, port: int, timeout_keep_alive: int = 5) -> None:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self._sock = socket.socket(family, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(128)
        self.server_port: int = self._sock.getsockname()[1]
        self._app = app
        self._tls: Optional[Tuple[str, str]] = None
        self._timeout_keep_alive = timeout_keep_alive
        self._server: Any = None
        self._stopped = threading.Event()
        self._stop_requested = False

    def enable_tls(self, cert_file: str, identity_file: str) -> None:
        self._tls = (cert_file, identity_file)

    def serve_forever(self) -> None:
        import uvicorn

        kwargs: Dict[str, Any] = {}
        if self._tls:
            kwargs.update(ssl_certfile=self._tls[0], ssl_keyfile=self._tls[1])
        config = uvicorn.Config(
            self._app,
            log_level="warning",
            timeout_keep_alive=self._timeout_keep_alive,
            access_log=False,
            proxy_headers=False,  # we read X-Forwarded-For ourselves, only from trusted proxies
            **kwargs,
        )
        self._server = uvicorn.Server(config)
        if self._stop_requested:
            self._server.should_exit = True
        try:
            self._server.run(sockets=[self._sock])
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        self._stop_requested = True
        if self._server is not None:
            self._server.should_exit = True
            self._stopped.wait(timeout=10)

    def server_close(self) -> None:
        self._sock.close()
