"""Tick-Density Gravity Zones (TDGZ).

Concept
-------
Forex/CFD candles carry no real volume, so TDGZ builds a *price density map*
from what candles do have: the time spent crossing each price level. Each bar
spreads its weight uniformly over every price bin between its low and high
(wicks included). When Deriv tick data is available the per-bar weight is the
real tick count; otherwise it is 1. Levels where density piles up act as
"gravity zones" that pull price.

Math
----
1. price_lo = min(low, lookback), price_hi = max(high, lookback); split into
   `price_bins` equal bins.
2. For bar i with weight w_i: add w_i / n_bins_touched to every bin touched
   by [low_i, high_i].
3. Keep only the last `lookback` bars (rolling map, recomputed each bar).
4. Gravity zones = contiguous bin runs with density >= quantile(density, 0.8);
   each run's level = density-weighted mean price.
5. For the current close find nearest zone above and below:
       distance_above/below in ATR units = |level - close| / ATR(14)
       pull strength = zone_density / total_density  (in [0,1])

Outputs: gravity_above, gravity_below (price), dist_above_atr, dist_below_atr,
pull_above, pull_below (0..1).
"""

from __future__ import annotations

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import Candle, CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


class TDGZ(Indicator):
    NAME = "TDGZ"
    PARAMS = {
        "lookback": (200, 40, 2000, "bars in the rolling density map"),
        "price_bins": (50, 10, 300, "number of price bins in the map"),
        "zone_quantile": (0.80, 0.5, 0.99, "density quantile defining a gravity zone"),
        "atr_period": (14, 5, 100, "ATR used to express distances"),
    }

    def _warmup(self) -> int:
        return int(self.params["lookback"] + self.params["atr_period"] + 2)

    # ------------------------------------------------------------------ core
    @staticmethod
    def density_map(
        candles: list[Candle],
        price_lo: float,
        price_hi: float,
        n_bins: int,
        weights: np.ndarray | None = None,
    ) -> np.ndarray:
        hist = np.zeros(n_bins)
        span = price_hi - price_lo
        if span <= 0:
            return hist
        for i, c in enumerate(candles):
            w = 1.0 if weights is None or weights[i] <= 0 else float(weights[i])
            lo_bin = int(np.clip((c.low - price_lo) / span * n_bins, 0, n_bins - 1))
            hi_bin = int(np.clip((c.high - price_lo) / span * n_bins, 0, n_bins - 1))
            if hi_bin < lo_bin:
                lo_bin, hi_bin = hi_bin, lo_bin
            share = w / (hi_bin - lo_bin + 1)
            hist[lo_bin : hi_bin + 1] += share
        return hist

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        candles = series.candles
        n = len(candles)
        high = np.asarray([x.high for x in candles])
        low = np.asarray([x.low for x in candles])
        close = nu.closes(series)
        atr = nu.atr(high, low, close, int(p["atr_period"]))
        ticks = nu.tick_counts(series)
        use_ticks = bool(np.any(ticks > 0))
        lb, nb = int(p["lookback"]), int(p["price_bins"])
        q = float(p["zone_quantile"])

        out: list[IndicatorOutput] = []
        for i, e in enumerate(series.epochs):
            if i < self.warmup:
                out.append(
                    IndicatorOutput(
                        epoch=int(e), indicator=self.NAME, ready=False, values={}
                    )
                )
                continue
            window = candles[i - lb + 1 : i + 1]
            w = ticks[i - lb + 1 : i + 1] if use_ticks else None
            plo = min(x.low for x in window)
            phi = max(x.high for x in window)
            hist = self.density_map(window, plo, phi, nb, w)
            thresh = np.quantile(hist[hist > 0], q) if np.any(hist > 0) else np.inf
            # contiguous runs above threshold -> zones
            zones: list[tuple[float, float]] = []  # (level_price, density)
            run_bins: list[int] = []
            for b in range(nb):
                if hist[b] >= thresh:
                    run_bins.append(b)
                else:
                    if run_bins:
                        dens = hist[run_bins].sum()
                        prices = (np.asarray(run_bins) + 0.5) / nb * (phi - plo) + plo
                        zones.append(
                            (
                                float(
                                    (prices * hist[run_bins]).sum() / (dens + nu.EPS)
                                ),
                                float(dens),
                            )
                        )
                        run_bins = []
            if run_bins:
                dens = hist[run_bins].sum()
                prices = (np.asarray(run_bins) + 0.5) / nb * (phi - plo) + plo
                zones.append(
                    (
                        float((prices * hist[run_bins]).sum() / (dens + nu.EPS)),
                        float(dens),
                    )
                )

            total = sum(d for _, d in zones) + nu.EPS
            px = close[i]
            above = [z for z in zones if z[0] > px]
            below = [z for z in zones if z[0] < px]
            za = min(above, key=lambda z: z[0]) if above else (phi, 0.0)
            zb = max(below, key=lambda z: z[0]) if below else (plo, 0.0)
            a = atr[i]
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=True,
                    values={
                        "gravity_above": float(za[0]),
                        "gravity_below": float(zb[0]),
                        "dist_above_atr": float(abs(za[0] - px) / (a + nu.EPS)),
                        "dist_below_atr": float(abs(px - zb[0]) / (a + nu.EPS)),
                        "pull_above": float(za[1] / total),
                        "pull_below": float(zb[1] / total),
                    },
                )
            )
        return out
