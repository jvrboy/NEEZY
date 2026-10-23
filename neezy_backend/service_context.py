"""One explicit bundle of shared runtime handles. (roadmap #6)

Before this module the shared runtime state (database, signal-history store,
tool registry) appeared as module-level globals constructed ad hoc: some tool
closures opened a fresh ``LocalDatabase()`` per call, other subsystems cached
their own handles, and ownership and lifetime were invisible.

:class:`ServiceContext` is that bundle: one object an entry point (UI shell,
CLI, MCP, tests) creates and hands around explicitly, while a small,
documented scoped default keeps existing ad-hoc consumers working until each
is migrated. Nothing here talks to the network and no credentials live here —
this is local runtime plumbing only.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .candles import CandleAccessor
    from .database import LocalDatabase
    from .events import EventBus
    from .storage import SignalHistoryStore
    from .tools import ToolRegistry

__all__ = [
    "ServiceContext",
    "current_context",
    "default_context",
    "pop_current_context",
    "reset_current_context",
    "scoped_context",
    "set_current_context",
]


class ServiceContext:
    """Shared runtime handles with lazy, single-instance construction.

    ``database`` is created once from ``database_factory`` (default: the
    standard local path); the candle accessor reuses it as its store; the
    history store and tool registry use injected values when provided and
    sane defaults otherwise. ``bus`` stays optional for entry points that do
    not stream yet.
    """

    def __init__(
        self,
        *,
        database_factory: Callable[[], LocalDatabase] | None = None,
        history_factory: Callable[[], SignalHistoryStore] | None = None,
        tools: ToolRegistry | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._database_factory = database_factory or self._default_database_factory
        self._history_factory = history_factory
        self.tools = tools
        self.bus = bus
        self._database: LocalDatabase | None = None
        self._candles: CandleAccessor | None = None
        self._history: SignalHistoryStore | None = None
        self._closed = False
        self._lock = threading.RLock()

    @staticmethod
    def _default_database_factory() -> LocalDatabase:
        from .database import LocalDatabase

        return LocalDatabase()

    # ---------------------------------------------------------------- handles
    @property
    def database(self) -> LocalDatabase:
        """Shared SQLite handle, created on first access."""
        with self._lock:
            if self._closed:
                raise RuntimeError("service context is closed")
            if self._database is None:
                self._database = self._database_factory()
            return self._database

    @property
    def candles(self) -> CandleAccessor:
        """Candle accessor bound to the shared database."""
        with self._lock:
            if self._candles is None:
                from .candles import CandleAccessor

                self._candles = CandleAccessor(self.database)
            return self._candles

    @property
    def history(self) -> SignalHistoryStore:
        """Signal-transition JSONL store (one instance per context)."""
        with self._lock:
            if self._history is None:
                if self._history_factory is not None:
                    self._history = self._history_factory()
                else:
                    from .storage import SignalHistoryStore

                    self._history = SignalHistoryStore()
            return self._history

    def registry(self) -> ToolRegistry:
        """The tool registry: injected one, else the shared default."""
        if self.tools is not None:
            return self.tools
        return _default_tool_registry()

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close the database handle; safe to call twice."""
        with self._lock:
            if self._database is not None:
                self._database.close()
            self._database = None
            self._candles = None
            self._closed = True

    def __enter__(self) -> ServiceContext:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _default_tool_registry() -> ToolRegistry:
    from .tools import DEFAULT_REGISTRY, register_default_tools

    register_default_tools()
    return DEFAULT_REGISTRY


# --------------------------------------------------------------------- scope
_scope_lock = threading.Lock()
_scoped: list[ServiceContext] = []


def set_current_context(context: ServiceContext) -> None:
    """Install ``context`` as the process-scoped current context."""
    with _scope_lock:
        _scoped.append(context)


def pop_current_context() -> None:
    with _scope_lock:
        if _scoped:
            _scoped.pop()


def current_context() -> ServiceContext:
    """The innermost scoped context, or the shared default."""
    with _scope_lock:
        if _scoped:
            return _scoped[-1]
    return default_context()


@contextmanager
def scoped_context(context: ServiceContext):
    """Temporarily install ``context`` as the current one, restoring after."""
    set_current_context(context)
    try:
        yield context
    finally:
        pop_current_context()


_default: ServiceContext | None = None
_default_lock = threading.Lock()


def default_context() -> ServiceContext:
    """Process-wide default context, created lazily and kept until reset.

    The shared database binds to the NEEZY data directory resolved at first
    use. If that directory changes afterwards (NEEZY_HOME override, test
    sandboxes), the old context is closed and a fresh one is built so the
    never-reopened-per-call behaviour of historical consumers is preserved.
    """
    global _default
    with _default_lock:
        if _default is not None and _default._database is not None:
            try:
                from .storage import get_data_dir

                expected = get_data_dir() / "neezy.sqlite3"
                if _default._database.path != expected:
                    _default.close()
                    _default = None
            except OSError:
                pass
        if _default is None:
            _default = ServiceContext()
        return _default


def reset_current_context() -> None:
    """Clear the scoped context and drop the default (for tests)."""
    global _default
    with _default_lock:
        _default = None
    with _scope_lock:
        _scoped.clear()
