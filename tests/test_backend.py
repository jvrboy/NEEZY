import unittest
from queue import Queue

from neezy_backend.config import AppSettings
from neezy_backend.events import EventBus


class BackendTests(unittest.TestCase):
    def test_settings_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings().updated(polling_ms=10)
        with self.assertRaises(ValueError):
            AppSettings().updated(theme="Unknown")

    def test_event_bus_fans_out_and_drains(self) -> None:
        bus = EventBus()
        first = bus.subscribe()
        second = bus.subscribe()
        bus.publish("tick", {"symbol": "frxEURUSD"})
        self.assertEqual(EventBus.drain(first)[0].payload["symbol"], "frxEURUSD")
        self.assertEqual(EventBus.drain(second)[0].kind, "tick")
        self.assertEqual(EventBus.drain(Queue()), [])


if __name__ == "__main__":
    unittest.main()
