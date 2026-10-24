"""Portable reference translation of user-supplied FXLAB C++ indicators.

No archive shared library is loaded. Formula names and rolling boundaries match
fxlab/cpp/fxind.cpp. Results are advisory research, never order instructions.
"""

from __future__ import annotations

import math
from statistics import mean, variance

from ..microkernels import ema_kernel


def compute(rows: list[tuple], indicator: str) -> list[dict]:
    opens, highs, lows, closes = ([row[k] for row in rows] for k in range(1, 5))
    size = len(rows)
    tr = [
        max(
            high - low,
            abs(high - closes[max(0, i - 1)]),
            abs(low - closes[max(0, i - 1)]),
        )
        for i, (high, low) in enumerate(zip(highs, lows, strict=True))
    ]
    values = []
    warmup = {"EWPO": 14, "RCBI": 120, "VRB": 52}[indicator]
    if indicator == "EWPO":
        pressure = []
        for i in range(size):
            path = (
                sum(abs(closes[k] - closes[k - 1]) for k in range(i - 9, i + 1))
                if i >= 10
                else 0
            )
            er = abs(closes[i] - closes[i - 10]) / path if path > 1e-12 else 0.0
            body = (
                (closes[i] - opens[i]) / (highs[i] - lows[i])
                if highs[i] - lows[i] > 1e-12
                else 0.0
            )
            pressure.append(body * (0.35 + 0.65 * er) * 100)
        values = [{"pressure": value} for value in ema_kernel(pressure, 14)]
    elif indicator == "RCBI":
        fast, slow = ema_kernel(tr, 8), ema_kernel(tr, 55)
        ratios = [f / s if s > 1e-12 else 1.0 for f, s in zip(fast, slow, strict=True)]
        for i in range(size):
            window = ratios[max(0, i - 119) : i + 1]
            rank = 100 * sum(v <= ratios[i] for v in window) / len(window)
            direction = (
                (closes[i] - closes[i - 8]) / (fast[i] * math.sqrt(8))
                if i >= 8 and fast[i] > 1e-12
                else 0.0
            )
            values.append(
                {"compression_rank": rank, "direction": max(-3.0, min(3.0, direction))}
            )
    else:
        returns = [0.0] + [math.log(closes[i] / closes[i - 1]) for i in range(1, size)]
        for i in range(size):
            if i < 52:
                values.append(
                    {
                        "mid": closes[i],
                        "upper": closes[i],
                        "lower": closes[i],
                        "variance_ratio": 1.0,
                    }
                )
                continue
            start = i - 47
            v1 = variance(returns[start : i + 1])
            q_returns = [
                math.log(closes[k] / closes[k - 4]) for k in range(start + 3, i + 1)
            ]
            vr = variance(q_returns) / (4 * v1) if v1 > 1e-18 else 1.0
            vr = max(0.3, min(2.5, vr))
            mid = mean(closes[start : i + 1])
            band = 1.8 * math.sqrt(v1) * closes[i] * 2 * math.sqrt(vr)
            values.append(
                {
                    "mid": mid,
                    "upper": mid + band,
                    "lower": mid - band,
                    "variance_ratio": vr,
                }
            )
    return [
        {"epoch": row[0], "ready": i >= warmup, "values": value}
        for i, (row, value) in enumerate(zip(rows, values, strict=True))
    ]
