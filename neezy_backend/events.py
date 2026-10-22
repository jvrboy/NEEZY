"""Thread-safe bounded event primitives for streaming market updates.

Payload contracts (roadmap #15): every core event kind has an explicit
payload type, listed in :data:`PAYLOAD_CONTRACTS`. ``EventBus`` validates
known kinds when constructed with ``validate_payloads=True`` (see
:func:`debug_bus`), so publisher/subscriber drift fails loudly during
development instead of surfacing as a silent UI bug. Validation is off by
default to keep the hot path unchanged in production.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import RLock
from typing import Any, TypedDict


class ClosedPayload(TypedDict):
    """Payload of the ``closed`` event: the WebSocket close frame."""

    code: int | None
    reason: str | None


# Runtime payload contract per core event kind. App-level kinds (for
# example the tools page's "backtest" events) are not listed here and are
# therefore never rejected by validation.
PAYLOAD_CONTRACTS: dict[str, tuple[type, ...]] = {
    # Parsed JSON message from the Deriv API (always an object in practice).
    "message": (dict,),
    # Human-readable failure description.
    "error": (str,),
    # Connection established / loop exited: no payload.
    "connected": (type(None),),
    "stopped": (type(None),),
    # Seconds until the next reconnect attempt.
    "reconnecting": (int, float),
    # Close frame contents (see ClosedPayload).
    "closed": (dict, Mapping),
}

KNOWN_EVENT_KINDS = frozenset(PAYLOAD_CONTRACTS)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Immutable event with an aware UTC creation timestamp."""

    kind: str
    payload: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Fan-out bus with bounded subscriber queues and thread-safe lifecycle."""

    def __init__(
        self,
        subscriber_queue_size: int = 1000,
        *,
        validate_payloads: bool = False,
    ) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        self._queue_size = subscriber_queue_size
        self._validate = validate_payloads
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
        if self._validate and kind in PAYLOAD_CONTRACTS:
            allowed = PAYLOAD_CONTRACTS[kind]
            if not isinstance(payload, allowed):
                expected = " or ".join(t.__name__ for t in allowed)
                raise TypeError(
                    f"event {kind!r} payload must be {expected}, "
                    f"got {type(payload).__name__}"
                )
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


def debug_bus(subscriber_queue_size: int = 1000) -> EventBus:
    """An :class:`EventBus` with payload validation enabled.

    Use in tests and development runs to catch payload-shape drift between
    publishers and subscribers at the moment it happens.
    """
    return EventBus(subscriber_queue_size, validate_payloads=True)
