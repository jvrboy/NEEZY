"""Bridge between the Kivy screens and the shared neezy_backend package.

Nothing in here touches Kivy, so the same logic can be exercised from a plain
Python shell during development.
"""

from __future__ import annotations

from pathlib import Path

from neezy_backend.alerts import AlertRuleStore
from neezy_backend.config import AppSettings
from neezy_backend.markets import granularity, watchlist, ws_urls
from neezy_backend.scanner import ConfluenceAnalyzer, ScanResult
from neezy_backend.storage import ConfluenceHistoryStore, SettingsStore
from neezy_backend.stream import fetch_candles

# Mobile networks are slow and memory is tight: cap history well below the
# Deriv limit of 5000 candles.
MAX_CANDLES = 1000
MIN_CANDLES = 100


class Services:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._settings_store = SettingsStore(data_dir / "settings.json")
        self.history = ConfluenceHistoryStore(data_dir / "confluence-history.jsonl")
        self.alerts = AlertRuleStore(data_dir / "alert-rules.json")
        self.settings: AppSettings = self._settings_store.load()

    def save_settings(self, settings: AppSettings) -> None:
        self._settings_store.save(settings)
        self.settings = settings

    def watch_symbols(self) -> dict[str, str]:
        return watchlist(self.settings.watchlist_extra)

    def candles(self, symbol: str, timeframe: str) -> list[tuple]:
        """Oldest-first five-tuples for one market. Used as the scanner source."""
        count = max(MIN_CANDLES, min(int(self.settings.history_candles), MAX_CANDLES))
        return fetch_candles(
            symbol,
            granularity(timeframe),
            count,
            url=ws_urls(self.settings.deriv_endpoint),
            timeout=self.settings.ml_fetch_timeout,
        )

    def scan(self, timeframe: str) -> ScanResult:
        """ANALYSIS pass over the watchlist; every signal is written to history."""
        analyzer = ConfluenceAnalyzer(
            candle_source=self.candles,
            settings=self.settings,
        )
        result = analyzer.full_analysis(self.watch_symbols(), timeframe)
        for signal in result.signals:
            self.history.append(signal.as_history_record())
        return result
