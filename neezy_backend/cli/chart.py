"""CLI handler for responsive, closed-candle ASCII charts."""

from __future__ import annotations

import textwrap

from ..markets import display_name, format_price, granularity
from ..terminal_chart import render_ascii_chart
from .common import _emit


def _write_wrapped(out, text: str, width: int) -> None:
    lines = textwrap.wrap(
        text,
        width=max(12, width),
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    for line in lines:
        out.write(line + "\n")


def cmd_chart(args, fetch, out) -> int:
    width = max(24, min(160, args.width))
    candles = fetch(args.symbol, granularity(args.timeframe), args.count)
    chart = render_ascii_chart(candles, width=width, height=args.height)
    change = chart.change_percent
    if args.json:
        _emit(
            out,
            {
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "closed_candles": chart.total_closed,
                "plotted_candles": chart.plotted,
                "open": chart.open,
                "high": chart.high,
                "low": chart.low,
                "close": chart.close,
                "change_percent": change,
                "chart": list(chart.lines),
            },
        )
        return 0

    fmt = lambda value: format_price(args.symbol, value)  # noqa: E731
    _write_wrapped(
        out,
        (
            f"{display_name(args.symbol)} | {args.timeframe} | "
            f"{chart.total_closed} closed / {chart.plotted} plotted"
        ),
        width,
    )
    _write_wrapped(out, f"O {fmt(chart.open)} | H {fmt(chart.high)}", width)
    change_text = "n/a" if change is None else f"{change:+.3f}%"
    _write_wrapped(
        out,
        f"L {fmt(chart.low)} | C {fmt(chart.close)} | {change_text}",
        width,
    )
    out.write("\n".join(chart.lines) + "\n")
    _write_wrapped(out, "up # | down = | doji + | wick |", width)
    _write_wrapped(out, "Closed candles only; educational display.", width)
    return 0
