"""Context management: token estimates and automatic compaction (on by default).

Compaction keeps long sessions usable: first old tool outputs are trimmed, then older turns are
replaced by a summary (written by the model when one is available, otherwise extracted
deterministically). Recent turns are kept verbatim and tool-call/result pairs are never split.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

Message = Dict[str, Any]
Summarizer = Callable[[str, str], Optional[str]]  # (transcript, instructions) -> summary

CHARS_PER_TOKEN = 3.5  # conservative for mixed Vietnamese/English text
MESSAGE_OVERHEAD = 6
TRIM_KEEP_CHARS = 600
SUMMARY_MARKER = "[Tóm tắt cuộc trò chuyện trước đó, đã nén tự động]"
SUMMARY_ACK = "Đã ghi nhận tóm tắt; tiếp tục từ đây."
OVERFLOW_HINTS = (
    "context length",
    "context window",
    "maximum context",
    "too many tokens",
    "context_length",
)


def estimate_tokens(value: Any) -> int:
    """Rough token count of a message, a list of messages or a string."""
    if isinstance(value, str):
        return int(len(value) / CHARS_PER_TOKEN) + 1
    if isinstance(value, list):
        return sum(estimate_tokens(m) for m in value)
    return MESSAGE_OVERHEAD + int(len(json.dumps(value, ensure_ascii=False)) / CHARS_PER_TOKEN)


def is_overflow_error(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in OVERFLOW_HINTS)


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


def render_transcript(
    messages: List[Message], tool_chars: int = 700, max_chars: int = 30000
) -> str:
    lines: List[str] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "tool":
            lines.append(f"[kết quả công cụ] {_clip(content, tool_chars)}")
        elif role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(
                f"{c['function']['name']}({_clip(c['function']['arguments'], 120)})"
                for c in m["tool_calls"]
            )
            lines.append(f"[trợ lý gọi] {calls}")
        elif role in ("user", "assistant"):
            lines.append(f"[{role}] {_clip(content, 1500)}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else "…\n" + text[-max_chars:]


def extractive_summary(messages: List[Message], limit: int = 3500) -> str:
    """Deterministic summary: requests, tools used and the start of each final answer."""
    lines: List[str] = []
    for m in messages:
        role, content = m.get("role"), m.get("content") or ""
        if role == "user" and content.startswith(SUMMARY_MARKER):
            lines.append(content[len(SUMMARY_MARKER) :].strip())
        elif role == "user":
            lines.append(f"- Người dùng: {_clip(content, 260)}")
        elif role == "assistant" and m.get("tool_calls"):
            names = ", ".join(c["function"]["name"] for c in m["tool_calls"])
            lines.append(f"  · công cụ đã dùng: {names}")
        elif role == "assistant" and content and content != SUMMARY_ACK:
            lines.append(f"  → Trợ lý: {_clip(content, 360)}")
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    head = limit // 3  # keep the original goal and the most recent work, drop the middle
    return text[:head] + "\n…(phần giữa đã lược)…\n" + text[-(limit - head) :]


class ContextManager:
    def __init__(
        self,
        window: int,
        threshold: float = 0.8,
        keep_fraction: float = 0.3,
        enabled: bool = True,
        summarizer: Optional[Summarizer] = None,
    ) -> None:
        self.window = max(int(window), 2048)
        self.threshold = min(max(threshold, 0.3), 0.95)
        self.keep_fraction = keep_fraction
        self.enabled = enabled
        self.summarizer = summarizer

    def usage(self, messages: List[Message], tools_tokens: int = 0) -> int:
        return estimate_tokens(messages) + tools_tokens

    def needs_compaction(self, messages: List[Message], tools_tokens: int = 0) -> bool:
        return self.enabled and self.usage(messages, tools_tokens) > self.window * self.threshold

    def compact(
        self, messages: List[Message], instructions: str = "", force: bool = False
    ) -> Tuple[List[Message], Optional[CompactionResult]]:
        """Return (new_messages, result). `result` is None when nothing could be shrunk."""
        before = estimate_tokens(messages)
        system, rest = messages[:1], messages[1:]
        boundary = self._split_index(rest)
        old, recent = rest[:boundary], rest[boundary:]
        trimmed_old = [self._trim(m) for m in old]
        trimmed = system + trimmed_old + recent
        target = self.window * self.threshold * 0.6
        if not force and estimate_tokens(trimmed) <= target and estimate_tokens(trimmed) < before:
            return trimmed, CompactionResult(before, estimate_tokens(trimmed), 0, "trim", old)
        if not old:
            if not force:
                return messages, None  # never trim the turn in progress unless the model overflowed
            shrunk = system + [self._trim(m, TRIM_KEEP_CHARS) for m in recent]
            after = estimate_tokens(shrunk)
            if after < before:
                return shrunk, CompactionResult(before, after, 0, "trim", recent)
            return messages, None
        summary, method = self._summarise(old, instructions)
        head: List[Message] = [
            {"role": "user", "content": f"{SUMMARY_MARKER}\n{summary}", "compacted": True},
            {"role": "assistant", "content": SUMMARY_ACK},
        ]
        new = system + head + recent
        after = estimate_tokens(new)
        if after >= before:
            return messages, None
        return new, CompactionResult(before, after, len(old), method, old)

    # -- internals -------------------------------------------------------------------------
    def _split_index(self, rest: List[Message]) -> int:
        """Index of the first message kept verbatim: always a user message, never mid tool-pair."""
        budget = self.window * self.keep_fraction
        starts = [
            i for i, m in enumerate(rest) if m.get("role") == "user" and not m.get("compacted")
        ]
        if not starts:
            return 0
        chosen = starts[-1]  # the latest user turn is always kept
        for index in reversed(starts):
            if estimate_tokens(rest[index:]) <= budget:
                chosen = index
            else:
                break
        return chosen

    @staticmethod
    def _trim(message: Message, keep: int = TRIM_KEEP_CHARS) -> Message:
        content = message.get("content")
        if message.get("role") == "tool" and isinstance(content, str) and len(content) > keep * 2:
            cut = len(content) - keep
            return {**message, "content": content[:keep] + f"…[đã rút gọn {cut} ký tự]"}
        return message

    def _summarise(self, old: List[Message], instructions: str) -> Tuple[str, str]:
        if self.summarizer:
            try:
                text = self.summarizer(render_transcript(old), instructions)
            except Exception:
                text = None
            if text and text.strip():
                return text.strip(), "model"
        return extractive_summary(old), "extractive"
