"""Elastic Displacement Index (EDI).

Concept
-------
EDI measures how far price is stretched away from an *adaptive equilibrium
line* — a volatility-weighted, efficiency-adjusted moving center — and how
much snap-back pressure is building.

Math (plain language)
---------------------
1. Base center: arithmetic mean of close over `center_period` bars.
2. Efficiency ratio ER in [0,1]: |C_t - C_{t-eff}| / sum(|dC|) over `eff_period`.
   ER near 1 = trending (efficient) market; near 0 = choppy.
3. Adaptive equilibrium: E_t = E_{t-1} + er * (C_t - E_{t-1}), seeded with the
   first base center. In trends E hugs price (large er), in chop E stays flat
   and slow.
4. Volatility normalisation: sigma = stdev(log returns, vol_period) *
   rolling_mean(sigma, 3*vol_period) normaliser, scaled by sqrt(center_period)
   to convert per-bar sigma into an expected excursion over the center window.
5. stretch = tanh((C_t - E_t) / sigma_exc) in (-1, +1).
6. Snap-back pressure = -stretch * exhaust, where exhaust in [0,1] grows the
   longer price holds the same side beyond |stretch| = 0.5 and the more the
   last-bar momentum (ROC) shrinks while stretch stays extreme.
7. exhaustion flag: |stretch| >= stretch_level for >= confirm bars.

Outputs: stretch (-1..1), snap_back (-1..1), exhaustion (0/1).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


class EDI(Indicator):
    NAME = "EDI"
    PARAMS = {
        "center_period": (48, 8, 400, "bars in the base moving center"),
        "vol_period": (48, 8, 400, "return-stdev window for normalisation"),
        "eff_period": (24, 5, 200, "efficiency-ratio window"),
        "stretch_level": (
            0.85,
            0.3,
            1.5,
            "stretch magnitude considered extreme (tuned v1.1)",
        ),
        "confirm": (
            4,
            1,
            20,
            "consecutive extreme bars to flag exhaustion (tuned v1.1)",
        ),
    }

    def _warmup(self) -> int:
        return int(
            max(
                self.params["center_period"],
                3 * self.params["vol_period"],
                self.params["eff_period"],
            )
            + 5
        )

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        c = nu.closes(series)
        n = len(c)
        out: list[IndicatorOutput] = []
        if n < self.warmup + 1:
            return [o if isinstance(o, IndicatorOutput) else None for o in []] or [
                IndicatorOutput(
                    epoch=int(e), indicator=self.NAME, ready=False, values={}
                )
                for e in series.epochs
            ]

        base = nu.rolling_mean(c, int(p["center_period"]))
        ret = np.concatenate([[0.0], np.diff(np.log(np.maximum(c, nu.EPS)))])
        vol = nu.rolling_std(ret, int(p["vol_period"]))
        vol_norm = vol / (nu.rolling_mean(vol, 3 * int(p["vol_period"])) + nu.EPS)

        er_win = int(p["eff_period"])
        net = np.abs(np.concatenate([np.zeros(er_win), c[er_win:] - c[:-er_win]]))
        d = np.abs(np.concatenate([[0.0], np.diff(c)]))
        path = nu.rolling_sum(d, er_win)
        er = net / (path + nu.EPS)

        eq = np.full(n, np.nan)
        seed_idx = int(p["center_period"]) - 1
        if seed_idx < n and not np.isnan(base[seed_idx]):
            eq[seed_idx] = base[seed_idx]
            k = 1.0 / np.sqrt(max(int(p["center_period"]), 1))
            for i in range(seed_idx + 1, n):
                er_i = 0.0 if np.isnan(er[i]) else float(np.clip(er[i], 0, 1))
                eq[i] = (
                    eq[i - 1]
                    + er_i * (c[i] - eq[i - 1]) * (1.0 if er_i < 1 else 1.0) * k
                    if False
                    else eq[i - 1] + er_i * (c[i] - eq[i - 1])
                )

        sigma_exc = vol * vol_norm * np.sqrt(p["center_period"])
        stretch = nu.tanh_scale(c - eq, sigma_exc)

        roc = nu.pct_change(c, 5)
        extreme = np.abs(stretch) >= p["stretch_level"]
        side = np.sign(stretch)
        snap = np.zeros(n)
        exhaust_flag = np.zeros(n)
        run = 0
        prev_side = 0.0
        for i in range(n):
            if np.isnan(stretch[i]):
                continue
            if side[i] == prev_side and extreme[i]:
                run += 1
            else:
                run = 1 if extreme[i] else 0
            prev_side = side[i]
            mom_ok = (not np.isnan(roc[i])) and abs(roc[i]) < abs(
                np.nanmean(roc[max(0, i - 10) : i + 1]) + 0.0
            ) * 0.5
            exhaust = min(1.0, run / max(p["confirm"], 1)) * (
                1.0 if mom_ok or run > p["confirm"] else 0.6
            )
            snap[i] = -stretch[i] * exhaust
            exhaust_flag[i] = (
                1.0
                if run >= p["confirm"] and abs(stretch[i]) >= p["stretch_level"]
                else 0.0
            )

        for i, e in enumerate(series.epochs):
            ready = (i >= self.warmup) and not np.isnan(stretch[i])
            vals = {
                "stretch": None if not ready else float(stretch[i]),
                "snap_back": None if not ready else float(np.clip(snap[i], -1, 1)),
                "exhaustion": None if not ready else float(exhaust_flag[i]),
                "equilibrium": None if np.isnan(eq[i]) else float(eq[i]),
            }
            out.append(
                IndicatorOutput(
                    epoch=int(e), indicator=self.NAME, ready=ready, values=vals
                )
            )
        return out
