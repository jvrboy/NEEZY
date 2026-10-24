"""Trend Integrity Score (TIS).

TIS grades the *quality* of the move over the last ``length`` bars on a 0-100
scale by blending four independent properties:

* Path efficiency ``PE = |C_t - C_{t-n}| / sum|dC|`` - straight vs. wandering.
* Directional persistence ``DPn = clamp((DP - 0.5) / 0.5, 0, 1)`` where ``DP``
  is the share of bars closing in the direction of the net move.
* Pullback consistency ``PC = exp(-0.5 (mean(d) + std(d)))`` where ``d`` are
  the pullback depths (in range units) from the running extreme in the trend
  direction - shallow and regular pullbacks score high.
* Noise ratio ``NR``: mean wick share ``(H - L - |C - O|) / (H - L)``.

``TIS = 100 (0.35 PE + 0.25 DPn + 0.20 PC + 0.20 (1 - NR))``

Regime labels: 3 ``clean_trend`` (TIS >= clean), 2 ``dirty_trend``
(TIS >= dirty), 1 ``range`` (lower TIS but orderly bars, NR < range_noise),
0 ``chop`` (low TIS and noisy bars).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import range_unit, shift, valid_mask, windows

REGIME_LABELS = {0: "chop", 1: "range", 2: "dirty_trend", 3: "clean_trend"}


@dataclass(frozen=True)
class TISParams:
    length: int = 40
    ru_len: int = 20
    clean: float = 62.0
    dirty: float = 48.0
    range_noise: float = 0.6


def compute_tis(candles: Candles, p: TISParams = TISParams()) -> IndicatorResult:
    o, h, l, c = candles.open, candles.high, candles.low, candles.close
    n = len(candles)
    L = p.length
    ok = valid_mask(o, h, l, c)
    ru = range_unit(h, l, c, p.ru_len)
    dc = c - shift(c, 1)
    span = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        wick = np.where(span > 0, (span - np.abs(c - o)) / span, 0.0)
    wick[~ok] = np.nan
    noise = windows(wick, L).mean(axis=1)

    names = (
        "score",
        "regime",
        "direction",
        "efficiency",
        "persistence",
        "pullback",
        "noise",
    )
    out = {k: np.full(n, np.nan) for k in names}
    for t in range(L, n):
        if not (math.isfinite(ru[t]) and ru[t] > 0 and math.isfinite(noise[t])):
            continue
        seg = c[t - L : t + 1]
        if not np.all(np.isfinite(seg)):
            continue
        rets = dc[t - L + 1 : t + 1]
        net = seg[-1] - seg[0]
        path = float(np.abs(rets).sum())
        pe = abs(net) / path if path > 0 else 0.0
        d = 1.0 if net > 0 else (-1.0 if net < 0 else 0.0)
        if d == 0.0:
            dp = 0.0
        else:
            dp = float(np.count_nonzero(np.sign(rets) == d)) / L
        dpn = min(1.0, max(0.0, (dp - 0.5) / 0.5))
        if d >= 0:
            depth = (np.maximum.accumulate(seg) - seg) / ru[t]
        else:
            depth = (seg - np.minimum.accumulate(seg)) / ru[t]
        pc = math.exp(-0.5 * (float(depth.mean()) + float(depth.std())))
        nr = float(noise[t])
        score = 100.0 * (0.35 * pe + 0.25 * dpn + 0.20 * pc + 0.20 * (1.0 - nr))
        if score >= p.clean:
            reg = 3.0
        elif score >= p.dirty:
            reg = 2.0
        elif nr < p.range_noise:
            reg = 1.0
        else:
            reg = 0.0
        out["score"][t] = score
        out["regime"][t] = reg
        out["direction"][t] = d
        out["efficiency"][t] = pe
        out["persistence"][t] = dpn
        out["pullback"][t] = pc
        out["noise"][t] = nr
    return IndicatorResult(
        "TIS",
        p.__dict__.copy(),
        out,
        warmup=max(L, p.ru_len - 1),
        labels={"regime": REGIME_LABELS},
    )
