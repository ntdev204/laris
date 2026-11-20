"""Chat backend on an open-weight LLM served through Hugging Face `transformers` (T231, ADR-021).

`OpenWeightChat` is a `ChatProvider` for `laris-model serve --backend
laris.model.inference.open_llm:OpenWeightChat`. Everything is configuration (`model_service`
section): the model id, quantisation, token limit, thinking switch and temperature. The model's
reasoning text (`<think>...</think>`) is returned as `AssistantTurn.reasoning` and as `reasoning`
stream events, never in the chat body. Tool calls in the model's own format are parsed into
`ToolCall`s. Inference only: no gradient is ever computed.
"""

import json
import re
import threading
import uuid
from typing import Any, Dict, Iterator, List, Tuple

from laris.protocol import AssistantTurn, ChatProvider, ProviderError, ToolCall

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
_TOOL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FUNCTION = re.compile(r"<function=([^>\s]+)>\s*(.*?)\s*</function>", re.DOTALL)
_PARAMETER = re.compile(r"<parameter=([^>\s]+)>\n?(.*?)\n?</parameter>", re.DOTALL)


def split_reasoning(text: str) -> Tuple[str, str]:
    """`(reasoning, answer)`: the `<think>` section of a reply and what follows it."""
    start = text.find(THINK_OPEN)
    end = text.find(THINK_CLOSE)
    if end >= 0:  # the opening tag may sit in the prompt (the template adds it)
        begin = start + len(THINK_OPEN) if 0 <= start < end else 0
        return text[begin:end].strip(), (text[:start] if 0 <= start < end else "") + text[
            end + len(THINK_CLOSE) :
        ]
    if start >= 0:  # cut off while still reasoning
        return text[start + len(THINK_OPEN) :].strip(), text[:start]
    return "", text


def _value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_tool_calls(text: str) -> Tuple[str, List[ToolCall]]:
    """The reply with tool-call blocks removed, and the calls in them (JSON or XML form)."""
    calls: List[ToolCall] = []
    for block in _TOOL_BLOCK.findall(text):
        name, arguments = "", {}  # type: str, Dict[str, Any]
        function = _FUNCTION.search(block)
        if function:
            name = function.group(1)
            arguments = {k: _value(v) for k, v in _PARAMETER.findall(function.group(2))}
        else:
            try:
                data = json.loads(block)
                name, arguments = str(data["name"]), dict(data.get("arguments") or {})
            except (ValueError, KeyError, TypeError):
                continue
        calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments))
    return _TOOL_BLOCK.sub("", text).strip(), calls


def template_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wire messages in the form chat templates expect: tool-call arguments as objects."""
    out: List[Dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        if item.get("content") is None:
            item["content"] = ""
        calls = []
        for call in item.get("tool_calls") or []:
            function = dict(call.get("function") or {})
            args = function.get("arguments")
            if isinstance(args, str):
                try:
                    function["arguments"] = json.loads(args or "{}")
                except ValueError:
                    function["arguments"] = {}
            calls.append({**call, "function": function})
        if calls:
            item["tool_calls"] = calls
        out.append(item)
    return out


class OpenWeightChat(ChatProvider):
    name = "open-llm"

    def __init__(self) -> None:
        from pathlib import Path

        from laris.shared.config.loader import load_runtime_config

        cfg = load_runtime_config(Path.cwd()).model_service
        if not cfg.chat_model_id:
            raise ProviderError("model_service.chat_model_id is not set")
        self.cfg = cfg
        self._model: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    # -- weights -------------------------------------------------------------------------------
    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        cfg = self.cfg
        device = cfg.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        kwargs: Dict[str, Any] = {"dtype": torch.bfloat16}
        if cfg.chat_quantization != "none":
            if device == "cpu":
                raise ProviderError("quantised loading needs a GPU")
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_8bit=cfg.chat_quantization == "8bit",
                load_in_4bit=cfg.chat_quantization == "4bit",
            )
        kwargs["device_map"] = device
        self._tokenizer = AutoTokenizer.from_pretrained(cfg.chat_model_id)
        self._model = AutoModelForCausalLM.from_pretrained(cfg.chat_model_id, **kwargs).eval()

    def unload(self) -> None:
        self._model = self._tokenizer = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def memory_bytes(self) -> int:
        try:
            import torch

            return int(torch.cuda.memory_allocated()) if torch.cuda.is_available() else 0
        except ImportError:
            return 0

    # -- generation ----------------------------------------------------------------------------
    def _inputs(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        self.load()
        prompt = self._tokenizer.apply_chat_template(
            template_messages(messages),
            tools=tools or None,
            add_generation_prompt=True,
            tokenize=False,
            enable_thinking=self.cfg.chat_thinking,
        )
        return self._tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(
            self._model.device
        )

    def _gen_kwargs(self) -> Dict[str, Any]:
        cfg = self.cfg
        kwargs: Dict[str, Any] = {"max_new_tokens": cfg.chat_max_new_tokens}
        if cfg.chat_temperature > 0:
            kwargs.update(do_sample=True, temperature=cfg.chat_temperature)
        else:
            kwargs.update(do_sample=False, temperature=None, top_p=None, top_k=None)
        return kwargs

    @staticmethod
    def _turn(raw: str) -> AssistantTurn:
        reasoning, answer = split_reasoning(raw)
        content, calls = parse_tool_calls(answer)
        return AssistantTurn(content=content or None, tool_calls=calls, reasoning=reasoning or None)

    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AssistantTurn:
        import torch

        with self._lock:
            inputs = self._inputs(messages, tools)
            try:
                with torch.inference_mode():
                    out = self._model.generate(**inputs, **self._gen_kwargs())
            except torch.cuda.OutOfMemoryError as exc:
                raise ProviderError("GPU out of memory while generating") from exc
            new = out[0][inputs["input_ids"].shape[1] :]
            return self._turn(self._tokenizer.decode(new, skip_special_tokens=True))

    def stream(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        import torch
        from transformers import TextIteratorStreamer

        with self._lock:
            inputs = self._inputs(messages, tools)
            streamer = TextIteratorStreamer(
                self._tokenizer, skip_prompt=True, skip_special_tokens=True
            )
            failure: List[BaseException] = []

            def run() -> None:
                try:
                    with torch.inference_mode():
                        self._model.generate(**inputs, streamer=streamer, **self._gen_kwargs())
                except BaseException as exc:  # reported after the stream ends
                    failure.append(exc)
                    streamer.on_finalized_text("", stream_end=True)

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            raw, sent_reasoning, sent_text = "", 0, 0
            for piece in streamer:
                raw += piece
                reasoning, answer = split_reasoning(raw)
                # hold back a possible partial tag or tool-call block at the end of the text
                visible = answer.split("<tool_call>")[0]
                for cut in range(1, len(THINK_CLOSE)):
                    if visible.endswith(THINK_CLOSE[:cut]) or visible.endswith(THINK_OPEN[:cut]):
                        visible = visible[:-cut]
                        break
                if len(reasoning) > sent_reasoning:
                    yield {"type": "reasoning", "delta": reasoning[sent_reasoning:]}
                    sent_reasoning = len(reasoning)
                if len(visible) > sent_text:
                    yield {"type": "text", "delta": visible[sent_text:]}
                    sent_text = len(visible)
            worker.join()
            if failure:
                raise ProviderError(f"generation failed: {type(failure[0]).__name__}")
            turn = self._turn(raw)
            tail = (turn.content or "")[sent_text:] if not turn.tool_calls else ""
            if tail:
                yield {"type": "text", "delta": tail}
            yield {"type": "turn", "turn": turn}
