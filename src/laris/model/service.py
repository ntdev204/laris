"""The model service core: what answers P2 requests. It knows nothing of keys, users or policy and
stores nothing. A backend is any `ChatProvider`; the default is the scripted placeholder planner.

With a `GpuQueue` every call that touches weights is queued and runs with its model resident in
VRAM (`chat` for the backend, `embed` for the encoder); without one calls run directly (tests).
"""

from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from laris.model.gpu_queue import GpuQueue, ModelSpec
from laris.protocol import ChatProvider
from laris.protocol.openai import completion_response, embeddings_response, stream_chunks, texts_of

CHAT, EMBED = "chat", "embed"


class Encoder:
    """The sentence encoder behind `/v1/embeddings`; its weights load and release on demand."""

    def __init__(self, checkpoint: str, tokenizer_model: str, device: str = "") -> None:
        self.checkpoint, self.tokenizer_model, self.device = checkpoint, tokenizer_model, device
        self._predictor: Any = None

    def load(self) -> None:
        if self._predictor is not None:
            return
        from laris.model.inference.loader import load_encoder
        from laris.model.inference.predictor import LanguageEncoderPredictor

        encoder = load_encoder(
            Path(self.checkpoint), Path(self.tokenizer_model), device=self.device or None
        )
        self._predictor = LanguageEncoderPredictor(encoder)

    def unload(self) -> None:
        self._predictor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def __call__(self, texts: List[str]) -> List[List[float]]:
        self.load()
        return [[float(x) for x in row] for row in self._predictor.embed(texts)]


Embedder = Callable[[List[str]], List[List[float]]]


def build_embedder(checkpoint: str, tokenizer_model: str, device: str = "") -> Optional[Encoder]:
    """The encoder behind `/v1/embeddings`, or None when no checkpoint is configured."""
    if not (checkpoint and tokenizer_model):
        return None
    return Encoder(checkpoint, tokenizer_model, device)


def build_queue(backend: ChatProvider, embedder: Optional[Embedder], cfg: Any) -> GpuQueue:
    """The queue for this service from the `model_service` configuration."""
    models = {
        CHAT: ModelSpec(
            CHAT,
            cfg.chat_vram_bytes,
            getattr(backend, "load", lambda: None),
            getattr(backend, "unload", lambda: None),
        )
    }
    if embedder is not None:
        models[EMBED] = ModelSpec(
            EMBED,
            cfg.embed_vram_bytes,
            getattr(embedder, "load", lambda: None),
            getattr(embedder, "unload", lambda: None),
        )
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
    ) -> None:
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
            raise ValueError("no embedding model loaded (set model_service.checkpoint)")
        texts, embedder = texts_of(body.get("input", [])), self.embedder

        def run() -> Dict[str, Any]:
            return embeddings_response(embedder(texts), self.model_name)

        return run() if self.queue is None else self.queue.call(EMBED, run)
