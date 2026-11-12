"""HTTP clients of the P2 protocol (OpenAI-compatible chat completions and embeddings).

`HttpChatProvider` is a `ChatProvider` over HTTP: the server uses it to reach the model service, and
the client's policy-server provider builds on it. `HttpEmbedder` calls `/embeddings` the same way.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, List, Optional

from laris.protocol import (
    AssistantTurn,
    ChatProvider,
    Message,
    ProviderError,
    ToolCall,
    decode_events,
    http_failure,
    wire_messages,
)

_http_failure = http_failure


class HttpChatProvider(ChatProvider):
    """Client for an OpenAI-compatible chat-completions endpoint (local or remote)."""

    name = "http"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: Optional[str] = None,
        timeout_s: float = 120.0,
        temperature: float = 0.0,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = os.environ.get(api_key_env) if api_key_env else None
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.last_usage: Dict[str, Any] = {}  # tokens the server billed for the last reply

    def _body(self, messages: List[Message], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": wire_messages(messages),
            "tools": tools,
            "temperature": self.temperature,
        }

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        body = self._body(messages, tools)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.url, json.dumps(body).encode("utf-8"), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            message = payload["choices"][0]["message"]
            calls: List[ToolCall] = []
            for raw in message.get("tool_calls") or []:
                fn = raw["function"]
                args = fn.get("arguments") or "{}"
                calls.append(
                    ToolCall(
                        str(raw.get("id") or f"call_{len(calls)}"),
                        fn["name"],
                        json.loads(args) if isinstance(args, str) else dict(args),
                    )
                )
            return AssistantTurn(message.get("content"), calls)
        except urllib.error.HTTPError as exc:
            raise _http_failure(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"model API unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"model API returned an invalid response: {exc}") from exc

    def stream(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        """Server-sent events from `stream: true`; tool-call fragments are merged by index."""
        body = {**self._body(messages, tools), "stream": True}
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.url, json.dumps(body).encode("utf-8"), headers, method="POST"
        )
        content: List[str] = []
        partial: Dict[int, Dict[str, str]] = {}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                for payload in decode_events(response):
                    if payload.get("usage"):
                        self.last_usage = dict(payload["usage"])
                    if payload.get("laris", {}).get("brain"):
                        yield {"type": "brain", "trace": list(payload["laris"]["brain"])}
                    if not payload.get("choices"):
                        continue
                    delta = payload["choices"][0].get("delta", {})
                    hidden = delta.get("reasoning_content") or delta.get("reasoning")
                    if hidden:  # a reasoning model's thoughts: passed on as their own event
                        yield {"type": "reasoning", "delta": hidden}
                    if delta.get("content"):
                        content.append(delta["content"])
                        yield {"type": "text", "delta": delta["content"]}
                    for frag in delta.get("tool_calls") or []:
                        slot = partial.setdefault(
                            int(frag.get("index", 0)), {"id": "", "name": "", "arguments": ""}
                        )
                        slot["id"] = frag.get("id") or slot["id"]
                        fn = frag.get("function") or {}
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["arguments"] += fn.get("arguments") or ""
        except urllib.error.HTTPError as exc:
            raise _http_failure(exc) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ProviderError(f"model API unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"model API returned an invalid stream: {exc}") from exc
        calls: List[ToolCall] = []
        for index in sorted(partial):
            slot = partial[index]
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError(f"invalid tool arguments from model: {exc}") from exc
            calls.append(ToolCall(slot["id"] or f"call_{index}", slot["name"], args))
        yield {"type": "turn", "turn": AssistantTurn("".join(content) or None, calls)}


class HttpEmbedder:
    """`POST {base_url}/embeddings`: the vectors of a list of texts."""

    def __init__(
        self,
        base_url: str,
        model: str = "",
        api_key_env: Optional[str] = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self.api_key = os.environ.get(api_key_env) if api_key_env else None
        self.timeout_s = timeout_s

    def __call__(self, texts: List[str]) -> List[List[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = json.dumps({"input": texts, "model": self.model}).encode("utf-8")
        request = urllib.request.Request(self.url, body, headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = sorted(payload["data"], key=lambda row: row["index"])
            return [[float(x) for x in row["embedding"]] for row in rows]
        except urllib.error.HTTPError as exc:
            raise _http_failure(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"model API unreachable: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"model API returned an invalid response: {exc}") from exc
