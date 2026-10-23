"""``neezy-cli indicators``: the advanced indicator suite for one market."""

from __future__ import annotations

from typing import Any, TextIO

from ..indicators import advanced_suite, analyze
from ..ui_style import kv_grid, sparkline, state_dot
from .common import _emit, _symbol


def cmd_indicators(args, fetch, out: TextIO) -> int:
    symbol = _symbol(args.symbol)
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}[args.timeframe]
    candles = fetch(symbol, seconds, args.count)
    if len(candles) < 30:
        raise ValueError(
            f"only {len(candles)} candles returned; the advanced suite "
            "needs at least 30 closed candles"
        )
    suite = advanced_suite(candles)
    core = analyze(candles) or {}
    if args.json:
        _emit(
            out,
            {
                "symbol": symbol,
                "timeframe": args.timeframe,
                "candles": suite["candles"],
                "core": {
                    key: core.get(key)
                    for key in ("signal", "score", "rsi", "atr", "atr_pct", "trend")
                },
                "advanced": suite["values"],
                "warmup": suite["warmup"],
            },
        )
        return 0

    out.write(f"{symbol} {args.timeframe} - advanced indicator suite\n")
    out.write(
        f"core read: {core.get('signal', 'n/a')} "
        f"(score {core.get('score', 0)}), trend {core.get('trend', 'n/a')}\n\n"
    )
    closes = [row[4] for row in candles[:-1]]
    if len(closes) >= 8:
        out.write("close trend: " + sparkline(closes[-40:], width=40) + "\n\n")
    values: dict[str, Any] = suite["values"]
    pairs: list[tuple[str, str]] = []
    pairs.append(("rsi", _fmt(core.get("rsi"))))
    pairs.append(("atr_pct", _fmt(core.get("atr_pct"), suffix="%")))
    pairs.append(("cci", _fmt(values.get("cci"))))
    pairs.append(("williams_r", _fmt(values.get("williams_r"))))
    pairs.append(("roc", _fmt(values.get("roc"), suffix="%")))
    pairs.append(("trix", _fmt(values.get("trix"), suffix="%")))
    pairs.append(("choppiness", _fmt(values.get("choppiness"))))
    pairs.append(("fisher", _fmt(values.get("fisher_transform"))))
    pairs.append(("ult_osc", _fmt(values.get("ultimate_oscillator"))))
    aroon = values.get("aroon")
    if isinstance(aroon, dict):
        pairs.append(("aroon", f"up {aroon['up']:.0f} / down {aroon['down']:.0f}"))
    ichimoku = values.get("ichimoku")
    if isinstance(ichimoku, dict):
        pairs.append(("ichimoku", f"cloud {ichimoku['cloud']}"))
    pivots = values.get("pivot_points")
    if isinstance(pivots, dict):
        pairs.append(("pivot_pp", _fmt(pivots.get("pp"))))
    elder = values.get("elder_ray")
    if isinstance(elder, dict):
        pairs.append(("elder_ray", f"bull {elder['bull_power']:+.4f}"))
    pairs.append(("zscore", _fmt(values.get("zscore"))))
    for line in kv_grid(pairs):
        out.write("  " + line + "\n")
    if suite["warmup"]:
        out.write(
            f"\n{state_dot('pending')} warming up (need more candles): "
            + ", ".join(suite["warmup"])
            + "\n"
        )
    out.write("\nEducational analysis only, not financial advice.\n")
    return 0


def _fmt(value: Any, *, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:+.3f}{suffix}" if value < 0 else f"{value:.3f}{suffix}"
    return str(value)
