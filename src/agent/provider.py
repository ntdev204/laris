"""Model providers: the seam where the future LARIS core model plugs in through an API.

`ChatProvider.chat(messages, tools)` follows the OpenAI-compatible chat-completions contract
(`/v1/chat/completions` with `tools`), so any service that speaks it can drive the agent.
`OfflinePlanner` is a deterministic fallback that needs no model, so the system runs end to end
before the core model exists. It is a scripted workflow, not a language model.
"""

import json
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

Message = Dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class AssistantTurn:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)


class ProviderError(RuntimeError):
    """The model API failed or returned something outside the contract."""


class ChatProvider(ABC):
    name = "provider"

    @abstractmethod
    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        """Return the next assistant turn: text, or tool calls to execute."""

    def stream(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        """Yield {"type": "text", "delta": str} events, then one {"type": "turn", "turn": ...}.

        Providers without native streaming fall back to a single text event.
        """
        turn = self.chat(messages, tools)
        if turn.content:
            yield {"type": "text", "delta": turn.content}
        yield {"type": "turn", "turn": turn}


class HttpChatProvider(ChatProvider):
    """Client for an OpenAI-compatible chat-completions endpoint (local or remote)."""

    name = "http"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: Optional[str] = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = os.environ.get(api_key_env) if api_key_env else None
        self.timeout_s = timeout_s

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        body = {"model": self.model, "messages": messages, "tools": tools, "temperature": 0}
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
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"model API unreachable: {exc}") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"model API returned an invalid response: {exc}") from exc

    def stream(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        """Server-sent events from `stream: true`; tool-call fragments are merged by index."""
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "temperature": 0,
            "stream": True,
        }
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
                for raw in response:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0].get("delta", {})
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


_PATH_RE = re.compile(r"(?:^|\s)([\w./~-]+\.(?:txt|md|pdf|png|jpe?g|tiff?))(?=\s|$|[.,;:?])", re.I)


class OfflinePlanner(ChatProvider):
    """Scripted workflow: read mentioned files, search the corpus, quote the best evidence.

    It decides tool calls with fixed rules and writes the final answer from tool results only.
    """

    name = "offline"

    def __init__(self, has_model: bool = False) -> None:
        self.has_model = has_model

    @staticmethod
    def _results(messages: List[Message]) -> Dict[str, List[Any]]:
        done: Dict[str, List[Any]] = {}
        calls: Dict[str, str] = {}
        for m in messages:
            for c in m.get("tool_calls") or []:
                calls[c["id"]] = c["function"]["name"]
            if m.get("role") == "tool":
                done.setdefault(calls.get(m["tool_call_id"], "?"), []).append(
                    json.loads(m["content"])
                )
        return done

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        task = messages[last_user]["content"]
        messages = messages[last_user:]  # only this turn's tool results count
        done = self._results(messages)
        step = sum(1 for m in messages if m["role"] == "tool")

        def call(name: str, **arguments: Any) -> AssistantTurn:
            return AssistantTurn(None, [ToolCall(f"call_{step}", name, arguments)])

        paths = _PATH_RE.findall(task)
        if paths and "read_file" not in done:
            return call("read_file", path=paths[0], max_chars=4000)
        wants_extraction = re.search(r"claim|metric|extract|trích|tách", task, re.I)
        if paths and wants_extraction and "extract_discourse" not in done:
            return call("extract_discourse", path=paths[0])
        if "search_corpus" not in done:
            return call("search_corpus", query=task, top_k=5)
        hits = done["search_corpus"][-1].get("hits", [])
        if self.has_model and hits and "answer_question" not in done:
            return call("answer_question", question=task)
        return AssistantTurn(self._compose(task, done, hits))

    @staticmethod
    def _compose(task: str, done: Dict[str, List[Any]], hits: List[Dict[str, Any]]) -> str:
        lines = [f"Task: {task}", ""]
        read = (done.get("read_file") or [{}])[-1]
        if read.get("text"):
            lines += [f"Read {read['path']} ({read['total_chars']} chars):", read["text"][:600], ""]
        found = (done.get("extract_discourse") or [{}])[-1]
        if "metrics" in found:
            counts = {k: len(found[k]) for k in ("claims", "methods", "datasets", "metrics")}
            lines.append("Extracted entities: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
            for metric in found["metrics"][:5]:
                lines.append(f"- metric {metric['name']} {metric.get('value')}")
            lines.append("")
        if "error" in (done.get("search_corpus") or [{}])[-1]:
            lines.append("Search failed: " + done["search_corpus"][-1]["error"]["message"])
        elif not hits:
            lines.append("No passage in the corpus matches this task.")
        else:
            answer = ((done.get("answer_question") or [{}])[-1]).get("primary")
            if answer:
                lines.append(f"Extractive answer: {answer['answer']} (source: {answer['source']})")
            lines.append("Evidence passages:")
            for hit in hits[:3]:
                snippet = " ".join(hit["text"].split())[:240]
                lines.append(f"- [{hit['source']} #{hit['rank']}] {hit['title']}: {snippet}")
        lines.append("")
        lines.append("Offline planner: results are quoted passages, not a model-written synthesis.")
        return "\n".join(lines)
