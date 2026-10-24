"""Session Rhythm Profile (SRP).

Concept
-------
Forex volatility and bias follow the clock: Asia consolidates, London breaks,
New York extends and fades. SRP *learns* the average behaviour per
hour-of-day (and per session) strictly from bars that are already complete,
then measures how the current, still-forming hour deviates from that norm.

Math
----
For hour h (UTC):
    expected_range[h] = mean(true range of all completed bars with hour == h)
    expected_bias[h]  = mean(signed return of those bars)
    range_sigma[h]    = stdev of those true ranges
Session map (UTC): Asia [23, 8), London [7, 16), NewYork [12, 21);
    a bar can belong to several sessions (overlaps win: London > NY > Asia).
Current deviation:
    actual_range  = high - low of the current hour bucket so far
    actual_vs_expected = actual_range / expected_range[current hour]
    rhythm_anomaly = 1 when actual_vs_expected > 1.5 or
                     |signed return so far - expected_bias| > 2 * range_sigma

Outputs: expected_range, actual_range, actual_vs_expected (>=0),
expected_bias, session (string), rhythm_anomaly (0/1).
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput


def session_of_hour(hour: int) -> str:
    if 7 <= hour < 16:
        return "london"
    if 12 <= hour < 21:
        return "newyork"
    if hour >= 23 or hour < 8:
        return "asia"
    return "off"


class SRP(Indicator):
    NAME = "SRP"
    PARAMS = {
        "history_days": (30, 7, 365, "days of history used to learn the profile"),
        "min_samples": (8, 3, 60, "minimum completed samples per hour to trust it"),
        "anomaly_range_mult": (
            1.5,
            0.5,
            4.0,
            "actual/expected ratio that flags anomaly",
        ),
        "anomaly_sigma": (2.0, 1.0, 4.0, "bias-deviation sigma that flags anomaly"),
    }

    def _warmup(self) -> int:
        return int(min(self.params["history_days"], 3) * 24 + 2)

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        p = self.params
        if series.granularity > 3600:
            raise ValueError("SRP requires candles of 1h granularity or finer")
        bars_per_hour = max(1, 3600 // series.granularity)
        tr = nu.true_range(
            np.asarray([c.high for c in series.candles]),
            np.asarray([c.low for c in series.candles]),
            nu.closes(series),
        )
        ret = np.concatenate(
            [[0.0], np.diff(np.log(np.maximum(nu.closes(series), nu.EPS)))]
        )
        n = len(series.candles)
        max_hist = int(p["history_days"]) * 24 * bars_per_hour

        # learning tables built ONLY from completed data as of each bar
        hour_tr: dict[int, list[float]] = defaultdict(list)
        hour_ret: dict[int, list[float]] = defaultdict(list)

        out: list[IndicatorOutput] = []
        for i, e in enumerate(series.epochs):
            hour = (e // 3600) % 24
            # current hour bucket so far (this bar closes the bucket at bar end)
            bucket_start = (e // 3600) * 3600
            j = i
            while j >= 0 and series.candles[j].epoch >= bucket_start:
                j -= 1
            cur_open = (
                series.candles[j + 1].open if j + 1 <= i else series.candles[i].open
            )
            actual_range = max(
                series.candles[k].high for k in range(j + 1, i + 1)
            ) - min(series.candles[k].low for k in range(j + 1, i + 1))
            actual_bias = np.log(
                max(series.candles[i].close, nu.EPS) / max(cur_open, nu.EPS)
            )

            ready = len(hour_tr.get(hour, [])) >= int(p["min_samples"])
            if ready:
                exp_r = float(np.mean(hour_tr[hour][-max_hist:]))
                sig = float(np.std(hour_tr[hour][-max_hist:])) + nu.EPS
                exp_b = float(np.mean(hour_ret[hour][-max_hist:]))
                avr = actual_range / (exp_r + nu.EPS)
                anomaly = (
                    1.0
                    if (
                        avr > p["anomaly_range_mult"]
                        or abs(actual_bias - exp_b) > p["anomaly_sigma"] * sig
                    )
                    else 0.0
                )
                vals = {
                    "expected_range": exp_r,
                    "actual_range": float(actual_range),
                    "actual_vs_expected": float(avr),
                    "expected_bias": exp_b,
                    "session_str": session_of_hour(hour),
                    "rhythm_anomaly": anomaly,
                }
            else:
                vals = {}
            out.append(
                IndicatorOutput(
                    epoch=int(e),
                    indicator=self.NAME,
                    ready=ready,
                    values=vals,
                    meta={"hour": int(hour)},
                )
            )

            # after emitting bar i, bar i becomes completed history for later bars
            hour_tr[hour].append(float(tr[i]))
            hour_ret[hour].append(float(ret[i]))
        return out
