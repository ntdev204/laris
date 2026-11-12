"""Reference model server (`laris model serve`).

Speaks the OpenAI-compatible contract the chat clients call: `GET /v1/models`, `GET /health`,
`POST /v1/chat/completions` (JSON or `stream: true` server-sent events, with `tools` and
`tool_calls`) and `POST /v1/embeddings`. The generation backend is any `ChatProvider`; the default
is the scripted offline planner, a placeholder until the core model is trained. A trained model
plugs in as another `ChatProvider` (`--backend package.module:ClassName`) with no client changes.
"""

import itertools
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from laris.protocol import ChatProvider, ProviderError, encode_done, encode_event
from laris.protocol.openai import completion_response, embeddings_response, stream_chunks, texts_of
from laris.server.serving.auth import KeyRing, StaticAuthenticator
from laris.server.serving.ports import (
    ACCOUNT,
    CHAT,
    EMBED,
    HELP,
    MODELS,
    WORKFLOWS,
    Authenticator,
    Principal,
    QuotaExceeded,
    UsageMeter,
)
from laris.shared.backend import load_backend  # noqa: F401  (re-exported for the CLI)


class ModelService:
    def __init__(
        self,
        backend: ChatProvider,
        model_name: str,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        keys: Optional[KeyRing] = None,
        gateway: Any = None,
        auth: Optional[Authenticator] = None,
        meter: Optional[UsageMeter] = None,
        admin: Any = None,
        chars_per_token: float = 4.0,
        reasoning_http: bool = False,
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.embedder = embedder
        # Policy gateway (duck-typed: stream(body), workflows(), help_text()). With a gateway the
        # bare model endpoint is closed: every request goes through the system policy.
        self.gateway = gateway
        self.keys = keys  # None = no authentication (tests only; `laris model serve` refuses it)
        # Authenticator: database keys with roles and limits; a plain KeyRing becomes role `user`.
        self.auth = auth or (
            StaticAuthenticator(keys, (CHAT, EMBED, MODELS, WORKFLOWS, HELP, ACCOUNT))
            if keys is not None
            else None
        )
        self.meter = meter
        self.admin = admin  # duck-typed: usage_summary(), reasoning_list(limit), reasoning_get(id)
        self.chars_per_token = chars_per_token
        self.reasoning_http = reasoning_http

    def estimate_tokens(self, text_chars: int) -> int:
        return int(text_chars / self.chars_per_token) + 1

    def bill(self, principal: Optional[Principal], prompt_chars: int, completion_chars: int,
             kind: str) -> None:  # fmt: skip
        if self.meter is not None and principal is not None:
            self.meter.record(
                principal,
                {
                    "kind": kind,
                    "prompt_tokens": self.estimate_tokens(prompt_chars),
                    "completion_tokens": self.estimate_tokens(completion_chars),
                },
            )

    def models(self) -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model", "owned_by": "laris"}],
        }

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        turn = self.backend.chat(list(body.get("messages") or []), list(body.get("tools") or []))
        return completion_response(turn, self.model_name)

    def stream_chunks(self, body: Dict[str, Any]) -> Any:
        """Yield OpenAI `chat.completion.chunk` dicts for the request."""
        events = self.backend.stream(
            list(body.get("messages") or []), list(body.get("tools") or [])
        )
        return stream_chunks(events, self.model_name)

    def embeddings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.embedder is None:
            raise ValueError("no embedding model loaded (start with --checkpoint)")
        vectors = self.embedder(texts_of(body.get("input", [])))
        return embeddings_response(vectors, self.model_name)


def make_handler(service: ModelService, max_body_bytes: int) -> type:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _principal(self) -> Optional[Principal]:
            """Who is calling; None means the key is missing, unknown, revoked or expired."""
            if (
                service.auth is None
            ):  # tests only: `laris model serve` refuses to run unauthenticated
                return Principal(
                    "open", "user", frozenset((CHAT, EMBED, MODELS, WORKFLOWS, HELP, ACCOUNT))
                )
            supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return service.auth.authenticate(supplied, self.client_address[0])

        def _allow(self, permission: str) -> Optional[Principal]:
            """The caller if the key is valid and allowed; otherwise this answers 401 or 403."""
            principal = self._principal()
            if principal is None:
                self._json(401, {"error": "invalid API key"})
            elif not principal.can(permission):
                self._json(403, {"error": f"this key lacks the '{permission}' permission"})
            else:
                return principal
            return None

        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            if path == "/health":
                self._json(200, {"status": "ok"})
                return
            routes = {
                "/v1/models": (MODELS, lambda p: service.models()),
                "/v1/laris/workflows": (
                    WORKFLOWS,
                    lambda p: (
                        {"workflows": service.gateway.workflows()} if service.gateway else None
                    ),
                ),
                "/v1/laris/help": (
                    HELP,
                    lambda p: {"text": service.gateway.help_text()} if service.gateway else None,
                ),
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
                    lambda p: self._reasoning(query),
                ),
            }
            if path not in routes:
                principal = self._principal()
                self._json(401 if principal is None else 404, {"error": "not found"})
                return
            permission, produce = routes[path]
            principal = self._allow(permission)
            if principal is None:
                return
            payload = produce(principal)
            self._json(200, payload) if payload is not None else self._json(
                404, {"error": "not found"}
            )

        def _reasoning(self, query: str) -> Optional[Dict[str, Any]]:
            """Admin-only and off by default: reasoning never travels to ordinary clients."""
            if not (service.reasoning_http and service.admin):
                return None
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if "id" in params and params["id"].isdigit():
                return {"trace": service.admin.reasoning_get(int(params["id"]))}
            limit = int(params["limit"]) if params.get("limit", "").isdigit() else 20
            return {"traces": service.admin.reasoning_list(min(limit, 200))}

        def do_POST(self) -> None:  # noqa: N802
            gateway_path = self.path == "/v1/laris/chat" and service.gateway
            permission = EMBED if self.path == "/v1/embeddings" else CHAT
            principal = self._allow(permission)
            if principal is None:
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > max_body_bytes:
                self._json(413, {"error": "request too large"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return
            try:
                if service.meter is not None:
                    service.meter.check(principal, service.estimate_tokens(length))
                if gateway_path:
                    self._sse(service.gateway.stream(body, principal))
                elif service.gateway and self.path == "/v1/chat/completions":
                    self._json(404, {"error": "not found"})
                elif self.path == "/v1/chat/completions" and body.get("stream"):
                    self._sse(service.stream_chunks(body))
                    service.bill(principal, length, 0, "chat")
                elif self.path == "/v1/chat/completions":
                    reply = service.complete(body)
                    self._json(200, reply)
                    service.bill(principal, length, len(json.dumps(reply)), "chat")
                elif self.path == "/v1/embeddings":
                    reply = service.embeddings(body)
                    self._json(200, reply)
                    service.bill(principal, length, 0, "embed")
                else:
                    self._json(404, {"error": "not found"})
            except QuotaExceeded as exc:
                self._json(429, {"error": str(exc)})
            except ProviderError as exc:
                self._json(502, {"error": str(exc)})
            except ValueError as exc:  # includes the gateway's refusals
                self._json(400, {"error": str(exc)})

        def _sse(self, chunks: Any) -> None:
            chunks = iter(chunks)
            try:
                first = next(chunks, None)  # a refusal raised here still becomes an HTTP error
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                for chunk in () if first is None else itertools.chain((first,), chunks):
                    self.wfile.write(encode_event(chunk))
                    self.wfile.flush()
                self.wfile.write(encode_done())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                close = getattr(chunks, "close", None)
                if close:
                    close()  # lets the gateway record usage and the trace even if the client left

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return Handler


def build_server(
    service: ModelService, host: str, port: int, max_body_bytes: int
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service, max_body_bytes))


def enable_tls(server: ThreadingHTTPServer, cert_file: str, identity_file: str) -> None:
    """Serve HTTPS: TLS 1.2 or newer, certificate and private key loaded from PEM files."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, identity_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
