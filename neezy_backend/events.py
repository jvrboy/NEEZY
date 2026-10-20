"""Thread-safe bounded event primitives for streaming market updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import RLock
from typing import Any


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Immutable event with an aware UTC creation timestamp."""

    kind: str
    payload: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Fan-out bus with bounded subscriber queues and thread-safe lifecycle."""

    def __init__(self, subscriber_queue_size: int = 1000) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        self._queue_size = subscriber_queue_size
        self._subscribers: set[Queue[StreamEvent]] = set()
        self._lock = RLock()

    def subscribe(self) -> Queue[StreamEvent]:
        channel: Queue[StreamEvent] = Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: Queue[StreamEvent]) -> None:
        with self._lock:
            self._subscribers.discard(channel)

    def publish(self, kind: str, payload: Any = None) -> StreamEvent:
        event = StreamEvent(kind, payload)
        with self._lock:
            subscribers = tuple(self._subscribers)
        for channel in subscribers:
            try:
                channel.put_nowait(event)
            except Full:
                # Prefer the newest market state when a consumer is behind.
                try:
                    channel.get_nowait()
                except Empty:
                    pass
                try:
                    channel.put_nowait(event)
                except Full:
                    pass
        return event

    @staticmethod
    def drain(channel: Queue[StreamEvent], limit: int = 100) -> list[StreamEvent]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        events: list[StreamEvent] = []
        for _ in range(limit):
            try:
                events.append(channel.get_nowait())
            except Empty:
                break
        return events
