"""Reconnectable Deriv websocket service with explicit lifecycle events."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import websocket

from .events import EventBus


class DerivStreamClient:
    def __init__(self, url: str, bus: EventBus, reconnect_seconds: float = 5.0) -> None:
        self.url = url
        self.bus = bus
        self.reconnect_seconds = reconnect_seconds
        self.ws: websocket.WebSocketApp | None = None
        self.connected = False
        self.running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, name="neezy-deriv-stream", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self.running:
            self.ws = websocket.WebSocketApp(
                self.url,
                on_open=lambda _: self._on_open(),
                on_message=lambda _, message: self._on_message(message),
                on_error=lambda _, error: self.bus.publish("error", str(error)),
                on_close=lambda _, code, reason: self._on_close(code, reason),
            )
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            self.connected = False
            if self.running:
                self.bus.publish("reconnecting", self.reconnect_seconds)
                time.sleep(self.reconnect_seconds)

    def _on_open(self) -> None:
        self.connected = True
        self.bus.publish("connected")

    def _on_message(self, message: str) -> None:
        try:
            self.bus.publish("message", json.loads(message))
        except json.JSONDecodeError:
            self.bus.publish("error", "Received malformed websocket payload")

    def _on_close(self, code: int | None, reason: str | None) -> None:
        self.connected = False
        self.bus.publish("closed", {"code": code, "reason": reason})

    def send(self, payload: dict[str, Any]) -> bool:
        if not self.connected or self.ws is None:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except (OSError, websocket.WebSocketException) as error:
            self.bus.publish("error", str(error))
            return False

    def stop(self) -> None:
        self.running = False
        if self.ws is not None:
            self.ws.close()
