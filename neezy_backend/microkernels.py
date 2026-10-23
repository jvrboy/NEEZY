"""Small fused numerical kernels used by NEEZY's indicator hot paths.

These are deterministic Python implementations, not a native runtime or a new
trading engine. They reduce temporary lists and repeated passes while keeping
the existing public indicator APIs and their numerical semantics.
"""

from __future__ import annotations

from collections.abc import Sequence

BACKEND_NAME = "python-fused-v1"
KERNEL_NAMES = ("ema", "macd_histogram", "atr")


def kernel_status() -> dict[str, object]:
    """Public, read-only description for SETTINGS and ``neezy-cli kernels``."""
    return {
        "backend": BACKEND_NAME,
        "kernels": list(KERNEL_NAMES),
        "deterministic": True,
        "native_dependency": False,
    }


def ema_kernel(values: Sequence[float], period: int) -> list[float]:
    """Preallocated EMA with one running value instead of append/index work."""
    if period < 1:
        raise ValueError("period must be positive")
    size = len(values)
    if not size:
        return []
    alpha = 2.0 / (period + 1.0)
    beta = 1.0 - alpha
    result = [0.0] * size
    previous = float(values[0])
    result[0] = previous
    for index in range(1, size):
        previous = float(values[index]) * alpha + previous * beta
        result[index] = previous
    return result


def macd_histogram_kernel(
    closes: Sequence[float], fast: int, slow: int, signal: int
) -> list[float]:
    """Fuse fast/slow EMA, MACD line, and signal smoothing into one pass."""
    if fast < 1 or slow < 1 or signal < 1:
        raise ValueError("MACD periods must be positive")
    if fast >= slow:
        raise ValueError("fast period must be shorter than slow period")
    size = len(closes)
    if not size:
        return []
    fast_alpha = 2.0 / (fast + 1.0)
    slow_alpha = 2.0 / (slow + 1.0)
    signal_alpha = 2.0 / (signal + 1.0)
    fast_beta = 1.0 - fast_alpha
    slow_beta = 1.0 - slow_alpha
    signal_beta = 1.0 - signal_alpha

    first = float(closes[0])
    fast_previous = first
    slow_previous = first
    signal_previous = 0.0
    result = [0.0] * size
    for index in range(1, size):
        value = float(closes[index])
        fast_previous = value * fast_alpha + fast_previous * fast_beta
        slow_previous = value * slow_alpha + slow_previous * slow_beta
        line = fast_previous - slow_previous
        signal_previous = line * signal_alpha + signal_previous * signal_beta
        result[index] = line - signal_previous
    return result


def atr_kernel(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> float | None:
    """Wilder ATR without allocating an intermediate true-range list."""
    if period < 1:
        raise ValueError("period must be positive")
    size = len(closes)
    if not size or len(highs) != size or len(lows) != size:
        return None

    initial_count = min(period, size)
    total = highs[0] - lows[0]
    for index in range(1, initial_count):
        high, low = highs[index], lows[index]
        previous = closes[index - 1]
        total += max(high - low, abs(high - previous), abs(low - previous))
    average = total / initial_count
    for index in range(initial_count, size):
        high, low = highs[index], lows[index]
        previous = closes[index - 1]
        current = max(high - low, abs(high - previous), abs(low - previous))
        average = (average * (period - 1) + current) / period
    return average
