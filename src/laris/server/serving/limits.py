"""Bounded concurrency towards the model block: at most N calls in flight, the rest wait."""

import threading
from typing import Any, Dict, Iterator, List

from laris.protocol import AssistantTurn, ChatProvider, Message


class LimitedProvider(ChatProvider):
    """Wraps a provider so that no more than `limit` calls run at the same time. A stream holds its
    slot until it ends or is closed, so a reader that leaves frees it."""

    def __init__(self, inner: ChatProvider, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.inner = inner
        self.name = inner.name
        self._slots = threading.BoundedSemaphore(limit)
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0

    def _enter(self) -> None:
        self._slots.acquire()
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)

    def _leave(self) -> None:
        with self._lock:
            self.in_flight -= 1
        self._slots.release()

    def chat(self, messages: List[Message], tools: List[Dict[str, Any]]) -> AssistantTurn:
        self._enter()
        try:
            return self.inner.chat(messages, tools)
        finally:
            self._leave()

    def stream(
        self, messages: List[Message], tools: List[Dict[str, Any]]
    ) -> Iterator[Dict[str, Any]]:
        self._enter()
        try:
            yield from self.inner.stream(messages, tools)
        finally:
            self._leave()
