"""Context management: token estimates and automatic compaction (on by default).

Compaction keeps long sessions usable: first old tool outputs are trimmed, then older turns are
replaced by a summary (written by the model when one is available, otherwise extracted
deterministically). Recent turns stay verbatim and tool-call/result pairs are never split.
All limits come from `ContextConfig`; all text from the string catalogue.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.runtime_schemas import ContextConfig
from harness.strings import StringCatalogue

Message = Dict[str, Any]
Summarizer = Callable[[str, str], Optional[str]]  # (transcript, instructions) -> summary


class TokenEstimator:
    """Rough token counts from character length; replace with a real tokenizer when available."""

    def __init__(self, cfg: ContextConfig) -> None:
        self.chars_per_token = cfg.chars_per_token
        self.overhead = cfg.message_overhead_tokens

    def __call__(self, value: Any) -> int:
        if isinstance(value, str):
            return int(len(value) / self.chars_per_token) + 1
        if isinstance(value, list):
            return sum(self(m) for m in value)
        return self.overhead + int(
            len(json.dumps(value, ensure_ascii=False)) / self.chars_per_token
        )


def is_overflow_error(message: str, hints: List[str]) -> bool:
    lowered = message.lower()
    return any(hint.lower() in lowered for hint in hints)


@dataclass
class CompactionResult:
    before: int
    after: int
    summarized: int
    method: str  # trim | model | extractive
    archived: Optional[List[Message]] = None

    def event(self) -> Dict[str, Any]:
        return {
            "type": "compact",
            "before": self.before,
            "after": self.after,
            "summarized": self.summarized,
            "method": self.method,
        }


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ContextManager:
    def __init__(
        self,
        cfg: ContextConfig,
        strings: StringCatalogue,
        summarizer: Optional[Summarizer] = None,
    ) -> None:
        self.cfg = cfg
        self.strings = strings
        self.summarizer = summarizer
        self.estimate = TokenEstimator(cfg)
        self.window = cfg.window_tokens
        self.enabled = cfg.enabled
        self.marker = strings.get("compaction.summary_marker")
        self.ack = strings.get("compaction.summary_ack")

    def is_overflow(self, message: str) -> bool:
        return is_overflow_error(message, self.cfg.overflow_hints)

    def usage(self, messages: List[Message], tools_tokens: int = 0) -> int:
        return self.estimate(messages) + tools_tokens

    def needs_compaction(self, messages: List[Message], tools_tokens: int = 0) -> bool:
        return (
            self.enabled and self.usage(messages, tools_tokens) > self.window * self.cfg.threshold
        )

    def compact(
        self, messages: List[Message], instructions: str = "", force: bool = False
    ) -> Tuple[List[Message], Optional[CompactionResult]]:
        """Return (new_messages, result). `result` is None when nothing could be shrunk."""
        before = self.estimate(messages)
        system, rest = messages[:1], messages[1:]
        boundary = self._split_index(rest)
        old, recent = rest[:boundary], rest[boundary:]
        trimmed = system + [self._trim(m) for m in old] + recent
        after_trim = self.estimate(trimmed)
        target = self.window * self.cfg.threshold * 0.6
        if not force and after_trim <= target and after_trim < before:
            return trimmed, CompactionResult(before, after_trim, 0, "trim", old)
        if not old:
            if not force:
                return messages, None  # never trim the turn in progress unless the model overflowed
            shrunk = system + [self._trim(m) for m in recent]
            after = self.estimate(shrunk)
            return (
                (shrunk, CompactionResult(before, after, 0, "trim", recent))
                if after < before
                else (
                    messages,
                    None,
                )
            )
        summary, method = self._summarise(old, instructions)
        head: List[Message] = [
            {"role": "user", "content": f"{self.marker}\n{summary}", "compacted": True},
            {"role": "assistant", "content": self.ack, "compacted_ack": True},
        ]
        new = system + head + recent
        after = self.estimate(new)
        if after >= before:
            return messages, None
        return new, CompactionResult(before, after, len(old), method, old)

    # -- internals -------------------------------------------------------------------------
    def _split_index(self, rest: List[Message]) -> int:
        """Index of the first message kept verbatim: always a user message, never mid tool-pair."""
        budget = self.window * self.cfg.keep_fraction
        starts = [
            i for i, m in enumerate(rest) if m.get("role") == "user" and not m.get("compacted")
        ]
        if not starts:
            return 0
        chosen = starts[-1]  # the latest user turn is always kept
        for index in reversed(starts):
            if self.estimate(rest[index:]) <= budget:
                chosen = index
            else:
                break
        return chosen

    def _trim(self, message: Message) -> Message:
        keep = self.cfg.trim_keep_chars
        content = message.get("content")
        if message.get("role") == "tool" and isinstance(content, str) and len(content) > keep * 2:
            cut = len(content) - keep
            return {
                **message,
                "content": content[:keep]
                + self.strings.get("compaction.trimmed_suffix", chars=cut),
            }
        return message

    def _summarise(self, old: List[Message], instructions: str) -> Tuple[str, str]:
        if self.summarizer:
            try:
                text = self.summarizer(self.transcript(old), instructions)
            except Exception:
                text = None
            if text and text.strip():
                return text.strip(), "model"
        return self.extractive_summary(old), "extractive"

    def transcript(
        self, messages: List[Message], tool_chars: int = 700, max_chars: int = 30000
    ) -> str:
        s = self.strings
        lines: List[str] = []
        for m in messages:
            role, content = m.get("role"), m.get("content") or ""
            if role == "tool":
                lines.append(s.get("compaction.transcript_tool", text=_clip(content, tool_chars)))
            elif role == "assistant" and m.get("tool_calls"):
                calls = ", ".join(
                    f"{c['function']['name']}({_clip(c['function']['arguments'], 120)})"
                    for c in m["tool_calls"]
                )
                lines.append(s.get("compaction.transcript_call", calls=calls))
            elif role in ("user", "assistant"):
                lines.append(f"[{role}] {_clip(content, 1500)}")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else "…\n" + text[-max_chars:]

    def extractive_summary(self, messages: List[Message], limit: int = 3500) -> str:
        """Deterministic summary: requests, tools used and the start of each final answer."""
        s = self.strings
        lines: List[str] = []
        for m in messages:
            role, content = m.get("role"), m.get("content") or ""
            if m.get("harness"):
                continue
            if role == "user" and content.startswith(self.marker):
                lines.append(content[len(self.marker) :].strip())
            elif role == "user":
                lines.append(s.get("compaction.user_label", text=_clip(content, 260)))
            elif role == "assistant" and m.get("tool_calls"):
                names = ", ".join(c["function"]["name"] for c in m["tool_calls"])
                lines.append(s.get("compaction.tool_label", names=names))
            elif role == "assistant" and content and content != self.ack:
                lines.append(s.get("compaction.assistant_label", text=_clip(content, 360)))
        text = "\n".join(lines)
        if len(text) <= limit:
            return text
        head = limit // 3  # keep the original goal and the most recent work, drop the middle
        return (
            text[:head] + "\n" + s.get("compaction.omitted_middle") + "\n" + text[-(limit - head) :]
        )
