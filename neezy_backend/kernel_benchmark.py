"""Opt-in correctness-checked benchmark for NEEZY's Python microkernels."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from .microkernels import atr_kernel, ema_kernel, macd_histogram_kernel


def _reference_ema(values, period: int) -> list[float]:
    if period < 1:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(float(value) * alpha + result[-1] * (1.0 - alpha))
    return result


def _reference_macd(closes, fast=12, slow=26, signal=9) -> list[float]:
    fast_ema, slow_ema = _reference_ema(closes, fast), _reference_ema(closes, slow)
    line = [a - b for a, b in zip(fast_ema, slow_ema, strict=True)]
    signal_line = _reference_ema(line, signal)
    return [a - b for a, b in zip(line, signal_line, strict=True)]


def _reference_atr(highs, lows, closes, period=14) -> float | None:
    if not closes or len(highs) != len(lows) or len(lows) != len(closes):
        return None
    ranges = [highs[0] - lows[0]]
    ranges.extend(
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(closes))
    )
    initial = ranges[:period]
    average = sum(initial) / len(initial)
    for current in ranges[period:]:
        average = (average * (period - 1) + current) / period
    return average


def _fixture(size: int) -> tuple[list[float], list[float], list[float]]:
    closes = [
        1.1 + index * 0.00001 + math.sin(index / 17) * 0.002 for index in range(size)
    ]
    previous = closes[0] - 0.0002
    highs, lows = [], []
    for close in closes:
        highs.append(max(previous, close) + 0.0004)
        lows.append(min(previous, close) - 0.0004)
        previous = close
    return highs, lows, closes


def _assert_compatible(optimized, reference) -> None:
    if optimized != reference:
        raise RuntimeError("microkernel benchmark exact-output check failed")


def _timed(call: Callable[[], object], iterations: int) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        call()
    return time.perf_counter() - started


def benchmark_kernels(*, iterations: int = 250, size: int = 512) -> dict[str, object]:
    """Measure optimized/reference times after checking equivalent outputs."""
    if not 1 <= iterations <= 10_000:
        raise ValueError("iterations must be between 1 and 10000")
    if not 60 <= size <= 5_000:
        raise ValueError("benchmark size must be between 60 and 5000")
    highs, lows, closes = _fixture(size)
    tasks = (
        ("ema", lambda: ema_kernel(closes, 21), lambda: _reference_ema(closes, 21)),
        (
            "macd_histogram",
            lambda: macd_histogram_kernel(closes, 12, 26, 9),
            lambda: _reference_macd(closes),
        ),
        (
            "atr",
            lambda: atr_kernel(highs, lows, closes, 14),
            lambda: _reference_atr(highs, lows, closes),
        ),
    )
    results = {}
    for name, optimized, reference in tasks:
        _assert_compatible(optimized(), reference())
        optimized_seconds = _timed(optimized, iterations)
        reference_seconds = _timed(reference, iterations)
        results[name] = {
            "optimized_ms": round(optimized_seconds * 1000, 3),
            "reference_ms": round(reference_seconds * 1000, 3),
            "speedup": round(reference_seconds / optimized_seconds, 3)
            if optimized_seconds
            else None,
        }
    return {
        "iterations": iterations,
        "candles": size,
        "correctness": "exact",
        "kernels": results,
    }
