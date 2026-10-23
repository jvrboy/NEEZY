"""Single candle accessor API — fetch, persist, and read in one place. (roadmap #2)

Before this module the candle pipeline was spread across four hand-rolled
implementations: :mod:`neezy_backend.stream` (live Deriv fetch),
:mod:`neezy_backend.providers` (REST providers), :mod:`neezy_backend.database`
(SQLite persistence) and the research paths. Each validated rows slightly
differently, which let malformed candles reach the strategy engine through
whichever path happened to skip its own check.

This module is the one API for candle-shaped data:

* :func:`validate_candle_rows` — one strict validator (shape, finite prices,
  ``0`` bounds, OHLC consistency) used by every accessor path.
* :func:`normalize_candles` — validate, de-duplicate by epoch (freshest row
  wins) and sort oldest-first, the canonical ordering across the backend.
* :class:`CandleStore` — the storage protocol (``load_candles`` /
  ``save_candles`` / ``candle_count``) matching :class:`LocalDatabase`, so an
  in-memory or JSON store can replace SQLite in tests and later features.
* :class:`CandleAccessor` — fetch (Deriv or MT5), persist, and read off one
  object with injectable delegates, keeping the module-level ``fetch_candles``
  patch targets (``neezy_backend.stream.fetch_candles``) working through late
  imports.

``Candle`` stays the ``(epoch, open, high, low, close)`` tuple used everywhere.
Only the standard library is used; no new dependencies.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .markets import granularity

if TYPE_CHECKING:
    from .database import LocalDatabase

Candle = tuple[int, float, float, float, float]

# Deriv caps a single history request at 5000 candles; the accessor mirrors it.
MAX_ACCESSOR_COUNT = 5000

_DERIV = "deriv"
_MT5 = "mt5"
_SOURCES = (_DERIV, _MT5)


class CandleError(ValueError):
    """A candle payload is malformed or no store is configured."""


def _positive_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > 10**12:
        raise ValueError("price outside the supported positive range")
    return number


def validate_candle_row(row: Any, *, source: str = "candle") -> Candle:
    """Convert one raw row (sequence or mapping) to a strict :data:`Candle`."""
    if isinstance(row, dict):
        keys = ("epoch", "open", "high", "low", "close")
        values = [row.get(key) for key in keys]
    elif isinstance(row, (tuple, list)) and len(row) >= 5:
        values = list(row[:5])
    else:
        raise CandleError(f"{source} returned a malformed candle row")
    issue = f"{source} returned a malformed candle row"
    try:
        epoch = int(float(values[0]))
        open_ = _positive_number(values[1])
        high = _positive_number(values[2])
        low = _positive_number(values[3])
        close = _positive_number(values[4])
    except (TypeError, ValueError, IndexError, CandleError) as error:
        raise CandleError(issue) from error
    # Synthetic candles (tests, research fixtures) legitimately start at
    # epoch 0; only negative epochs are nonsense.
    if (
        epoch < 0
        or low > high
        or not (low <= open_ <= high)
        or not (low <= close <= high)
    ):
        raise CandleError(issue)
    return (epoch, open_, high, low, close)


def validate_candle_rows(
    rows: Iterable[Any], *, source: str = "candle"
) -> list[Candle]:
    """Validate every row; the first bad one raises with its origin named."""
    return [validate_candle_row(row, source=source) for row in rows]


def normalize_candles(rows: Iterable[Any], *, source: str = "candle") -> list[Candle]:
    """Validate, de-duplicate by epoch (last occurrence wins) and sort.

    Repeated fetches overlap freely; for one epoch the newest read wins, so
    merged history always carries the freshest mirrored data.
    """
    merged: dict[int, Candle] = {}
    for candle in validate_candle_rows(rows, source=source):
        merged[candle[0]] = candle
    return [merged[epoch] for epoch in sorted(merged)]


@runtime_checkable
class CandleStore(Protocol):
    """Storage boundary for candles; :class:`LocalDatabase` satisfies it."""

    def save_candles(
        self, symbol: str, timeframe: str, candles: Iterable[Any]
    ) -> int: ...

    def load_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[Candle]: ...

    def candle_count(self, symbol: str | None = None) -> int: ...


class InMemoryCandleStore:
    """Thread-safe dict-backed :class:`CandleStore` for tests and offline runs."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[int, Candle]] = {}
        self._lock = threading.RLock()

    def save_candles(self, symbol: str, timeframe: str, candles: Iterable[Any]) -> int:
        written = 0
        with self._lock:
            bucket = self._rows.setdefault((symbol, timeframe), {})
            for row in validate_candle_rows(candles, source="in-memory store"):
                if bucket.get(row[0]) != row:
                    bucket[row[0]] = row
                    written += 1
        return written

    def load_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[Candle]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            bucket = self._rows.get((symbol, timeframe), {})
            epochs = sorted(bucket)[-limit:]
            return [bucket[epoch] for epoch in epochs]

    def candle_count(self, symbol: str | None = None) -> int:
        with self._lock:
            if symbol is None:
                return sum(len(bucket) for bucket in self._rows.values())
            return sum(
                len(bucket)
                for (bucket_symbol, _), bucket in self._rows.items()
                if bucket_symbol == symbol
            )

    def stored_frames(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._rows)


Store = CandleStore
FetchFn = Callable[..., list[Candle]]


class CandleAccessor:
    """The one place to fetch, persist, and read candles.

    ``store`` receives normalized candles through ``persist``/``refresh`` and
    answers ``read``/``latest``/``count``. ``stream_fetch`` and
    ``stream_history`` override the Deriv delegates (they are bound lazily by
    default so ``mock.patch("neezy_backend.stream.fetch_candles", ...)`` keeps
    working for every consumer). ``mt5_fetch`` must be provided before
    ``source="mt5"`` fetches are possible.
    """

    def __init__(
        self,
        store: CandleStore | None = None,
        *,
        stream_fetch: FetchFn | None = None,
        stream_history: FetchFn | None = None,
        mt5_fetch: FetchFn | None = None,
    ) -> None:
        self.store = store
        self._stream_fetch = stream_fetch
        self._stream_history = stream_history
        self._mt5_fetch = mt5_fetch

    # ------------------------------------------------------------------ fetch
    def _fetch_fn(self) -> FetchFn:
        if self._stream_fetch is not None:
            return self._stream_fetch
        from .stream import fetch_candles

        return fetch_candles

    def _history_fn(self) -> FetchFn:
        if self._stream_history is not None:
            return self._stream_history
        from .stream import fetch_history

        return fetch_history

    def _checked_count(self, count: int) -> int:
        try:
            value = int(count)
        except (TypeError, ValueError) as error:
            raise CandleError("count must be an integer") from error
        if not 1 <= value <= MAX_ACCESSOR_COUNT:
            raise CandleError(f"count must be between 1 and {MAX_ACCESSOR_COUNT}")
        return value

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        count: int = 300,
        *,
        source: str = _DERIV,
    ) -> list[Candle]:
        """Fresh candles, oldest first, de-duplicated and sorted.

        ``source`` selects ``deriv`` (WebSocket/history fetch, resolved to
        seconds) or ``mt5`` (the timeframe name is passed to the injected
        ``mt5_fetch``, matching the bridge signature).
        """
        value = self._checked_count(count)
        seconds = granularity(timeframe)
        if source == _DERIV:
            rows: list[Any] = self._fetch_fn()(symbol, seconds, value)
        elif source == _MT5:
            if self._mt5_fetch is None:
                raise CandleError(
                    "mt5 source requires an mt5_fetch delegate on the accessor"
                )
            rows = self._mt5_fetch(symbol, timeframe, value)
        else:
            raise CandleError(
                f"unknown candle source {source!r}; choose from " + ", ".join(_SOURCES)
            )
        normalized = normalize_candles(rows, source=f"{source} fetch")
        return normalized[-value:]

    def history(
        self, symbol: str, timeframe: str, total: int = 1000, *, source: str = _DERIV
    ) -> list[Candle]:
        """Deep paged history, oldest first (deriv source pages backwards)."""
        if total < 1:
            raise CandleError("total must be at least 1")
        seconds = granularity(timeframe)
        if source == _DERIV:
            rows: list[Any] = self._history_fn()(symbol, seconds, int(total))
        elif source == _MT5:
            if self._mt5_fetch is None:
                raise CandleError(
                    "mt5 source requires an mt5_fetch delegate on the accessor"
                )
            rows = self._mt5_fetch(symbol, timeframe, int(total))
        else:
            raise CandleError(
                f"unknown candle source {source!r}; choose from " + ", ".join(_SOURCES)
            )
        normalized = normalize_candles(rows, source=f"{source} history")
        return normalized[-int(total) :]

    # ---------------------------------------------------------------- persist
    def persist(self, symbol: str, timeframe: str, candles: Iterable[Any]) -> int:
        """Validate, normalize, and write candles to the store; rows written."""
        if self.store is None:
            raise CandleError(
                "no candle store configured; construct the accessor with one"
            )
        normalized = normalize_candles(candles, source="persist")
        return self.store.save_candles(symbol, timeframe, normalized)

    # ------------------------------------------------------------------- read
    def read(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        if self.store is None:
            raise CandleError(
                "no candle store configured; construct the accessor with one"
            )
        if limit < 1:
            raise CandleError("limit must be positive")
        return self.store.load_candles(symbol, timeframe, limit)

    def latest(self, symbol: str, timeframe: str) -> Candle | None:
        rows = self.read(symbol, timeframe, limit=1)
        return rows[-1] if rows else None

    def count(self, symbol: str | None = None) -> int:
        if self.store is None:
            raise CandleError(
                "no candle store configured; construct the accessor with one"
            )
        return self.store.candle_count(symbol)

    # --------------------------------------------------- combined operations
    def refresh(
        self,
        symbol: str,
        timeframe: str,
        count: int = 300,
        *,
        source: str = _DERIV,
    ) -> list[Candle]:
        """Fetch fresh candles and persist them to the store when present."""
        candles = self.fetch(symbol, timeframe, count, source=source)
        if self.store is not None:
            self.persist(symbol, timeframe, candles)
        return candles

    def ensure(
        self,
        symbol: str,
        timeframe: str,
        min_count: int = 300,
        *,
        source: str = _DERIV,
    ) -> list[Candle]:
        """Enough stored candles, fetching+persisting only what is missing."""
        if self.store is None:
            raise CandleError(
                "no candle store configured; construct the accessor with one"
            )
        wanted = self._checked_count(min_count)
        rows = self.read(symbol, timeframe, limit=wanted)
        if len(rows) >= wanted:
            return rows
        missing = wanted - len(rows)
        fetched = self.fetch(symbol, timeframe, missing, source=source)
        self.persist(symbol, timeframe, fetched)
        return self.read(symbol, timeframe, limit=wanted)


def local_accessor(
    store: CandleStore | None = None, **kwargs: FetchFn | None
) -> CandleAccessor:
    """Accessor with explicit delegates; perfect for tests and offline tools."""
    return CandleAccessor(store, **kwargs)


def database_accessor(
    database: LocalDatabase | None = None,
) -> CandleAccessor:
    """Accessor backed by an existing (or the default) SQLite database."""
    if database is None:
        from .database import LocalDatabase

        database = LocalDatabase()
    return CandleAccessor(store=database)


_default: CandleAccessor | None = None
_default_lock = threading.Lock()


def accessor() -> CandleAccessor:
    """Shared fetch-only accessor (no store); safe process-wide default."""
    global _default
    with _default_lock:
        if _default is None:
            _default = CandleAccessor()
        return _default
