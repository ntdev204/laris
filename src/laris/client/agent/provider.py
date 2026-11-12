"""Model providers: the seam where the future LARIS core model plugs in through an API.

`ChatProvider.chat(messages, tools)` follows the OpenAI-compatible chat-completions contract
(`/v1/chat/completions` with `tools`), so any service that speaks it can drive the agent.
`OfflinePlanner` (now in `laris.shared.offline`) is re-exported here for the existing importers.
"""

import copy
from typing import Any, Dict, List, Optional

from laris.protocol import (
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    AssistantTurn,
    AuthError,
    ChatProvider,
    Message,
    ProviderError,
    QuotaError,
    ToolCall,
    check_key,
    http_failure,
    wire_messages,
)
from laris.shared.http_provider import HttpChatProvider
from laris.shared.offline import OfflinePlanner

__all__ = [
    "AssistantTurn",
    "AuthError",
    "ChatProvider",
    "HttpChatProvider",
    "Message",
    "OfflinePlanner",
    "ProviderError",
    "QuotaError",
    "ToolCall",
    "check_key",
    "wire_messages",
]

_http_failure = http_failure  # kept for the modules that import the old name


class PolicyServerProvider(HttpChatProvider):
    """Client for the policy server: it sends the conversation and the user's own layers; the
    server adds the system prompt, runs the brain and guards the reply. Streaming only."""

    name = "policy-server"
    extra_headers = {PROTOCOL_HEADER: PROTOCOL_VERSION}

    def __init__(self, *args: Any, kind: str = "turn", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.url = self.url.removesuffix("/chat/completions") + "/laris/chat"
        self.kind = kind

    def summarizer(self) -> "PolicyServerProvider":
        clone = copy.copy(self)
        clone.kind = "summarize"
        return clone

    def _body(self, messages: List[Message], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        body = super()._body(messages, tools)
        # our own server also needs to know which user messages are harness notes, not the user
        wire = wire_messages(messages, keep=("harness",))
        body["messages"] = [m for m in wire if m.get("role") != "system"]
        meta: Dict[str, Any] = {"kind": self.kind}
        system = messages[0] if messages and messages[0].get("role") == "system" else {}
        meta.update(system.get("laris") or {})
        body["laris"] = meta
        return body

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        turn: Optional[AssistantTurn] = None
        for event in self.stream(messages, tools):
            if event["type"] == "turn":
                turn = event["turn"]
        if turn is None:
            raise ProviderError("policy server returned no turn")
        return turn
