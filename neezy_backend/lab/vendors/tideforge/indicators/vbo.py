"""Volatility Breath Oscillator (VBO).

Concept
-------
Volatility breathes: long quiet compression phases (inhale) alternate with
violent expansions (exhale). VBO compares realised volatility measured on a
fast, a mid and a slow scale, converts their relationship into a breathing
phase, and estimates how likely an expansion is imminent.

Math
----
For scale s in {fast, mid, slow}:
    rv_s      = stdev(log returns, s)
    z_s       = rv_s / rolling_mean(rv_s, 3s)          (vol relative to its own norm)
    B         = z_fast - 0.5*z_mid - 0.5*z_slow        (breath index)
Phase:
    inhale if B < -thr and z_fast falling
    exhale if B > +thr and z_fast rising
    hold otherwise
Phase age: bars since the phase last changed.
Expansion-imminent probability:
    p = sigmoid(0.9 * (-B) + 0.12 * age_inhale - 1.1)   (clipped to [0,1])

Outputs: breath_index (-2..2), breath_phase (0 inhale /1 hold /2 exhale),
phase_age (bars), expansion_prob (0..1).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


class VBO(Indicator):
    NAME = "VBO"
    PARAMS = {
        "fast": (12, 4, 100, "fast volatility window"),
        "mid": (36, 8, 300, "mid volatility window"),
        "slow": (144, 16, 600, "slow volatility window (tuned v1.1)"),
        "threshold": (0.30, 0.05, 1.5, "breath index phase threshold (tuned v1.1)"),
    }

    def _warmup(self) -> int:
        return int(3 * self.params["slow"] + 5)

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        c = nu.closes(series)
        n = len(c)
        ret = np.concatenate([[0.0], np.diff(np.log(np.maximum(c, nu.EPS)))])

        def zscore(w: int) -> np.ndarray:
            rv = nu.rolling_std(ret, w)
            return rv / (nu.rolling_mean(rv, 3 * w) + nu.EPS)

        zf, zm, zs = (
            zscore(int(p["fast"])),
            zscore(int(p["mid"])),
            zscore(int(p["slow"])),
        )
        B = zf - 0.5 * zm - 0.5 * zs
        thr = float(p["threshold"])
        zf_falling = np.full(n, np.nan)
        r = nu.rolling_mean(zf, 3)
        zf_falling[1:] = r[1:] - r[:-1]

        phase = np.full(n, np.nan)
        age = np.zeros(n)
        prob = np.full(n, np.nan)
        cur, cur_age = 1, 0
        for i in range(n):
            if np.isnan(B[i]):
                continue
            if B[i] < -thr and (np.isnan(zf_falling[i]) or zf_falling[i] <= 0):
                new = 0
            elif B[i] > thr and (np.isnan(zf_falling[i]) or zf_falling[i] >= 0):
                new = 2
            else:
                new = 1
            if new != cur:
                cur, cur_age = new, 0
            cur_age += 1
            phase[i], age[i] = cur, cur_age
            prob[i] = float(
                np.clip(
                    nu.logistic(
                        0.9 * (-B[i]) + 0.12 * (cur_age if cur == 0 else 0) - 1.1
                    ),
                    0,
                    1,
                )
            )

        out = []
        for i, e in enumerate(series.epochs):
            ready = (i >= self.warmup) and not np.isnan(phase[i])
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=ready,
                    values={
                        "breath_index": None if not ready else float(B[i]),
                        "breath_phase": None if not ready else float(phase[i]),
                        "phase_age": None if not ready else float(age[i]),
                        "expansion_prob": None if not ready else float(prob[i]),
                    },
                )
            )
        return out
