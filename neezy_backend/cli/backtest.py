"""Simulation CLI commands: backtest and position-size/risk calculator."""

from __future__ import annotations

import math

from ..backtest import BacktestConfig, run_backtest
from ..markets import display_name, format_price, granularity, pip_size
from ..risk import position_size, resolve_stop
from .common import _emit, _table


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
    entry = args.entry
    stop, _target = resolve_stop(
        args.direction,
        entry,
        args.atr,
        stop=args.stop,
        stop_atr=args.stop_atr,
        reward_risk=args.reward_risk,
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
