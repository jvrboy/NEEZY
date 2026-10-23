"""Responsive ASCII OHLC charts for terminals that cannot display GUI charts."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AsciiChart:
    lines: tuple[str, ...]
    total_closed: int
    plotted: int
    open: float
    high: float
    low: float
    close: float

    @property
    def change_percent(self) -> float | None:
        if self.open == 0:
            return None
        return (self.close - self.open) / abs(self.open) * 100.0


def _price(value: float) -> str:
    return f"{value:.6g}"


def _closed_rows(candles: Sequence[Sequence[float]]) -> list[tuple[float, ...]]:
    rows = []
    for candle in candles[:-1]:
        if len(candle) < 5:
            raise ValueError("each candle needs time, open, high, low, and close")
        try:
            row = tuple(float(value) for value in candle[:5])
        except (TypeError, ValueError) as error:
            raise ValueError("candle values must be numeric") from error
        if not all(math.isfinite(value) for value in row[1:]):
            raise ValueError("candle prices must be finite")
        _time, open_, high, low, close = row
        if high < low or high < max(open_, close) or low > min(open_, close):
            raise ValueError("candle OHLC bounds are inconsistent")
        rows.append(row)
    if not rows:
        raise ValueError("at least two candles are required for a closed-candle chart")
    return rows


def render_ascii_chart(
    candles: Sequence[Sequence[float]], *, width: int = 72, height: int = 14
) -> AsciiChart:
    """Render the latest closed candles, one ASCII column per plotted candle."""
    width = max(24, min(160, int(width)))
    height = max(6, min(30, int(height)))
    rows = _closed_rows(candles)
    all_high = max(row[2] for row in rows)
    all_low = min(row[3] for row in rows)
    axis_width = min(12, max(8, len(_price(all_high)), len(_price(all_low))))
    plot_width = max(4, width - axis_width - 1)
    selected = rows[-plot_width:]
    high = max(row[2] for row in selected)
    low = min(row[3] for row in selected)
    span = high - low

    def y(price: float) -> int:
        if span == 0:
            return height // 2
        return round((high - price) / span * (height - 1))

    grid = [[" " for _ in selected] for _ in range(height)]
    for column, row in enumerate(selected):
        _time, open_, candle_high, candle_low, close = row
        top, bottom = y(candle_high), y(candle_low)
        for line in range(top, bottom + 1):
            grid[line][column] = "|"
        open_y, close_y = y(open_), y(close)
        body = "#" if close > open_ else "=" if close < open_ else "+"
        for line in range(min(open_y, close_y), max(open_y, close_y) + 1):
            grid[line][column] = body

    lines = []
    for index, grid_row in enumerate(grid):
        price = high - (span * index / (height - 1) if height > 1 else 0)
        lines.append(f"{_price(price).rjust(axis_width)} {''.join(grid_row).rstrip()}")
    return AsciiChart(
        lines=tuple(lines),
        total_closed=len(rows),
        plotted=len(selected),
        open=selected[0][1],
        high=high,
        low=low,
        close=selected[-1][4],
    )
