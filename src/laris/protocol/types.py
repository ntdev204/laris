"""Chat types shared by client, server and model: messages, tool calls, turns, providers, errors.

`ChatProvider.chat(messages, tools)` follows the OpenAI-compatible chat-completions contract, so any
service that speaks it can drive the agent. This module imports nothing from the other packages.
"""

import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
    reasoning: Optional[str] = None  # the model's private reasoning; only a server may keep it


class ProviderError(RuntimeError):
    """The model API failed or returned something outside the contract."""


class QuotaError(ProviderError):
    """The server accepted the key but it has no tokens left (HTTP 429)."""


class AuthError(ProviderError):
    """The server rejected the API key (HTTP 401 or 403)."""


def http_failure(exc: urllib.error.HTTPError) -> ProviderError:
    if exc.code == 429:
        return QuotaError("token quota of this API key is used up")
    if exc.code in (401, 403):
        return AuthError(f"API key rejected by the server (HTTP {exc.code})")
    return ProviderError(f"model API returned HTTP {exc.code}")


class ChatProvider(ABC):
    name = "provider"

    @abstractmethod
    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        """Return the next assistant turn: text, or tool calls to execute."""

    def stream(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        """Yield {"type": "text", "delta": str} events, then one {"type": "turn", "turn": ...}.
        A reasoning model may also yield {"type": "reasoning", "delta": str}.

        Providers without native streaming fall back to a single text event.
        """
        turn = self.chat(messages, tools)
        if turn.content:
            yield {"type": "text", "delta": turn.content}
        yield {"type": "turn", "turn": turn}


_WIRE_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")


def wire_messages(messages: List[Message], keep: Tuple[str, ...] = ()) -> List[Message]:
    """What the model API receives: internal bookkeeping keys and superseded drafts removed.
    `keep` names extra keys to pass on (the policy server needs the `harness` mark)."""
    return [
        {k: m[k] for k in (*_WIRE_KEYS, *keep) if k in m}
        for m in messages
        if not m.get("superseded") and not m.get("ui_only")
    ]
