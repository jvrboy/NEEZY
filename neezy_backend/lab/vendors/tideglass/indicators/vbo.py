"""Volatility Breath Oscillator (VBO).

Markets "breathe": realized volatility compresses (inhale), pauses (hold) and
then expands (exhale). VBO measures the breath across three time scales and
estimates, from the instrument's own history, how likely an expansion is soon.

Per bar ``t``:

* ``r_t = ln(C_t / C_{t-1})``; ``sigma_k = sqrt(mean(r^2))`` over ``k`` bars for
  ``k`` in (short, mid, long).
* Breath ``B_t = w ln(sigma_s / sigma_m) + (1 - w) ln(sigma_m / sigma_l)``.
* Phase: ``-1`` inhale if ``B < -band``, ``+1`` exhale if ``B > band``, else ``0``
  hold. ``phase_age`` counts consecutive bars in the current phase.
* ``expansion_prob``: among past bars ``j`` in ``[t - hist, t - horizon]`` with
  the same phase and ``|B_j - B_t| <= sim_tol``, the Laplace-smoothed fraction
  that reached an exhale phase within ``horizon`` bars. Only outcomes that are
  fully known at time ``t`` are used, so the estimate is causal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import EPS, shift, windows


@dataclass(frozen=True)
class VBOParams:
    short: int = 10
    mid: int = 30
    long: int = 90
    w_short: float = 0.6
    band: float = 0.15
    horizon: int = 10
    hist: int = 250
    sim_tol: float = 0.2


PHASE_LABELS = {-1: "inhale", 0: "hold", 1: "exhale"}


def compute_vbo(candles: Candles, p: VBOParams = VBOParams()) -> IndicatorResult:
    c = candles.close
    n = len(candles)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.log(c / shift(c, 1))
    r2 = r * r

    def sigma(k: int) -> np.ndarray:
        return np.sqrt(windows(r2, k).mean(axis=1)) + EPS

    ss, sm, sl = sigma(p.short), sigma(p.mid), sigma(p.long)
    breath = p.w_short * np.log(ss / sm) + (1.0 - p.w_short) * np.log(sm / sl)

    phase = np.full(n, np.nan)
    ok = np.isfinite(breath)
    phase[ok] = np.where(
        breath[ok] < -p.band, -1.0, np.where(breath[ok] > p.band, 1.0, 0.0)
    )

    age = np.full(n, np.nan)
    run = 0
    for t in range(n):
        if not ok[t]:
            run = 0
            continue
        run = run + 1 if (t > 0 and ok[t - 1] and phase[t - 1] == phase[t]) else 1
        age[t] = run

    # Distance to the next exhale bar for each j (used only once j + horizon <= t).
    next_ex = np.full(n, np.iinfo(np.int64).max // 4, dtype=np.int64)
    nxt = np.iinfo(np.int64).max // 4
    for j in range(n - 1, -1, -1):
        next_ex[j] = nxt
        if ok[j] and phase[j] == 1.0:
            nxt = j
    success = (next_ex - np.arange(n)) <= p.horizon

    prob = np.full(n, np.nan)
    for t in range(n):
        if not ok[t]:
            continue
        lo = max(0, t - p.hist)
        hi = t - p.horizon
        if hi < lo:
            prob[t] = 0.5
            continue
        seg = slice(lo, hi + 1)
        cand = (
            ok[seg]
            & (phase[seg] == phase[t])
            & (np.abs(breath[seg] - breath[t]) <= p.sim_tol)
        )
        m = int(cand.sum())
        k = int((cand & success[seg]).sum())
        prob[t] = (k + 1.0) / (m + 2.0)

    warm = p.long
    return IndicatorResult(
        "VBO",
        p.__dict__.copy(),
        {
            "breath": breath,
            "phase": phase,
            "phase_age": age,
            "expansion_prob": prob,
            "sigma_short": np.where(ok, ss, np.nan),
            "sigma_long": np.where(ok, sl, np.nan),
        },
        warmup=warm,
        labels={"phase": PHASE_LABELS},
    )
