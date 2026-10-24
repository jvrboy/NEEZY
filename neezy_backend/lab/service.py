"""Validated, bounded adapters around the uploaded research engines.

NumPy engines load lazily. Neither catalog discovery nor FRAS/FXLAB require it.
Input must consist of CLOSED bars; no feed, filesystem config, broker, or agent
permissions are available through this module.
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

MAX_BARS = 5000
TIDE_INDICATORS = ("EDI", "VBO", "FSCR", "TDGZ", "TIS", "MDR", "SRP", "CC")
ENGINES = {
    "fras": ("Flow-Risk Adaptive Structure", ("FRAS",), False),
    "fxlab": ("FXLAB portable reference", ("EWPO", "RCBI", "VRB"), False),
    "tideforge": ("TideForge 1.1.0", TIDE_INDICATORS, True),
    "tideglass": ("Tideglass 1.0.0", TIDE_INDICATORS, True),
}


def catalog() -> dict[str, Any]:
    numpy_available = importlib.util.find_spec("numpy") is not None
    return {
        "schema": 1,
        "advisory_only": True,
        "closed_bars_required": True,
        "max_bars": MAX_BARS,
        "engines": [
            {
                "id": key,
                "name": value[0],
                "indicators": list(value[1]),
                "requires_numpy": value[2],
                "available": not value[2] or numpy_available,
                "install_hint": "pip install 'neezy-market-workspace[research-lab]'"
                if value[2] and not numpy_available
                else None,
            }
            for key, value in ENGINES.items()
        ],
        "warning": (
            "Experimental research signals are not validated trading strategies "
            "or financial advice."
        ),
    }


def validate_rows(rows: Iterable[Sequence[Any]]) -> list[tuple]:
    result = []
    previous = -1
    for row in rows:
        if len(result) >= MAX_BARS:
            raise ValueError(f"research input exceeds {MAX_BARS} bars")
        if not isinstance(row, (list, tuple)) or len(row) not in (5, 6):
            raise ValueError(
                "each candle must be [epoch, open, high, low, close, optional_ticks]"
            )
        epoch = row[0]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= previous:
            raise ValueError("epochs must be nonnegative, unique, increasing integers")
        prices = row[1:5]
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
            for v in prices
        ):
            raise ValueError("OHLC values must be positive finite numbers")
        o, h, low, c = map(float, prices)
        if h < max(o, c, low) or low > min(o, c, h):
            raise ValueError("inconsistent candle high/low")
        ticks = row[5] if len(row) == 6 else 0
        if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
            raise ValueError("tick counts must be nonnegative integers")
        result.append((epoch, o, h, low, c, ticks))
        previous = epoch
    if not result:
        raise ValueError("at least one closed candle is required")
    return result


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):
        return _clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def analyze(
    rows: Iterable[Sequence[Any]],
    *,
    engine: str = "fras",
    indicator: str | None = None,
    symbol: str = "UNKNOWN",
    granularity: int = 300,
    params: Mapping[str, Any] | None = None,
    include_series: bool = False,
) -> dict[str, Any]:
    if engine not in ENGINES:
        raise ValueError(f"unknown research engine {engine!r}")
    indicator = (indicator or ENGINES[engine][1][0]).upper()
    if indicator not in ENGINES[engine][1]:
        raise ValueError(f"unknown {engine} indicator {indicator!r}")
    if (
        isinstance(granularity, bool)
        or not isinstance(granularity, int)
        or not 1 <= granularity <= 86400
    ):
        raise ValueError("granularity must be an integer in 1..86400 seconds")
    if (
        not isinstance(symbol, str)
        or not 1 <= len(symbol) <= 80
        or any(ord(c) < 32 for c in symbol)
    ):
        raise ValueError("invalid research symbol")
    candles = validate_rows(rows)
    params = dict(params or {})
    if engine == "fras":
        from .vendors.fras import Candle, calculate

        allowed = {
            "atr_period": (2, 300, int),
            "efficiency_period": (2, 300, int),
            "channel_period": (2, 300, int),
            "volatility_median_period": (2, 500, int),
            "signal_threshold": (1, 100, float),
            "shock_ratio": (1, 10, float),
            "quiet_ratio": (0.01, 1, float),
            "minimum_efficiency_for_signal": (0, 1, float),
        }
        for key, value in params.items():
            if key not in allowed:
                raise ValueError(f"unknown FRAS parameter {key!r}")
            lo, hi, kind = allowed[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lo <= value <= hi
                or (kind is int and not isinstance(value, int))
            ):
                raise ValueError(f"invalid FRAS parameter {key!r}")
        points = calculate([Candle(*row[:5]) for row in candles], **params)
        output = [
            {"epoch": p.epoch, "ready": p.score is not None, "values": asdict(p)}
            for p in points
        ]
    elif engine == "fxlab":
        from .fxlab import compute

        if params:
            raise ValueError(
                "FXLAB portable reference currently uses archive default parameters"
            )
        output = compute(candles, indicator)
    else:
        if importlib.util.find_spec("numpy") is None:
            raise RuntimeError(
                "this engine needs NumPy: "
                "pip install 'neezy-market-workspace[research-lab]'"
            )
        if engine == "tideforge":
            from .vendors.tideforge.core.candles import CandleSeries
            from .vendors.tideforge.indicators import ALL

            # Filesystem configuration is never accepted by the public adapter.
            if "weights_path" in params:
                raise ValueError("research parameters cannot reference local files")
            cls = ALL[indicator]
            for key, value in params.items():
                if key not in cls.PARAMS:
                    raise ValueError(f"unknown {indicator} parameter {key!r}")
                default, lo, hi, _ = cls.PARAMS[key]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not lo <= value <= hi
                    or (isinstance(default, int) and not isinstance(value, int))
                ):
                    raise ValueError(f"invalid {indicator} parameter {key!r}")
            output = [
                o.to_json()
                for o in cls(**params).compute(
                    CandleSeries.from_rows(symbol, granularity, candles)
                )
            ]
        else:
            from pathlib import Path

            from .vendors import tideglass
            from .vendors.tideglass import Candles, compute, compute_all, load_config

            cfg = load_config(Path(tideglass.__file__).parent / "resources")
            data = Candles.from_records(
                [
                    dict(
                        zip(
                            ("epoch", "open", "high", "low", "close", "ticks"),
                            row,
                            strict=True,
                        )
                    )
                    for row in candles
                ],
                symbol=symbol,
                granularity=granularity,
            )
            result = (
                compute_all(data, {"CC": params}, backend="python", config=cfg)["CC"]
                if indicator == "CC"
                else compute(indicator, data, params, backend="python", config=cfg)
            )
            output = [
                {
                    "epoch": row[0],
                    "ready": i >= result.warmup,
                    "values": {
                        key: values[i] for key, values in result.outputs.items()
                    },
                }
                for i, row in enumerate(candles)
            ]
    output = _clean(output)
    document = {
        "schema": 1,
        "engine": engine,
        "indicator": indicator,
        "symbol": symbol,
        "granularity": granularity,
        "bars": len(candles),
        "advisory_only": True,
        "closed_bars_required": True,
        "params": params,
        "latest": output[-1],
        "warning": (
            "Research only. Warm-up and statistical confidence "
            "do not imply profitability."
        ),
    }
    if include_series:
        document["series"] = output
    return document
