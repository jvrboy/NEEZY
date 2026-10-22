"""Contract tests for EventBus payload validation (roadmap #15).

Every core event kind has an explicit payload type
(``events.PAYLOAD_CONTRACTS``). With ``validate_payloads=True`` (the
``debug_bus`` factory) publishers violating the contract fail immediately;
production buses keep the historical no-validation behaviour.
"""

from __future__ import annotations

import unittest

from neezy_backend.events import (
    KNOWN_EVENT_KINDS,
    PAYLOAD_CONTRACTS,
    EventBus,
    StreamEvent,
    debug_bus,
)


class ContractTableTests(unittest.TestCase):
    """The contract table itself is coherent."""

    def test_core_kinds_are_covered(self) -> None:
        for kind in (
            "message",
            "error",
            "connected",
            "reconnecting",
            "closed",
            "stopped",
        ):
            self.assertIn(kind, PAYLOAD_CONTRACTS)

    def test_known_kinds_matches_contracts(self) -> None:
        self.assertEqual(KNOWN_EVENT_KINDS, frozenset(PAYLOAD_CONTRACTS))


class ValidationModeTests(unittest.TestCase):
    """debug_bus() enforces payload types for known kinds."""

    def test_valid_payloads_publish_normally(self) -> None:
        bus = debug_bus()
        bus.publish("message", {"candles": []})
        bus.publish("error", "boom")
        bus.publish("connected")
        bus.publish("stopped")
        bus.publish("reconnecting", 2.0)
        bus.publish("reconnecting", 3)
        bus.publish("closed", {"code": 1000, "reason": "bye"})

    def test_wrong_payload_type_raises_type_error(self) -> None:
        bus = debug_bus()
        with self.assertRaises(TypeError) as ctx:
            bus.publish("error", 42)
        self.assertIn("error", str(ctx.exception))
        self.assertIn("str", str(ctx.exception))

    def test_message_payload_must_be_a_dict(self) -> None:
        bus = debug_bus()
        with self.assertRaises(TypeError):
            bus.publish("message", [1, 2, 3])

    def test_connected_payload_must_be_none(self) -> None:
        bus = debug_bus()
        with self.assertRaises(TypeError):
            bus.publish("connected", "yes")

    def test_unknown_kinds_are_never_rejected(self) -> None:
        """App-level kinds (backtest, etc.) stay open for extension."""
        bus = debug_bus()
        bus.publish("backtest", ("frxEURUSD", "5m", {"stats": {}}))
        bus.publish("custom-anything", object())

    def test_error_message_names_expected_and_actual(self) -> None:
        bus = debug_bus()
        with self.assertRaises(TypeError) as ctx:
            bus.publish("closed", "not-a-mapping")
        message = str(ctx.exception)
        self.assertIn("closed", message)
        self.assertIn("dict", message)
        self.assertIn("str", message)


class ProductionModeTests(unittest.TestCase):
    """Default buses keep the historical, validation-free behaviour."""

    def test_default_bus_accepts_anything(self) -> None:
        bus = EventBus()
        bus.publish("error", 12345)  # would fail validation; must not raise
        bus.publish("message", "not-a-dict")

    def test_event_carries_kind_and_payload(self) -> None:
        bus = EventBus()
        event = bus.publish("reconnecting", 4)
        self.assertIsInstance(event, StreamEvent)
        self.assertEqual(event.kind, "reconnecting")
        self.assertEqual(event.payload, 4)

    def test_subscribers_receive_validated_events(self) -> None:
        bus = debug_bus()
        channel = bus.subscribe()
        bus.publish("error", "described failure")
        events = EventBus.drain(channel)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload, "described failure")


if __name__ == "__main__":
    unittest.main()
