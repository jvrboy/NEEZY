"""Offline tests for deep candle history paging against a fake Deriv server."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import websocket

from neezy_backend.stream import fetch_history


class FakeHistoryServer:
    """Answers ``ticks_history`` requests from a fixed list of candle epochs."""

    def __init__(self, epochs: list[int]) -> None:
        self.epochs = sorted(epochs)
        self.requests: list[dict] = []

    def connect(self, *args, **kwargs) -> _FakeHistoryConnection:
        return _FakeHistoryConnection(self)


class _FakeHistoryConnection:
    def __init__(self, server: FakeHistoryServer) -> None:
        self.server = server
        self.reply = ""

    def send(self, payload: str) -> None:
        request = json.loads(payload)
        self.server.requests.append(request)
        end = request["end"]
        limit = self.server.epochs[-1] if end == "latest" else int(end)
        eligible = [epoch for epoch in self.server.epochs if epoch <= limit]
        chosen = eligible[-request["count"] :]
        self.reply = json.dumps(
            {
                "msg_type": "candles",
                "candles": [
                    {"epoch": epoch, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1}
                    for epoch in chosen
                ],
            }
        )

    def recv(self) -> str:
        return self.reply

    def close(self) -> None:
        pass


class FetchHistoryTests(unittest.TestCase):
    def test_pages_backwards_and_returns_oldest_first(self) -> None:
        server = FakeHistoryServer([index * 60 for index in range(12_000)])
        with mock.patch.object(
            websocket, "create_connection", side_effect=server.connect
        ):
            rows = fetch_history("R_10", 60, 12_000, url="wss://example.invalid")

        self.assertEqual(len(rows), 12_000)
        epochs = [row[0] for row in rows]
        self.assertEqual(epochs, sorted(set(epochs)))
        self.assertEqual(epochs[0], 0)
        # Three pages: 5000 from latest, 5000 before that, the last 2000.
        self.assertEqual([r["count"] for r in server.requests], [5000, 5000, 2000])
        self.assertEqual(server.requests[0]["end"], "latest")
        # Page one holds the newest 5000 candles, so the oldest is index 7000.
        self.assertEqual(server.requests[1]["end"], 7_000 * 60 - 1)

    def test_stops_when_history_is_exhausted(self) -> None:
        server = FakeHistoryServer([index * 60 for index in range(3_000)])
        with mock.patch.object(
            websocket, "create_connection", side_effect=server.connect
        ):
            rows = fetch_history(
                "R_10", 60, 10_000, url="wss://example.invalid", page_size=5000
            )

        self.assertEqual(len(rows), 3_000)
        # Second page asks for older data, gets nothing new, and paging ends.
        self.assertEqual(len(server.requests), 2)

    def test_total_trims_to_the_most_recent_candles(self) -> None:
        server = FakeHistoryServer([index * 60 for index in range(9_000)])
        with mock.patch.object(
            websocket, "create_connection", side_effect=server.connect
        ):
            rows = fetch_history(
                "R_10", 60, 1_500, url="wss://example.invalid", page_size=1000
            )

        self.assertEqual(len(rows), 1_500)
        self.assertEqual(rows[-1][0], 8_999 * 60)
        self.assertEqual(rows[0][0], (9_000 - 1_500) * 60)

    def test_fails_over_once_then_keeps_the_working_endpoint(self) -> None:
        server = FakeHistoryServer([index * 60 for index in range(6_000)])
        blocked = websocket.WebSocketBadStatusException("x", 520)
        calls: list[str] = []

        def connect(url, *args, **kwargs):
            calls.append(url)
            if url == "wss://blocked.invalid":
                raise blocked
            return server.connect()

        with mock.patch.object(websocket, "create_connection", side_effect=connect):
            rows = fetch_history(
                "R_10",
                60,
                6_000,
                url=["wss://blocked.invalid", "wss://good.invalid"],
                page_size=5000,
            )

        self.assertEqual(len(rows), 6_000)
        # Page one tries blocked then good; page two goes straight to good.
        self.assertEqual(
            calls,
            ["wss://blocked.invalid", "wss://good.invalid", "wss://good.invalid"],
        )

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(ValueError):
            fetch_history("R_10", 60, 0, url="wss://example.invalid")
        with self.assertRaises(ValueError):
            fetch_history("R_10", 60, 10, url="wss://example.invalid", page_size=0)
        with self.assertRaises(ValueError):
            fetch_history("R_10", 60, 10, url="wss://example.invalid", page_size=5001)
        with self.assertRaises(ValueError):
            fetch_history("R_10", 0, 10, url="wss://example.invalid")
        with self.assertRaises(ValueError):
            fetch_history("R_10", 60, 10, url="wss://example.invalid", max_pages=0)


if __name__ == "__main__":
    unittest.main()
