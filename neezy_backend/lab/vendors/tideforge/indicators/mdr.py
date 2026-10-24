"""Momentum Decay Radar (MDR).

Concept
-------
Momentum rarely dies all at once — it loses energy in measurable stages
before price turns. MDR watches (a) the rate-of-change of the rate-of-change
(momentum curvature), (b) the energy of the latest swing versus the previous
same-direction swing, and (c) estimates the decay half-life of momentum.

Math
----
1. roc_p = C_t / C_{t-roc_period} - 1        (first derivative proxy)
2. curvature = roc_t - roc_{t-curv_period}   (second derivative proxy),
   normalised by rolling stdev of roc.
3. Swing energy: zigzag pivots with threshold = swing_atr_mult * ATR;
   energy of a leg = |sum of roc over the leg| . energy_ratio =
   energy(last leg) / energy(previous same-direction leg)   (0..inf, clipped 2)
4. decay_raw = 0.5 * tanh(-curv_norm) + 0.5 * tanh(1 - energy_ratio)
   decay score in [-1, 1]  (>0 = losing energy)
5. Half-life estimate: fit exponential decay H_t = H_0 * 0.5^(t/hl) to the
   recent |roc| series via log-linear regression over the last
   `half_life_win` bars; hl clipped to [2, half_life_max].
6. Divergence warning: price made a new swing high (low) within the window
   while the roc trendline slope is negative (positive).
7. reversal_risk 0..100 = 40*max(decay,0) + 30*(1 - min(energy_ratio,1))
   + 30*divergence_flag.

Outputs: decay (-1..1), energy_ratio (0..2), half_life (bars),
divergence (0/1), reversal_risk (0..100).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


class MDR(Indicator):
    NAME = "MDR"
    PARAMS = {
        "roc_period": (10, 3, 100, "first rate-of-change period"),
        "curv_period": (7, 2, 50, "period of ROC-of-ROC (tuned v1.1)"),
        "swing_atr_mult": (
            2.0,
            0.3,
            6.0,
            "zigzag threshold in ATR multiples (tuned v1.1)",
        ),
        "swing_lookback": (60, 20, 300, "bars searched for swing legs"),
        "half_life_win": (20, 5, 100, "regression window for half-life"),
        "half_life_max": (40, 5, 200, "cap on half-life estimate"),
    }

    def _warmup(self) -> int:
        return int(
            max(
                self.params["roc_period"] + self.params["curv_period"],
                self.params["swing_lookback"],
                self.params["half_life_win"],
            )
            + 5
        )

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        close = nu.closes(series)
        high = np.asarray([x.high for x in series.candles])
        low = np.asarray([x.low for x in series.candles])
        n = len(close)
        roc = nu.pct_change(close, int(p["roc_period"]))
        roc_std = nu.rolling_std(roc, 50)
        curv = np.full(n, np.nan)
        k = int(p["curv_period"])
        curv[k:] = roc[k:] - roc[:-k]
        curv_n = curv / (roc_std + nu.EPS)

        atr = nu.atr(high, low, close, 14)
        # per-bar zigzag threshold: ATR * mult at each bar (no lookahead —
        # bar i's threshold only uses bar i's own ATR)
        thr_arr = np.where(np.isnan(atr), np.inf, atr * float(p["swing_atr_mult"]))
        legs = nu.zigzag_swings(close, thr_arr)
        leg_energy: list[tuple[int, int, int, float]] = []
        for i0, i1, drc in legs:
            seg = roc[i0 : i1 + 1]
            seg = seg[~np.isnan(seg)]
            leg_energy.append((i0, i1, drc, float(np.abs(seg).sum())))

        out: list[IndicatorOutput] = []
        for i, e in enumerate(series.epochs):
            if i < self.warmup:
                out.append(
                    IndicatorOutput(
                        epoch=int(e), indicator=self.NAME, ready=False, values={}
                    )
                )
                continue
            # energy ratio: last completed leg vs previous same-direction leg
            prev_legs = [le for le in leg_energy if le[1] <= i]
            eratio = np.nan
            if len(prev_legs) >= 2:
                last = prev_legs[-1]
                same = [le for le in prev_legs[:-1] if le[2] == last[2]]
                if same and same[-1][3] > nu.EPS:
                    eratio = float(np.clip(last[3] / same[-1][3], 0, 2))

            cn = 0.0 if np.isnan(curv_n[i]) else float(np.clip(curv_n[i], -3, 3))
            decay = 0.5 * float(np.tanh(-cn)) + (
                0.5 * float(np.tanh(1.0 - eratio)) if not np.isnan(eratio) else 0.0
            )

            # half-life via log-linear fit on |roc|
            w = int(p["half_life_win"])
            seg = np.abs(roc[i - w + 1 : i + 1])
            mask = seg > nu.EPS
            hl = np.nan
            if mask.sum() >= 5:
                y = np.log(seg[mask])
                x = np.arange(len(seg))[mask].astype(float)
                if len(x) >= 3 and x[-1] - x[0] > 1:
                    slope = float(np.polyfit(x, y, 1)[0])
                    if slope < -nu.EPS:
                        hl = float(np.clip(np.log(0.5) / slope, 2, p["half_life_max"]))
                    else:
                        hl = float(p["half_life_max"])

            # divergence: price new extreme in window vs roc slope sign
            lb = int(p["swing_lookback"])
            c_win = close[i - lb + 1 : i + 1]
            r_win = roc[i - lb + 1 : i + 1]
            div = 0.0
            rm = r_win[~np.isnan(r_win)]
            if len(rm) >= 5 and len(c_win) > 3:
                r_slope = float(np.polyfit(np.arange(len(rm)), rm, 1)[0])
                if c_win[-1] >= np.nanmax(c_win) and r_slope < 0:
                    div = 1.0
                elif c_win[-1] <= np.nanmin(c_win) and r_slope > 0:
                    div = 1.0

            risk = 100.0 * (
                0.40 * max(decay, 0.0)
                + 0.30 * (1.0 - (min(eratio, 1.0) if not np.isnan(eratio) else 0.5))
                + 0.30 * div
            )
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=True,
                    values={
                        "decay": float(np.clip(decay, -1, 1)),
                        "energy_ratio": None if np.isnan(eratio) else float(eratio),
                        "half_life": None if np.isnan(hl) else float(hl),
                        "divergence": float(div),
                        "reversal_risk": float(np.clip(risk, 0, 100)),
                    },
                )
            )
        return out
