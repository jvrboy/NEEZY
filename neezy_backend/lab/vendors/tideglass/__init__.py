"""Tideglass - an original Forex technical-analysis indicator suite.

Quick start::

    from tideglass import compute_all, load_config
    from tideglass.data.synthetic import generate_candles

    candles = generate_candles("frxEURUSD", 3600, 3000, seed=7)
    results = compute_all(candles)
    print(results["CC"].text["reason"][-1])
"""

from __future__ import annotations

from pathlib import Path as _Path


def _read_version() -> str:
    for cand in (
        _Path(__file__).resolve().parents[2] / "VERSION",
        _Path(__file__).resolve().parent / "resources" / "VERSION",
    ):
        if cand.is_file():
            return cand.read_text(encoding="utf-8").strip()
    return "1.0.0"


__version__ = _read_version()

from .config import load_config, SuiteConfig  # noqa: E402
from .indicators import compute, compute_all, backend_name, INDICATORS  # noqa: E402
from .types import Candles, IndicatorResult  # noqa: E402

__all__ = [
    "__version__",
    "Candles",
    "IndicatorResult",
    "load_config",
    "SuiteConfig",
    "compute",
    "compute_all",
    "backend_name",
    "INDICATORS",
]
