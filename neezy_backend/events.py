"""Thread-safe event primitives for streaming market updates."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    payload: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Small fan-out bus: producers publish once, consumers poll independently."""

    def __init__(self) -> None:
        self._subscribers: list[Queue[StreamEvent]] = []

    def subscribe(self) -> Queue[StreamEvent]:
        channel: Queue[StreamEvent] = Queue()
        self._subscribers.append(channel)
        return channel

    def publish(self, kind: str, payload: Any = None) -> None:
        event = StreamEvent(kind, payload)
        for channel in tuple(self._subscribers):
            channel.put(event)

    @staticmethod
    def drain(channel: Queue[StreamEvent], limit: int = 100) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for _ in range(limit):
            try:
                events.append(channel.get_nowait())
            except Empty:
                break
        return events
