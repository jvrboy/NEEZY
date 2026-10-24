"""Indicator registry and the shared JSON output contract.

Every TideForge indicator is a class with:
  - NAME: unique short code (e.g. "EDI")
  - PARAMS: dict of parameter name -> (default, min, max, description)
  - WARMUP: minimum bars needed before the first stable value
  - compute(series) -> list[IndicatorOutput] (one per bar; None-valued
    fields before warm-up)

The registry lets the CLI, evaluator and optimizer enumerate indicators
dynamically without hardcoding imports.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Type

from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries

# phase / regime vocabulary shared across indicators and languages
PHASES = {"inhale": 0, "hold": 1, "exhale": 2}
REGIMES = ["clean_trend", "dirty_trend", "range", "chop"]


@dataclass
class IndicatorOutput:
    """Standard per-bar result for one indicator.

    The JSON contract (schemas/indicator_output.schema.json) is generated
    from this shape:
      epoch, indicator, values (flat map of named numeric/enum outputs),
      ready (bool: past warm-up), meta (optional free-form map).
    """

    epoch: int
    indicator: str
    values: Dict[str, Optional[float]] = field(default_factory=dict)
    ready: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        clean = {
            k: (
                None
                if (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
                else v
            )
            for k, v in self.values.items()
        }
        return {
            "epoch": self.epoch,
            "indicator": self.indicator,
            "values": clean,
            "ready": self.ready,
            "meta": self.meta,
        }


def series_to_json(outputs: List[IndicatorOutput]) -> Dict[str, Any]:
    return {
        "indicator": outputs[0].indicator if outputs else "?",
        "n": len(outputs),
        "rows": [o.to_json() for o in outputs],
    }


class Indicator:
    """Base class for all TideForge indicators."""

    NAME: str = "BASE"
    PARAMS: Dict[str, tuple] = {}

    def __init__(self, **overrides: float) -> None:
        params = {k: v[0] for k, v in self.PARAMS.items()}
        for k, v in overrides.items():
            if k not in params:
                raise KeyError(f"{self.NAME}: unknown parameter '{k}'")
            lo, hi = self.PARAMS[k][1], self.PARAMS[k][2]
            if not (lo <= v <= hi):
                raise ValueError(
                    f"{self.NAME}: {k}={v} outside valid range [{lo},{hi}]"
                )
            params[k] = v
        self.params: Dict[str, float] = params
        self.warmup = self._warmup()

    def _warmup(self) -> int:
        raise NotImplementedError

    def compute(self, series: CandleSeries) -> List[IndicatorOutput]:
        raise NotImplementedError

    # helpers ---------------------------------------------------------------
    def _out(self, epoch: int, ready: bool, **values: Any) -> IndicatorOutput:
        return IndicatorOutput(
            epoch=epoch,
            indicator=self.NAME,
            ready=ready,
            values={k: v for k, v in values.items()},
        )


class Registry:
    """Name -> indicator class map, populated by `register_all`."""

    def __init__(self) -> None:
        self._indicators: Dict[str, Type[Indicator]] = {}

    def register(self, cls: Type[Indicator]) -> Type[Indicator]:
        self._indicators[cls.NAME] = cls
        return cls

    def get(self, name: str) -> Type[Indicator]:
        if name not in self._indicators:
            raise KeyError(
                f"unknown indicator '{name}'; known: {sorted(self._indicators)}"
            )
        return self._indicators[name]

    def names(self) -> List[str]:
        return sorted(self._indicators)

    def all(self) -> Dict[str, Type[Indicator]]:
        return dict(self._indicators)

    def param_schema(self) -> Dict[str, Any]:
        return {
            cls.NAME: {
                k: {"default": v[0], "min": v[1], "max": v[2], "desc": v[3]}
                for k, v in cls.PARAMS.items()
            }
            for cls in self._indicators.values()
        }


def load_indicator_config(path: str) -> Dict[str, Any]:
    """Load and lightly validate /config/indicators.json."""
    with open(path) as fh:
        cfg = json.load(fh)
    if "indicators" not in cfg:
        raise ValueError("indicators.json missing 'indicators' key")
    return cfg
