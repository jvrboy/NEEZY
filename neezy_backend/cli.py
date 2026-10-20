"""Headless NEEZY command-line tools: scan, analyze, backtest, risk, and more.

Run ``neezy-cli --help`` (or ``python -m neezy_backend --help``). Market data
comes from Deriv's public API. Output is educational, not financial advice.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .alerts import METRICS, OPERATORS, AlertRule, AlertRuleStore
from .analytics import correlation_matrix, rank_opportunities, strongest_pairs
from .backtest import BacktestConfig, run_backtest
from .indicators import analyze
from .markets import (
    SYMBOLS,
    TIMEFRAMES,
    WS_URL,
    display_name,
    format_price,
    granularity,
    pip_size,
)
from .patterns import price_action_summary
from .risk import atr_levels, position_size
from .storage import SignalHistoryStore
from .stream import fetch_candles

Fetcher = Callable[[str, int, int], list[tuple[int, float, float, float, float]]]


def _default_fetch(symbol: str, seconds: int, count: int):
    return fetch_candles(symbol, seconds, count, url=WS_URL)


def _symbol(value: str) -> str:
    candidates = {key.upper(): key for key in SYMBOLS}
    candidates.update(
        {name.replace("/", "").upper(): key for key, name in SYMBOLS.items()}
    )
    key = value.replace("/", "").upper()
    if key in candidates:
        return candidates[key]
    if ("FRX" + key) in candidates:
        return candidates["FRX" + key]
    raise argparse.ArgumentTypeError(
        f"unknown market {value!r}; run 'neezy-cli markets' to list them"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    raise TypeError(f"not serialisable: {type(value).__name__}")


def _emit(out: TextIO, data: Any) -> None:
    out.write(json.dumps(_finite(data), indent=2, default=_json_default) + "\n")


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(item) for item in value]
    return value


def _table(out: TextIO, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [
        max(len(header), *(len(row[i]) for row in cells)) if cells else len(header)
        for i, header in enumerate(headers)
    ]
    out.write(
        "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)) + "\n"
    )
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row in cells:
        out.write(
            "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) + "\n"
        )


def _without_series(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "closes"}


def cmd_markets(args, fetch, out) -> int:
    if args.json:
        _emit(out, {"markets": SYMBOLS, "timeframes": TIMEFRAMES})
        return 0
    _table(
        out,
        ["SYMBOL", "MARKET", "PIP"],
        [(s, n, pip_size(s)) for s, n in SYMBOLS.items()],
    )
    out.write("\nTimeframes: " + ", ".join(TIMEFRAMES) + "\n")
    return 0


def cmd_scan(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    results, errors = {}, {}
    for symbol in args.symbols or list(SYMBOLS):
        try:
            result = analyze(fetch(symbol, seconds, args.count))
        except (OSError, RuntimeError, ValueError) as error:
            errors[symbol] = str(error)
            continue
        if result:
            results[symbol] = result
    ranked = rank_opportunities(results, include_neutral=True)
    if args.json:
        _emit(
            out,
            {
                "timeframe": args.timeframe,
                "ranked": ranked,
                "results": {s: _without_series(r) for s, r in results.items()},
                "errors": errors,
            },
        )
        return 0 if results else 1
    rows = []
    for item in ranked:
        result = results[item["symbol"]]
        rows.append(
            (
                display_name(item["symbol"]),
                format_price(item["symbol"], result["closes"][-1]),
                result["signal"],
                f"{result['score']:+d}",
                f"{result['rsi']:.1f}" if result["rsi"] is not None else "—",
                f"{result['adx']['adx']:.1f}" if result["adx"] else "—",
                result["regime"],
                f"{item['opportunity']:.1f}",
            )
        )
    _table(
        out, ["MARKET", "PRICE", "BIAS", "SCORE", "RSI", "ADX", "REGIME", "RANK"], rows
    )
    for symbol, message in errors.items():
        out.write(f"! {display_name(symbol)}: {message}\n")
    return 0 if results else 1


def cmd_analyze(args, fetch, out) -> int:
    candles = fetch(args.symbol, granularity(args.timeframe), args.count)
    result = analyze(candles)
    if result is None:
        out.write("Not enough closed candles for analysis (need 60).\n")
        return 1
    action = price_action_summary(candles[:-1])
    if args.json:
        _emit(out, {"analysis": _without_series(result), "price_action": action})
        return 0
    fmt = lambda price: format_price(args.symbol, price)  # noqa: E731
    out.write(f"{display_name(args.symbol)} · {args.timeframe}\n")
    out.write(
        f"{result['signal']}  score {result['score']:+d}/4  trend {result['trend']}"
    )
    out.write(f"  regime {result['regime']}\n\n")
    for reason in result["why"]:
        out.write(f"  · {reason}\n")
    out.write(f"\nEMA 9/21/50  {fmt(result['ema9'])} / {fmt(result['ema21'])} / ")
    out.write(f"{fmt(result['ema50'])}\n")
    out.write(f"ATR 14       {fmt(result['atr'])} ({result['atr_pct']:.2f}%)\n")
    if result["bollinger"]:
        bands = result["bollinger"]
        out.write(
            f"Bollinger    {fmt(bands['lower'])} to {fmt(bands['upper'])}"
            f"  %B {bands['percent_b']:.2f}\n"
        )
    if result["stochastic"]:
        out.write(
            f"Stochastic   %K {result['stochastic']['k']:.1f}"
            f"  %D {result['stochastic']['d']:.1f}\n"
        )
    if result["adx"]:
        d = result["adx"]
        out.write(
            f"ADX          {d['adx']:.1f}  +DI {d['plus_di']:.1f}"
            f"  -DI {d['minus_di']:.1f}\n"
        )
    if action["pivots"]:
        p = action["pivots"]
        out.write(
            f"Pivots       S2 {fmt(p['s2'])}  S1 {fmt(p['s1'])}  P {fmt(p['pivot'])}"
            f"  R1 {fmt(p['r1'])}  R2 {fmt(p['r2'])}\n"
        )
    levels = action["levels"]
    out.write("Support      " + (", ".join(map(fmt, levels["support"])) or "—") + "\n")
    out.write(
        "Resistance   " + (", ".join(map(fmt, levels["resistance"])) or "—") + "\n"
    )
    names = [f"{p['name']} ({p['bias']})" for p in action["patterns"]]
    out.write("Patterns     " + (", ".join(names) or "none") + "\n")
    out.write("\nEducational summary only — not financial advice.\n")
    return 0


def cmd_backtest(args, fetch, out) -> int:
    config = BacktestConfig(
        min_score=args.min_score,
        stop_atr_multiple=args.stop_atr,
        reward_to_risk=args.reward_risk,
        spread=args.spread_pips * pip_size(args.symbol),
        max_bars_in_trade=args.max_bars,
        exit_on_opposite=not args.hold_through_reversals,
    )
    candles = fetch(args.symbol, granularity(args.timeframe), args.count)
    result = run_backtest(candles, config)
    stats = result.stats
    if args.json:
        _emit(
            out,
            {"symbol": args.symbol, "timeframe": args.timeframe, **result.to_dict()},
        )
        return 0
    out.write(f"Backtest · {display_name(args.symbol)} · {args.timeframe} ")
    out.write(f"· {stats['candles_tested']} candles\n\n")
    pf = stats["profit_factor"]
    _table(
        out,
        ["METRIC", "VALUE"],
        [
            (
                "Trades",
                f"{stats['trades']} ({stats['long_trades']}L"
                f" / {stats['short_trades']}S)",
            ),
            ("Win rate", f"{stats['win_rate']:.1f}%"),
            ("Total", f"{stats['total_r']:+.2f} R"),
            ("Expectancy", f"{stats['expectancy_r']:+.3f} R / trade"),
            ("Profit factor", "∞" if math.isinf(pf) else f"{pf:.2f}"),
            ("Max drawdown", f"{stats['max_drawdown_r']:.2f} R"),
            ("Sharpe / trade", f"{stats['sharpe_per_trade']:.2f}"),
            ("Avg bars held", f"{stats['avg_bars']:.1f}"),
        ],
    )
    if args.trades:
        out.write("\n")
        _table(
            out,
            ["DIR", "ENTRY", "EXIT", "REASON", "R"],
            [
                (
                    t.direction,
                    format_price(args.symbol, t.entry),
                    format_price(args.symbol, t.exit),
                    t.reason,
                    f"{t.r_multiple:+.2f}",
                )
                for t in result.trades
            ],
        )
    out.write(
        "\nSimulated results; past performance does not predict future results.\n"
    )
    return 0


def cmd_risk(args, fetch, out) -> int:
    entry, stop = args.entry, args.stop
    if stop is None:
        if args.atr is None or args.direction is None:
            raise SystemExit("risk: provide --stop, or both --direction and --atr")
        stop, _target = atr_levels(
            args.direction, entry, args.atr, args.stop_atr, args.reward_risk
        )
    plan = position_size(
        symbol=args.symbol,
        balance=args.balance,
        risk_percent=args.risk,
        entry=entry,
        stop=stop,
        reward_to_risk=args.reward_risk,
        pip_value_per_lot=args.pip_value,
    )
    if args.json:
        _emit(out, plan.to_dict())
        return 0
    fmt = lambda price: format_price(args.symbol, price)  # noqa: E731
    _table(
        out,
        ["FIELD", "VALUE"],
        [
            ("Direction", plan.direction),
            ("Entry", fmt(plan.entry)),
            ("Stop", f"{fmt(plan.stop)} ({plan.stop_pips:.1f} pips)"),
            ("Target", f"{fmt(plan.target)} ({plan.target_pips:.1f} pips)"),
            ("Size", f"{plan.lots:.2f} lots ({plan.units:,} units)"),
            ("Risk", f"{plan.risk_amount:,.2f}"),
            ("Reward", f"{plan.reward_amount:,.2f}"),
        ],
    )
    return 0


def cmd_correlation(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    closes = {}
    for symbol in args.symbols or list(SYMBOLS):
        try:
            closes[symbol] = [row[4] for row in fetch(symbol, seconds, args.window + 1)]
        except (OSError, RuntimeError, ValueError) as error:
            out.write(f"! {display_name(symbol)}: {error}\n")
    matrix = correlation_matrix(closes, window=args.window)
    pairs = strongest_pairs(matrix, limit=args.top)
    if args.json:
        _emit(out, {"matrix": matrix, "strongest": pairs})
        return 0
    _table(
        out,
        ["PAIR A", "PAIR B", "CORRELATION"],
        [(display_name(a), display_name(b), f"{v:+.2f}") for a, b, v in pairs],
    )
    return 0


def cmd_history(args, fetch, out) -> int:
    store = SignalHistoryStore()
    if args.export:
        out.write(f"Exported {store.export_csv(Path(args.export))} records\n")
        return 0
    if args.compact:
        out.write(f"Kept {store.compact(args.compact)} records\n")
        return 0
    if args.summary:
        summary = store.summary()
        if args.json:
            _emit(out, summary)
        else:
            out.write(f"{summary['total']} transitions\n")
            _table(out, ["SIGNAL", "COUNT"], sorted(summary["by_signal"].items()))
        return 0
    records = store.read(limit=args.limit)
    if args.json:
        _emit(out, records)
        return 0
    _table(
        out,
        ["TIME", "MARKET", "FROM", "TO", "PRICE", "SCORE"],
        [
            (
                r["timestamp"][:19],
                display_name(r["symbol"]),
                r["previous"],
                r["current"],
                format_price(r["symbol"], r["price"]),
                f"{r['score']:+d}",
            )
            for r in records
        ],
    )
    return 0


def cmd_alerts(args, fetch, out) -> int:
    store = AlertRuleStore()
    rules = store.load()
    if args.action == "add":
        rule = AlertRule(
            symbol="*" if args.symbol == "*" else _symbol(args.symbol),
            metric=args.metric,
            operator=args.operator,
            value=args.value,
            note=args.note or "",
        )
        store.save([*rules, rule])
        out.write(f"Added {rule.rule_id}: {rule.describe()}\n")
        return 0
    if args.action == "remove":
        remaining = [rule for rule in rules if rule.rule_id != args.rule_id]
        if len(remaining) == len(rules):
            out.write(f"No rule with id {args.rule_id}\n")
            return 1
        store.save(remaining)
        out.write(f"Removed {args.rule_id}\n")
        return 0
    if args.json:
        _emit(out, [asdict(rule) for rule in rules])
        return 0
    _table(
        out,
        ["ID", "RULE", "ENABLED", "NOTE"],
        [
            (r.rule_id, r.describe(), "yes" if r.enabled else "no", r.note)
            for r in rules
        ],
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neezy-cli",
        description="NEEZY market tools (educational analysis, not financial advice).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, *, timeframe=True, count=None):
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if timeframe:
            p.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
        if count:
            p.add_argument(
                "-n", "--count", type=int, default=count, help="candles to fetch"
            )
        return p

    p = common(
        sub.add_parser("markets", help="list supported markets"), timeframe=False
    )
    p.set_defaults(handler=cmd_markets)

    p = common(
        sub.add_parser("scan", help="rank all markets by signal strength"), count=300
    )
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.set_defaults(handler=cmd_scan)

    p = common(
        sub.add_parser("analyze", help="full indicator & price-action read"), count=300
    )
    p.add_argument("symbol", type=_symbol)
    p.set_defaults(handler=cmd_analyze)

    p = common(
        sub.add_parser("backtest", help="simulate the signal engine"), count=2000
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--min-score", type=int, default=2)
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--reward-risk", type=float, default=2.0)
    p.add_argument("--spread-pips", type=float, default=0.0)
    p.add_argument("--max-bars", type=int, default=0, help="time stop (0 = off)")
    p.add_argument("--hold-through-reversals", action="store_true")
    p.add_argument("--trades", action="store_true", help="list every trade")
    p.set_defaults(handler=cmd_backtest)

    p = common(sub.add_parser("risk", help="position size calculator"), timeframe=False)
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--balance", type=float, required=True)
    p.add_argument("--risk", type=float, default=1.0, help="percent of balance")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float)
    p.add_argument("--direction", type=str.upper, choices=["BUY", "SELL"])
    p.add_argument("--atr", type=float, help="ATR value for an ATR-based stop")
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--reward-risk", type=float, default=2.0)
    p.add_argument("--pip-value", type=float, default=10.0, help="per standard lot")
    p.set_defaults(handler=cmd_risk)

    p = common(sub.add_parser("correlation", help="cross-market return correlation"))
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.add_argument("--window", type=int, default=100)
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(handler=cmd_correlation)

    p = common(
        sub.add_parser("history", help="local signal-transition history"),
        timeframe=False,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true")
    group.add_argument("--export", metavar="CSV")
    group.add_argument("--compact", type=int, metavar="KEEP")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(handler=cmd_history)

    p = common(sub.add_parser("alerts", help="manage alert rules"), timeframe=False)
    p.set_defaults(handler=cmd_alerts)
    actions = p.add_subparsers(dest="action")
    add = actions.add_parser("add")
    add.add_argument("symbol", help="market or * for all markets")
    add.add_argument("metric", choices=METRICS)
    add.add_argument("operator", choices=OPERATORS)
    add.add_argument("value")
    add.add_argument("--note")
    remove = actions.add_parser("remove")
    remove.add_argument("rule_id")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetcher | None = None,
    out: TextIO | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = out or sys.stdout
    try:
        return args.handler(args, fetch or _default_fetch, out)
    except (OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"neezy-cli: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
