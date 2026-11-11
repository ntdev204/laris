"""HTTP server for the chat web UI and JSON API (standard library only, local by default)."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from laris.application.chat_app import ChatApp
from laris.application.service import SearchService, ServiceError
from laris.application.web_ui import PAGE
from laris.application.workspace import IngestError, decode_upload

MAX_BODY_BYTES = 32 * 1024 * 1024
_CONVERSATION = re.compile(r"^/api/conversations/([0-9a-f]{12})(/messages)?$")


def handle_api(
    service: SearchService,
    method: str,
    path: str,
    body: Dict[str, Any],
    chat: Optional[ChatApp] = None,
) -> Tuple[int, Any]:
    """Pure routing for every non-streaming endpoint, testable without sockets."""
    try:
        if method == "GET" and path == "/api/status":
            info = service.status()
            if chat:
                info["model_api"] = chat.model_health()
            return 200, info
        if method == "POST" and path == "/api/ingest":
            chunks = decode_upload(
                str(body.get("name") or "document.txt"), body.get("text"), body.get("data_base64")
            )
            with service._lock:
                counts = service.workspace.add(chunks)
            return 200, counts
        if method == "POST" and path == "/api/search":
            return 200, service.search(
                body.get("query", ""), body.get("mode", "bm25"), int(body.get("top_k", 5))
            )
        if method == "POST" and path == "/api/answer":
            return 200, service.answer(body.get("query", ""), body.get("mode", "bm25"))
        if method == "POST" and path == "/api/index":
            return 200, service.build_dense_index()
        if chat is not None:
            routed = _chat_routes(chat, method, path, body)
            if routed is not None:
                return routed
    except (ServiceError, IngestError) as exc:
        return 400, {"error": str(exc)}
    except KeyError:
        return 404, {"error": "not found"}
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return 500, {"error": str(exc)}
    return 404, {"error": "not found"}


def _chat_routes(
    chat: ChatApp, method: str, path: str, body: Dict[str, Any]
) -> Optional[Tuple[int, Any]]:
    if path == "/api/settings":
        if method == "GET":
            return 200, chat.settings.load()
        if method == "POST":
            return 200, chat.settings.update(body)
    if path == "/api/model-health" and method == "GET":
        return 200, chat.model_health()
    if path == "/api/conversations":
        if method == "GET":
            return 200, chat.conversations.list()
        if method == "POST":
            return 200, chat.conversations.create()
    match = _CONVERSATION.match(path)
    if match and not match.group(2):
        if method == "GET":
            return 200, chat.conversations.get(match.group(1))
        if method == "DELETE":
            chat.conversations.delete(match.group(1))
            return 200, {"deleted": match.group(1)}
        if method == "PATCH":
            conversation = chat.conversations.get(match.group(1))
            conversation["title"] = str(body.get("title") or conversation["title"])[:120]
            chat.conversations.save(conversation)
            return 200, conversation
    if path == "/api/upload" and method == "POST":
        return 200, chat.upload(
            str(body.get("name") or "upload"),
            str(body.get("data_base64") or ""),
            bool(body.get("ingest", True)),
        )
    return None


def make_handler(service: SearchService, chat: Optional[ChatApp] = None) -> type:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: Any, content_type: str = "application/json") -> None:
            data = (
                payload.encode("utf-8")
                if isinstance(payload, str)
                else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(code)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> Optional[Dict[str, Any]]:
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._send(415, {"error": "Content-Type must be application/json"})
                return None  # blocks cross-site form posts to the local server
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._send(413, {"error": "request too large"})
                return None
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid JSON"})
                return None
            if not isinstance(data, dict):
                self._send(400, {"error": "JSON object expected"})
                return None
            return data

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE, "text/html")
            else:
                self._send(*handle_api(service, "GET", self.path, {}, chat))

        def do_DELETE(self) -> None:  # noqa: N802
            self._send(*handle_api(service, "DELETE", self.path, {}, chat))

        def do_PATCH(self) -> None:  # noqa: N802
            body = self._body()
            if body is not None:
                self._send(*handle_api(service, "PATCH", self.path, body, chat))

        def do_POST(self) -> None:  # noqa: N802
            body = self._body()
            if body is None:
                return
            match = _CONVERSATION.match(self.path)
            if chat is not None and match and match.group(2):
                self._stream_message(chat, match.group(1), str(body.get("text", "")).strip())
                return
            self._send(*handle_api(service, "POST", self.path, body, chat))

        def _stream_message(self, chat: ChatApp, conversation_id: str, text: str) -> None:
            if not text:
                self._send(400, {"error": "message is empty"})
                return
            try:
                chat.conversations.get(conversation_id)
            except KeyError:
                self._send(404, {"error": "conversation not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            events = chat.send(conversation_id, text)
            try:
                for event in events:
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                events.close()  # client stopped; the conversation is still saved

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return Handler


def serve(
    service: SearchService, host: str, port: int, chat: Optional[ChatApp] = None
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service, chat))
