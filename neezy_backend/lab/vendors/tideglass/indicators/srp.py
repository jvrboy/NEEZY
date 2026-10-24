"""Session Rhythm Profile (SRP).

Every FX pair has a daily rhythm: quiet Asian hours, the London open burst,
the London/New York overlap, the late fade. SRP *learns* that rhythm from the
instrument's own history and reports how the current bar deviates from it.

For each hour-of-day bucket (UTC) and each session bucket the learner keeps
exponentially weighted statistics of

* relative range ``rr = (H - L) / O`` and its log ``lr = ln(max(rr, 1e-7))``
  (mean and variance),
* bar return ``ret = ln(C / O)`` and ``|ret|``.

The learning rate is ``max(1 / learn_len, 1 / count)``, so the first
observations form a plain average and later ones an EW average. A bucket
produces output only after ``min_obs`` observations. The bar's *own* values are
added to the learner only after its outputs are computed, which keeps SRP
strictly causal.

Outputs (hour bucket unless prefixed ``session_``):

* ``expected_range`` = learned mean ``rr x O_t`` (price units)
* ``range_ratio`` = actual range / expected range
* ``anomaly_z`` = ``(lr - mean lr) / sd lr``; ``anomaly_flag`` = ``sign(z)``
  when ``|z| >= anomaly_z`` (+1 unusually hot, -1 unusually dead)
* ``hour_bias`` = learned ``mean ret / mean |ret|`` in [-1, 1]
* ``session`` code: 0 Asia (00-06 UTC), 1 Asia/London overlap (07),
  2 London (08-11), 3 London/New York overlap (12-15), 4 New York (16-20),
  5 Late/Pacific (21-23)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import LOG_FLOOR, valid_mask

SESSION_LABELS = {
    0: "asia",
    1: "asia_london_overlap",
    2: "london",
    3: "london_newyork_overlap",
    4: "newyork",
    5: "late_pacific",
}
_SESSION_OF_HOUR = [0] * 7 + [1] + [2] * 4 + [3] * 4 + [4] * 5 + [5] * 3


@dataclass(frozen=True)
class SRPParams:
    learn_len: int = 20
    min_obs: int = 5
    anomaly_z: float = 2.0


def session_of_hour(hour: int) -> int:
    """Session code for a UTC hour 0..23."""
    return _SESSION_OF_HOUR[hour]


class _Learner:
    """EW mean/variance learner for one bucket."""

    __slots__ = ("count", "mu_lr", "var_lr", "mu_rr", "mu_ret", "mu_abs")

    def __init__(self) -> None:
        self.count = 0
        self.mu_lr = self.var_lr = self.mu_rr = self.mu_ret = self.mu_abs = 0.0

    def update(self, lr: float, rr: float, ret: float, alpha: float) -> None:
        self.count += 1
        if self.count == 1:
            self.mu_lr, self.var_lr, self.mu_rr, self.mu_ret, self.mu_abs = (
                lr,
                0.0,
                rr,
                ret,
                abs(ret),
            )
            return
        a = max(alpha, 1.0 / self.count)
        delta = lr - self.mu_lr
        self.mu_lr += a * delta
        self.var_lr = (1.0 - a) * (self.var_lr + a * delta * delta)
        self.mu_rr += a * (rr - self.mu_rr)
        self.mu_ret += a * (ret - self.mu_ret)
        self.mu_abs += a * (abs(ret) - self.mu_abs)

    def bias(self) -> float:
        return self.mu_ret / self.mu_abs if self.mu_abs > 0 else 0.0


def compute_srp(candles: Candles, p: SRPParams = SRPParams()) -> IndicatorResult:
    o, h, l, c = candles.open, candles.high, candles.low, candles.close
    n = len(candles)
    ok = valid_mask(o, h, l, c) & (o > 0)
    alpha = 1.0 / p.learn_len
    hours = [_Learner() for _ in range(24)]
    sessions = [_Learner() for _ in range(6)]
    names = (
        "expected_range",
        "range_ratio",
        "anomaly_z",
        "anomaly_flag",
        "hour_bias",
        "session",
        "session_expected_range",
        "session_range_ratio",
        "session_bias",
        "signal",
    )
    out = {k: np.full(n, np.nan) for k in names}
    for t in range(n):
        hour = int((int(candles.epoch[t]) % 86400) // 3600)
        ses = session_of_hour(hour)
        out["session"][t] = ses
        if not ok[t]:
            continue
        rr = (h[t] - l[t]) / o[t]
        lr = math.log(max(rr, LOG_FLOOR))
        ret = math.log(c[t] / o[t])
        hb, sb = hours[hour], sessions[ses]
        if hb.count >= p.min_obs:
            exp_r = hb.mu_rr * o[t]
            z = (lr - hb.mu_lr) / math.sqrt(hb.var_lr + 1e-12)
            out["expected_range"][t] = exp_r
            out["range_ratio"][t] = (h[t] - l[t]) / exp_r if exp_r > 0 else math.nan
            out["anomaly_z"][t] = z
            out["anomaly_flag"][t] = (
                (1.0 if z > 0 else -1.0) if abs(z) >= p.anomaly_z else 0.0
            )
            out["hour_bias"][t] = hb.bias()
            out["signal"][t] = hb.bias()
        if sb.count >= p.min_obs:
            exp_s = sb.mu_rr * o[t]
            out["session_expected_range"][t] = exp_s
            out["session_range_ratio"][t] = (
                (h[t] - l[t]) / exp_s if exp_s > 0 else math.nan
            )
            out["session_bias"][t] = sb.bias()
        hb.update(lr, rr, ret, alpha)
        sb.update(lr, rr, ret, alpha)
    return IndicatorResult(
        "SRP", p.__dict__.copy(), out, warmup=0, labels={"session": SESSION_LABELS}
    )
