"""Fractal Slope Consensus Ribbon (FSCR).

FSCR asks the same question at several geometric scales - "which way is price
sloping?" - and reports how much the scales agree.

Per scale ``k`` (default Fibonacci 5..55):

* ``slope_k``: least-squares slope of close over the last ``k`` bars.
* ``z_k = slope_k sqrt(k) / RU_t``: slope expressed as range units per bar,
  scaled by the square root of the horizon (longer evidence counts more).
* ``v_k = tanh(z_k / gain)`` in [-1, 1] is the scale's vote.

Outputs:

* ``consensus``  ``C = sum(w_k v_k) / sum(w_k)`` with ``w_k = ln k``; [-1, 1].
* ``width``      weighted standard deviation of the votes; [0, 1]. Wide = the
  scales disagree.
* ``maturity``   ``0.6 persist + 0.4 fade`` in [0, 1] where ``persist`` is how
  long ``|C| >= persist_thr`` has held with the same sign (relative to
  ``maturity_len``) and ``fade`` is how much the short scales have weakened
  versus the long scales in the trend direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import clamp, range_unit, rolling_ols_slope


@dataclass(frozen=True)
class FSCRParams:
    scales: Tuple[int, ...] = (5, 8, 13, 21, 34, 55)
    ru_len: int = 20
    gain: float = 1.0
    persist_thr: float = 0.3
    maturity_len: int = 50


def compute_fscr(candles: Candles, p: FSCRParams = FSCRParams()) -> IndicatorResult:
    c = candles.close
    n = len(candles)
    scales = tuple(sorted(int(k) for k in p.scales))
    ru = range_unit(candles.high, candles.low, c, p.ru_len)
    votes = np.empty((n, len(scales)))
    for i, k in enumerate(scales):
        with np.errstate(invalid="ignore", divide="ignore"):
            votes[:, i] = np.tanh(rolling_ols_slope(c, k) * math.sqrt(k) / ru / p.gain)
    w = np.log(np.array(scales, dtype=np.float64))
    wsum = float(w.sum())
    consensus = votes @ w / wsum
    width = np.sqrt(((votes - consensus[:, None]) ** 2) @ w / wsum)

    half = len(scales) // 2
    v_short = votes[:, :half].mean(axis=1)
    v_long = votes[:, half:].mean(axis=1)

    maturity = np.full(n, np.nan)
    run = 0
    prev_sign = 0.0
    for t in range(n):
        ct = consensus[t]
        if not math.isfinite(ct):
            run = 0
            prev_sign = 0.0
            continue
        if abs(ct) >= p.persist_thr:
            s = 1.0 if ct > 0 else -1.0
            run = run + 1 if s == prev_sign else 1
            prev_sign = s
        else:
            run = 0
            prev_sign = 0.0
        if ct == 0.0:
            maturity[t] = 0.0
            continue
        persist = min(1.0, run / p.maturity_len)
        fade = clamp((1.0 if ct > 0 else -1.0) * (v_long[t] - v_short[t]), 0.0, 1.0)
        maturity[t] = 0.6 * persist + 0.4 * fade

    outputs = {"consensus": consensus, "width": width, "maturity": maturity}
    for i, k in enumerate(scales):
        outputs[f"vote_{k}"] = votes[:, i]
    return IndicatorResult(
        "FSCR",
        {**p.__dict__, "scales": list(scales)},
        outputs,
        warmup=max(max(scales), p.ru_len) - 1,
    )
