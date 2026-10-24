"""Read-only loopback status API for Cloudflare Tunnel and health checks."""

from __future__ import annotations

import copy
import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .storage import _atomic_json_write


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StatusState:
    """Thread-safe status with a bounded, optionally persistent equity series."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        persistence_path: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self._persistence_path = persistence_path
        now = clock().astimezone(timezone.utc).isoformat(timespec="seconds")
        self._data: dict[str, Any] = {
            "schema": 1,
            "service": "neezy-light-executor",
            "status": "starting",
            "started_at": now,
            "heartbeat_utc": now,
            "issues": [],
        }
        self._equity: deque[dict[str, Any]] = deque(maxlen=240)
        if persistence_path is not None:
            self._equity.extend(self._load_equity(persistence_path))
        self._last_equity_monotonic = 0.0

    @staticmethod
    def _load_equity(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        content = path.read_bytes()
        if len(content) > 500_000:
            raise ValueError("stored equity history exceeds the size limit")
        document = json.loads(content.decode("utf-8"))
        if not isinstance(document, dict) or document.get("schema") != 1:
            raise ValueError("stored equity history has an unsupported schema")
        samples = document.get("samples")
        if not isinstance(samples, list):
            raise ValueError("stored equity history samples are invalid")
        validated = []
        for sample in samples:
            if not isinstance(sample, dict) or not isinstance(sample.get("time"), str):
                raise ValueError("stored equity sample is invalid")
            timestamp = datetime.fromisoformat(sample["time"])
            if timestamp.tzinfo is None:
                raise ValueError("stored equity sample time must be aware")
            equity = sample.get("equity")
            if (
                isinstance(equity, bool)
                or not isinstance(equity, (int, float))
                or not math.isfinite(float(equity))
                or equity < 0
            ):
                raise ValueError("stored equity sample value is invalid")
            validated.append({"time": sample["time"], "equity": float(equity)})
        return validated[-240:]

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(copy.deepcopy(values))

    def heartbeat(self, status: str, issues: list[dict[str, str]]) -> None:
        now = self._clock().astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._data.update(
                heartbeat_utc=now,
                status=status,
                issues=copy.deepcopy(issues),
            )

    def record_equity(self, equity: float, *, force: bool = False) -> None:
        if (
            isinstance(equity, bool)
            or not isinstance(equity, (int, float))
            or not math.isfinite(float(equity))
            or equity < 0
        ):
            raise ValueError("equity must be a nonnegative finite number")
        monotonic = time.monotonic()
        if not force and monotonic - self._last_equity_monotonic < 60:
            return
        self._last_equity_monotonic = monotonic
        sample = {
            "time": self._clock()
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds"),
            "equity": round(float(equity), 8),
        }
        with self._lock:
            self._equity.append(sample)
            if self._persistence_path is not None:
                _atomic_json_write(
                    self._persistence_path,
                    {"schema": 1, "samples": list(self._equity)},
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = copy.deepcopy(self._data)
            result["equity_history"] = list(self._equity)
        heartbeat = datetime.fromisoformat(result["heartbeat_utc"])
        result["heartbeat_age_seconds"] = max(
            0.0,
            round(
                (self._clock().astimezone(timezone.utc) - heartbeat).total_seconds(), 3
            ),
        )
        return result


class _StatusHandler(BaseHTTPRequestHandler):
    server_version = "NEEZYStatus/1.0"
    sys_version = ""

    def _send(self, status: int, document: dict[str, Any]) -> None:
        content = json.dumps(document, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        state: StatusState = self.server.state  # type: ignore[attr-defined]
        path = urlsplit(self.path).path
        snapshot = state.snapshot()
        if path == "/api/capabilities":
            from .lab.service import catalog

            self._send(200, catalog())
            return
        if path == "/api/status":
            self._send(200, snapshot)
            return
        if path == "/health":
            self._send(
                200,
                {
                    "ok": snapshot.get("status") == "ok",
                    "status": snapshot.get("status"),
                    "heartbeat_utc": snapshot.get("heartbeat_utc"),
                    "heartbeat_age_seconds": snapshot.get("heartbeat_age_seconds"),
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._send(405, {"error": "status API is read-only"})

    def log_message(self, _format: str, *args: Any) -> None:
        # Do not log request paths, Access headers, or client metadata.
        del args


class StatusServer:
    """Run the API on a daemon thread; it exposes no broker mutation routes."""

    def __init__(self, state: StatusState, host: str, port: int) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("status server must bind to loopback")
        self._server = ThreadingHTTPServer((host, port), _StatusHandler)
        self._server.daemon_threads = True
        self._server.state = state  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="neezy-status-api",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            self._server.server_close()
            return
        self._server.shutdown()
        self._server.server_close()
        if thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
