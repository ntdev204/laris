"""Keeps the model's reasoning away from the client.

Some models write their reasoning inline between tags (`<think>...</think>`); others send it in a
separate field. Either way it is diverted here, stored for the operator, and never streamed.
"""

from typing import List, Sequence, Tuple


class ThinkSplitter:
    """Splits a text stream into visible text and reasoning, even when a tag spans two chunks."""

    def __init__(self, tags: Sequence[Sequence[str]]) -> None:
        self.tags: List[Tuple[str, str]] = [(t[0], t[1]) for t in tags if len(t) == 2 and t[0]]
        self._buffer = ""
        self._closing = ""  # the end tag we are waiting for while inside reasoning
        self.reasoning: List[str] = []

    def _keep(self, text: str, tags: Sequence[str]) -> int:
        """Length of a tail that could still turn into one of `tags`: held back, not emitted."""
        longest = 0
        for tag in tags:
            for size in range(min(len(tag) - 1, len(text)), 0, -1):
                if text.endswith(tag[:size]):
                    longest = max(longest, size)
                    break
        return longest

    def feed(self, delta: str) -> str:
        """Returns the visible part of this chunk."""
        self._buffer += delta
        visible: List[str] = []
        while self._buffer:
            if self._closing:
                end = self._buffer.find(self._closing)
                if end < 0:
                    hold = self._keep(self._buffer, [self._closing])
                    cut = len(self._buffer) - hold
                    self.reasoning.append(self._buffer[:cut])
                    self._buffer = self._buffer[cut:]
                    break
                self.reasoning.append(self._buffer[:end])
                self._buffer = self._buffer[end + len(self._closing) :]
                self._closing = ""
                continue
            hits = [(self._buffer.find(o), o, c) for o, c in self.tags if o in self._buffer]
            if hits:
                at, opener, closer = min(hits)
                visible.append(self._buffer[:at])
                self._buffer = self._buffer[at + len(opener) :]
                self._closing = closer
                continue
            hold = self._keep(self._buffer, [o for o, _ in self.tags])
            cut = len(self._buffer) - hold
            visible.append(self._buffer[:cut])
            self._buffer = self._buffer[cut:]
            break
        return "".join(visible)

    def finish(self) -> str:
        """Flush at the end of the stream: unfinished reasoning stays reasoning."""
        rest, self._buffer = self._buffer, ""
        if self._closing:
            self.reasoning.append(rest)
            return ""
        return rest
