"""P2 wire format (OpenAI-compatible chat completions and embeddings), built from chat types.

Used by the model service to answer, by the server's reference service, and by tests that check
real responses against the schemas.
"""

import json
import time
import uuid
from typing import Any, Dict, Iterable, Iterator, List

from laris.protocol.types import AssistantTurn


def message_payload(turn: AssistantTurn) -> Dict[str, Any]:
    message: Dict[str, Any] = {"role": "assistant", "content": turn.content}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in turn.tool_calls
        ]
    return message


def completion_response(turn: AssistantTurn, model: str) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message_payload(turn),
                "finish_reason": "tool_calls" if turn.tool_calls else "stop",
            }
        ],
    }


def stream_chunks(events: Iterable[Dict[str, Any]], model: str) -> Iterator[Dict[str, Any]]:
    """`chat.completion.chunk` dicts for provider events (`text`, `reasoning`, then `turn`)."""
    base = {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion.chunk",
            "model": model}  # fmt: skip
    for event in events:
        kind = event["type"]
        if kind == "text":
            yield {**base, "choices": [{"index": 0, "delta": {"content": event["delta"]}}]}
        elif kind == "reasoning":
            delta = {"reasoning_content": event["delta"]}
            yield {**base, "choices": [{"index": 0, "delta": delta}]}
        elif kind == "turn":
            turn: AssistantTurn = event["turn"]
            if turn.tool_calls:
                calls = [
                    {
                        "index": i,
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for i, c in enumerate(turn.tool_calls)
                ]
                yield {**base, "choices": [{"index": 0, "delta": {"tool_calls": calls}}]}
            reason = "tool_calls" if turn.tool_calls else "stop"
            yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def embeddings_response(vectors: List[List[float]], model: str) -> Dict[str, Any]:
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
        ],
    }


def texts_of(raw: Any) -> List[str]:
    """The `input` of an embeddings request as a list of strings."""
    return [raw] if isinstance(raw, str) else [str(t) for t in raw]
