"""Small NumPy helpers shared by every indicator. No external TA library."""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np

EPS = 1e-12


def closes(series) -> np.ndarray:
    return np.asarray(series.closes, dtype=float)


def epochs(series) -> np.ndarray:
    return np.asarray([c.epoch for c in series.candles], dtype=np.int64)


def tick_counts(series) -> np.ndarray:
    return np.asarray([c.tick_count for c in series.candles], dtype=float)


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """NaN-aware rolling mean: NaN inputs count as missing (skipped)."""
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < n or n <= 0:
        return out
    v = np.where(np.isnan(x), 0.0, x)
    valid = (~np.isnan(x)).astype(float)
    cv, cs = np.cumsum(np.insert(v, 0, 0.0)), np.cumsum(np.insert(valid, 0, 0.0))
    s = cv[n:] - cv[:-n]  # sum of valid values
    k = cs[n:] - cs[:-n]  # count of valid values
    ok = k >= max(1, n // 2)  # need at least half the window valid
    out[n - 1 :] = np.where(ok, s / np.maximum(k, 1), np.nan)
    return out


def rolling_std(x: np.ndarray, n: int, ddof: int = 0) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < n or n < 2:
        return out
    v = np.where(np.isnan(x), 0.0, x)
    v2 = v * v
    valid = (~np.isnan(x)).astype(float)
    c1 = np.cumsum(np.insert(v, 0, 0.0))
    c2 = np.cumsum(np.insert(v2, 0, 0.0))
    ck = np.cumsum(np.insert(valid, 0, 0.0))
    s1 = c1[n:] - c1[:-n]
    s2 = c2[n:] - c2[:-n]
    k = ck[n:] - ck[:-n]
    ok = k >= max(2, n // 2)
    mean = s1 / np.maximum(k, 1)
    var = s2 / np.maximum(k, 1) - mean * mean
    var = np.maximum(var, 0.0)
    out[n - 1 :] = np.where(
        ok, np.sqrt(var if ddof == 0 else var * k / np.maximum(k - 1, 1)), np.nan
    )
    return out


def rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) < n or n <= 0:
        return out
    v = np.where(np.isnan(x), 0.0, x)
    c = np.cumsum(np.insert(v, 0, 0.0))
    out[n - 1 :] = c[n:] - c[:-n]
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.concatenate([[close[0]], close[:-1]])
    return np.maximum(
        high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )


def atr(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14
) -> np.ndarray:
    tr = true_range(high, low, close)
    return rolling_mean(tr, n)


def logistic(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def tanh_scale(x: np.ndarray, scale: float) -> np.ndarray:
    return np.tanh(x / (scale + EPS))


def rankdata(a: np.ndarray) -> np.ndarray:
    """Average-rank (ties get mean rank), matching scipy.stats.rankdata."""
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation with NaN pairs dropped."""
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 3:
        return float("nan")
    rx, ry = rankdata(x[mask]), rankdata(y[mask])
    rx -= rx.mean()
    ry -= ry.mean()
    denom = math.sqrt(float((rx * rx).sum()) * float((ry * ry).sum()))
    if denom <= EPS:
        return float("nan")
    return float((rx * ry).sum() / denom)


def pct_change(x: np.ndarray, n: int = 1) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if n < len(x):
        out[n:] = x[n:] / x[:-n] - 1.0
    return out


def sign(x: np.ndarray) -> np.ndarray:
    return np.sign(np.asarray(x, dtype=float))


def max_drawdown(equity: Sequence[float]) -> float:
    eq = np.asarray(equity, dtype=float)
    if len(eq) == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    dd = np.where(peak > 0, (eq - peak) / np.where(peak != 0, peak, 1.0), 0.0)
    return float(dd.min()) if len(dd) else 0.0


def zigzag_swings(close: np.ndarray, threshold) -> List[Tuple[int, int, int]]:
    """ZigZag pivots on close prices.

    `threshold` is either a scalar or a PER-BAR array (same length as close)
    so the leg threshold only uses information available at each bar — this
    keeps the function free of lookahead bias.
    Returns list of (start_idx, end_idx, direction).
    """
    close = np.asarray(close, dtype=float)
    if len(close) < 3:
        return []
    if np.isscalar(threshold):
        thr = np.full(len(close), float(threshold))
    else:
        thr = np.asarray(threshold, dtype=float)
    pivots: List[Tuple[int, int]] = [(0, close[0])]
    direction = 0
    extreme_idx, extreme_px = 0, close[0]
    for i in range(1, len(close)):
        px = close[i]
        t = thr[i]
        if direction >= 0 and px > extreme_px:
            extreme_idx, extreme_px = i, px
        elif direction <= 0 and px < extreme_px:
            extreme_idx, extreme_px = i, px
        elif direction >= 0 and t == t and px < extreme_px - t:
            pivots.append((extreme_idx, extreme_px))
            direction = -1
            extreme_idx, extreme_px = i, px
        elif direction <= 0 and t == t and px > extreme_px + t:
            pivots.append((extreme_idx, extreme_px))
            direction = +1
            extreme_idx, extreme_px = i, px
    pivots.append((extreme_idx, extreme_px))
    legs: List[Tuple[int, int, int]] = []
    for (i0, _), (i1, _) in zip(pivots, pivots[1:]):
        d = 1 if close[i1] > close[i0] else -1
        legs.append((i0, i1, d))
    return legs
