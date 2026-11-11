"""HTTP server for the chat web UI and JSON API (standard library only, local by default)."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from application.chat_app import ChatApp
from application.service import SearchService, ServiceError
from application.web_ui import PAGE
from application.workspace import IngestError, decode_upload
from config.runtime_schemas import AppConfig
from harness.prefs import PrefsError

_CONVERSATION = re.compile(r"^/api/conversations/([0-9a-f]{12})(/messages)?$")
_COMPACT = re.compile(r"^/api/conversations/([0-9a-f]{12})/compact$")


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
                if not chat.runtime.config.security.expose_internal_info:
                    info.pop("checkpoint", None)  # internal paths and digests stay private
                    info.pop("model_sha256", None)
                info["model_api"] = chat.model_health()
            return 200, info
        if method == "POST" and path == "/api/ingest":
            chunks = decode_upload(
                str(body.get("name") or "document.txt"),
                body.get("text"),
                body.get("data_base64"),
                chat.runtime.config.app if chat else None,
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
    except PrefsError as exc:
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
            return 200, chat.settings()
        if method == "POST":
            return 200, chat.update_settings(body)
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
            conversation = chat.conversations.get(match.group(1))
            return 200, {**conversation, "usage": chat.usage(match.group(1))}
        if method == "DELETE":
            chat.conversations.delete(match.group(1))
            return 200, {"deleted": match.group(1)}
        if method == "PATCH":
            conversation = chat.conversations.get(match.group(1))
            conversation["title"] = str(body.get("title") or conversation["title"])[:120]
            chat.conversations.save(conversation)
            return 200, conversation
    if path == "/api/skills" and method == "GET":
        library = chat.skills_for(chat.runtime)
        return 200, {
            "skills": [
                {
                    "name": k.name,
                    "description": k.summary(400),
                    "scope": k.scope,
                    "references": len(k.references),
                }
                for k in (library.skills[n] for n in library.names())
            ],
            "problems": library.problems,
        }
    if path == "/api/instructions" and method == "GET":
        return 200, chat.instruction_summary()
    compact = _COMPACT.match(path)
    if compact and method == "POST":
        events = list(chat.compact(compact.group(1), str(body.get("instructions", ""))))
        return 200, {"events": events}
    if path == "/api/upload" and method == "POST":
        return 200, chat.upload(
            str(body.get("name") or "upload"),
            str(body.get("data_base64") or ""),
            bool(body.get("ingest", True)),
        )
    return None


def make_handler(
    service: SearchService, chat: Optional[ChatApp] = None, max_body_bytes: Optional[int] = None
) -> type:
    max_body = max_body_bytes or AppConfig().max_body_bytes

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
            if length > max_body:
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
    limit = chat.runtime.config.app.max_body_bytes if chat else None
    return ThreadingHTTPServer((host, port), make_handler(service, chat, limit))
