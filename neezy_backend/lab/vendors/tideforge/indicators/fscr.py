"""Fractal Slope Consensus Ribbon (FSCR).

Concept
-------
Trends are fractal: they only matter when several geometric scales of the
same price path agree. FSCR measures the normalised slope of price at scales
5, 8, 13, 21, 34, 55 bars (Fibonacci-like ladder), counts how many scales
agree in sign, and expresses disagreement as ribbon width.

Math
----
For scale s:
    slope_s = (C_t - C_{t-s}) / s
    ns_s    = slope_s / (ATR_s / s + eps)      (ATR_s = mean true range over s bars)
Consensus = (1/N) * sum(sign(ns_s))            in [-1, +1]
Ribbon width (disagreement) = stdev(ns over scales) / (mean|ns| + eps), clipped [0, 2]
Trend maturity = min(1, bars_since(consensus sign changed) / 20)

Outputs: consensus (-1..1), ribbon_width (0..2), trend_maturity (0..1).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput

DEFAULT_SCALES = (5, 8, 13, 21, 34, 55)


class FSCR(Indicator):
    NAME = "FSCR"
    PARAMS = {
        "scales": (
            0,
            0,
            0,
            "0 = default ladder 5,8,13,21,34,55; 1 = conservative ladder 13,21,34,55 (drops noisy fast scales); or a list of scales",
        ),
        "maturity_span": (20, 5, 100, "bars to full maturity"),
    }

    LADDERS = {0: DEFAULT_SCALES, 1: (13, 21, 34, 55)}

    def __init__(self, **overrides) -> None:
        # list/tuple scale overrides bypass the numeric-range validation
        # (they are popped before super().__init__, which calls _warmup)
        self._scale_override = (
            list(overrides.pop("scales"))
            if isinstance(overrides.get("scales"), (list, tuple))
            else None
        )
        raw = (
            str(int(overrides["scales"]))
            if overrides.get("scales")
            else ",".join(map(str, DEFAULT_SCALES))
        )
        self.scale_list = [
            int(s)
            for s in (
                self._scale_override or [int(s) for s in raw.split(",") if s.strip()]
            )
        ]
        if len(self.scale_list) < 2:
            raise ValueError("FSCR needs at least 2 scales")
        super().__init__(**overrides)
        if self._scale_override is not None:
            self.scale_list = list(self._scale_override)
        elif int(self.params["scales"]) in self.LADDERS:
            self.scale_list = list(self.LADDERS[int(self.params["scales"])])
        else:
            self.scale_list = [
                int(s) for s in str(int(self.params["scales"])).split(",") if s.strip()
            ]
        if len(self.scale_list) < 2:
            raise ValueError("FSCR needs at least 2 scales")

    def _warmup(self) -> int:
        return max(self.scale_list) + 5

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        c = nu.closes(series)
        high = np.asarray([x.high for x in series.candles])
        low = np.asarray([x.low for x in series.candles])
        n = len(c)
        ns = np.full((len(self.scale_list), n), np.nan)
        for k, s in enumerate(self.scale_list):
            slope = np.full(n, np.nan)
            slope[s:] = (c[s:] - c[:-s]) / s
            atr_s = nu.atr(high, low, c, s)
            ns[k] = slope / (atr_s / s + nu.EPS)

        signs = np.sign(ns)
        valid = ~np.isnan(ns)
        consensus = np.where(
            valid.sum(0) > 0,
            np.nansum(np.where(valid, signs, 0), 0) / np.maximum(valid.sum(0), 1),
            np.nan,
        )
        mean_abs = np.nanmean(np.abs(ns), 0)
        std_ns = np.nanstd(ns, 0)
        width = np.clip(std_ns / (mean_abs + nu.EPS), 0, 2)

        maturity = np.full(n, np.nan)
        run, prev_sign = 0, 0.0
        for i in range(n):
            if np.isnan(consensus[i]):
                continue
            s_i = float(np.sign(consensus[i]))
            if s_i == prev_sign and s_i != 0:
                run += 1
            else:
                run, prev_sign = (1 if s_i != 0 else 0), s_i
            maturity[i] = min(1.0, run / self.params["maturity_span"])

        out = []
        for i, e in enumerate(series.epochs):
            ready = not np.isnan(consensus[i])
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=ready,
                    values={
                        "consensus": None if not ready else float(consensus[i]),
                        "ribbon_width": None if not ready else float(width[i]),
                        "trend_maturity": None if not ready else float(maturity[i]),
                    },
                )
            )
        return out
