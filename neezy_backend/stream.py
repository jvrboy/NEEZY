"""Reconnectable Deriv WebSocket service with explicit lifecycle events."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Mapping
from typing import Any

import websocket

from .events import EventBus


class DerivStreamClient:
    """One background connection, reconnecting until stopped by the owner."""

    def __init__(
        self,
        url: str,
        bus: EventBus,
        reconnect_seconds: float = 2.0,
        max_reconnect_seconds: float = 30.0,
    ) -> None:
        if reconnect_seconds <= 0 or max_reconnect_seconds < reconnect_seconds:
            raise ValueError("reconnect intervals must be positive and max >= initial")
        self.url = url
        self.bus = bus
        self.reconnect_seconds = reconnect_seconds
        self.max_reconnect_seconds = max_reconnect_seconds
        self.ws: websocket.WebSocketApp | None = None
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def running(self) -> bool:
        return bool(
            self._thread and self._thread.is_alive() and not self._stop.is_set()
        )

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="neezy-deriv-stream", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        delay = self.reconnect_seconds
        while not self._stop.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=lambda _: self._on_open(),
                    on_message=lambda _, message: self._on_message(message),
                    on_error=lambda _, error: self.bus.publish("error", str(error)),
                    on_close=lambda _, code, reason: self._on_close(code, reason),
                )
                if self._stop.is_set():
                    self.ws.close()
                    break
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except (
                OSError,
                websocket.WebSocketException,
                RuntimeError,
                ValueError,
            ) as error:
                self.bus.publish("error", f"WebSocket loop failed: {error}")
            finally:
                was_connected = self._connected.is_set()
                self._connected.clear()
                self.ws = None
            if was_connected:
                delay = self.reconnect_seconds
            if not self._stop.is_set():
                self.bus.publish("reconnecting", delay)
                self._stop.wait(delay)
                delay = min(delay * 2, self.max_reconnect_seconds)
        self.bus.publish("stopped")

    def _on_open(self) -> None:
        self._connected.set()
        self.bus.publish("connected")

    def _on_message(self, message: str) -> None:
        try:
            self.bus.publish("message", json.loads(message))
        except (json.JSONDecodeError, TypeError):
            self.bus.publish("error", "Received malformed WebSocket payload")

    def _on_close(self, code: int | None, reason: str | None) -> None:
        self._connected.clear()
        self.bus.publish("closed", {"code": code, "reason": reason})

    def send(self, payload: dict[str, Any]) -> bool:
        if not self.connected or self.ws is None:
            return False
        try:
            with self._send_lock:
                self.ws.send(json.dumps(payload, separators=(",", ":")))
            return True
        except (OSError, websocket.WebSocketException, RuntimeError) as error:
            self.bus.publish("error", f"Send failed: {error}")
            return False

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._connected.clear()
        ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except (OSError, websocket.WebSocketException):
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))


def parse_candle(
    candle: Mapping[str, Any], time_key: str = "epoch"
) -> tuple[int, float, float, float, float]:
    """Convert a Deriv candle/ohlc payload into a validated OHLC five-tuple."""
    timestamp = int(candle[time_key])
    values = [float(candle[name]) for name in ("open", "high", "low", "close")]
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("OHLC prices must be finite positive numbers")
    open_, high, low, close = values
    if high < max(open_, close) or low > min(open_, close) or high < low:
        raise ValueError("inconsistent OHLC values")
    return (timestamp, open_, high, low, close)


def parse_history_response(
    message: Mapping[str, Any],
) -> list[tuple[int, float, float, float, float]]:
    """Validate a ``ticks_history`` candles response, raising on API errors."""
    error = message.get("error")
    if error:
        detail = error.get("message") if isinstance(error, Mapping) else error
        raise RuntimeError(f"Deriv API error: {detail}")
    rows = message.get("candles")
    if not isinstance(rows, list):
        raise ValueError("response did not contain a candles list")
    candles = [parse_candle(row) for row in rows]
    return sorted({row[0]: row for row in candles}.values())


def fetch_candles(
    symbol: str,
    granularity: int,
    count: int = 1000,
    *,
    url: str,
    timeout: float = 20.0,
) -> list[tuple[int, float, float, float, float]]:
    """One-shot (non-streaming) request for historical candles, oldest first."""
    if not 1 <= count <= 5000:
        raise ValueError("count must be between 1 and 5000 (Deriv API limit)")
    request = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": granularity,
        "style": "candles",
    }
    try:
        connection = websocket.create_connection(url, timeout=timeout)
    except websocket.WebSocketException as error:
        raise ConnectionError(
            f"Could not reach market data service: {error}"
        ) from error
    try:
        connection.send(json.dumps(request))
        while True:
            message = json.loads(connection.recv())
            if message.get("msg_type") in {"candles", "ticks_history"} or message.get(
                "error"
            ):
                return parse_history_response(message)
    except websocket.WebSocketException as error:
        raise ConnectionError(f"Market data request failed: {error}") from error
    finally:
        connection.close()
