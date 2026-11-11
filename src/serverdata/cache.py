"""A small thread-safe TTL + LRU cache."""

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional, Tuple


class TTLCache:
    def __init__(
        self, ttl_s: float, max_entries: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_s, self.max_entries, self._clock = ttl_s, max_entries, clock
        self._items: "OrderedDict[Any, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            entry = self._items.get(key)
            if entry is None or entry[0] < self._clock():
                self._items.pop(key, None)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return entry[1]

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_s, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def invalidate(self, key: Any = None) -> None:
        with self._lock:
            if key is None:
                self._items.clear()
            else:
                self._items.pop(key, None)
