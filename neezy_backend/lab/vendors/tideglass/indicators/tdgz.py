"""Tick-Density Gravity Zones (TDGZ).

Spot FX has no centralised volume. TDGZ substitutes *tick density* (how many
price updates Deriv streamed during a bar) and *time spent at price* (each bar
spreads its weight uniformly over its high-low range) to build a rolling price
density map. Peaks of the map are "gravity" levels that price tends to revisit
or stall at.

Per bar ``t``:

1. Collect the last ``lookback`` valid bars ``j``. Weight
   ``w_j = ticks_j * 0.5^((t - j) / half_life)`` (``ticks_j = 1`` when unknown).
2. Grid ``[min L, max H]`` into ``bins`` equal bins. Each bar adds
   ``w_j * overlap(bin, [L_j, H_j]) / (H_j - L_j)`` to the bins it covers.
3. Smooth with the kernel ``[1, 2, 3, 2, 1]`` (renormalised at the edges).
4. A bin is a gravity peak when it is strictly higher than its left neighbour,
   not lower than its right neighbour and at least ``peak_min`` x the mean
   density.

Outputs: nearest peak above/below the close (``level_above``/``level_below``),
their distance in range units, their relative strength ``d_peak / max(d)``
and ``net_pull = strength_above / (1 + dist_above) - strength_below / (1 + dist_below)``
in [-1, 1]. Positive net pull means the stronger, nearer magnet is above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import range_unit, valid_mask

KERNEL = np.array([1.0, 2.0, 3.0, 2.0, 1.0])


@dataclass(frozen=True)
class TDGZParams:
    lookback: int = 200
    bins: int = 48
    half_life: float = 100.0
    ru_len: int = 20
    peak_min: float = 1.0
    min_bars: int = 20


def density_map(
    lo_j: np.ndarray, hi_j: np.ndarray, w_j: np.ndarray, lo: float, hi: float, bins: int
) -> np.ndarray:
    """Raw (unsmoothed) density histogram on ``bins`` equal bins over ``[lo, hi]``."""
    bw = (hi - lo) / bins
    edges = lo + bw * np.arange(bins + 1)
    dens = np.zeros(bins)
    span = hi_j - lo_j
    wide = span > 0
    if np.any(wide):
        left = np.maximum(edges[None, :-1], lo_j[wide, None])
        right = np.minimum(edges[None, 1:], hi_j[wide, None])
        overlap = np.clip(right - left, 0.0, None)
        dens += (overlap * (w_j[wide] / span[wide])[:, None]).sum(axis=0)
    flat = ~wide
    if np.any(flat):
        idx = np.minimum(bins - 1, np.floor((lo_j[flat] - lo) / bw).astype(np.int64))
        np.add.at(dens, idx, w_j[flat])
    return dens


def smooth_density(d: np.ndarray) -> np.ndarray:
    """Apply the 5-tap kernel, renormalising the weights at the edges."""
    n = d.shape[0]
    out = np.empty(n)
    for b in range(n):
        acc = 0.0
        ws = 0.0
        for k in range(-2, 3):
            i = b + k
            if 0 <= i < n:
                acc += KERNEL[k + 2] * d[i]
                ws += KERNEL[k + 2]
        out[b] = acc / ws
    return out


def find_peaks(d: np.ndarray, peak_min: float) -> np.ndarray:
    """Indices of gravity peaks according to the TDGZ peak rule."""
    n = d.shape[0]
    thr = peak_min * float(d.mean())
    peaks = []
    for b in range(n):
        left = d[b - 1] if b > 0 else -math.inf
        right = d[b + 1] if b < n - 1 else -math.inf
        if d[b] > left and d[b] >= right and d[b] >= thr and d[b] > 0:
            peaks.append(b)
    return np.array(peaks, dtype=np.int64)


def compute_tdgz(candles: Candles, p: TDGZParams = TDGZParams()) -> IndicatorResult:
    h, l, c = candles.high, candles.low, candles.close
    n = len(candles)
    ok = valid_mask(candles.open, h, l, c)
    ru = range_unit(h, l, c, p.ru_len)
    ticks = np.where(
        np.isfinite(candles.ticks) & (candles.ticks > 0), candles.ticks, 1.0
    )
    decay = 0.5 ** (1.0 / p.half_life)

    names = (
        "level_above",
        "level_below",
        "dist_above",
        "dist_below",
        "strength_above",
        "strength_below",
        "net_pull",
    )
    out = {k: np.full(n, np.nan) for k in names}
    for t in range(n):
        if not (ok[t] and math.isfinite(ru[t]) and ru[t] > 0):
            continue
        lo_i = max(0, t - p.lookback + 1)
        idx = np.arange(lo_i, t + 1)[ok[lo_i : t + 1]]
        if idx.size < p.min_bars:
            continue
        lj, hj = l[idx], h[idx]
        lo, hi = float(lj.min()), float(hj.max())
        if not hi > lo:
            continue
        wj = ticks[idx] * decay ** (t - idx).astype(np.float64)
        dens = smooth_density(density_map(lj, hj, wj, lo, hi, p.bins))
        dmax = float(dens.max())
        peaks = find_peaks(dens, p.peak_min)
        bw = (hi - lo) / p.bins
        centers = lo + bw * (peaks.astype(np.float64) + 0.5)
        price = c[t]
        up = 0.0
        dn = 0.0
        above = peaks[centers > price]
        below = peaks[centers <= price]
        if above.size:
            b = int(above[0])  # peaks are sorted ascending, first above is nearest
            lvl = lo + bw * (b + 0.5)
            d = (lvl - price) / ru[t]
            s = dens[b] / dmax
            out["level_above"][t], out["dist_above"][t], out["strength_above"][t] = (
                lvl,
                d,
                s,
            )
            up = s / (1.0 + d)
        if below.size:
            b = int(below[-1])
            lvl = lo + bw * (b + 0.5)
            d = (price - lvl) / ru[t]
            s = dens[b] / dmax
            out["level_below"][t], out["dist_below"][t], out["strength_below"][t] = (
                lvl,
                d,
                s,
            )
            dn = s / (1.0 + d)
        out["net_pull"][t] = up - dn
    return IndicatorResult(
        "TDGZ", p.__dict__.copy(), out, warmup=max(p.ru_len - 1, p.min_bars - 1)
    )
