"""Reference model server (`laris model serve`).

Speaks the OpenAI-compatible contract the chat clients call: `GET /v1/models`, `GET /health`,
`POST /v1/chat/completions` (JSON or `stream: true` server-sent events, with `tools` and
`tool_calls`) and `POST /v1/embeddings`. The generation backend is any `ChatProvider`; the default
is the scripted offline planner, a placeholder until the core model is trained. A trained model
plugs in as another `ChatProvider` (`--backend package.module:ClassName`) with no client changes.
"""

import hmac
import importlib
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from agent.provider import AssistantTurn, ChatProvider, OfflinePlanner, ProviderError

MAX_BODY_BYTES = 32 * 1024 * 1024
PLACEHOLDER_NAME = "laris-placeholder"


def load_backend(spec: Optional[str]) -> ChatProvider:
    """`package.module:ClassName` (zero-argument constructor) or the offline placeholder."""
    if not spec:
        return OfflinePlanner()
    module_name, _, class_name = spec.partition(":")
    if not class_name:
        raise ValueError("--backend must look like package.module:ClassName")
    backend = getattr(importlib.import_module(module_name), class_name)()
    if not isinstance(backend, ChatProvider):
        raise TypeError(f"{spec} is not a ChatProvider")
    return backend


def _message_payload(turn: AssistantTurn) -> Dict[str, Any]:
    message: Dict[str, Any] = {"role": "assistant", "content": turn.content}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in turn.tool_calls
        ]
    return message


class ModelService:
    def __init__(
        self,
        backend: ChatProvider,
        model_name: str = PLACEHOLDER_NAME,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.embedder = embedder
        self.api_key = api_key

    def models(self) -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model", "owned_by": "laris"}],
        }

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        turn = self.backend.chat(list(body.get("messages") or []), list(body.get("tools") or []))
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": _message_payload(turn),
                    "finish_reason": "tool_calls" if turn.tool_calls else "stop",
                }
            ],
        }

    def stream_chunks(self, body: Dict[str, Any]) -> Any:
        """Yield OpenAI `chat.completion.chunk` dicts for the request."""
        ident = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        base = {"id": ident, "object": "chat.completion.chunk", "model": self.model_name}
        for event in self.backend.stream(
            list(body.get("messages") or []), list(body.get("tools") or [])
        ):
            if event["type"] == "text":
                yield {**base, "choices": [{"index": 0, "delta": {"content": event["delta"]}}]}
            else:
                turn: AssistantTurn = event["turn"]
                if turn.tool_calls:
                    calls = [
                        {
                            "index": i,
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for i, c in enumerate(turn.tool_calls)
                    ]
                    yield {**base, "choices": [{"index": 0, "delta": {"tool_calls": calls}}]}
                reason = "tool_calls" if turn.tool_calls else "stop"
                yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}

    def embeddings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.embedder is None:
            raise ValueError("no embedding model loaded (start with --checkpoint)")
        raw = body.get("input", [])
        texts = [raw] if isinstance(raw, str) else [str(t) for t in raw]
        vectors = self.embedder(texts)
        return {
            "object": "list",
            "model": self.model_name,
            "data": [
                {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
            ],
        }


def make_handler(service: ModelService) -> type:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: Any) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            if not service.api_key:
                return True
            supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(supplied, service.api_key)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(200, {"status": "ok", "model": service.model_name})
            elif self.path == "/v1/models" and self._authorized():
                self._json(200, service.models())
            else:
                self._json(401 if not self._authorized() else 404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._json(401, {"error": "invalid API key"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._json(413, {"error": "request too large"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return
            try:
                if self.path == "/v1/chat/completions" and body.get("stream"):
                    self._sse(service.stream_chunks(body))
                elif self.path == "/v1/chat/completions":
                    self._json(200, service.complete(body))
                elif self.path == "/v1/embeddings":
                    self._json(200, service.embeddings(body))
                else:
                    self._json(404, {"error": "not found"})
            except ProviderError as exc:
                self._json(502, {"error": str(exc)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})

        def _sse(self, chunks: Any) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return Handler


def build_server(service: ModelService, host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service))


def api_key_from_env(name: Optional[str]) -> Optional[str]:
    return os.environ.get(name) if name else None
