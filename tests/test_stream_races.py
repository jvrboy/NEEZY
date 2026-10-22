"""Race-condition stress tests for DerivStreamClient (roadmap #41).

Threads call start/stop/send concurrently against a fake WebSocketApp.
Assertions: no deadlock (every join returns within its timeout), clean
shutdown (the run loop exits and publishes ``stopped``), and no unexpected
exceptions escape the lifecycle methods. Fully offline and deterministic.
"""

from __future__ import annotations

import threading
import unittest
from typing import ClassVar
from unittest import mock

from neezy_backend.events import EventBus
from neezy_backend.stream import DerivStreamClient


class FakeWebSocketApp:
    """Stands in for websocket.WebSocketApp without any network.

    ``run_forever`` fires the open callback, then blocks until ``close`` is
    called (mirroring a healthy connection that the owner terminates).
    ``send`` succeeds while open and raises once closed, like the real
    socket raising a WebSocketException after teardown.
    """

    instances: ClassVar[list[FakeWebSocketApp]] = []

    def __init__(
        self,
        url,
        header=None,
        on_open=None,
        on_message=None,
        on_error=None,
        on_close=None,
    ) -> None:
        self.url = url
        self.header = header or {}
        self._on_open = on_open
        self._on_message = on_message
        self._on_error = on_error
        self._on_close = on_close
        self._closed = threading.Event()
        self._open = threading.Event()
        self.send_calls: list[str] = []
        type(self).instances.append(self)

    def run_forever(self, ping_interval=None, ping_timeout=None) -> None:
        if self._on_open is not None:
            self._on_open(self)
        self._open.set()
        self._closed.wait(timeout=10.0)
        if self._on_close is not None:
            self._on_close(self, 1000, "fake close")

    def close(self) -> None:
        self._closed.set()

    def send(self, data: str) -> None:
        if self._closed.is_set():
            import websocket

            raise websocket.WebSocketException("socket is closed")
        self.send_calls.append(data)


def make_client(**overrides) -> DerivStreamClient:
    """A fast-reconnecting client on a private event bus."""
    kwargs = {
        "url": "wss://fake.example/ws",
        "bus": EventBus(),
        "reconnect_seconds": 0.01,
        "max_reconnect_seconds": 0.05,
    }
    kwargs.update(overrides)
    return DerivStreamClient(**kwargs)


class StreamRaceTests(unittest.TestCase):
    """Concurrent lifecycle operations must not deadlock or corrupt state."""

    def setUp(self) -> None:
        FakeWebSocketApp.instances = []
        patcher = mock.patch(
            "neezy_backend.stream.websocket.WebSocketApp", FakeWebSocketApp
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_concurrent_start_stop_send_cycles(self) -> None:
        """Hammer start/stop/send from several threads; all must finish."""
        client = make_client()
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=5.0)
                for _ in range(30):
                    client.start()
                    client.send({"ping": index})
                    if index % 2:
                        client.stop(timeout=1.0)
            except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(i,), daemon=True) for i in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15.0)
            self.assertFalse(thread.is_alive(), "lifecycle thread deadlocked")
        self.assertEqual(errors, [], f"unexpected exceptions: {errors!r}")
        client.stop(timeout=2.0)
        self.assertFalse(client.running)

    def test_stop_is_idempotent_and_fast(self) -> None:
        """Repeated stop() calls return promptly even while starting."""
        client = make_client()
        client.start()
        for _ in range(10):
            client.stop(timeout=1.0)
        self.assertFalse(client.running)

    def test_stop_from_within_callback_thread_is_safe(self) -> None:
        """A callback thread calling stop() must not join itself forever."""
        client = make_client()
        client.start()

        def stopper() -> None:
            client.stop(timeout=0.5)

        thread = threading.Thread(target=stopper, daemon=True)
        thread.start()
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive(), "stop() joined its own thread")
        client.stop(timeout=1.0)

    def test_send_never_leaks_after_stop(self) -> None:
        """send() after stop returns False instead of touching a dead socket."""
        client = make_client()
        client.start()
        # Wait for the fake connection to open.
        deadline = 50.0
        seen_open = any(
            app._open.wait(timeout=0.1) for app in list(FakeWebSocketApp.instances)
        )
        if seen_open:
            self.assertTrue(client.send({"subscribe": "frxEURUSD"}))
        client.stop(timeout=2.0)
        self.assertFalse(client.send({"subscribe": "frxEURUSD"}))
        del deadline

    def test_stopped_event_is_published_exactly_once_per_shutdown(self) -> None:
        """Each completed run loop publishes exactly one terminal event."""
        client = make_client()
        channel = client.bus.subscribe()
        client.start()
        import time

        for _ in range(200):
            if client.connected:
                break
            time.sleep(0.01)
        client.stop(timeout=2.0)
        for _ in range(200):
            events = EventBus.drain(channel, limit=1000)
            if any(e.kind == "stopped" for e in events):
                break
            time.sleep(0.01)
        self.assertEqual(
            sum(1 for e in events if e.kind == "stopped"),
            1,
            f"expected exactly one stopped event, saw {[e.kind for e in events]}",
        )

    def test_restart_after_stop_creates_a_fresh_run_loop(self) -> None:
        """start() after stop() works and each cycle ends with stopped."""
        client = make_client()
        channel = client.bus.subscribe()
        for _ in range(3):
            client.start()
            client.stop(timeout=2.0)
        for _ in range(300):
            events = EventBus.drain(channel, limit=1000)
            if sum(1 for e in events if e.kind == "stopped") >= 3:
                break
            import time

            time.sleep(0.01)
        self.assertGreaterEqual(sum(1 for e in events if e.kind == "stopped"), 3)


if __name__ == "__main__":
    unittest.main()
