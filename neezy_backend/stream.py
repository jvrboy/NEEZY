"""Reconnectable Deriv WebSocket service with explicit lifecycle events."""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Mapping, Sequence
from typing import Any

import websocket

from .events import EventBus
from .markets import ws_urls

# Cloudflare fronts Deriv's hosts and rejects some networks with a bare HTTP
# status plus a full header dump. Browsers are treated more kindly than bare
# clients, so every handshake advertises a normal browser identity.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Origin": "https://app.deriv.com",
}

_HANDSHAKE_STATUS = re.compile(r"Handshake status\s+(\d{3})")

_STATUS_HINTS: dict[int, str] = {
    401: "Deriv rejected the app id (HTTP 401)",
    403: "Deriv refused the connection (HTTP 403)",
    429: "Deriv rate-limited this network (HTTP 429)",
    520: "Deriv's edge could not reach its origin (HTTP 520)",
    521: "Deriv's origin refused the connection (HTTP 521)",
    522: "Deriv's origin timed out (HTTP 522)",
    525: "Deriv's TLS handshake failed (HTTP 525)",
}


def describe_connection_error(error: object) -> str:
    """Collapse a raw WebSocket/Cloudflare failure into one readable sentence."""
    text = str(error)
    match = _HANDSHAKE_STATUS.search(text)
    if match:
        status = int(match.group(1))
        hint = _STATUS_HINTS.get(
            status, f"WebSocket handshake failed with HTTP {status}"
        )
        if status == 520:
            return f"{hint}; this Deriv host is down or refused the request."
        return f"{hint}; this endpoint is unavailable from your network."
    lowered = text.lower()
    if "getaddrinfo" in lowered or "name or service not known" in lowered:
        return "Could not resolve the market data host; check your connection or DNS."
    if "timed out" in lowered or "timeout" in lowered:
        return "Timed out reaching the market data service; check firewall or VPN."
    if "connection refused" in lowered:
        return (
            "The market data host refused the connection; a proxy may be blocking it."
        )
    if "ssl" in lowered or "tls" in lowered:
        return (
            "The TLS handshake was closed early; antivirus, a firewall, or a proxy "
            "may be intercepting HTTPS traffic."
        )
    return text


class DerivStreamClient:
    """One background connection, reconnecting until stopped by the owner."""

    def __init__(
        self,
        url: str | Sequence[str],
        bus: EventBus,
        reconnect_seconds: float = 2.0,
        max_reconnect_seconds: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if reconnect_seconds <= 0 or max_reconnect_seconds < reconnect_seconds:
            raise ValueError("reconnect intervals must be positive and max >= initial")
        candidates = (url,) if isinstance(url, str) else tuple(url)
        if not candidates:
            raise ValueError("at least one WebSocket URL is required")
        self.urls = candidates
        self.url = candidates[0]
        self.headers = dict(BROWSER_HEADERS if headers is None else headers)
        self.bus = bus
        self.reconnect_seconds = reconnect_seconds
        self.max_reconnect_seconds = max_reconnect_seconds
        self.ws: websocket.WebSocketApp | None = None
        self._candidate = 0
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
            self.url = self.urls[self._candidate % len(self.urls)]
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    header=self.headers,
                    on_open=lambda _: self._on_open(),
                    on_message=lambda _, message: self._on_message(message),
                    on_error=lambda _, error: self.bus.publish(
                        "error", describe_connection_error(error)
                    ),
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
                self.bus.publish(
                    "error",
                    f"WebSocket loop failed: {describe_connection_error(error)}",
                )
            finally:
                was_connected = self._connected.is_set()
                self._connected.clear()
                self.ws = None
            if was_connected:
                delay = self.reconnect_seconds
            elif len(self.urls) > 1 and not self._stop.is_set():
                # This host never accepted a session, so try the next one first.
                self._candidate += 1
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


def _request_candles(
    url: str,
    request: Mapping[str, Any],
    timeout: float,
) -> list[tuple[int, float, float, float, float]]:
    """Fetch candles from one endpoint, raising ConnectionError on failure."""
    try:
        connection = websocket.create_connection(
            url, timeout=timeout, header=BROWSER_HEADERS
        )
    except (OSError, websocket.WebSocketException) as error:
        raise ConnectionError(
            f"Could not reach market data service: {describe_connection_error(error)}"
        ) from error
    try:
        connection.send(json.dumps(request))
        while True:
            message = json.loads(connection.recv())
            if message.get("msg_type") in {"candles", "ticks_history"} or message.get(
                "error"
            ):
                return parse_history_response(message)
    except (OSError, websocket.WebSocketException) as error:
        raise ConnectionError(
            f"Market data request failed: {describe_connection_error(error)}"
        ) from error
    finally:
        connection.close()


def probe_endpoint(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Open one short-lived connection and complete a ping round trip."""
    try:
        connection = websocket.create_connection(
            url, timeout=timeout, header=BROWSER_HEADERS
        )
    except (OSError, websocket.WebSocketException) as error:
        return False, describe_connection_error(error)
    try:
        connection.send(json.dumps({"ping": 1}))
        message = json.loads(connection.recv())
        error = message.get("error")
        if error:
            detail = error.get("message") if isinstance(error, Mapping) else error
            return False, f"Deriv API error: {detail}"
        return True, "ping ok"
    except (
        OSError,
        websocket.WebSocketException,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        return False, describe_connection_error(error)
    finally:
        connection.close()


MAX_HISTORY_COUNT = 5000
Candle = tuple[int, float, float, float, float]


def _candidate_urls(url: str | Sequence[str] | None) -> tuple[str, ...]:
    if isinstance(url, str):
        return (url,)
    return tuple(url) if url else tuple(ws_urls())


def _history_request(
    symbol: str, granularity: int, count: int, end: int | str
) -> dict[str, Any]:
    return {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": end,
        "granularity": granularity,
        "style": "candles",
    }


def _request_with_failover(
    candidates: Sequence[str], request: Mapping[str, Any], timeout: float
) -> tuple[str, list[Candle]]:
    """Try each endpoint in order; return the one that answered with its rows."""
    failures: list[str] = []
    for candidate in candidates:
        try:
            return candidate, _request_candles(candidate, request, timeout)
        except ConnectionError as error:
            failures.append(str(error))
    raise ConnectionError(
        "Could not reach any market data endpoint. " + " ".join(failures)
    )


def fetch_candles(
    symbol: str,
    granularity: int,
    count: int = 1000,
    *,
    url: str | Sequence[str] | None = None,
    timeout: float = 20.0,
) -> list[tuple[int, float, float, float, float]]:
    """Historical candles, oldest first.

    With ``url`` unset, every configured endpoint is tried in order so one
    Cloudflare-rejected host does not take the whole request down. ``url`` may
    be one endpoint or an ordered candidate list.
    """
    if not 1 <= count <= MAX_HISTORY_COUNT:
        raise ValueError("count must be between 1 and 5000 (Deriv API limit)")
    request = _history_request(symbol, granularity, count, "latest")
    _, rows = _request_with_failover(_candidate_urls(url), request, timeout)
    return rows


def fetch_history(
    symbol: str,
    granularity: int,
    total: int,
    *,
    url: str | Sequence[str] | None = None,
    timeout: float = 20.0,
    page_size: int = MAX_HISTORY_COUNT,
    max_pages: int = 200,
) -> list[Candle]:
    """Deep candle history by paging ``ticks_history`` backwards from now.

    Returns up to ``total`` candles, oldest first, de-duplicated by epoch. Each
    page ends just before the oldest candle already held. Paging stops once
    ``total`` is reached, a page adds nothing new (history exhausted), or
    ``max_pages`` is hit. Deriv may retain less than requested; the result then
    holds what exists. The endpoint that answered a page is tried first for the
    next one.
    """
    if total < 1:
        raise ValueError("total must be at least 1")
    if not 1 <= page_size <= MAX_HISTORY_COUNT:
        raise ValueError("page_size must be between 1 and 5000 (Deriv API limit)")
    if granularity < 1:
        raise ValueError("granularity must be a positive number of seconds")
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    candidates = _candidate_urls(url)
    collected: dict[int, Candle] = {}
    end: int | str = "latest"
    for _ in range(max_pages):
        remaining = total - len(collected)
        if remaining <= 0:
            break
        count = min(page_size, remaining)
        request = _history_request(symbol, granularity, count, end)
        endpoint, rows = _request_with_failover(candidates, request, timeout)
        candidates = (endpoint, *(c for c in candidates if c != endpoint))
        fresh = [row for row in rows if row[0] not in collected]
        if not fresh:
            break
        for row in fresh:
            collected[row[0]] = row
        end = min(collected) - 1
    return sorted(collected.values())[-total:]
