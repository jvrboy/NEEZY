"""Backend analysis agent: scan a watchlist into card-ready confluence signals.

:class:`ConfluenceAnalyzer` is the "agent" behind the SIGNALS ANALYSIS button.
It runs the full confluence engine across every requested market in one pass,
records strict-mode results first, then:
relaxes into search mode for the rest so the caller always receives signals,
and returns per-market errors separately so the UI can surface provider or
network problems without losing the already-found signals.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import AppSettings
from .confluence import ConfluenceSignal, build_confluence
from .markets import display_name


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Signals for a pass over one or more markets."""

    signals: tuple[ConfluenceSignal, ...] = ()
    errors: dict[str, str] = field(default_factory=dict)
    mode: str = "strict"
    duration_seconds: float = 0.0
    scanned: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scanned": self.scanned,
            "duration_seconds": round(self.duration_seconds, 2),
            "signals": [signal.to_dict() for signal in self.signals],
            "errors": dict(self.errors),
        }

    def summary(self) -> str:
        """Short human line for status labels."""
        label = "signal" if len(self.signals) == 1 else "signals"
        base = f"{len(self.signals)} {label} from {self.scanned} market(s)"
        if self.errors:
            base += f" · {len(self.errors)} unavailable"
        return base


class ConfluenceAnalyzer:
    """Combine the whole backend into scanner passes over a watchlist.

    ``candle_source`` supplies history for one market; the default source is the
    workspace-configured data provider (Deriv stream for live buffers and the
    REST providers otherwise). Passing ``None`` candles or letting the source
    raise registers a per-market error and the pass continues.
    """

    def __init__(
        self,
        candle_source: Callable[[str, str], list[tuple]] | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self.candle_source = candle_source
        self.settings = settings

    def _candles_for(self, symbol: str, timeframe: str) -> list[tuple]:
        if self.candle_source is None:
            raise ValueError("no candle source configured")
        return self.candle_source(symbol, timeframe)

    def analyze_symbol(
        self,
        symbol: str,
        timeframe: str,
        *,
        search: bool = False,
    ) -> ConfluenceSignal | None:
        try:
            candles = self._candles_for(symbol, timeframe)
        except Exception as error:  # provider/network errors are per-market only
            raise ConnectionError(f"{display_name(symbol)}: {error}") from error
        signal = build_confluence(
            candles,
            symbol,
            timeframe,
            min_score=(
                self.settings.confluence_min_score
                if self.settings is not None
                else 55.0
            ),
            search=search,
            stop_mult=(
                self.settings.confluence_atr_stop_mult
                if self.settings is not None
                else 1.5
            ),
            tp_mult=(
                self.settings.confluence_atr_tp_mult
                if self.settings is not None
                else 2.5
            ),
            horizon=(
                self.settings.confluence_horizon if self.settings is not None else 20
            ),
            min_analogs=(
                self.settings.confluence_min_analogs if self.settings is not None else 4
            ),
            instrument=display_name(symbol),
        )
        if signal is None and search:
            raise ValueError(f"{display_name(symbol)}: not enough closed candles")
        return signal

    def scan(
        self,
        symbols: Mapping[str, str] | list[str] | tuple[str, ...],
        timeframe: str,
        *,
        search: bool = False,
    ) -> ScanResult:
        """Strict pass over every market; search mode only when asked."""
        names = (
            list(symbols) if not isinstance(symbols, Mapping) else list(symbols.keys())
        )
        started = time.monotonic()
        signals: list[ConfluenceSignal] = []
        errors: dict[str, str] = {}
        for symbol in names:
            try:
                signal = self.analyze_symbol(symbol, timeframe, search=search)
            except (ConnectionError, ValueError) as error:
                errors[symbol] = str(error)
                continue
            if signal is not None:
                signals.append(signal)
        duration = time.monotonic() - started
        signals.sort(key=lambda item: -item.score)
        return ScanResult(
            signals=tuple(signals),
            errors=errors,
            mode="search" if search else "strict",
            duration_seconds=duration,
            scanned=len(names),
        )

    def full_analysis(
        self,
        symbols: Mapping[str, str] | list[str] | tuple[str, ...],
        timeframe: str,
    ) -> ScanResult:
        """The ANALYSIS button pipeline: strict first, search fills the rest.

        This method always yields signals for markets with enough candles - the
        strict pass filters, then the search pass converts every remaining
        market into a signal even when its confluence is weak.
        """
        names = (
            list(symbols) if not isinstance(symbols, Mapping) else list(symbols.keys())
        )
        started = time.monotonic()
        signals: list[ConfluenceSignal] = []
        errors: dict[str, str] = {}
        pending: list[str] = []
        for symbol in names:
            try:
                signal = self.analyze_symbol(symbol, timeframe, search=False)
            except (ConnectionError, ValueError) as error:
                errors[symbol] = str(error)
                continue
            if signal is None:
                pending.append(symbol)
            else:
                signals.append(signal)
        for symbol in pending:
            try:
                signal = self.analyze_symbol(symbol, timeframe, search=True)
            except (ConnectionError, ValueError) as error:
                errors[symbol] = str(error)
                continue
            if signal is None:
                errors[symbol] = "not enough closed candles"
            else:
                signals.append(signal)
        duration = time.monotonic() - started
        signals.sort(key=lambda item: -item.score)
        return ScanResult(
            signals=tuple(signals),
            errors=errors,
            mode="full",
            duration_seconds=duration,
            scanned=len(names),
        )
