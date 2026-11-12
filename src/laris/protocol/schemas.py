"""Pydantic schemas of the two wire protocols.

P1 (client to server, public): `POST /v1/laris/chat` carries messages, the client's tool schemas
and a `laris` block. P2 (server to model, internal): OpenAI-compatible chat completions and
embeddings.
Extra fields are allowed so a newer peer does not break an older one inside one protocol version.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Wire(BaseModel):
    model_config = ConfigDict(extra="allow")


class InstructionLayer(_Wire):
    label: str = "client"
    text: str = ""


class Layers(_Wire):
    instructions: List[InstructionLayer] = Field(default_factory=list)
    skills_index: str = ""
    memory: str = ""
    extra: str = ""


class WorkflowRequest(_Wire):
    name: str
    request: str = ""


class LarisMeta(_Wire):
    kind: Literal["turn", "summarize"] = "turn"
    session_id: Optional[str] = None
    task: str = ""
    focus: str = ""
    workflow: Optional[WorkflowRequest] = None
    layers: Layers = Field(default_factory=Layers)


class ChatRequest(_Wire):
    """P1 chat request."""

    messages: List[Dict[str, Any]]
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    stream: bool = True
    laris: LarisMeta = Field(default_factory=LarisMeta)


class ModelChatRequest(_Wire):
    """P2 chat-completions request."""

    model: str = ""
    messages: List[Dict[str, Any]]
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.0
    stream: bool = False


class EmbedRequest(_Wire):
    """P1 `POST /v1/laris/embed` and P2 `POST /v1/embeddings`."""

    input: Union[str, List[str]]
    model: str = ""


class EmbeddingItem(_Wire):
    object: Literal["embedding"] = "embedding"
    index: int
    embedding: List[float]


class EmbedResponse(_Wire):
    object: Literal["list"] = "list"
    model: str = ""
    data: List[EmbeddingItem]


class Usage(_Wire):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolCallFunction(_Wire):
    name: str = ""
    arguments: str = ""


class ToolCallPayload(_Wire):
    index: Optional[int] = None
    id: Optional[str] = None
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatMessagePayload(_Wire):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)


class ChatChoice(_Wire):
    index: int
    message: ChatMessagePayload
    finish_reason: Literal["stop", "tool_calls"]


class ChatCompletionResponse(_Wire):
    """P2 non-streaming chat completion."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]


class ChunkDelta(_Wire):
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)


class ChunkChoice(_Wire):
    index: int
    delta: ChunkDelta
    finish_reason: Optional[Literal["stop", "tool_calls"]] = None


class ChatCompletionChunk(_Wire):
    """One P2 streaming event."""

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    model: str
    choices: List[ChunkChoice] = Field(default_factory=list)
    usage: Optional[Usage] = None


class StreamError(_Wire):
    """The event sent when a stream fails after it has started; `[DONE]` follows it."""

    error: Dict[str, Any]
