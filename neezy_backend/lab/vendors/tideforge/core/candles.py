"""Candle model, series container and CSV/JSON IO for TideForge.

A candle is a single OHLC bar. `CandleSeries` is an immutable-by-convention
list of candles sorted ascending by epoch timestamp with de-duplication and
gap handling built in.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

log = logging.getLogger("tideforge.candles")


@dataclass(frozen=True)
class Candle:
    """One OHLC bar.

    Attributes:
        epoch: bar open time, seconds since Unix epoch (UTC).
        open / high / low / close: prices in quote units.
        tick_count: optional number of ticks aggregated into the bar
            (used by TDGZ as a density proxy; 0 when unknown).
    """

    epoch: int
    open: float
    high: float
    low: float
    close: float
    tick_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.high < max(self.open, self.close) - 1e-12
            or self.low > min(self.open, self.close) + 1e-12
        ):
            raise ValueError(
                f"inconsistent OHLC at epoch={self.epoch}: "
                f"O={self.open} H={self.high} L={self.low} C={self.close}"
            )

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass
class CandleSeries:
    """Ordered, de-duplicated OHLC series."""

    symbol: str
    granularity: int  # seconds per bar
    candles: List[Candle] = field(default_factory=list)

    # ------------------------------------------------------------------ core
    @property
    def epochs(self) -> Sequence[int]:
        return [c.epoch for c in self.candles]

    @property
    def closes(self) -> Sequence[float]:
        return [c.close for c in self.candles]

    def __len__(self) -> int:
        return len(self.candles)

    def validate_and_sort(self) -> "CandleSeries":
        """Sort ascending by epoch, drop duplicates, log the dropped count."""
        seen: dict[int, Candle] = {}
        dropped = 0
        for c in self.candles:
            if c.epoch in seen:
                dropped += 1
                # keep the later-arriving (usually corrected) value
            seen[c.epoch] = c
        if dropped:
            log.warning("dropped %d duplicate candles for %s", dropped, self.symbol)
        self.candles = [seen[e] for e in sorted(seen)]
        return self

    def gaps(self) -> List[tuple[int, int]]:
        """Return [(missing_epoch_start, missing_epoch_end)] for missing bars."""
        out: List[tuple[int, int]] = []
        step = self.granularity
        for a, b in zip(self.candles, self.candles[1:]):
            delta = b.epoch - a.epoch
            if delta > step:
                out.append((a.epoch + step, b.epoch - step))
        return out

    def slice(self, start: int, end: int) -> "CandleSeries":
        cs = [c for c in self.candles if start <= c.epoch <= end]
        return CandleSeries(self.symbol, self.granularity, cs)

    # ------------------------------------------------------------------- IO
    @classmethod
    def from_rows(
        cls, symbol: str, granularity: int, rows: Iterable[Sequence]
    ) -> "CandleSeries":
        candles: List[Candle] = []
        for row in rows:
            # accepts [epoch, open, high, low, close] or with tick_count 6th
            epoch, o, h, l, c = (
                row[0],
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
            )
            ticks = int(row[5]) if len(row) > 5 and row[5] is not None else 0
            candles.append(Candle(int(epoch), o, h, l, c, ticks))
        return cls(symbol, granularity, candles).validate_and_sort()

    @classmethod
    def from_csv(
        cls, path: str | Path, symbol: str = "", granularity: int = 0
    ) -> "CandleSeries":
        path = Path(path)
        rows: List[List] = []
        with path.open(newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            for row in reader:
                if not row or row[0].startswith("#"):
                    continue
                rows.append(row)
        if header and header[0].strip().lower() in ("epoch", "time", "timestamp"):
            rows = rows  # header already consumed
        symbol = symbol or (path.stem.split("_")[0] if path.stem else "UNKNOWN")
        granularity = granularity or 3600
        return cls.from_rows(symbol, granularity, rows)

    def to_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["epoch", "open", "high", "low", "close", "tick_count"])
            for c in self.candles:
                w.writerow([c.epoch, c.open, c.high, c.low, c.close, c.tick_count])

    @classmethod
    def from_json(cls, path: str | Path) -> "CandleSeries":
        data = json.loads(Path(path).read_text())
        return cls.from_rows(
            data["symbol"], int(data.get("granularity", 3600)), data["candles"]
        )

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "symbol": self.symbol,
                    "granularity": self.granularity,
                    "candles": [
                        [c.epoch, c.open, c.high, c.low, c.close, c.tick_count]
                        for c in self.candles
                    ],
                }
            )
        )


def fill_forward_gaps(series: CandleSeries) -> CandleSeries:
    """Insert flat carry-forward candles into missing slots.

    Missing bars are filled with open=high=low=close=previous close and
    tick_count=0, and flagged in the log. Indicators treat zero-range filled
    bars as neutral (they contribute nothing to volatility or slope).
    """
    out: List[Candle] = []
    step = series.granularity
    prev: Optional[Candle] = None
    n_filled = 0
    for c in series.candles:
        if prev is not None:
            t = prev.epoch + step
            while t < c.epoch:
                out.append(Candle(t, prev.close, prev.close, prev.close, prev.close, 0))
                n_filled += 1
                t += step
        out.append(c)
        prev = c
    if n_filled:
        log.info(
            "fill_forward_gaps: inserted %d flat candles for %s",
            n_filled,
            series.symbol,
        )
    return CandleSeries(series.symbol, series.granularity, out)
