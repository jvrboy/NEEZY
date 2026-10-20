"""Small in-memory TTL/LRU cache for AI answers.

Identical questions about an unchanged market snapshot should not burn provider
quota. Keys are SHA-256 hashes of everything that influences the answer.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any


class AnswerCache:
    """Thread-safe cache with a size cap and per-entry time-to-live."""

    def __init__(
        self,
        max_items: int = 128,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(
        provider: str,
        model: str | None,
        messages: Sequence[Any],
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        blob = json.dumps(
            [provider, model, messages, system_prompt, temperature],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self._misses += 1
                return None
            stored_at, value = entry
            if self._clock() - stored_at > self.ttl_seconds:
                del self._items[key]
                self._misses += 1
                return None
            self._items.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._items),
                "hits": self._hits,
                "misses": self._misses,
            }
