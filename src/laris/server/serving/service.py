"""The state a P1 server needs: backend, authenticator, meter, gateway and admin ports."""

from typing import Any, Callable, Dict, List, Optional

from laris.protocol import ChatProvider
from laris.protocol.openai import completion_response, embeddings_response, stream_chunks, texts_of
from laris.server.serving.auth import KeyRing, StaticAuthenticator
from laris.server.serving.ports import (
    ACCOUNT,
    CHAT,
    EMBED,
    HELP,
    MODELS,
    WORKFLOWS,
    Authenticator,
    Principal,
    UsageMeter,
)


class ModelService:
    def __init__(
        self,
        backend: ChatProvider,
        model_name: str,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        keys: Optional[KeyRing] = None,
        gateway: Any = None,
        auth: Optional[Authenticator] = None,
        meter: Optional[UsageMeter] = None,
        admin: Any = None,
        chars_per_token: float = 4.0,
        reasoning_http: bool = False,
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.embedder = embedder
        # Policy gateway (duck-typed: stream(body), workflows(), help_text()). With a gateway the
        # bare model endpoint is closed: every request goes through the system policy.
        self.gateway = gateway
        self.keys = keys  # None = no authentication (tests only; `laris model serve` refuses it)
        # Authenticator: database keys with roles and limits; a plain KeyRing becomes role `user`.
        self.auth = auth or (
            StaticAuthenticator(keys, (CHAT, EMBED, MODELS, WORKFLOWS, HELP, ACCOUNT))
            if keys is not None
            else None
        )
        self.meter = meter
        self.admin = admin  # duck-typed: usage_summary(), reasoning_list(limit), reasoning_get(id)
        self.chars_per_token = chars_per_token
        self.reasoning_http = reasoning_http

    def estimate_tokens(self, text_chars: int) -> int:
        return int(text_chars / self.chars_per_token) + 1

    def bill(self, principal: Optional[Principal], prompt_chars: int, completion_chars: int,
             kind: str) -> None:  # fmt: skip
        if self.meter is not None and principal is not None:
            self.meter.record(
                principal,
                {
                    "kind": kind,
                    "prompt_tokens": self.estimate_tokens(prompt_chars),
                    "completion_tokens": self.estimate_tokens(completion_chars),
                },
            )

    def models(self) -> Dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": self.model_name, "object": "model", "owned_by": "laris"}],
        }

    def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        turn = self.backend.chat(list(body.get("messages") or []), list(body.get("tools") or []))
        return completion_response(turn, self.model_name)

    def stream_chunks(self, body: Dict[str, Any]) -> Any:
        """Yield OpenAI `chat.completion.chunk` dicts for the request."""
        events = self.backend.stream(
            list(body.get("messages") or []), list(body.get("tools") or [])
        )
        return stream_chunks(events, self.model_name)

    def embeddings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.embedder is None:
            raise ValueError("no embedding model loaded (start with --checkpoint)")
        vectors = self.embedder(texts_of(body.get("input", [])))
        return embeddings_response(vectors, self.model_name)
