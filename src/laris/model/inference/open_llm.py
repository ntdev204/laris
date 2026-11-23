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
from typing import Any, Callable, Dict, Iterator, List, Tuple

from laris.protocol import AssistantTurn, ChatProvider, ProviderError, ToolCall

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
# Markers that end an assistant turn in the chat templates of the open models (ChatML, Llama 3).
END_OF_TURN_MARKS = ("<|im_end|>", "<|endoftext|>", "<|eot_id|>")
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


_CUT_MARK = "\n[... shortened to fit the model's context budget ...]\n"
_MIN_KEEP = 400  # a message is never shortened below this many characters


def _shorten(text: str) -> str:
    keep = max(_MIN_KEEP, len(text) // 2)
    head = keep * 3 // 5
    return text[:head] + _CUT_MARK + text[len(text) - (keep - head) :]


def fit_to_budget(
    messages: List[Dict[str, Any]], measure: Callable[[List[Dict[str, Any]]], int], budget: int
) -> List[Dict[str, Any]]:
    """`messages`, with the oldest bulky content shortened until `measure` says it fits `budget`.

    Tool results are what grow a prompt (pages, passages), so they go first, largest first; the
    system message, the user's latest question and the latest message (unless it is a tool result)
    are left alone. If shortening is not enough, the oldest turns after the system message are
    dropped, always keeping the latest message with the call it answers and the user's latest
    question (a chat template refuses a conversation without one).
    `budget <= 0` turns this off.
    """
    if budget <= 0 or measure(messages) <= budget:
        return messages
    work = [dict(m) for m in messages]

    def question(items: List[Dict[str, Any]]) -> int:
        users = [i for i, m in enumerate(items) if m.get("role") == "user"]
        return users[-1] if users else -1

    # the latest message is kept whole unless it is a tool result: data, not the question
    last = len(work) - 1
    protected = {question(work)} | {i for i, m in enumerate(work) if m.get("role") == "system"}
    if work[last].get("role") != "tool":
        protected.add(last)
    while measure(work) > budget:
        candidates = [
            (len(str(m.get("content") or "")), i)
            for i, m in enumerate(work)
            if i not in protected and len(str(m.get("content") or "")) > _MIN_KEEP * 2
        ]
        if not candidates:
            break
        _, index = max(candidates, key=lambda c: (work[c[1]].get("role") == "tool", c[0]))
        work[index]["content"] = _shorten(str(work[index]["content"]))

    def tail(items: List[Dict[str, Any]]) -> int:
        """Start of the last block: the latest message, with the call its tool results answer."""
        start = len(items) - 1
        while start > 0 and items[start].get("role") == "tool":
            start -= 1
        return start if items[-1].get("role") == "tool" else len(items) - 1

    while measure(work) > budget:
        asked = question(work)
        droppable = [i for i in range(tail(work)) if work[i].get("role") != "system" and i != asked]
        if not droppable:
            raise ProviderError("the conversation does not fit the model's input budget")
        first = droppable[0]
        del work[first]
        # never leave a tool result without the call that asked for it
        while first < tail(work) and work[first].get("role") == "tool":
            del work[first]
    return work


TOOL_OPEN = "<tool_call>"


def _hold_back(text: str, marks: Tuple[str, ...] = (THINK_OPEN, THINK_CLOSE)) -> str:
    """`text` without a possible partial tag (one of `marks`) at its end."""
    for cut in range(max(len(m) for m in marks) - 1, 0, -1):
        if any(len(m) > cut and text.endswith(m[:cut]) for m in marks):
            return text[:-cut]
    return text


def assistant_turn(raw: str, opened: bool = False) -> AssistantTurn:
    """The assistant turn in a raw reply: reasoning, visible text and tool calls apart.
    `opened`: the prompt ended inside the reasoning (the template wrote `<think>`), so the reply
    is reasoning until `</think>`, even when it is cut off before the tag."""
    reasoning, answer = split_reasoning(THINK_OPEN + raw if opened else raw)
    content, calls = parse_tool_calls(answer)
    return AssistantTurn(content=content or None, tool_calls=calls, reasoning=reasoning or None)


class StreamEvents:
    """Stream events of a raw reply that arrives in pieces: `reasoning` and `text` deltas as they
    become certain, then the final `turn`. A possible partial tag and every tool-call block are
    held back, so neither reaches the chat body."""

    def __init__(self, opened: bool = False) -> None:
        self.raw, self.opened, self._reasoning, self._text = "", opened, 0, 0

    def feed(self, piece: str) -> Iterator[Dict[str, Any]]:
        self.raw += piece
        text = THINK_OPEN + self.raw if self.opened else self.raw
        reasoning, answer = split_reasoning(text)
        if THINK_OPEN in text and THINK_CLOSE not in text:  # still reasoning: it may end in a tag
            reasoning = _hold_back(text[text.find(THINK_OPEN) + len(THINK_OPEN) :]).strip()
        visible = _hold_back(answer.split(TOOL_OPEN)[0], (THINK_OPEN, THINK_CLOSE, TOOL_OPEN))
        if len(reasoning) > self._reasoning:
            yield {"type": "reasoning", "delta": reasoning[self._reasoning :]}
            self._reasoning = len(reasoning)
        if len(visible) > self._text:
            yield {"type": "text", "delta": visible[self._text :]}
            self._text = len(visible)

    def finish(self) -> Iterator[Dict[str, Any]]:
        turn = assistant_turn(self.raw, self.opened)
        tail = (turn.content or "")[self._text :] if not turn.tool_calls else ""
        if tail:
            yield {"type": "text", "delta": tail}
        yield {"type": "turn", "turn": turn}


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
        self._opened = False

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
    def _prompt(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> str:
        return self._tokenizer.apply_chat_template(
            template_messages(messages),
            tools=tools or None,
            add_generation_prompt=True,
            tokenize=False,
            enable_thinking=self.cfg.chat_thinking,
        )

    def _inputs(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        self.load()

        def measure(items: List[Dict[str, Any]]) -> int:
            return len(
                self._tokenizer(self._prompt(items, tools), add_special_tokens=False)["input_ids"]
            )

        # The prompt (tool schemas plus every earlier tool result) is what makes memory climb during
        # tool use: the activations and the cache of one call grow with its length. Bound it.
        fitted = fit_to_budget(messages, measure, self.cfg.chat_max_input_tokens)
        prompt = self._prompt(fitted, tools)
        self._opened = prompt.rstrip().endswith(THINK_OPEN)  # the reply starts inside the reasoning
        return self._tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(
            self._model.device
        )

    def _release(self) -> None:
        """Hand the memory of a finished call back to the GPU, so tool turns do not pile up."""
        if not self.cfg.chat_release_cache:
            return
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _gen_kwargs(self) -> Dict[str, Any]:
        cfg = self.cfg
        kwargs: Dict[str, Any] = {"max_new_tokens": cfg.chat_max_new_tokens}
        stops = self._stop_ids()
        if stops:
            # a snapshot without generation_config.json would only stop at its end-of-text
            # token and write the next turns of the conversation itself; the end of an
            # assistant turn is a stop as well
            kwargs.update(eos_token_id=stops, pad_token_id=stops[0])
        if cfg.chat_temperature > 0:
            kwargs.update(do_sample=True, temperature=cfg.chat_temperature)
        else:
            kwargs.update(do_sample=False, temperature=None, top_p=None, top_k=None)
        return kwargs

    def _stop_ids(self) -> List[int]:
        """The tokens that end an assistant turn: the tokenizer's end token and the
        chat end-of-turn markers its vocabulary has."""
        tokenizer = self._tokenizer
        ids: List[int] = []
        candidates = [getattr(tokenizer, "eos_token_id", None)]
        vocab = tokenizer.get_vocab() if hasattr(tokenizer, "get_vocab") else {}
        candidates += [vocab.get(mark) for mark in END_OF_TURN_MARKS]
        for value in candidates:
            if isinstance(value, int) and value not in ids:
                ids.append(value)
        return ids

    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AssistantTurn:
        import torch

        with self._lock:
            inputs = self._inputs(messages, tools)
            try:
                with torch.inference_mode():
                    out = self._model.generate(**inputs, **self._gen_kwargs())
            except torch.cuda.OutOfMemoryError as exc:
                self._release()
                raise ProviderError("GPU out of memory while generating") from exc
            new = out[0][inputs["input_ids"].shape[1] :]
            text = self._tokenizer.decode(new, skip_special_tokens=True)
            del out, new, inputs
            self._release()
            return assistant_turn(text, self._opened)

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
            events = StreamEvents(self._opened)
            for piece in streamer:
                yield from events.feed(piece)
            worker.join()
            inputs = streamer = None  # let the prompt tensors go before the cache is released
            self._release()
            if failure:
                raise ProviderError(f"generation failed: {type(failure[0]).__name__}")
            yield from events.finish()
