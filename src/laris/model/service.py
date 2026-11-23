"""The model service core: what answers P2 requests. It knows nothing of keys, users or policy and
stores nothing. A backend is any `ChatProvider`; the default is the scripted placeholder planner.

With a `GpuQueue` every call that touches weights is queued and runs with its model resident in
VRAM (`chat` for the backend); without one calls run directly (tests). No embedding model ships
(T233 removed the self-trained encoder): `/v1/embeddings` answers an error unless an `Embedder`
is handed to `ModelService`, and an embedder is never queued.
"""

from typing import Any, Callable, Dict, Iterator, List, Optional

from laris.model.gpu_queue import GpuQueue, ModelSpec
from laris.model.tools import ToolBox
from laris.protocol import ChatProvider
from laris.protocol.openai import completion_response, embeddings_response, stream_chunks, texts_of

CHAT = "chat"

Embedder = Callable[[List[str]], List[List[float]]]


def build_queue(backend: ChatProvider, cfg: Any) -> GpuQueue:
    """The queue for this service from the `model_service` configuration. A backend whose weights
    live in an inference server declares the server's reservation (`vram_bytes`); the queue counts
    the larger of it and `chat_vram_bytes`, so the budget accounts for the server's share."""
    size = max(cfg.chat_vram_bytes, int(getattr(backend, "vram_bytes", 0) or 0))
    models = {
        CHAT: ModelSpec(
            CHAT,
            size,
            getattr(backend, "load", lambda: None),
            getattr(backend, "unload", lambda: None),
        )
    }
    return GpuQueue(
        models,
        cfg.vram_budget_bytes,
        cfg.vram_margin_bytes,
        cfg.gpu_workers,
        cfg.queue_max_waiting,
        cfg.queue_wait_timeout_s,
    )


class ModelService:
    def __init__(
        self,
        backend: ChatProvider,
        model_name: str,
        embedder: Optional[Embedder] = None,
        queue: Optional[GpuQueue] = None,
        tools: Optional[ToolBox] = None,
    ) -> None:
        self.tools = tools
        self.backend = backend
        self.model_name = model_name
        self.embedder = embedder
        self.queue = queue

    def models(self) -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model", "owned_by": "laris"}],
        }

    def health(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "status": "ok",
            "model": self.model_name,
            "backend": self.backend.name,
            "embeddings": self.embedder is not None,
            "tools": 0 if self.tools is None else len(self.tools.schemas()),
        }
        if self.queue is not None:
            info["gpu"] = self.queue.status()
        return info

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        messages, tools = list(body.get("messages") or []), list(body.get("tools") or [])

        def run() -> Dict[str, Any]:
            return completion_response(self.backend.chat(messages, tools), self.model_name)

        return run() if self.queue is None else self.queue.call(CHAT, run)

    def stream(self, body: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        messages, tools = list(body.get("messages") or []), list(body.get("tools") or [])

        def chunks() -> Iterator[Dict[str, Any]]:
            return stream_chunks(self.backend.stream(messages, tools), self.model_name)

        return chunks() if self.queue is None else self.queue.stream(CHAT, chunks)

    def embed(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.embedder is None:
            raise ValueError("no embedding model is configured")
        texts, embedder = texts_of(body.get("input", [])), self.embedder

        return embeddings_response(embedder(texts), self.model_name)
