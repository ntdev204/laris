"""The served chat backend against a scripted OpenAI-compatible server (T282; no model, no GPU)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from laris.model.inference.served_llm import ServedChat, server_messages
from laris.model.service import ModelService, build_queue
from laris.protocol import ProviderError
from laris.shared.config.runtime_schemas import ModelServiceConfig

MODEL = "Qwen/Qwen3.5-4B"


class Script:
    """What the scripted server answers, and what it was sent."""

    def __init__(self) -> None:
        self.served = MODEL
        self.max_model_len = 4096
        self.reply = "plain answer"
        self.pieces: List[str] = []
        self.status = 200
        self.requests: List[Dict[str, Any]] = []


def _tokens(body: Dict[str, Any]) -> List[int]:
    # one token per 4 characters of the rendered conversation, tools included
    text = json.dumps(body.get("messages")) + json.dumps(body.get("tools") or [])
    return list(range(max(1, len(text) // 4)))


@pytest.fixture()
def server():
    script = Script()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            script.requests.append({"path": self.path})
            self._json({"data": [{"id": script.served, "max_model_len": script.max_model_len}]})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            script.requests.append({"path": self.path, "body": body})
            if script.status != 200:
                self._json({"error": {"message": "scripted failure"}}, script.status)
            elif self.path == "/tokenize":
                tokens = _tokens(body)
                thinking = body["chat_template_kwargs"]["enable_thinking"]
                tail = ["<think>", "Ċ"] if thinking else ["<think>", "ĊĊ", "</think>", "ĊĊ"]
                strs = ["x"] * (len(tokens) - len(tail)) + tail
                self._json({"count": len(tokens), "tokens": tokens, "token_strs": strs})
            elif not body.get("stream"):
                self._json({"choices": [{"text": script.reply, "finish_reason": "stop"}]})
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in script.pieces:
                    event = {"choices": [{"text": piece, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.write(b'data: {"choices": [], "usage": {"completion_tokens": 3}}\n\n')
                self.wfile.write(b"data: [DONE]\n\n")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    script.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield script
    httpd.shutdown()


def _cfg(url: str, **extra: Any) -> ModelServiceConfig:
    values = {"chat_server_url": url, "chat_model_id": MODEL, "chat_max_new_tokens": 256}
    return ModelServiceConfig(**{**values, **extra})


def _posts(script: Script, path: str) -> List[Dict[str, Any]]:
    return [r["body"] for r in script.requests if r["path"] == path]


def test_configuration_is_checked():
    with pytest.raises(ProviderError, match="chat_server_url"):
        ServedChat(ModelServiceConfig(chat_model_id=MODEL))
    with pytest.raises(ProviderError, match="chat_model_id"):
        ServedChat(ModelServiceConfig(chat_server_url="http://x"))
    with pytest.raises(ProviderError, match="BF16"):
        ServedChat(_cfg("http://x", chat_quantization="8bit"))


def test_reply_is_split_into_reasoning_and_text(server):
    server.reply = "weighing the options\n</think>\n\nThe answer is 4."
    chat = ServedChat(_cfg(server.url, chat_thinking=True, chat_temperature=0.0))
    turn = chat.chat([{"role": "user", "content": "2+2?"}], [])
    assert turn.reasoning == "weighing the options"
    assert turn.content.strip() == "The answer is 4." and turn.tool_calls == []
    tokenize = _posts(server, "/tokenize")[-1]
    assert tokenize["chat_template_kwargs"] == {"enable_thinking": True}
    assert tokenize["add_generation_prompt"] is True and "tools" not in tokenize
    completion = _posts(server, "/v1/completions")[-1]
    assert completion["model"] == MODEL and completion["max_tokens"] == 256
    assert completion["temperature"] == 0.0 and completion["prompt"] == _tokens(tokenize)


def test_reasoning_cut_off_stays_out_of_the_text(server):
    server.reply = "still weighing the opt"  # the reply ended inside the reasoning
    turn = ServedChat(_cfg(server.url, chat_thinking=True)).chat(
        [{"role": "user", "content": "q"}], []
    )
    assert turn.reasoning == "still weighing the opt" and turn.content is None
    server.reply = "still weighing"  # thinking off: the template closed the reasoning itself
    turn = ServedChat(_cfg(server.url)).chat([{"role": "user", "content": "q"}], [])
    assert turn.content == "still weighing" and turn.reasoning is None


def test_tool_calls_are_parsed_and_tools_reach_the_template(server):
    server.reply = (
        "<tool_call>\n<function=search>\n<parameter=query>\nbm25\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
    turn = ServedChat(_cfg(server.url)).chat([{"role": "user", "content": "find"}], tools)
    assert turn.content is None
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [("search", {"query": "bm25"})]
    assert _posts(server, "/tokenize")[-1]["tools"] == tools


def test_messages_are_sent_in_wire_form():
    out = server_messages(
        [
            {"role": "user", "content": "q", "harness": "x", "superseded": False},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "1", "function": {"name": "f", "arguments": {"a": 1}}}],
            },
            {"role": "tool", "tool_call_id": "1", "content": "r"},
            {"role": "assistant", "content": "done", "tool_calls": []},
        ]
    )
    assert out[0] == {"role": "user", "content": "q"}
    assert out[1]["content"] == ""
    assert out[1]["tool_calls"] == [
        {"type": "function", "id": "1", "function": {"name": "f", "arguments": '{"a": 1}'}}
    ]
    assert out[2] == {"role": "tool", "tool_call_id": "1", "content": "r"}
    assert out[3] == {"role": "assistant", "content": "done"}


def test_prompt_is_fitted_to_the_input_budget(server):
    server.max_model_len = 1000  # the server's context caps the configured budget
    chat = ServedChat(_cfg(server.url, chat_max_input_tokens=4096, chat_max_new_tokens=500))
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "read this"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "page " * 2000},
        {"role": "user", "content": "and summarise"},
    ]
    prompt = chat.prompt(messages, [])
    assert chat.input_budget() == 500
    assert len(prompt) <= 500
    sent = _posts(server, "/tokenize")[-1]["messages"]
    assert sent[0]["content"] == "rules" and sent[-1]["content"] == "and summarise"
    assert "shortened" in sent[3]["content"]


def test_stream_yields_reasoning_text_and_turn(server):
    server.pieces = [
        "think",
        "ing</th",
        "ink>\n\nHel",
        "lo",
        "<tool_",
        'call>{"name": "f"}</tool_call>',
    ]
    chat = ServedChat(_cfg(server.url, chat_thinking=True))  # the template opens the reasoning
    events = list(chat.stream([{"role": "user", "content": "hi"}], []))
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "turn" and "reasoning" in kinds
    reasoning = "".join(e["delta"] for e in events if e["type"] == "reasoning")
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert reasoning == "thinking" and text.strip() == "Hello"
    assert "<" not in text  # no partial tag or tool-call block reaches the chat body
    turn = events[-1]["turn"]
    assert [c.name for c in turn.tool_calls] == ["f"]
    body = _posts(server, "/v1/completions")[-1]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


def test_server_failures_become_provider_errors(server):
    chat = ServedChat(_cfg(server.url))
    server.served = "other/model"
    with pytest.raises(ProviderError, match="serves other/model"):
        chat.chat([{"role": "user", "content": "hi"}], [])
    server.served = MODEL
    server.status = 500
    with pytest.raises(ProviderError, match="HTTP 500: scripted failure"):
        chat.chat([{"role": "user", "content": "hi"}], [])
    down = ServedChat(_cfg("http://127.0.0.1:9", chat_server_timeout_s=2.0))
    with pytest.raises(ProviderError, match="unreachable"):
        down.chat([{"role": "user", "content": "hi"}], [])


def test_queue_counts_the_server_reservation(server):
    gib = 1024**3
    cfg = _cfg(
        server.url,
        chat_server_gpu_share=0.85,
        gpu_memory_bytes=16 * gib,
        vram_budget_bytes=int(14.5 * gib),
        gpu_workers=4,
    )
    chat = ServedChat(cfg)
    assert chat.vram_bytes == int(0.85 * 16 * gib)
    queue = build_queue(chat, cfg)
    assert queue.models["chat"].size_bytes == chat.vram_bytes
    service = ModelService(chat, "laris-core", queue=queue)
    server.reply = "ok"
    reply = service.complete({"messages": [{"role": "user", "content": "hi"}]})
    assert reply["choices"][0]["message"]["content"] == "ok"
    chunks = list(service.stream({"messages": [{"role": "user", "content": "hi"}]}))
    assert chunks
    too_big = _cfg(
        server.url,
        chat_server_gpu_share=0.95,
        gpu_memory_bytes=16 * gib,
        vram_budget_bytes=int(14.5 * gib),
    )
    with pytest.raises(ValueError, match="larger than the VRAM budget"):
        build_queue(ServedChat(too_big), too_big)
    small = SimpleNamespace(
        chat_vram_bytes=gib,
        vram_budget_bytes=2 * gib,
        vram_margin_bytes=0,
        gpu_workers=1,
        queue_max_waiting=4,
        queue_wait_timeout_s=5.0,
    )
    assert build_queue(SimpleNamespace(), small).models["chat"].size_bytes == gib
