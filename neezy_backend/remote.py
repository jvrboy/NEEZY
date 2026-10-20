"""Safe cross-thread command bridge for local MCP and Telegram controls.

Network workers never touch Tk widgets. They enqueue a small allow-listed
command and wait for the desktop's main event loop to execute it.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Request:
    action: str
    arguments: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


class AppCommandBridge:
    """Marshal remote commands onto the thread that owns the desktop UI."""

    def __init__(self, *, max_pending: int = 100, timeout: float = 15.0) -> None:
        if max_pending < 1 or timeout <= 0:
            raise ValueError("max_pending and timeout must be positive")
        self._queue: queue.Queue[_Request] = queue.Queue(maxsize=max_pending)
        self._timeout = timeout
        self._owner = threading.get_ident()
        self._closed = threading.Event()

    def call(self, action: str, **arguments: Any) -> Any:
        """Queue an action and synchronously return its desktop-thread result."""
        if self._closed.is_set():
            raise RuntimeError("NEEZY is shutting down")
        if threading.get_ident() == self._owner:
            raise RuntimeError(
                "remote bridge cannot synchronously call itself on the UI thread"
            )
        request = _Request(action=action, arguments=arguments)
        try:
            self._queue.put(request, timeout=1.0)
        except queue.Full as error:
            raise TimeoutError("remote control queue is busy") from error
        if not request.done.wait(self._timeout):
            raise TimeoutError("desktop did not process the remote command in time")
        if request.error is not None:
            raise RuntimeError(str(request.error)) from request.error
        return request.result

    def process(self, handler, *, limit: int = 25) -> int:
        """Run queued commands on the owner thread; call this from the UI poll."""
        if threading.get_ident() != self._owner:
            raise RuntimeError("remote commands must be processed by the UI thread")
        if limit < 1:
            return 0
        processed = 0
        while processed < limit:
            try:
                request = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                request.result = handler(request.action, request.arguments)
            except Exception as error:  # noqa: BLE001 - forward handler failures
                request.error = error
            finally:
                request.done.set()
                self._queue.task_done()
            processed += 1
        return processed

    def close(self) -> None:
        """Reject future requests and wake every client waiting in the queue."""
        self._closed.set()
        while True:
            try:
                request = self._queue.get_nowait()
            except queue.Empty:
                break
            request.error = RuntimeError("NEEZY is shutting down")
            request.done.set()
            self._queue.task_done()
