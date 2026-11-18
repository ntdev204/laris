"""Record the P1 and P2 fixtures of `laris-protocol` from the generation-1 server (T123).

Usage (never trains anything; scripted model, no network):

    git worktree add <dir> laris-v1 --detach
    .venv/bin/python scripts/record_protocol_fixtures.py <dir> crates/laris-protocol/tests/fixtures

It starts the real generation-1 FastAPI server (`laris.server.api`, branch `laris-v1`) with a scripted
model, sends requests over HTTP and stores the exact bytes it answers. Nothing is edited by hand, so a
fixture is evidence of what generation 1 sends. Re-running overwrites the files; the Rust tests then
show whether the Rust types still accept them.
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / "src"))

from laris.protocol import AssistantTurn, ChatProvider, ProviderError, ToolCall  # noqa: E402
from laris.server.api import ApiServer, create_app  # noqa: E402
from laris.server.gateway import PolicyGateway  # noqa: E402
from laris.server.serving.auth import KeyRing  # noqa: E402
from laris.server.serving.service import ModelService  # noqa: E402
from laris.shared.harness.runtime import HarnessRuntime  # noqa: E402

KEY = "fixture-key-0001"
HEADERS = {"Authorization": f"Bearer {KEY}", "X-Laris-Protocol": "1", "Content-Type": "application/json"}


class Scripted(ChatProvider):
    """Answers by the last user message: text, a tool call, a reasoning model, or a failure."""

    name = "scripted"

    def _last(self, messages):
        users = [m for m in messages if m.get("role") == "user"]
        return str(users[-1].get("content", "")) if users else ""

    def chat(self, messages, tools):
        text = self._last(messages)
        if "read the file" in text:
            return AssistantTurn(None, [ToolCall("call_0001", "read_file", {"path": "notes/a.md"})])
        return AssistantTurn("Perovskite is stable under encapsulation [nguồn #1].")

    def stream(self, messages, tools):
        text = self._last(messages)
        if "fail early" in text:
            yield {"type": "text", "delta": "Perovskite "}
            raise ProviderError("model died")
        if "fail late" in text:  # more than the output guard holds back, so bytes are sent first
            for _ in range(60):
                yield {"type": "text", "delta": "Perovskite films degrade under moisture and heat. "}
            raise ProviderError("model died")
        if "think" in text:
            yield {"type": "reasoning", "delta": "The user asks about stability. "}
        if "read the file" in text:
            yield from super().stream(messages, tools)
            return
        yield {"type": "text", "delta": "Perovskite is "}
        yield {"type": "text", "delta": "stable under encapsulation."}
        yield {"type": "turn", "turn": AssistantTurn("Perovskite is stable under encapsulation.")}


def embedder(texts):
    return [[round(0.125 * (i + 1) * (j + 1), 6) for j in range(4)] for i, _ in enumerate(texts)]


def call(port, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers or HEADERS
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def serve(service):
    server = ApiServer(create_app(service, 1_000_000), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def save(group, name, request, status, raw):
    folder = out / group
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n")
    suffix = "sse" if raw.startswith(b"data:") else "json"
    if suffix == "json":
        raw = (json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n").encode()
    (folder / f"{name}.response.{suffix}").write_bytes(raw)
    (folder / f"{name}.status").write_text(f"{status}\n")


def volatile(raw: bytes) -> bytes:
    """Ids and times differ per run; pin them so a re-record only changes real behaviour."""
    import re

    text = raw.decode()
    seen = {}

    def pin(match):
        seen.setdefault(match.group(0), f"chatcmpl-fixture{len(seen):02d}")
        return seen[match.group(0)]

    text = re.sub(r"chatcmpl-[0-9a-f]{12}", pin, text)
    text = re.sub(r'"created": ?\d+', '"created": 1700000000', text)
    return text.encode()


def main():
    runtime = HarnessRuntime.load(root)
    model = Scripted()
    gateway = PolicyGateway(runtime, model, "laris-test")
    p1 = serve(ModelService(model, "laris-test", embedder, KeyRing([KEY]), gateway))
    p2 = serve(ModelService(model, "laris-test", embedder, KeyRing([KEY])))
    tools = [{"type": "function", "function": {"name": "read_file", "description": "Read a file",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]

    def chat(name, text, extra=None):
        body = {"messages": [{"role": "user", "content": text}], "tools": tools,
                "laris": {"kind": "turn", "session_id": "abc123", "task": text, **(extra or {})}}
        status, raw = call(p1.server_port, "POST", "/v1/laris/chat", body)
        save("p1", name, body, status, volatile(raw))

    chat("chat_text", "Is perovskite stable?")
    chat("chat_tool_call", "please read the file notes/a.md")
    chat("chat_refused_before_stream", "fail early")
    chat("chat_midstream_error", "fail late")
    chat("chat_brain", "citation analysis: who cites whom in my corpus?")
    chat("chat_layers", "Is perovskite stable?", {
        "layers": {"instructions": [{"label": "project", "text": "Answer in Vietnamese."}],
                   "skills_index": "- review: review a paper", "memory": "The user studies solar cells."}})
    chat("chat_workflow", "Review this paper", {"workflow": {"name": "citation-analysis", "request": "Analyse my corpus"}})
    body = {"messages": [{"role": "user", "content": "Summarise the conversation."}],
            "laris": {"kind": "summarize", "focus": "decisions"}}
    status, raw = call(p1.server_port, "POST", "/v1/laris/chat", body)
    save("p1", "chat_summarize", body, status, volatile(raw))
    body = {"stream": True}
    status, raw = call(p1.server_port, "POST", "/v1/laris/chat", body)
    save("p1", "error_invalid_request", body, status, raw)
    status, raw = call(p1.server_port, "POST", "/v1/laris/chat", {"messages": []}, {**HEADERS, "X-Laris-Protocol": "9"})
    save("p1", "error_protocol_mismatch", {"messages": []}, status, raw)
    status, raw = call(p1.server_port, "GET", "/v1/laris/workflows")
    save("p1", "workflows", None, status, raw)
    status, raw = call(p1.server_port, "GET", "/v1/laris/help")
    save("p1", "help", None, status, raw)
    status, raw = call(p1.server_port, "GET", "/v1/laris/account")
    save("p1", "account", None, status, raw)
    status, raw = call(p1.server_port, "GET", "/v1/models")
    save("p1", "models", None, status, raw)
    status, raw = call(p1.server_port, "GET", "/v1/laris/account", None, {"Authorization": "Bearer wrong-key-0000", "X-Laris-Protocol": "1"})
    save("p1", "error_unauthorized", None, status, raw)
    body = {"input": ["alpha", "beta"], "model": "laris-test"}
    status, raw = call(p1.server_port, "POST", "/v1/laris/embed", body)
    save("p1", "embed", body, status, raw)

    def completions(name, text, stream):
        body = {"model": "laris-test", "messages": [{"role": "user", "content": text}], "tools": tools,
                "temperature": 0.0, "stream": stream}
        status, raw = call(p2.server_port, "POST", "/v1/chat/completions", body)
        save("p2", name, body, status, volatile(raw))

    completions("completion_text", "Is perovskite stable?", False)
    completions("completion_tool_call", "please read the file notes/a.md", False)
    completions("stream_text", "Is perovskite stable?", True)
    completions("stream_reasoning", "think about perovskite", True)
    completions("stream_tool_call", "please read the file notes/a.md", True)
    completions("stream_error", "fail early", True)
    body = {"input": ["alpha", "beta"], "model": "laris-test"}
    status, raw = call(p2.server_port, "POST", "/v1/embeddings", body)
    save("p2", "embeddings", body, status, raw)
    status, raw = call(p2.server_port, "GET", "/v1/models")
    save("p2", "models", None, status, raw)
    p1.shutdown()
    p2.shutdown()


main()
