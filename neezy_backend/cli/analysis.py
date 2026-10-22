"""Market-analysis CLI commands: markets, doctor, scan, analyze, reads.

These commands fetch candles (through the injected fetcher), run the
deterministic indicator/strategy engine, and render tables or JSON.
"""

from __future__ import annotations

from ..analytics import correlation_matrix, rank_opportunities, strongest_pairs
from ..catalog import instrument, instruments
from ..context import market_snapshot
from ..divergence import detect_divergences, rank_correlation_divergences
from ..indicators import analyze
from ..markets import (
    DEFAULT_WATCHLIST,
    SYMBOLS,
    TIMEFRAMES,
    display_name,
    format_price,
    granularity,
    pip_size,
    ws_urls,
)
from ..patterns import price_action_summary
from ..regime import market_regime
from ..strategies import consensus, describe_strategies, evaluate, run_all
from ..stream import probe_endpoint
from ..trend import trend_summary
from .common import _closed, _emit, _symbol, _table, _without_series


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


def cmd_regime(args, fetch, out) -> int:
    candles = fetch(args.symbol, granularity(args.timeframe), args.count)
    result = {"symbol": args.symbol, "timeframe": args.timeframe}
    result.update(market_regime(candles))
    if args.json:
        _emit(out, result)
        return 0
    out.write(f"{display_name(args.symbol)} · {args.timeframe}\n")
    out.write(f"Regime       {result['regime']}\n")
    out.write(f"Volatility   {result['volatility']}\n")
    out.write(f"{result['summary']}\n")
    if result.get("adx") is not None:
        out.write(
            f"ADX          {result['adx']:.1f}  +DI {result['plus_di']:.1f}"
            f"  -DI {result['minus_di']:.1f}\n"
        )
        out.write(
            f"Bandwidth    {result['bandwidth']:.5f}"
            f"  ({result['bandwidth_percentile']:.0f}th percentile)\n"
        )
    out.write("\nEducational summary only — not financial advice.\n")
    return 0


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


def cmd_decision_metrics(args, fetch, out) -> int:
    """Compute trade decision metrics and strategy matrix for a symbol."""
    symbol = _symbol(args.symbol)
    candles = fetch(symbol, granularity(args.timeframe), args.count)
    from ..dm import compute_decision_metrics

    metrics = compute_decision_metrics(
        symbol,
        args.timeframe,
        candles,
        balance=args.balance,
        risk_percent=args.risk,
    )
    if args.json:
        _emit(out, metrics)
    else:
        out.write(
            f"Decision Metrics for {symbol} ({args.timeframe}):\n"
            f"  Verdict: {metrics['decision']} ({metrics['confidence']}% confidence)\n"
            f"  Consensus: {metrics['consensus_direction']} "
            f"(Votes: {metrics['strategy_votes']})\n"
            f"  RSI: {metrics['rsi']} | ADX: {metrics['adx']} | "
            f"ATR: {metrics['atr']}\n"
            f"  Reasons: {', '.join(metrics['reasons'])}\n"
        )
    return 0
