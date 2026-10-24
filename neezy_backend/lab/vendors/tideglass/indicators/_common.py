"""Shared numeric primitives used by every Tideglass indicator.

All helpers follow the same NaN contract so that the Python reference, the C++
core and the C# library agree bar-for-bar:

* A *bar* is valid when open, high, low and close are all finite.
* Windowed statistics are NaN if any bar inside the window is invalid or if the
  window is not yet full (warm-up).
* Recursive states (EMAs, adaptive centres, learners) skip invalid bars: the
  output at that bar is NaN and the state is carried forward unchanged.

Every function is strictly causal: the value at index ``t`` uses data from
indices ``<= t`` only.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

FloatArray = np.ndarray

#: Small constants shared across languages (keep in sync with C++/C#).
EPS = 1e-12
LOG_FLOOR = 1e-7


def as_float_array(values: Sequence[float] | np.ndarray) -> FloatArray:
    """Return ``values`` as a contiguous float64 array (copy only if needed)."""
    return np.ascontiguousarray(np.asarray(values, dtype=np.float64))


def valid_mask(
    o: FloatArray, h: FloatArray, l: FloatArray, c: FloatArray
) -> np.ndarray:
    """Boolean mask of bars whose OHLC values are all finite."""
    return np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)


def windows(x: FloatArray, w: int) -> FloatArray:
    """Return an ``(n, w)`` matrix whose row ``t`` holds ``x[t-w+1 .. t]``.

    Rows for ``t < w - 1`` are filled with NaN so that reductions over them
    return NaN, which implements the warm-up rule.
    """
    n = x.shape[0]
    out = np.full((n, w), np.nan)
    if n >= w:
        out[w - 1 :] = sliding_window_view(x, w)
    return out


def rolling_sum(x: FloatArray, w: int) -> FloatArray:
    """Rolling sum with NaN propagation (NaN if any element is NaN)."""
    return windows(x, w).sum(axis=1)


def rolling_mean(x: FloatArray, w: int) -> FloatArray:
    """Rolling arithmetic mean with NaN propagation."""
    return windows(x, w).mean(axis=1)


def shift(x: FloatArray, k: int) -> FloatArray:
    """Shift ``x`` forward by ``k`` bars (``out[t] = x[t-k]``), NaN padded."""
    out = np.full_like(x, np.nan)
    if k == 0:
        return x.copy()
    if k < x.shape[0]:
        out[k:] = x[:-k]
    return out


def true_range(h: FloatArray, l: FloatArray, c: FloatArray) -> FloatArray:
    """Bar range extended to the previous close.

    ``TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)``; when the
    previous close is unavailable the plain ``H_t - L_t`` is used.
    """
    prev_c = shift(c, 1)
    hl = h - l
    with np.errstate(invalid="ignore"):
        ext = np.fmax(np.abs(h - prev_c), np.abs(l - prev_c))
    tr = np.where(np.isfinite(prev_c), np.fmax(hl, ext), hl)
    tr[~(np.isfinite(h) & np.isfinite(l))] = np.nan
    return tr


def range_unit(h: FloatArray, l: FloatArray, c: FloatArray, length: int) -> FloatArray:
    """Tideglass "range unit" (RU): simple mean of the true range over ``length``.

    RU is the common yard-stick used to express distances in volatility units.
    """
    return rolling_mean(true_range(h, l, c), length)


def ema_skip_nan(x: FloatArray, alpha: float) -> FloatArray:
    """Exponential smoother seeded with the first finite value.

    NaN inputs produce NaN outputs and leave the internal state unchanged.
    """
    out = np.full_like(x, np.nan)
    state = math.nan
    for t, v in enumerate(x):
        if not math.isfinite(v):
            continue
        state = v if not math.isfinite(state) else state + alpha * (v - state)
        out[t] = state
    return out


def rolling_ols_slope(y: FloatArray, w: int) -> FloatArray:
    """Least-squares slope of ``y`` against bar index over a rolling window.

    Uses ``slope = sum((x - xbar) * y) / sum((x - xbar)^2)`` with ``x = 0..w-1``.
    """
    x = np.arange(w, dtype=np.float64)
    xc = x - x.mean()
    sxx = float(np.dot(xc, xc))
    return windows(y, w) @ xc / sxx


def sign(v: float) -> float:
    """Sign as float in ``{-1, 0, 1}``; NaN stays NaN."""
    if not math.isfinite(v):
        return math.nan
    return 1.0 if v > 0 else (-1.0 if v < 0 else 0.0)


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp ``v`` to ``[lo, hi]``."""
    return lo if v < lo else (hi if v > hi else v)


def first_valid_index(x: FloatArray) -> int:
    """Index of the first finite value, or ``len(x)`` if there is none."""
    idx = np.flatnonzero(np.isfinite(x))
    return int(idx[0]) if idx.size else int(x.shape[0])
