"""The shared contract of the blocks: chat types, SSE framing, wire schemas, protocol version.

Imports nothing from other LARIS packages (ADR-019, D10 to D12).
"""

from laris.protocol.chunk import Chunk
from laris.protocol.keycheck import check_key
from laris.protocol.schemas import (
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatRequest,
    EmbedRequest,
    EmbedResponse,
    LarisMeta,
    ModelChatRequest,
    StreamError,
    Usage,
)
from laris.protocol.sse import DONE, decode_events, encode_done, encode_event
from laris.protocol.types import (
    AssistantTurn,
    AuthError,
    ChatProvider,
    Message,
    ProviderError,
    QuotaError,
    ToolCall,
    http_failure,
    wire_messages,
)
from laris.protocol.version import PROTOCOL_HEADER, PROTOCOL_VERSION

__all__ = [
    "AssistantTurn",
    "AuthError",
    "ChatCompletionChunk",
    "ChatCompletionResponse",
    "ChatProvider",
    "ChatRequest",
    "Chunk",
    "DONE",
    "EmbedRequest",
    "EmbedResponse",
    "LarisMeta",
    "Message",
    "ModelChatRequest",
    "PROTOCOL_HEADER",
    "PROTOCOL_VERSION",
    "ProviderError",
    "QuotaError",
    "StreamError",
    "ToolCall",
    "Usage",
    "check_key",
    "decode_events",
    "encode_done",
    "encode_event",
    "http_failure",
    "wire_messages",
]
