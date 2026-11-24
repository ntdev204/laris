"""Chat backend on an inference server that holds the open-weight model (T282, ADR-021).

`ServedChat` is a `ChatProvider` for `laris-model serve --backend
laris.model.inference.served_llm:ServedChat`. The weights live in one vLLM server
(`vllm/vllm-openai`, BF16), which the STEM benchmark runner calls as well, so chat and evaluation
share one engine and one precision. The model block keeps the same contract as `OpenWeightChat`:

- the server renders the model's own chat template (`/tokenize`, with the tools and the thinking
  switch), the prompt is shortened to the input budget with `fit_to_budget`, and the token ids are
  sent to `/v1/completions`; the raw reply is split into reasoning, text and tool calls here, with
  the parsers of `open_llm`, so the server needs no reasoning or tool parser and its output for the
  benchmark is the plain text that T275 measured;
- streaming reads the server's event stream and yields the same `reasoning`, `text` and `turn`
  events.

Everything is configuration (`model_service`): the server URL, the model id it serves, token limits,
thinking, temperature, the timeout and the server's GPU share. Inference only; this module imports
nothing beyond the standard library.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from laris.model.inference.open_llm import (
    THINK_OPEN,
    StreamEvents,
    assistant_turn,
    fit_to_budget,
)
from laris.protocol import AssistantTurn, ChatProvider, ProviderError, http_failure

_SERVER_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")

Opener = Callable[..., Any]


def server_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages in the OpenAI wire form the server validates: no extra keys, text content and
    tool-call arguments as JSON strings (the server decodes them for the chat template)."""
    out: List[Dict[str, Any]] = []
    for message in messages:
        item = {k: message[k] for k in _SERVER_KEYS if k in message}
        if item.get("content") is None:
            item["content"] = ""
        calls = []
        for call in item.get("tool_calls") or []:
            function = dict(call.get("function") or {})
            args = function.get("arguments")
            if not isinstance(args, str):
                function["arguments"] = json.dumps(args or {}, ensure_ascii=False)
            calls.append({"type": "function", **call, "function": function})
        if calls:
            item["tool_calls"] = calls
        elif "tool_calls" in item:
            del item["tool_calls"]
        out.append(item)
    return out


class ServedChat(ChatProvider):
    name = "served-llm"

    def __init__(self, cfg: Any = None, opener: Optional[Opener] = None) -> None:
        if cfg is None:
            from pathlib import Path

            from laris.shared.config.loader import load_runtime_config

            cfg = load_runtime_config(Path.cwd()).model_service
        if not cfg.chat_server_url:
            raise ProviderError("model_service.chat_server_url is not set")
        if not cfg.chat_model_id:
            raise ProviderError("model_service.chat_model_id is not set")
        if cfg.chat_quantization not in ("none", "fp8"):
            # the server holds the weights in BF16 or FP8 (T279); a bitsandbytes setting here
            # would be a false record of what it serves
            raise ProviderError(
                "the served model runs in BF16 or FP8: "
                "set model_service.chat_quantization to none or fp8"
            )
        self.cfg = cfg
        self._open = opener or urllib.request.urlopen
        self._max_model_len = 0

    # -- the GPU queue -------------------------------------------------------------------------
    @property
    def vram_bytes(self) -> int:
        """GPU memory the server reserves (its share of the device), declared to the GPU queue."""
        return int(self.cfg.chat_server_gpu_share * self.cfg.gpu_memory_bytes)

    def load(self) -> None:
        """The weights are in the server: check that it serves the configured model."""
        if self._max_model_len:
            return
        listing = self._request("GET", "/v1/models")
        for entry in listing.get("data") or []:
            if entry.get("id") == self.cfg.chat_model_id:
                self._max_model_len = int(entry.get("max_model_len") or 0)
                return
        served = ", ".join(str(e.get("id")) for e in listing.get("data") or []) or "nothing"
        raise ProviderError(f"the model server serves {served}, not {self.cfg.chat_model_id}")

    def unload(self) -> None:
        """Nothing to release here: the server keeps its reservation for every caller."""

    def memory_bytes(self) -> int:
        return 0  # no weights in this process

    # -- requests ------------------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return str(self.cfg.chat_server_url).rstrip("/") + path

    def _send(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._url(path), data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            return self._open(request, timeout=self.cfg.chat_server_timeout_s)
        except urllib.error.HTTPError as exc:
            raise http_failure(exc) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderError(f"the model server is unreachable: {exc}") from exc

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        with self._send(method, path, body) as response:
            try:
                return json.loads(response.read())
            except ValueError as exc:
                raise ProviderError("the model server answered something that is not JSON") from exc

    def _tokenize(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Tuple[List[int], bool]:
        """The prompt token ids, and whether the template left the reasoning open at the end."""
        body: Dict[str, Any] = {
            "model": self.cfg.chat_model_id,
            "messages": messages,
            "add_generation_prompt": True,
            "chat_template_kwargs": {"enable_thinking": self.cfg.chat_thinking},
            "return_token_strs": True,
        }
        if tools:
            body["tools"] = tools
        reply = self._request("POST", "/tokenize", body)
        tokens, strs = reply.get("tokens"), reply.get("token_strs") or []
        if not isinstance(tokens, list):
            raise ProviderError("the model server returned no prompt tokens")
        tail = [s for s in strs[-4:] if str(s).strip("\nĊ ")]  # Ċ: a newline in byte-level BPE
        return tokens, bool(tail) and tail[-1] == THINK_OPEN

    def input_budget(self) -> int:
        """Prompt tokens one request may use: the configured budget, and never more than the
        server's context leaves after the reply (0: no budget)."""
        budget = int(self.cfg.chat_max_input_tokens)
        if self._max_model_len:
            room = max(1, self._max_model_len - self.cfg.chat_max_new_tokens)
            budget = min(budget, room) if budget > 0 else room
        return budget

    def prompt(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Tuple[List[int], bool]:
        """The prompt token ids of a conversation, fitted to the input budget, and whether the
        reply starts inside the reasoning."""
        self.load()
        rendered: Dict[str, Tuple[List[int], bool]] = {}

        def render(items: List[Dict[str, Any]]) -> Tuple[List[int], bool]:
            key = json.dumps(items, sort_keys=True, ensure_ascii=False)
            if key not in rendered:
                rendered[key] = self._tokenize(items, tools)
            return rendered[key]

        fitted = fit_to_budget(
            server_messages(messages), lambda items: len(render(items)[0]), self.input_budget()
        )
        return render(fitted)

    def _body(self, prompt: List[int], stream: bool) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.cfg.chat_model_id,
            "prompt": prompt,
            "max_tokens": self.cfg.chat_max_new_tokens,
            "temperature": self.cfg.chat_temperature,  # 0 is greedy decoding
        }
        if stream:
            body.update(stream=True, stream_options={"include_usage": True})
        return body

    @staticmethod
    def _choice(reply: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        choices = reply.get("choices") or []
        if not choices:
            return "", None
        return str(choices[0].get("text") or ""), choices[0].get("finish_reason")

    # -- chat ----------------------------------------------------------------------------------
    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AssistantTurn:
        prompt, opened = self.prompt(messages, tools)
        reply = self._request("POST", "/v1/completions", self._body(prompt, False))
        if not reply.get("choices"):
            raise ProviderError("the model server returned no completion")
        return assistant_turn(self._choice(reply)[0], opened)

    def stream(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        prompt, opened = self.prompt(messages, tools)
        events = StreamEvents(opened)
        with self._send("POST", "/v1/completions", self._body(prompt, True)) as response:
            for line in response:
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                data = text[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError as exc:
                    raise ProviderError("the model server sent a broken stream event") from exc
                if "error" in event and not event.get("choices"):
                    raise ProviderError(f"generation failed: {event['error']}")
                piece, _ = self._choice(event)
                if piece:
                    yield from events.feed(piece)
        yield from events.finish()
