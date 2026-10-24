"""Trend Integrity Score (TIS).

Concept
-------
A trend is more than direction: it has *integrity* — how clean, persistent,
and consistently retraced the path is. TIS blends four orthogonal path
statistics into a single 0-100 score and labels the regime.

Math (window = `window` bars, current bar included, no lookahead)
----
1. Path efficiency  eff = |C_t - C_{t-w+1}| / sum|dC|            in [0,1]
2. Directional persistence = max(sign-run fraction of bar directions)
3. Pullback depth consistency: collect retracement depths of the dominant
   direction (fraction of the leg given back); consistency = 1/(1+CV) where
   CV = stdev(depth)/mean(depth).
4. Noise ratio = 1 - |net move| / sum(high - low)                 in [0,1]
5. score = 100 * (0.35*eff + 0.25*persist + 0.20*consist + 0.20*(1-noise))
6. Regime:
     clean_trend : eff >= 0.35 and score >= 60
     dirty_trend : score >= 45 (not clean)
     range       : eff < 0.15 and score < 40
     chop        : everything else

Outputs: score (0..100), efficiency (0..1), persistence (0..1),
consistency (0..1), noise (0..1), regime (string).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


class TIS(Indicator):
    NAME = "TIS"
    PARAMS = {
        "window": (64, 20, 400, "analysis window"),
        "w_eff": (0.35, 0.0, 1.0, "weight: path efficiency"),
        "w_persist": (0.25, 0.0, 1.0, "weight: directional persistence"),
        "w_consist": (0.20, 0.0, 1.0, "weight: pullback consistency"),
        "w_noise": (0.20, 0.0, 1.0, "weight: 1 - noise"),
    }

    def _warmup(self) -> int:
        return int(self.params["window"] + 2)

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        w = int(p["window"])
        close = nu.closes(series)
        high = np.asarray([x.high for x in series.candles])
        low = np.asarray([x.low for x in series.candles])
        d = np.concatenate([[0.0], np.diff(close)])
        n = len(close)

        out: list[IndicatorOutput] = []
        for i, e in enumerate(series.epochs):
            if i < self.warmup:
                out.append(
                    IndicatorOutput(
                        epoch=int(e), indicator=self.NAME, ready=False, values={}
                    )
                )
                continue
            sl = slice(i - w + 1, i + 1)
            c_w, d_w = close[sl], d[sl]
            h_w, l_w = high[sl], low[sl]
            net = abs(c_w[-1] - c_w[0])
            path = float(np.abs(d_w).sum()) + nu.EPS
            eff = float(np.clip(net / path, 0, 1))

            dirs = np.sign(d_w[1:])
            dirs = dirs[dirs != 0]
            if len(dirs) == 0:
                persist = 0.0
            else:
                best = run = 1
                for a, b in zip(dirs, dirs[1:]):
                    run = run + 1 if a == b else 1
                    best = max(best, run)
                persist = float(best / len(dirs))

            up_leg = c_w[-1] >= c_w[0]
            depths: list[float] = []
            extreme = c_w[0]
            for px in c_w[1:]:
                if up_leg:
                    extreme = max(extreme, px)
                    depths.append((extreme - px) / (extreme + nu.EPS))
                else:
                    extreme = min(extreme, px)
                    depths.append((px - extreme) / (extreme + nu.EPS))
            depths = [x for x in depths if 0 < x < 1]
            if len(depths) >= 3:
                m = float(np.mean(depths))
                s = float(np.std(depths))
                consist = float(1.0 / (1.0 + s / (m + nu.EPS)))
            else:
                consist = 0.5

            rng = float((h_w - l_w).sum()) + nu.EPS
            noise = float(np.clip(1.0 - net / rng, 0, 1))

            score = (
                100.0
                * (
                    p["w_eff"] * eff
                    + p["w_persist"] * persist
                    + p["w_consist"] * consist
                    + p["w_noise"] * (1.0 - noise)
                )
                / max(
                    p["w_eff"] + p["w_persist"] + p["w_consist"] + p["w_noise"], nu.EPS
                )
            )
            if eff >= 0.35 and score >= 60:
                regime = "clean_trend"
            elif score >= 45:
                regime = "dirty_trend"
            elif eff < 0.15 and score < 40:
                regime = "range"
            else:
                regime = "chop"
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=True,
                    values={
                        "score": float(np.clip(score, 0, 100)),
                        "efficiency": eff,
                        "persistence": persist,
                        "consistency": consist,
                        "noise": noise,
                        "regime_str": regime,
                    },
                )
            )
        return out
