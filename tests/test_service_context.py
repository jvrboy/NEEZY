"""Tests for the ServiceContext runtime handles (roadmap #6).

Covers lazy single-instance construction, injected factories, scoped
override/restore semantics, close/enter-exit protection, the NEEZY_HOME
rebind behaviour for any already-open shared database, and the tools that
now read through the context instead of opening per-call connections.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from neezy_backend.database import LocalDatabase
from neezy_backend.service_context import (
    ServiceContext,
    current_context,
    default_context,
    pop_current_context,
    reset_current_context,
    scoped_context,
    set_current_context,
)
from neezy_backend.tools import ToolRegistry, register_default_tools


class FakeDatabase:
    """Minimal LocalDatabase stand-in bound to an injected path."""

    store_candles: bool = True

    def __init__(self, path: str = "/tmp/fake.sqlite3") -> None:
        self.path = path
        self.related = None

    def save_candles(self, symbol: str, timeframe: str, candles: object) -> int:

        return len(candles)  # fake writes "succeed"

    def close(self) -> None:
        self.related = "closed"


class ServiceContextConstructionTests(unittest.TestCase):
    def test_database_is_lazy_and_single_instance(self) -> None:
        builder = ServiceContext(database_factory=FakeDatabase)
        database = builder.database
        self.assertIsInstance(database, FakeDatabase)
        self.assertIs(database, builder.database)
        self.assertIsNone(database.related, "close() must not have run yet")

    def test_candle_accessor_reuses_database(self) -> None:
        context = ServiceContext(database_factory=FakeDatabase)
        accessor = context.candles
        self.assertIs(accessor, context.candles)
        self.assertIs(accessor.store, context.database)

    def test_history_defaults_once_and_injection_wins(self) -> None:
        context = ServiceContext()
        history = context.history
        self.assertIs(history, context.history)
        injected = ServiceContext(history_factory=lambda: "fake-history")  # type: ignore[return-value]
        self.assertEqual(injected.history, "fake-history")

    def test_registry_prefers_injection_then_default(self) -> None:
        custom = ToolRegistry()
        context = ServiceContext(tools=custom)
        self.assertIs(context.registry(), custom)
        plain = ServiceContext()
        self.assertEqual(plain.registry().list_tools()[0]["name"], "read_market")

    def test_close_is_idempotent_and_blocks_further_access(self) -> None:
        context = ServiceContext(database_factory=FakeDatabase)
        database = context.database
        context.close()
        self.assertEqual(database.related, "closed")
        context.close()
        self.assertTrue(context.is_closed())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            _ = context.database

    def test_enter_exit_closes(self) -> None:
        builder = ServiceContext(database_factory=FakeDatabase)
        with builder as entered:
            self.assertIs(entered, builder)
            self.assertIsInstance(entered.database, FakeDatabase)
        self.assertTrue(builder.is_closed())


class ScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_current_context()
        self.addCleanup(reset_current_context)

    def test_current_context_falls_back_to_default(self) -> None:
        self.assertIs(current_context(), default_context())
        self.assertIs(default_context(), default_context())

    def test_scoped_context_swap_and_restore(self) -> None:
        outer_default = default_context()
        inner = ServiceContext(database_factory=FakeDatabase)
        with scoped_context(inner) as handle:
            self.assertIs(handle, inner)
            self.assertIs(current_context(), inner)
        self.assertIs(current_context(), outer_default)

    def test_nesting_returns_the_innermost(self) -> None:
        one = ServiceContext(database_factory=FakeDatabase)
        two = ServiceContext(database_factory=FakeDatabase)
        with scoped_context(one):
            with scoped_context(two):
                self.assertIs(current_context(), two)
            self.assertIs(current_context(), one)
        self.assertIs(current_context(), default_context())
        self.assertFalse(one.is_closed())
        self.assertFalse(two.is_closed())

    def test_pop_without_scope_is_a_noop(self) -> None:
        pop_current_context()
        self.assertIs(current_context(), default_context())

    def test_set_then_pop(self) -> None:
        context = ServiceContext(database_factory=FakeDatabase)
        set_current_context(context)
        self.assertIs(current_context(), context)
        pop_current_context()
        self.assertIs(current_context(), default_context())


def directory() -> str:
    return tempfile.mkdtemp()


class RebindTests(unittest.TestCase):
    """Changing NEEZY_HOME with an open default db rebuilds the context."""

    def setUp(self) -> None:
        reset_current_context()
        self.addCleanup(reset_current_context)

    def test_rebind_recreates_default_database(self) -> None:
        original = default_context()
        first_database = original.database
        fake_previous = first_database.path
        self.assertTrue(fake_previous)

        with (
            tempfile.TemporaryDirectory() as rebind_target,
            mock.patch.dict(os.environ, {"NEEZY_HOME": rebind_target}),
        ):
            rebound = default_context()
            self.assertIsNot(rebound, original)
            self.assertIsNot(rebound.database, first_database)
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                first_database._connection.execute("SELECT 1")
            self.assertEqual(
                str(rebound.database.path),
                os.path.join(rebind_target, "neezy.sqlite3"),
            )


class ToolsThroughContextTests(unittest.TestCase):
    """The memory/signal tools read and write through the shared context."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = mock.patch.dict(os.environ, {"NEEZY_HOME": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        reset_current_context()
        self.addCleanup(reset_current_context)

    def test_memory_roundtrip_through_context(self) -> None:
        registry = ToolRegistry()
        register_default_tools(registry)
        self.assertEqual(
            registry.execute("search_memory", dry_run=False, query="latent heat"),
            "No matching memory.",
        )
        self.assertIn(
            "Memory saved as #",
            registry.execute(
                "add_memory",
                dry_run=False,
                confirm=True,
                content="latent heat of vaporisation",
            ),
        )
        hits = registry.execute("search_memory", dry_run=False, query="latent heat")
        self.assertIn("latent heat of vaporisation", hits)

        database = current_context().database
        self.assertEqual(
            database.search_memory("latent heat", limit=10)[0]["content"],
            "latent heat of vaporisation",
        )
        self.assertEqual(database.candle_count(), 0)

    def test_recent_signals_reads_context_database(self) -> None:
        registry = ToolRegistry()
        register_default_tools(registry)
        self.assertEqual(
            registry.execute("recent_signals", dry_run=False), "No saved signals."
        )
        context = current_context()
        context.database.save_signal(
            symbol="frxEURUSD", timeframe="1h", signal="BUY", score=2.0
        )
        lines = registry.execute(
            "recent_signals", dry_run=False, limit="3"
        ).splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("frxEURUSD 1h BUY", lines[0])


class ContextConcurrencyTests(unittest.TestCase):
    def test_lazy_database_is_created_once_across_threads(self) -> None:
        context = ServiceContext(database_factory=FakeDatabase)
        instances: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            database = context.database
            with lock:
                instances.append(database)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(instances), 6)
        self.assertTrue(all(item is instances[0] for item in instances))


class LocalDatabaseDefaultsTests(unittest.TestCase):
    def test_default_context_uses_localdatabase(self) -> None:
        context = ServiceContext()
        self.assertIsInstance(context.database, LocalDatabase)


if __name__ == "__main__":
    unittest.main()
