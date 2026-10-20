"""Headless NEEZY command-line tools: scan, analyze, backtest, risk, and more.

Run ``neezy-cli --help`` (or ``python -m neezy_backend --help``). Market data
comes from Deriv's public API. Output is educational, not financial advice.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .ai import (
    PROVIDERS,
    AIClient,
    AIKeyStore,
    free_models,
    resolve_provider,
)
from .alerts import METRICS, OPERATORS, AlertRule, AlertRuleStore
from .analytics import correlation_matrix, rank_opportunities, strongest_pairs
from .backtest import BacktestConfig, run_backtest
from .catalog import instrument, instruments
from .context import chat_messages, format_context, market_snapshot
from .database import LocalDatabase
from .divergence import detect_divergences, rank_correlation_divergences
from .indicators import analyze
from .markets import (
    DEFAULT_WATCHLIST,
    SYMBOLS,
    TIMEFRAMES,
    display_name,
    format_price,
    granularity,
    pip_size,
    ws_urls,
)
from .patterns import price_action_summary
from .risk import atr_levels, position_size
from .storage import SignalHistoryStore
from .strategies import (
    STRATEGIES,
    consensus,
    describe_strategies,
    evaluate,
    run_all,
)
from .stream import fetch_candles, probe_endpoint
from .trend import trend_summary

Fetcher = Callable[[str, int, int], list[tuple[int, float, float, float, float]]]


def _default_fetch(symbol: str, seconds: int, count: int):
    # No explicit url: fetch_candles rotates through every configured endpoint.
    return fetch_candles(symbol, seconds, count)


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
    category = getattr(args, "category", None)
    selected = {
        symbol: name
        for symbol, name in SYMBOLS.items()
        if not category or instrument(symbol).market == category
    }
    if args.json:
        _emit(
            out,
            {
                "markets": selected,
                "timeframes": TIMEFRAMES,
                "categories": sorted({item.market for item in instruments().values()}),
            },
        )
        return 0
    _table(
        out,
        ["SYMBOL", "MARKET", "PIP"],
        [(s, n, pip_size(s)) for s, n in selected.items()],
    )
    out.write("\nTimeframes: " + ", ".join(TIMEFRAMES) + "\n")
    return 0


def cmd_doctor(args, fetch, out) -> int:
    """Probe each market-data endpoint so connection problems are diagnosable."""
    results = [(url, *probe_endpoint(url, timeout=args.timeout)) for url in ws_urls()]
    if args.json:
        _emit(
            out,
            [
                {"url": url, "reachable": ok, "detail": detail}
                for url, ok, detail in results
            ],
        )
        return 0 if any(ok for _, ok, _ in results) else 1
    _table(
        out,
        ["ENDPOINT", "STATUS", "DETAIL"],
        [(url, "ok" if ok else "failed", detail) for url, ok, detail in results],
    )
    if not any(ok for _, ok, _ in results):
        out.write(
            "\nNo endpoint answered. The network, a VPN/proxy, or a firewall is "
            "blocking Deriv. Try another network, or set NEEZY_WS_URL to an "
            "endpoint you know works.\n"
        )
        return 1
    return 0


def cmd_scan(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    results, errors = {}, {}
    for symbol in args.symbols or list(DEFAULT_WATCHLIST):
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
    for symbol in args.symbols or list(DEFAULT_WATCHLIST):
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


def _closed(candles):
    return list(candles[:-1]) if len(candles) > 1 else []


def cmd_read(args, fetch, out) -> int:
    """One full advanced read: engine, Supertrend, divergence, strategies."""
    seconds = granularity(args.timeframe)
    candles = fetch(args.symbol, seconds, args.count)
    snapshot = market_snapshot(
        candles,
        symbol=args.symbol,
        timeframe=args.timeframe,
        strategy=args.strategy,
        supertrend_period=args.period,
        supertrend_multiplier=args.multiplier,
        divergence_lookback=args.lookback,
    )
    if snapshot is None:
        raise RuntimeError("not enough closed candles to analyse this market yet")
    if args.json:
        _emit(out, snapshot)
        return 0
    out.write(f"{display_name(args.symbol)}  ·  {args.timeframe}\n")
    out.write(
        f"price {snapshot['price_display']}   engine {snapshot['signal']} "
        f"({snapshot['score']:+d}/4)   regime {snapshot['regime']}\n"
    )
    trend = snapshot["supertrend"]
    out.write(
        f"Supertrend {trend['label']} · line {trend['line']} · "
        f"{trend['bars_since_flip']} bars since flip\n"
    )
    out.write(
        f"RSI {snapshot['rsi']:.2f}   ATR {snapshot['atr_pct']:.3f}%   "
        f"MACD hist {snapshot['macd_histogram']:+.6f}\n"
    )
    divergences = snapshot["divergences"]
    out.write(
        "Divergences: "
        + (
            ", ".join(
                f"{item['kind']} {item['oscillator'].upper()} "
                f"({item['bars_ago']}b, {item['strength']:.0%})"
                for item in divergences
            )
            or "none"
        )
        + "\n"
    )
    strategy = snapshot["strategy"]
    out.write(
        f"\n{strategy['strategy']}: {strategy['label']} "
        f"({strategy['confidence']:.0f}% confidence) - {strategy['summary']}\n"
    )
    for reason in strategy["reasons"]:
        out.write(f"  · {reason}\n")
    verdict = snapshot["consensus"]
    out.write(
        f"\nConsensus across strategies: {verdict['label']} "
        f"({verdict['confidence']:.0f}%) votes {verdict['votes']}\n"
    )
    return 0


def cmd_supertrend(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    candles = fetch(args.symbol, seconds, args.count)
    closed = _closed(candles)
    summary = trend_summary(closed, args.period, args.multiplier)
    signal = evaluate(
        "SUPERTREND", candles, period=args.period, multiplier=args.multiplier
    )
    payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "period": args.period,
        "multiplier": args.multiplier,
        "trend": summary,
        "signal": signal.to_dict(),
    }
    if args.json:
        _emit(out, payload)
        return 0
    _table(
        out,
        ["FIELD", "VALUE"],
        [
            ("market", display_name(args.symbol)),
            ("timeframe", args.timeframe),
            ("direction", summary["label"]),
            ("line", summary["line"]),
            (
                "distance",
                f"{summary['distance_pct']}%"
                if summary["distance_pct"] is not None
                else "n/a",
            ),
            ("bars since flip", summary["bars_since_flip"]),
            ("strategy", f"{signal.label} ({signal.confidence:.0f}%)"),
            ("summary", signal.summary),
        ],
    )
    return 0


def cmd_divergence(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    candles = fetch(args.symbol, seconds, args.count)
    found = detect_divergences(_closed(candles), args.lookback)
    payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "lookback": args.lookback,
        "divergences": found,
    }
    if args.json:
        _emit(out, payload)
        return 0
    if not found:
        out.write(
            f"No RSI or MACD divergence within {args.lookback} bars of the last "
            f"swing for {display_name(args.symbol)}.\n"
        )
        return 0
    _table(
        out,
        ["OSCILLATOR", "KIND", "BARS AGO", "STRENGTH", "PRICE PIVOTS", "OSC PIVOTS"],
        [
            (
                item["oscillator"].upper(),
                item["kind"],
                item["bars_ago"],
                f"{item['strength']:.0%}",
                " -> ".join(f"{point['price']:.5f}" for point in item["price_points"]),
                " -> ".join(
                    f"{point['value']:.2f}" for point in item["oscillator_points"]
                ),
            )
            for item in found
        ],
    )
    return 0


def cmd_corrdiv(args, fetch, out) -> int:
    seconds = granularity(args.timeframe)
    symbols = args.symbols or list(SYMBOLS)
    closes = {}
    for symbol in symbols:
        try:
            closes[symbol] = [
                row[4] for row in fetch(symbol, seconds, args.window + args.baseline)
            ]
        except (OSError, RuntimeError, ValueError) as error:
            out.write(f"! {display_name(symbol)}: {error}\n")
    ranked = rank_correlation_divergences(
        closes, window=args.window, baseline=args.baseline, limit=args.top
    )
    if args.json:
        _emit(out, ranked)
        return 0
    if not ranked:
        out.write("Not enough overlapping history to compare these markets.\n")
        return 0
    _table(
        out,
        ["PAIR", "STATE", "BASELINE", "RECENT", "DELTA", "STRENGTH"],
        [
            (
                f"{display_name(item['first'])} / {display_name(item['second'])}",
                item["state"],
                f"{item['baseline']:+.2f}",
                f"{item['recent']:+.2f}",
                f"{item['delta']:+.2f}",
                f"{item['strength']:.0%}",
            )
            for item in ranked
        ],
    )
    return 0


def cmd_strategies(args, fetch, out) -> int:
    if not args.symbol:
        catalogue = describe_strategies()
        if args.json:
            _emit(out, catalogue)
            return 0
        _table(
            out,
            ["NAME", "LABEL", "MARKETS", "DESCRIPTION"],
            [
                (
                    item["name"],
                    item["label"],
                    "pair" if item["pair"] else "single",
                    item["description"],
                )
                for item in catalogue
            ],
        )
        out.write("\nRun 'neezy-cli strategies EURUSD -t 15m' to score them all.\n")
        return 0
    seconds = granularity(args.timeframe)
    candles = fetch(args.symbol, seconds, args.count)
    signals = run_all(candles)
    verdict = consensus(signals)
    payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "strategies": [signal.to_dict() for signal in signals],
        "consensus": verdict,
    }
    if args.json:
        _emit(out, payload)
        return 0
    _table(
        out,
        ["STRATEGY", "CALL", "CONFIDENCE", "SUMMARY"],
        [
            (
                signal.strategy,
                signal.label,
                f"{signal.confidence:.0f}%",
                signal.summary,
            )
            for signal in signals
        ],
    )
    out.write(
        f"\nConsensus: {verdict['label']} ({verdict['confidence']:.0f}%) "
        f"- votes {verdict['votes']}\n"
    )
    return 0


def _open_database() -> LocalDatabase:
    return LocalDatabase()


def cmd_db(args, fetch, out) -> int:
    with _open_database() as database:
        if args.action == "stats":
            payload = database.stats()
            if args.json:
                _emit(out, payload)
                return 0
            _table(
                out,
                ["FIELD", "VALUE"],
                [
                    ("database", payload["path"]),
                    ("size", f"{payload['size_mb']} MB"),
                    ("journal", payload["journal_mode"]),
                    ("retention", f"{payload['retention_days']} days"),
                    *[(name, count) for name, count in payload["counts"].items()],
                ],
            )
            return 0
        if args.action == "signals":
            records = database.recent_signals(
                args.limit, _symbol(args.symbol) if args.symbol else None
            )
            if args.json:
                _emit(out, records)
                return 0
            _table(
                out,
                ["TIME", "MARKET", "TIMEFRAME", "SIGNAL", "SCORE", "STRATEGY"],
                [
                    (
                        record["created_at"][:19],
                        display_name(record["symbol"]),
                        record["timeframe"],
                        record["signal"],
                        f"{record['score']:+.1f}",
                        record["strategy"] or "-",
                    )
                    for record in records
                ],
            )
            return 0
        if args.action == "candles":
            symbol = _symbol(args.symbol)
            rows = database.load_candles(symbol, args.timeframe, args.limit)
            if args.json:
                _emit(
                    out,
                    [
                        {
                            "epoch": row[0],
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                        }
                        for row in rows
                    ],
                )
                return 0
            _table(
                out,
                ["EPOCH", "OPEN", "HIGH", "LOW", "CLOSE"],
                rows[-args.limit :],
            )
            return 0
        if args.action == "save":
            symbol = _symbol(args.symbol)
            seconds = granularity(args.timeframe)
            candles = fetch(symbol, seconds, args.count)
            written = database.save_candles(symbol, args.timeframe, candles)
            snapshot = market_snapshot(candles, symbol=symbol, timeframe=args.timeframe)
            if snapshot is not None:
                database.save_snapshot(
                    symbol=symbol, timeframe=args.timeframe, result=snapshot
                )
            if args.json:
                _emit(
                    out,
                    {"symbol": symbol, "written": written},
                )
                return 0
            out.write(
                f"Stored {written} candles for {display_name(symbol)} "
                f"{args.timeframe} locally.\n"
            )
            return 0
        if args.action == "export":
            destination = Path(args.path).expanduser()
            counts = database.export_json(destination)
            if args.json:
                _emit(out, {"destination": str(destination), "counts": counts})
                return 0
            out.write(f"Exported local database to {destination}\n")
            for name, count in counts.items():
                out.write(f"  {name}: {count}\n")
            return 0
        if args.action == "prune":
            removed = database.prune(retention_days=args.days)
            if args.json:
                _emit(out, removed)
                return 0
            out.write(
                "Pruned rows: "
                + ", ".join(f"{k}={v}" for k, v in removed.items())
                + "\n"
            )
            return 0
        if args.action == "vacuum":
            database.vacuum()
            out.write("Database vacuumed.\n")
            return 0
    raise ValueError(f"unknown db action {args.action!r}")


def _ai_store() -> AIKeyStore:
    return AIKeyStore()


def _resolve_secret(args, provider: str) -> str:
    if args.key:
        return args.key
    from_env = os.environ.get("NEEZY_AI_KEY", "").strip()
    if from_env:
        return from_env
    return getpass.getpass(f"Paste the {provider} API key (input hidden): ")


def cmd_ai(args, fetch, out) -> int:
    store = _ai_store()
    if args.action == "providers":
        payload = [
            {
                **spec.to_dict(),
                "keys": store.count(spec.key),
                "usable_keys": store.usable_count(spec.key),
            }
            for spec in PROVIDERS.values()
        ]
        if args.json:
            _emit(out, payload)
            return 0
        _table(
            out,
            ["PROVIDER", "MODELS", "KEYS", "USABLE", "BASE URL"],
            [
                (
                    item["label"],
                    len(item["models"]),
                    item["keys"],
                    item["usable_keys"],
                    item["base_url"],
                )
                for item in payload
            ],
        )
        out.write(
            "\nFree models only; add keys with 'neezy-cli ai keys add PROVIDER'.\n"
        )
        return 0
    if args.action == "models":
        spec = resolve_provider(args.provider)
        models = free_models(spec.key)
        if args.json:
            _emit(out, {"provider": spec.key, "models": models})
            return 0
        out.write(f"{spec.label} free models:\n")
        for model in models:
            out.write(f"  {model}\n")
        return 0
    if args.action == "keys":
        if not args.verb:
            summaries = []
            for spec in PROVIDERS.values():
                for status in store.statuses(spec.key):
                    summaries.append({**status.to_dict(), "provider_label": spec.label})
            if args.json:
                _emit(out, summaries)
                return 0
            _table(
                out,
                ["PROVIDER", "ID", "LABEL", "KEY", "USABLE", "USES", "LAST ERROR"],
                [
                    (
                        item["provider_label"],
                        item["id"],
                        item["label"],
                        item["hint"],
                        "yes" if item["usable"] else "no",
                        item["uses"],
                        item["last_error"][:40],
                    )
                    for item in summaries
                ],
            )
            return 0
        if args.verb == "add":
            spec = resolve_provider(args.provider)
            status = store.add(
                spec.key, _resolve_secret(args, spec.label), args.label or ""
            )
            if args.json:
                _emit(out, status.to_dict())
                return 0
            out.write(f"Stored {spec.label} key '{status.label}' ({status.hint}).\n")
            return 0
        if args.verb == "remove":
            spec = resolve_provider(args.provider)
            removed = store.remove(spec.key, args.key_id)
            out.write(
                f"Removed key {args.key_id}\n" if removed else f"No key {args.key_id}\n"
            )
            return 0 if removed else 1
        if args.verb == "reset":
            changed = store.reset(args.provider.lower() if args.provider else None)
            out.write(f"Cleared cooldowns on {changed} key(s).\n")
            return 0
        raise ValueError(f"unknown ai keys action {args.verb!r}")
    if args.action == "chat":
        spec = resolve_provider(args.provider)
        context = ""
        if args.symbol:
            symbol = _symbol(args.symbol)
            try:
                candles = fetch(symbol, granularity(args.timeframe), args.count)
                snapshot = market_snapshot(
                    candles, symbol=symbol, timeframe=args.timeframe
                )
                if snapshot:
                    context = format_context(snapshot)
            except (OSError, RuntimeError, ValueError) as error:
                out.write(f"! market context unavailable: {error}\n")
        messages = chat_messages(args.prompt, context or "No live context supplied.")
        with _open_database() as database:
            client = AIClient(store, recorder=database.record_ai_call)
            result = client.chat(
                spec.key,
                messages,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        if args.json:
            _emit(out, result.to_dict())
            return 0
        out.write(f"{result.text}\n\n")
        out.write(
            f"[{spec.label} · {result.model} · key {result.key_label} · "
            f"{result.latency_ms} ms]\n"
        )
        return 0
    if args.action == "usage":
        with _open_database() as database:
            payload = database.ai_usage(args.limit)
        if args.json:
            _emit(out, payload)
            return 0
        out.write(f"{payload['total']} recent AI calls\n")
        _table(
            out,
            ["PROVIDER", "CALLS"],
            sorted(payload["by_provider"].items()),
        )
        _table(out, ["STATUS", "CALLS"], sorted(payload["by_status"].items()))
        return 0
    if args.action == "reset":
        changed = store.reset()
        out.write(f"Cleared cooldowns on {changed} key(s).\n")
        return 0
    raise ValueError(f"unknown ai action {args.action!r}")


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
    p.add_argument(
        "--category",
        help="only this category, e.g. forex, synthetic_index, indices, commodities",
    )
    p.set_defaults(handler=cmd_markets)

    p = common(
        sub.add_parser("doctor", help="check market-data connectivity"),
        timeframe=False,
    )
    p.add_argument("--timeout", type=float, default=8.0, help="seconds per endpoint")
    p.set_defaults(handler=cmd_doctor)

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
    p = common(sub.add_parser("read", help="full advanced market read"), count=300)
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="SUPERTREND")
    p.add_argument("--period", type=int, default=10)
    p.add_argument("--multiplier", type=float, default=3.0)
    p.add_argument("--lookback", type=int, default=5)
    p.set_defaults(handler=cmd_read)

    p = common(
        sub.add_parser("supertrend", help="Supertrend line and flip state"), count=300
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--period", type=int, default=10)
    p.add_argument("--multiplier", type=float, default=3.0)
    p.set_defaults(handler=cmd_supertrend)

    p = common(
        sub.add_parser("divergence", help="RSI/MACD divergence near the last swing"),
        count=300,
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--lookback", type=int, default=5)
    p.set_defaults(handler=cmd_divergence)

    p = common(
        sub.add_parser("corrdiv", help="correlation divergence across markets"),
        timeframe=True,
    )
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.add_argument("--window", type=int, default=50)
    p.add_argument("--baseline", type=int, default=200)
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(handler=cmd_corrdiv)

    p = common(
        sub.add_parser("strategies", help="list or score every strategy"), count=300
    )
    p.add_argument("symbol", nargs="?", type=_symbol)
    p.set_defaults(handler=cmd_strategies)

    p = sub.add_parser("db", help="local SQLite database tools")
    p.set_defaults(handler=cmd_db)
    db_actions = p.add_subparsers(dest="action", required=True)

    a = db_actions.add_parser("stats", help="database size and row counts")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("signals", help="signals saved on this PC")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--symbol", help="restrict to one market")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("candles", help="stored candles for a market")
    a.add_argument("symbol")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("save", help="fetch candles and store them locally")
    a.add_argument("symbol")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    a.add_argument("-n", "--count", type=int, default=300)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("export", help="export the whole database to JSON")
    a.add_argument("path")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("prune", help="apply the retention window now")
    a.add_argument("--days", type=int)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("vacuum", help="reclaim disk space")
    a.add_argument("--json", action="store_true")

    p = sub.add_parser("ai", help="AI providers, key pools, and chat")
    p.set_defaults(handler=cmd_ai)
    ai_actions = p.add_subparsers(dest="action", required=True)

    a = ai_actions.add_parser("providers", help="list providers and key counts")
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("models", help="list free models for a provider")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument("--json", action="store_true")

    keys = ai_actions.add_parser("keys", help="manage the local key pool")
    keys.add_argument("--json", action="store_true")
    key_actions = keys.add_subparsers(dest="verb")

    a = key_actions.add_parser("add", help="store another key for a provider")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument(
        "--key", help="key value; omit to paste it hidden or use NEEZY_AI_KEY"
    )
    a.add_argument("--label", help="friendly name, e.g. 'work laptop'")

    a = key_actions.add_parser("remove", help="delete a stored key")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument("key_id")

    a = key_actions.add_parser("reset", help="clear cooldowns and failure counters")
    a.add_argument("provider", nargs="?", choices=sorted(PROVIDERS))

    a = ai_actions.add_parser("chat", help="ask the configured provider a question")
    a.add_argument("prompt")
    a.add_argument("--provider", choices=sorted(PROVIDERS), default="openrouter")
    a.add_argument("--model", help="free model id (default: provider default)")
    a.add_argument("--temperature", type=float, default=0.3)
    a.add_argument("--max-tokens", type=int, default=700)
    a.add_argument("--timeout", type=float, default=45.0)
    a.add_argument("--symbol", help="attach live indicator context for this market")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="15m")
    a.add_argument("-n", "--count", type=int, default=300)
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("usage", help="recent AI calls logged locally")
    a.add_argument("--limit", type=int, default=50)
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("reset", help="clear every key cooldown")
    a.add_argument("--json", action="store_true")

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
