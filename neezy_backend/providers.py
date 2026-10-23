"""External market-data providers.

NEEZY streams live candles from Deriv's public WebSocket feed. This module adds
optional REST providers used by the confluence engine and the ANALYSIS button:
Deriv, Alpha Vantage, Finnhub, Binance and Twelve Data. Everything runs with
the standard library; there is no third-party HTTP dependency.

Keys are read from the local key store (``provider-keys.json`` in the NEEZY
data directory) or from environment variables, so no secret is ever hard-coded.
Providers that cannot cover a Deriv symbol (for example Binance has no forex
pairs) raise a clear error instead of silently returning other data.

Candles returned by every provider are validated ``(epoch, open, high, low,
close)`` tuples ordered oldest first, matching the shape used across the
backend. Prices above zero and consistent OHLC are enforced before data can
reach the analysis engine.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .candles import Candle
from .markets import TIMEFRAMES
from .storage import get_data_dir


@runtime_checkable
class Provider(Protocol):
    """Common market-data provider interface."""

    key: str
    label: str
    description: str
    requires_key: bool
    env_var: str

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 300,
        *,
        keystore: ProviderKeyStore | None = None,
        fetcher: Callable[[str], str] | None = None,
        base_urls: Mapping[str, str] | None = None,
    ) -> list[Candle]: ...

    def health(
        self,
        symbol: str = "frxEURUSD",
        timeframe: str = "15m",
        *,
        keystore: ProviderKeyStore | None = None,
        fetcher: Callable[[str], str] | None = None,
        base_urls: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...


# Timeout and user agent for every provider request.
HTTP_TIMEOUT = 20.0
_USER_AGENT = "NEEZY/1.6 (educational market monitor)"


class ProviderError(RuntimeError):
    """A provider request failed or the symbol is unavailable on it."""


def _http_get(url: str, timeout: float = HTTP_TIMEOUT) -> str:
    """Bounded GET with a user agent; raises ProviderError on any failure."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise ProviderError(f"HTTP {response.status} from {url.split('?')[0]}")
            return response.read().decode("utf-8", errors="replace")
    except ProviderError:
        raise
    except Exception as error:  # urllib raises many unrelated types
        origin = url.split("?")[0]
        raise ProviderError(f"request to {origin} failed: {error}") from error


def _check_candles(rows: Any, source: str) -> list[Candle]:
    """Validate provider payloads into the shared candle shape."""
    if not isinstance(rows, list):
        raise ProviderError(f"{source} returned no candle list")
    candles: list[Candle] = []
    for row in rows:
        try:
            if len(row) < 5:
                raise ValueError("short row")
            epoch, open_, high, low, close = (
                float(row[0]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
            )
            epoch = int(epoch)
        except (TypeError, ValueError, IndexError) as error:
            issue = f"{source} returned a malformed candle row"
            raise ProviderError(issue) from error
        within_bounds = 0 < open_ <= 10**12 and 0 < close <= 10**12
        if not (epoch > 0 and 0 < low <= high and within_bounds):
            raise ProviderError(f"{source} returned inconsistent candle values")
        if high < max(open_, close) or low > min(open_, close):
            raise ProviderError(f"{source} returned inconsistent candle values")
        candles.append((epoch - epoch % 1, open_, high, low, close))
    candles.sort(key=lambda row: row[0])
    candle_epochs = [row[0] for row in candles]
    if len(set(candle_epochs)) != len(candle_epochs):
        raise ProviderError(f"{source} returned duplicate timestamps")
    return candles


def _strip(symbol: str) -> str:
    """``frxEURUSD`` -> ``EURUSD``; leave other catalogs untouched."""
    return symbol[3:] if symbol.startswith("frx") and len(symbol) >= 7 else symbol


def _split_xccy(symbol: str) -> tuple[str, str] | None:
    """Split a forex pair into base/quote; returns None for non-forex symbols."""
    stripped = _strip(symbol)
    quotes = ("JPY", "USD", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD")
    for quote in quotes:
        if stripped.endswith(quote) and len(stripped) > len(quote) + 2:
            return stripped[: -len(quote)], quote
    return None


# ---------------------------------------------------------------------------
# Per-provider timeframe mapping and payload parsing
# ---------------------------------------------------------------------------


def _alpha_vantage_interval(seconds: int) -> str:
    minutes = seconds // 60
    if minutes >= 60:
        return "60min"
    if minutes >= 15:
        return "15min"
    if minutes >= 5:
        return "5min"
    if minutes >= 1:
        return "1min"
    raise ProviderError("Alpha Vantage does not offer sub-minute candles")


def _parse_alpha_vantage(payload: str) -> list[Candle]:
    """Parse any Alpha Vantage intraday FX series without knowing the interval."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProviderError("Alpha Vantage sent invalid JSON") from error
    if "Note" in document or "Information" in document or "Error Message" in document:
        message = next(
            document[key]
            for key in ("Note", "Information", "Error Message")
            if key in document
        )
        raise ProviderError(f"Alpha Vantage refused the request: {message[:120]}")
    series_key = next(
        (key for key in document if key.startswith("Time Series FX")), None
    )
    if series_key is None:
        raise ProviderError("Alpha Vantage response contains no time series")
    rows = [
        (
            _iso_epoch(stamp) or 0.0,
            block.get("1. open", 0.0),
            block.get("2. high", 0.0),
            block.get("3. low", 0.0),
            block.get("4. close", 0.0),
        )
        for stamp, block in document[series_key].items()
    ]
    return _check_candles(rows, "Alpha Vantage")


def _iso_epoch(stamp: str) -> float | None:
    from datetime import datetime, timezone

    try:
        return (
            datetime.fromisoformat(
                stamp.replace("Z", "+00:00") if stamp.endswith("Z") else stamp
            )
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return None


def _finnhub_resolution(seconds: int) -> str:
    return {60: "1", 300: "5", 900: "15", 1800: "30", 3600: "60", 14400: "240"}.get(
        seconds, "D"
    )


def _parse_finnhub(payload: str) -> list[Candle]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProviderError("Finnhub sent invalid JSON") from error
    if "error" in document:
        raise ProviderError(
            f"Finnhub refused the request: {str(document['error'])[:120]}"
        )
    if document.get("s") != "ok":
        raise ProviderError("Finnhub returned no candles for this symbol")
    stamps = document.get("t")
    if not isinstance(stamps, list):
        raise ProviderError("Finnhub returned no candle list")
    rows = [
        (
            float(stamp),
            document.get("o", [])[index],
            document.get("h", [])[index],
            document.get("l", [])[index],
            document.get("c", [])[index],
        )
        for index, stamp in enumerate(stamps)
    ]
    return _check_candles(rows, "Finnhub")


_BINANCE_INTERVALS = {
    60: "1m",
    300: "5m",
    900: "15m",
    1800: "30m",
    3600: "1h",
    14400: "4h",
    86400: "1d",
}


def _binance_interval(seconds: int) -> str:
    try:
        return _BINANCE_INTERVALS[seconds]
    except KeyError as error:
        raise ProviderError(f"Binance has no {seconds}-second interval") from error


def _parse_binance(payload: str) -> list[Candle]:
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProviderError("Binance sent invalid JSON") from error
    if isinstance(rows, dict):
        raise ProviderError(f"Binance refused the request: {str(rows)[:120]}")
    return _check_candles(
        [(row[0], row[1], row[2], row[3], row[4]) for row in rows], "Binance"
    )


def _twelve_data_interval(seconds: int) -> str:
    return {
        60: "1min",
        300: "5min",
        900: "15min",
        1800: "30min",
        3600: "1h",
        14400: "4h",
        86400: "1day",
    }.get(seconds) or (_throw_bad_interval(seconds))


def _throw_bad_interval(seconds: int) -> str:
    raise ProviderError(f"Twelve Data has no {seconds}-second interval")


def _parse_twelve_data(payload: str) -> list[Candle]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProviderError("Twelve Data sent invalid JSON") from error
    if document.get("status") == "error" or "message" in document:
        raise ProviderError(
            f"Twelve Data refused the request: {str(document.get('message'))[:120]}"
        )
    values = document.get("values", [])
    rows = [
        (
            _iso_epoch(item["datetime"]) or 0.0,
            item["open"],
            item["high"],
            item["low"],
            item["close"],
        )
        for item in values
    ]
    return _check_candles(rows, "Twelve Data")


# ---------------------------------------------------------------------------
# Provider specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderSpec:
    """One REST market-data provider and its request builders."""

    key: str
    label: str
    description: str
    requires_key: bool
    env_var: str
    keyfile_field: str

    def translate(self, symbol: str) -> str | None:
        """Deriv symbol -> provider symbol, or None when unsupported."""
        return _TRANSLATORS[self.key](symbol)

    def interval(self, seconds: int) -> str:
        return _INTERVALS[self.key](seconds)

    def build_url(
        self, symbol: str, seconds: int, count: int, key: str | None, base: str
    ) -> str:
        return _URL_BUILDERS[self.key](symbol, seconds, count, key, base)

    def parse(self, payload: str) -> list[Candle]:
        return _PARSERS[self.key](payload)

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 300,
        *,
        keystore: ProviderKeyStore | None = None,
        fetcher: Callable[[str], str] | None = None,
        base_urls: Mapping[str, str] | None = None,
    ) -> list[Candle]:
        return get_candles(
            self.key,
            symbol,
            timeframe,
            count,
            keystore=keystore,
            fetcher=fetcher,
            base_urls=base_urls,
        )

    def health(
        self,
        symbol: str = "frxEURUSD",
        timeframe: str = "15m",
        *,
        keystore: ProviderKeyStore | None = None,
        fetcher: Callable[[str], str] | None = None,
        base_urls: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        issue = provider_key_issues(self.key, keystore=keystore)
        if issue is not None:
            return {
                "ok": False,
                "provider": self.key,
                "error": issue,
                "candle_count": 0,
            }
        try:
            candles = self.fetch_candles(
                symbol,
                timeframe,
                count=5,
                keystore=keystore,
                fetcher=fetcher,
                base_urls=base_urls,
            )
            return {
                "ok": True,
                "provider": self.key,
                "error": "",
                "candle_count": len(candles),
            }
        except (ProviderError, ValueError, ConnectionError, OSError) as error:
            return {
                "ok": False,
                "provider": self.key,
                "error": str(error),
                "candle_count": 0,
            }


def _alpha_translate(symbol: str) -> str | None:
    pair = _split_xccy(symbol)
    if pair is None:
        return None
    base, quote = pair
    return f"{base}/{quote}"


def _alpha_url(
    symbol: str, seconds: int, count: int, key: str | None, _base: str
) -> str:
    pair = _split_xccy(symbol) or ("", "")
    base, quote = pair
    return (
        "https://www.alphavantage.co/query"
        f"?function=FX_INTRADAY&from_symbol={base}&to_symbol={quote}"
        f"&interval={_alpha_vantage_interval(seconds)}&outputsize=full"
        f"&apikey={key or 'demo'}"
    )


def _finnhub_translate(symbol: str) -> str | None:
    pair = _split_xccy(symbol)
    if pair is None:
        return None
    base, quote = pair
    return f"OANDA:{base}_{quote}"


def _finnhub_url(
    symbol: str, seconds: int, count: int, key: str | None, base: str
) -> str:
    provider_symbol = _finnhub_translate(symbol) or symbol
    resolution = _finnhub_resolution(seconds)
    return (
        f"{base or 'https://finnhub.io'}/api/v1/forex/candle"
        f"?symbol={provider_symbol}&resolution={resolution}&count={min(count, 500)}"
        f"&token={key or ''}"
    )


_BINANCE_CRYPTO = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT",
    "BNB": "BNBUSDT",
}


def _binance_translate(symbol: str) -> str | None:
    stripped = _strip(symbol)
    if not stripped.startswith(("cqg", "frx", "CRY", "1HZ", "R_", "DSI")):
        return None
    return _BINANCE_CRYPTO.get(stripped.removeprefix("frx").upper())


_BINANCE_EXTRA_SYMBOLS = {
    "frxBTCUSD": "BTCUSDT",
    "frxETHUSD": "ETHUSDT",
    "frxXRPUSD": "XRPUSDT",
    "frxDOGEUSD": "DOGEUSDT",
}


def _binance_url(
    symbol: str, seconds: int, count: int, _key: str | None, base: str
) -> str:
    provider_symbol = _binance_translate(symbol) or _BINANCE_EXTRA_SYMBOLS.get(symbol)
    if provider_symbol is None:
        raise ProviderError(
            f"Binance does not cover {symbol}; use a crypto symbol such as frxBTCUSD"
        )
    return (
        f"{base or 'https://api.binance.com'}/api/v3/klines"
        f"?symbol={provider_symbol}&interval={_binance_interval(seconds)}"
        f"&limit={min(count, 1000)}"
    )


def _twelve_translate(symbol: str) -> str | None:
    stripped = _strip(symbol)
    if stripped.startswith(("1HZ", "R_", "DSI", "CRY", "cqg")):
        return None
    pair = _split_xccy(symbol)
    if pair is None:
        return None
    return f"{pair[0]}/{pair[1]}"


def _twelve_url(
    symbol: str, seconds: int, count: int, key: str | None, base: str
) -> str:
    pair = _split_xccy(symbol) or ("", "")
    provider_symbol = f"{pair[0]}/{pair[1]}"
    return (
        f"{base or 'https://api.twelvedata.com'}/time_series"
        f"?symbol={provider_symbol}&interval={_twelve_data_interval(seconds)}"
        f"&outputsize={min(count, 5000)}&format=JSON&apikey={key or 'demo'}"
    )


PROVIDERS: dict[str, ProviderSpec] = {
    "deriv": ProviderSpec(
        "deriv",
        "Deriv (public WebSocket)",
        "Default live feed. No API key or login is needed.",
        False,
        "",
        "unused",
    ),
    "alpha_vantage": ProviderSpec(
        "alpha_vantage",
        "Alpha Vantage",
        "Forex and stock candles. Free tier keys live at alphavantage.co.",
        True,
        "ALPHA_VANTAGE_KEY",
        "alpha_vantage",
    ),
    "finnhub": ProviderSpec(
        "finnhub",
        "Finnhub",
        "Forex via OANDA mapping plus stocks and crypto. finnhub.io keys.",
        True,
        "FINNHUB_KEY",
        "finnhub",
    ),
    "binance": ProviderSpec(
        "binance",
        "Binance",
        "Crypto spot candles without a key. Forex/synthetics unsupported.",
        False,
        "",
        "unused",
    ),
    "twelve_data": ProviderSpec(
        "twelve_data",
        "Twelve Data",
        "Multi-asset API with a free tier. twelvedata.com keys.",
        True,
        "TWELVE_DATA_KEY",
        "twelve_data",
    ),
}


_TRANSLATORS: dict[str, Callable[[str], str | None]] = {
    "deriv": lambda symbol: symbol,
    "alpha_vantage": _alpha_translate,
    "finnhub": _finnhub_translate,
    "binance": _binance_translate,
    "twelve_data": _twelve_translate,
}
_INTERVALS: dict[str, Callable[[int], str]] = {
    "deriv": lambda seconds: str(seconds),
    "alpha_vantage": _alpha_vantage_interval,
    "finnhub": _finnhub_resolution,
    "binance": _binance_interval,
    "twelve_data": _twelve_data_interval,
}
_URL_BUILDERS: dict[str, Callable[[str, int, int, str | None, str], str]] = {
    "deriv": lambda symbol, seconds, count, key, base: "",
    "alpha_vantage": _alpha_url,
    "finnhub": _finnhub_url,
    "binance": _binance_url,
    "twelve_data": _twelve_url,
}
_PARSERS: dict[str, Callable[[str], list[Candle]]] = {
    "deriv": lambda payload: _check_candles(json.loads(payload), "Deriv"),
    "alpha_vantage": _parse_alpha_vantage,
    "finnhub": _parse_finnhub,
    "binance": _parse_binance,
    "twelve_data": _parse_twelve_data,
}


def provider_names() -> list[str]:
    """Ordered provider keys for dropdowns and settings validation."""
    return list(PROVIDERS)


def resolve_provider(name: str) -> ProviderSpec:
    try:
        return PROVIDERS[name.strip().lower()]
    except (AttributeError, KeyError):
        raise ValueError(
            f"unknown provider {name!r}; choose from {', '.join(PROVIDERS)}"
        ) from None


# ===========================================================================
# Response cache: short-TTL, per-request-key (roadmap #105)
# ===========================================================================


class ProviderResponseCache:
    """In-memory TTL cache in front of provider fetches.

    Repeated analysis within the TTL window (default 30 s) is served from
    memory instead of hammering the provider and its rate limits. Entries are
    keyed by the exact request tuple; ``invalidate`` clears everything so
    tests and explicit refreshes can force a live fetch.
    """

    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 128) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[tuple, tuple[float, list[Candle]]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> list[Candle] | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        stamp, candles = entry
        if time.monotonic() - stamp > self.ttl_seconds:
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return list(candles)

    def put(self, key: tuple, candles: list[Candle]) -> None:
        if len(self._entries) >= self.max_entries:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]
        self._entries[key] = (time.monotonic(), list(candles))

    def invalidate(self) -> None:
        self._entries.clear()

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
        }


_RESPONSE_CACHE = ProviderResponseCache()


# ===========================================================================
# Key store: provider-keys.json (owner-only file) with environment fallback
# ===========================================================================


class ProviderKeyStore:
    """Persists provider API keys next to the other local credential files."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "provider-keys.json"

    def load(self) -> dict[str, str]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {}
        return {
            str(name): str(value)
            for name, value in document.items()
            if isinstance(name, str) and isinstance(value, str) and value
        }

    def set(self, provider: str, key: str) -> None:
        keys = self.load()
        if key:
            keys[provider] = key
        else:
            keys.pop(provider, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .storage import _atomic_json_write

        _atomic_json_write(self.path, keys)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._restrict_permissions()

    def _restrict_permissions(self) -> None:
        import stat

        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def get(self, provider: str) -> str:
        """Store value first, then the matching environment variable."""
        stored = self.load().get(provider, "")
        spec = PROVIDERS.get(provider)
        if spec and spec.env_var:
            env_value = os.environ.get(spec.env_var, "").strip()
            if env_value:
                return env_value
        return stored


# ===========================================================================
# Fetch pipeline
# ===========================================================================

_DEFAULT_FETCH = _http_get


def get_candles(
    provider: str,
    symbol: str,
    timeframe: str,
    count: int = 300,
    *,
    keystore: ProviderKeyStore | None = None,
    fetcher: Callable[[str], str] | None = None,
    base_urls: Mapping[str, str] | None = None,
) -> list[Candle]:
    """Historical candles from any registered provider, oldest first.

    ``fetcher`` lets tests and offline tools inject canned payloads; ``base_urls``
    overrides provider endpoints ( proxies/self-hosted gateways). Deriv uses the
    existing WebSocket history fetch; the rest use bounded HTTPS GET.
    """
    spec = resolve_provider(provider)
    seconds = TIMEFRAMES[timeframe] if timeframe in TIMEFRAMES else int(timeframe)
    cache_key = (spec.key, symbol, timeframe, int(count))
    cached = _RESPONSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    candles: list[Candle]
    if spec.key == "deriv":
        from .stream import fetch_candles

        candles = fetch_candles(symbol, seconds, min(int(count), 1000))
    else:
        key = (keystore or ProviderKeyStore()).get(spec.key)
        if spec.requires_key and not key:
            raise ProviderError(
                f"{spec.label} needs an API key; add one in SETTINGS > DATA PROVIDERS"
            )
        base = (base_urls or {}).get(spec.key, "")
        url = spec.build_url(symbol, seconds, int(count), key, base)
        fetch = fetcher or _DEFAULT_FETCH
        candles = spec.parse(fetch(url))
        limit = int(count)
        if limit and len(candles) > limit:
            candles = candles[-limit:]
        if fetcher is None:
            # Only live fetches are cached; injected test fetchers are not.
            _RESPONSE_CACHE.put(cache_key, candles)
    return candles


def provider_key_issues(
    provider: str, keystore: ProviderKeyStore | None = None
) -> str | None:
    """Human-readable reason a provider cannot run yet, or None when ready."""
    spec = resolve_provider(provider)
    if not spec.requires_key:
        return None
    store = keystore or ProviderKeyStore()
    if not store.get(spec.key):
        return f"{spec.label} is missing an API key ({spec.env_var} or settings)"
    return None


def default_settings_provider(settings: Any) -> str:
    """Workspace-configured provider, falling back to Deriv when unknown."""
    value = getattr(settings, "market_data_provider", "deriv")
    try:
        resolve_provider(value)
        return value
    except (ValueError, AttributeError):
        return "deriv"
