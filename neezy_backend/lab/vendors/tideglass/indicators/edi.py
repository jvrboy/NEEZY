"""Elastic Displacement Index (EDI).

EDI measures how far price is stretched away from an *adaptive equilibrium*
and how strongly it is likely to snap back.

Equilibrium construction (per bar ``t``):

1. Volatility-weighted centre ``VW_t``: mean of the typical price
   ``(H + L + 2C) / 4`` over the last ``eq_len`` bars, each bar weighted by
   ``1 / TR``. Calm bars, where the market agreed on a price, count more than
   violent bars.
2. Efficiency ``ER_t = |C_t - C_{t-eq_len}| / sum |dC|`` over ``eq_len`` bars.
3. Adaptive centre ``E_t = E_{t-1} + a_t (VW_t - E_{t-1})`` with
   ``a_t = slow + (fast - slow) ER_t``. In efficient (trending) markets the
   centre follows price faster, so trends are not mistaken for stretch.

Outputs:

* ``displacement``  ``D_t = (C_t - E_t) / RU_t`` (range units).
* ``stretch``       ``S_t = D_t / RMS(D over z_len)``, typical range [-4, 4].
* ``snap_back``     ``P_t = -tanh(S_t / 2) (1 - ER_t)`` in [-1, 1]; positive
  values are upward pull back toward equilibrium.
* ``exhaustion``    ``sign(S_t)`` when ``|S_t| >= exhaust`` and the stretch
  shrank versus the previous bar, else 0.
* ``equilibrium``, ``efficiency`` diagnostic series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import EPS, range_unit, shift, true_range, windows


@dataclass(frozen=True)
class EDIParams:
    eq_len: int = 34
    fast_len: int = 3
    ru_len: int = 20
    z_len: int = 100
    exhaust: float = 2.5


def efficiency_ratio(c: np.ndarray, length: int) -> np.ndarray:
    """Net move divided by path length over ``length`` bars (0 when path is 0)."""
    net = np.abs(c - shift(c, length))
    path = windows(np.abs(c - shift(c, 1)), length).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        er = np.where(path > 0, net / path, 0.0)
    er[~(np.isfinite(net) & np.isfinite(path))] = np.nan
    return er


def compute_edi(candles: Candles, p: EDIParams = EDIParams()) -> IndicatorResult:
    h, l, c = candles.high, candles.low, candles.close
    n = len(candles)
    tr = true_range(h, l, c)
    ru = range_unit(h, l, c, p.ru_len)
    typical = (h + l + 2.0 * c) / 4.0
    weight = 1.0 / (tr + 1e-9 * np.abs(c) + EPS)
    w_win = windows(weight, p.eq_len)
    vw = (w_win * windows(typical, p.eq_len)).sum(axis=1) / w_win.sum(axis=1)
    er = efficiency_ratio(c, p.eq_len)

    slow = 2.0 / (p.eq_len + 1.0)
    fast = 2.0 / (p.fast_len + 1.0)
    eq = np.full(n, np.nan)
    state = math.nan
    for t in range(n):
        if not (math.isfinite(vw[t]) and math.isfinite(er[t])):
            continue
        if not math.isfinite(state):
            state = vw[t]
        else:
            state += (slow + (fast - slow) * er[t]) * (vw[t] - state)
        eq[t] = state

    with np.errstate(invalid="ignore", divide="ignore"):
        disp = (c - eq) / ru
    rms = np.sqrt(windows(disp * disp, p.z_len).mean(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        stretch = np.where(rms > 0, disp / rms, 0.0)
    stretch[~np.isfinite(rms)] = np.nan
    snap = -np.tanh(stretch / 2.0) * (1.0 - er)

    exhaustion = np.full(n, np.nan)
    prev_d = shift(disp, 1)
    for t in range(n):
        s = stretch[t]
        if not math.isfinite(s):
            continue
        fading = math.isfinite(prev_d[t]) and abs(disp[t]) < abs(prev_d[t])
        exhaustion[t] = (
            (1.0 if s > 0 else -1.0) if (abs(s) >= p.exhaust and fading) else 0.0
        )

    warm = max(p.eq_len, p.ru_len - 1) + p.z_len - 1
    return IndicatorResult(
        "EDI",
        p.__dict__.copy(),
        {
            "stretch": stretch,
            "snap_back": snap,
            "exhaustion": exhaustion,
            "displacement": disp,
            "equilibrium": eq,
            "efficiency": er,
        },
        warmup=warm,
    )
