"""Resilience helpers for flaky network providers."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable


def backoff_delay(
    attempt: int,
    base: float = 0.5,
    cap: float = 30.0,
    jitter: float = 0.2,
    rng: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff in seconds with symmetric jitter, never above ``cap``."""
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    delay = min(cap, base * (2 ** min(attempt, 30)))
    delay *= 1.0 + jitter * (rng() * 2.0 - 1.0)
    return max(0.0, min(cap, delay))


class CircuitBreaker:
    """Stop calling a failing provider for a cool-down, then allow one trial."""

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if reset_seconds <= 0:
            raise ValueError("reset_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None

    def _state_locked(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.reset_seconds:
            return "half_open"
        return "open"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    def allow(self) -> bool:
        """Whether a call may be attempted right now."""
        with self._lock:
            return self._state_locked() != "open"

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._opened_at is not None or self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
