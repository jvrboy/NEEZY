"""Advanced quantitative risk and regime analytics.

Pure, deterministic functions with no I/O: feed them closes (floats) or candle
rows and get back volatility, drawdown, risk-adjusted return, tail-risk and
regime measures. Everything runs locally and never places trades; outputs are
descriptive analytics, not investment advice.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

TRADING_DAYS = 252
TRADING_HOURS = TRADING_DAYS * 24


def closes_from_candles(
    candles: Sequence[Mapping[str, Any] | Sequence[float]],
) -> list[float]:
    """Extract close prices from dict rows or OHLC tuples.

    Accepts mappings with a "close" (or "c") key and sequences of at least
    four numbers where the last element is the close. Non-finite and
    non-positive values are skipped.
    """
    closes: list[float] = []
    for candle in candles:
        if isinstance(candle, Mapping):
            value = candle.get("close", candle.get("c"))
        elif len(candle) >= 4:
            value = candle[-1]
        else:
            value = None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            closes.append(number)
    return closes


def ewma_volatility(
    returns: Sequence[float], lam: float = 0.94, periods_per_year: int | None = None
) -> float | None:
    """RiskMetrics-style EWMA volatility of a return series.

    "lam" is the decay factor (higher = smoother). When "periods_per_year"
    is given the result is annualised with the square-root-of-time rule.
    """
    if lam <= 0 or lam >= 1:
        raise ValueError("lam must be between 0 and 1")
    if len(returns) < 2:
        return None
    variance = sum(r * r for r in returns) / len(returns)
    for ret in returns:
        variance = lam * variance + (1 - lam) * ret * ret
    vol = math.sqrt(max(variance, 0.0))
    if periods_per_year:
        vol *= math.sqrt(periods_per_year)
    return vol


def sharpe_ratio(
    returns: Sequence[float],
    periods_per_year: int = TRADING_DAYS,
    risk_free: float = 0.0,
) -> float | None:
    """Annualised Sharpe ratio; "risk_free" is per-period."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns) - risk_free
    variance = sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / (
        len(returns) - 1
    )
    std = math.sqrt(max(variance, 0.0))
    if std == 0:
        return None
    return math.sqrt(periods_per_year) * mean / std


def sortino_ratio(
    returns: Sequence[float],
    periods_per_year: int = TRADING_DAYS,
    risk_free: float = 0.0,
) -> float | None:
    """Annualised Sortino ratio (downside deviation only)."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns) - risk_free
    downside = [min(r, 0.0) ** 2 for r in returns]
    dd = math.sqrt(sum(downside) / len(downside))
    if dd == 0:
        return None
    return math.sqrt(periods_per_year) * mean / dd


def drawdown_stats(closes: Sequence[float]) -> dict[str, float]:
    """Peak-to-trough drawdown statistics for a close-price series."""
    if len(closes) < 2:
        return {"max_drawdown": 0.0, "current_drawdown": 0.0}
    peak = closes[0]
    max_dd = 0.0
    current = 0.0
    for close in closes:
        if close > peak:
            peak = close
        dd = (peak - close) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        current = dd
    return {"max_drawdown": max_dd, "current_drawdown": current}


def historical_var(returns: Sequence[float], confidence: float = 0.95) -> float | None:
    """Historical Value-at-Risk as a positive loss fraction."""
    if len(returns) < 10:
        return None
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    ordered = sorted(returns)
    rank = math.floor((1 - confidence) * len(ordered))
    index = max(0, min(len(ordered) - 1, rank))
    return max(-ordered[index], 0.0)


def expected_shortfall(
    returns: Sequence[float], confidence: float = 0.95
) -> float | None:
    """Average loss beyond the VaR cut-off (CVaR)."""
    if len(returns) < 10:
        return None
    ordered = sorted(returns)
    tail = ordered[: max(1, math.floor((1 - confidence) * len(ordered)))]
    return max(-sum(tail) / len(tail), 0.0)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Full-Kelly position fraction from win rate and average win/loss sizes.

    "avg_loss" is a positive magnitude. Returns 0 for degenerate inputs and
    clamps the result to [0, 1] - half-Kelly is the usual practical ceiling.
    """
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    if not 0 <= win_rate <= 1:
        raise ValueError("win_rate must be between 0 and 1")
    payoff = avg_win / avg_loss
    edge = win_rate * payoff - (1 - win_rate)
    return max(0.0, min(edge / payoff, 1.0))


def hurst_exponent(closes: Sequence[float], min_window: int = 8) -> float | None:
    """Hurst exponent via scaled-window variance of diffs (0.5 = random walk).

    Values above 0.5 hint at trending persistence, below 0.5 at mean
    reversion. Needs at least 4 * min_window points.
    """
    if len(closes) < 4 * min_window:
        return None
    diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    xs: list[float] = []
    ys: list[float] = []
    window = min_window
    while window <= len(diffs) // 2:
        chunks = [
            diffs[i : i + window] for i in range(0, len(diffs) - window + 1, window)
        ]
        if not chunks:
            break
        mean_var = sum(sum(c) ** 2 / len(c) for c in chunks) / len(chunks)
        if mean_var <= 0:
            return None
        xs.append(math.log(window))
        ys.append(0.5 * math.log(mean_var))
        window *= 2
    if len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denom
    )
    return max(0.0, min(1.0, slope))


def efficiency_ratio(closes: Sequence[float], period: int = 20) -> float | None:
    """Kaufman efficiency ratio: net move divided by the path travelled.

    1.0 = perfectly directional, ~0 = choppy.
    """
    if period < 2 or len(closes) < period + 1:
        return None
    segment = list(closes[-(period + 1) :])
    net = abs(segment[-1] - segment[0])
    path = sum(abs(segment[i] - segment[i - 1]) for i in range(1, len(segment)))
    if path == 0:
        return None
    return net / path


def classify_regime(hurst: float | None, er: float | None) -> str:
    """Human-readable market regime from Hurst and efficiency ratio."""
    if hurst is None or er is None:
        return "Unknown"
    if hurst >= 0.55 and er >= 0.3:
        return "Trending"
    if hurst <= 0.45 and er <= 0.2:
        return "Mean-reverting"
    return "Choppy"


def risk_report(
    candles: Sequence[Mapping[str, Any] | Sequence[float]],
    periods_per_year: int = TRADING_HOURS,
) -> dict[str, Any]:
    """One-call risk snapshot for a candle series.

    Returns a JSON-serialisable dict with volatility, risk-adjusted return,
    drawdown, tail risk and regime classification. Empty or tiny inputs yield
    a report with None metrics rather than raising.
    """
    closes = closes_from_candles(candles)
    returns = [
        math.log(after / before)
        for before, after in pairwise(closes)
        if before > 0 and after > 0
    ]
    hurst = hurst_exponent(closes)
    er = efficiency_ratio(closes)
    dd = drawdown_stats(closes)
    report: dict[str, Any] = {
        "samples": len(closes),
        "returns": len(returns),
        "ewma_vol": ewma_volatility(returns, periods_per_year=None),
        "ewma_vol_annualised": ewma_volatility(
            returns, periods_per_year=periods_per_year
        ),
        "sharpe": sharpe_ratio(returns, periods_per_year=periods_per_year),
        "sortino": sortino_ratio(returns, periods_per_year=periods_per_year),
        "max_drawdown": dd["max_drawdown"],
        "current_drawdown": dd["current_drawdown"],
        "var_95": historical_var(returns),
        "es_95": expected_shortfall(returns),
        "hurst": hurst,
        "efficiency_ratio": er,
        "regime": classify_regime(hurst, er),
    }
    return report


def format_risk_report(
    symbol_name: str, timeframe: str, report: Mapping[str, Any]
) -> str:
    """Render a risk report as a compact text panel for the UI."""
    if not report.get("samples"):
        return (
            f"RISK - {symbol_name} - {timeframe}\n\n"
            "Not enough candle history yet. Keep candle storage enabled and "
            "retry after more data arrives."
        )

    def num(key: str, scale: float = 100.0, digits: int = 2) -> str:
        value = report.get(key)
        return "-" if value is None else f"{float(value) * scale:.{digits}f}"

    def raw(key: str) -> str:
        value = report.get(key)
        return "-" if value is None else f"{float(value):.3f}"

    lines = [
        f"Samples            {report['samples']:.0f} candles",
        f"EWMA volatility    {num('ewma_vol')}%",
        f"Vol (annualised)   {num('ewma_vol_annualised')}%",
        f"Sharpe             {raw('sharpe')}",
        f"Sortino             {raw('sortino')}",
        f"Max drawdown       {num('max_drawdown')}%",
        f"Current drawdown   {num('current_drawdown')}%",
        f"VaR 95%            {num('var_95')}%",
        f"ES 95%             {num('es_95')}%",
        f"Hurst              {raw('hurst')}",
        f"Efficiency ratio   {raw('efficiency_ratio')}",
        f"Regime             {report.get('regime', 'Unknown')}",
        "",
        "Descriptive analytics only - not investment advice.",
    ]
    return "\n".join(lines)
