"""Momentum Decay Radar (MDR).

MDR looks for momentum that is *losing energy* while price is still moving the
same way - the typical precursor of a turn. Three independent probes are
blended into a decay score:

1. **Acceleration probe** - momentum ``m = EMA(ROC_k / RU)`` and its rate of
   change ``a = EMA(m_raw_t - m_raw_{t-k})``. When ``a`` opposes ``m`` the
   push is weakening: ``accel = clamp(|a| / (|m| + 0.25), 0, 1)``.
2. **Swing energy probe** - a causal close-only zig-zag (reversal threshold
   ``swing_mult x RU``) splits price into legs. Leg energy is ``(move/bars)^2``
   (a kinetic-energy analogue). ``swing_ratio`` compares the leg in progress
   with the previous leg in the same direction; ``swing = clamp(1 - ratio, 0, 1)``.
3. **Half-life probe** - fit ``ln(|m| + 1e-6) = a + b x`` over ``hl_len`` bars.
   If ``b < 0`` the momentum half-life is ``ln 2 / -b`` bars;
   ``hl = clamp(1 - half_life / (2 hl_len), 0, 1)``.

``decay = 0.4 accel + 0.3 swing + 0.3 hl`` in [0, 1].

``warning`` is a divergence-like flag: +1 when the current up-leg made a new
high above the previous swing high with ``swing_ratio < div_ratio`` (bearish
warning), -1 for the mirrored case. ``risk`` buckets decay into 0..3 (low,
moderate, high, extreme) and adds one level when a warning is active.
``signal = -sign(m) decay`` is the directional (reversal) reading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import clamp, ema_skip_nan, range_unit, shift, windows

RISK_LABELS = {0: "low", 1: "moderate", 2: "high", 3: "extreme"}
HL_FLOOR = 1e-6


@dataclass(frozen=True)
class MDRParams:
    roc_len: int = 10
    smooth: int = 5
    hl_len: int = 20
    swing_mult: float = 2.0
    div_ratio: float = 0.8
    ru_len: int = 20


def _half_life(m: np.ndarray, hl_len: int) -> np.ndarray:
    """Momentum half-life (bars) from a rolling log-linear fit; capped at 10 hl_len."""
    cap = 10.0 * hl_len
    x = np.arange(hl_len, dtype=np.float64)
    xc = x - x.mean()
    sxx = float(np.dot(xc, xc))
    y = np.log(np.abs(m) + HL_FLOOR)
    b = windows(y, hl_len) @ xc / sxx
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.where(b < 0, math.log(2.0) / -b, cap)
    hl = np.minimum(hl, cap)
    hl[~np.isfinite(b)] = np.nan
    return hl


def compute_mdr(candles: Candles, p: MDRParams = MDRParams()) -> IndicatorResult:
    h, l, c = candles.high, candles.low, candles.close
    n = len(candles)
    ru = range_unit(h, l, c, p.ru_len)
    with np.errstate(invalid="ignore", divide="ignore"):
        m_raw = (c - shift(c, p.roc_len)) / ru
    a_raw = m_raw - shift(m_raw, p.roc_len)
    alpha = 2.0 / (p.smooth + 1.0)
    m = ema_skip_nan(m_raw, alpha)
    a = ema_skip_nan(a_raw, alpha)
    m[~np.isfinite(a_raw)] = np.nan  # report momentum only once both probes exist
    hl = _half_life(m, p.hl_len)

    swing_ratio = np.full(n, np.nan)
    warning = np.full(n, np.nan)
    # Zig-zag state.
    started = False
    direction = 0
    ext_p = ext_i = 0.0
    pivots: list[tuple[int, float]] = []  # confirmed pivots, alternating
    for t in range(n):
        ct, rt = c[t], ru[t]
        if not (math.isfinite(ct) and math.isfinite(rt) and rt > 0):
            continue
        thr = p.swing_mult * rt
        if not started:
            started = True
            pivots.append((t, ct))
            ext_p, ext_i = ct, t
        elif direction == 0:
            anchor = pivots[-1][1]
            if ct >= anchor + thr:
                direction, ext_p, ext_i = 1, ct, t
            elif ct <= anchor - thr:
                direction, ext_p, ext_i = -1, ct, t
        elif direction == 1:
            if ct > ext_p:
                ext_p, ext_i = ct, t
            elif ext_p - ct >= thr:
                pivots.append((int(ext_i), ext_p))
                direction, ext_p, ext_i = -1, ct, t
        else:
            if ct < ext_p:
                ext_p, ext_i = ct, t
            elif ct - ext_p >= thr:
                pivots.append((int(ext_i), ext_p))
                direction, ext_p, ext_i = 1, ct, t

        warn = 0.0
        if direction != 0 and len(pivots) >= 3:
            p_last_i, p_last = pivots[-1]
            p_a_i, p_a = pivots[-3]
            p_b_i, p_b = pivots[-2]
            bars_cur = max(1.0, ext_i - p_last_i)
            e_cur = ((ext_p - p_last) / bars_cur) ** 2
            bars_ref = max(1.0, p_b_i - p_a_i)
            e_ref = ((p_b - p_a) / bars_ref) ** 2
            if e_ref > 0:
                ratio = e_cur / e_ref
                swing_ratio[t] = ratio
                if ratio < p.div_ratio:
                    if direction == 1 and ext_p > p_b:
                        warn = 1.0
                    elif direction == -1 and ext_p < p_b:
                        warn = -1.0
        warning[t] = warn

    decay = np.full(n, np.nan)
    risk = np.full(n, np.nan)
    signal = np.full(n, np.nan)
    for t in range(n):
        mt, at, ht = m[t], a[t], hl[t]
        if not (
            math.isfinite(mt)
            and math.isfinite(at)
            and math.isfinite(ht)
            and math.isfinite(warning[t])
        ):
            continue
        sm = 1.0 if mt > 0 else (-1.0 if mt < 0 else 0.0)
        sa = 1.0 if at > 0 else (-1.0 if at < 0 else 0.0)
        acc = (
            clamp(abs(at) / (abs(mt) + 0.25), 0.0, 1.0)
            if (sm != 0.0 and sa == -sm)
            else 0.0
        )
        sr = swing_ratio[t]
        sw = clamp(1.0 - sr, 0.0, 1.0) if math.isfinite(sr) else 0.0
        hlt = clamp(1.0 - ht / (2.0 * p.hl_len), 0.0, 1.0)
        dt = 0.4 * acc + 0.3 * sw + 0.3 * hlt
        rk = 0.0 if dt < 0.3 else (1.0 if dt < 0.5 else (2.0 if dt < 0.7 else 3.0))
        if warning[t] != 0.0:
            rk = min(3.0, rk + 1.0)
        decay[t] = dt
        risk[t] = rk
        signal[t] = -sm * dt
    return IndicatorResult(
        "MDR",
        p.__dict__.copy(),
        {
            "decay": decay,
            "signal": signal,
            "risk": risk,
            "warning": warning,
            "momentum": m,
            "accel": a,
            "half_life": hl,
            "swing_ratio": swing_ratio,
        },
        warmup=p.ru_len - 1 + 2 * p.roc_len + p.hl_len - 1,
        labels={"risk": RISK_LABELS},
    )
