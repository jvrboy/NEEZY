"""Core data containers shared by every Tideglass module."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np

from . import __version__

GRANULARITIES = (60, 300, 900, 1800, 3600, 14400, 86400)


@dataclass
class Candles:
    """Column-oriented OHLC candles.

    Attributes:
        epoch: Bar open time in UTC seconds.
        open, high, low, close: Prices.
        ticks: Optional tick count per bar (Deriv tick density). NaN or absent
            means "unknown" and indicators fall back to an equal-weight proxy.
        symbol: Deriv symbol, e.g. ``frxEURUSD``.
        granularity: Bar size in seconds.
        synthetic: True when the data came from the synthetic generator rather
            than the Deriv API. Reports surface this flag prominently.
    """

    epoch: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    ticks: Optional[np.ndarray] = None
    symbol: str = "UNKNOWN"
    granularity: int = 3600
    synthetic: bool = False

    def __post_init__(self) -> None:
        self.epoch = np.asarray(self.epoch, dtype=np.int64)
        for name in ("open", "high", "low", "close"):
            setattr(
                self,
                name,
                np.ascontiguousarray(np.asarray(getattr(self, name), dtype=np.float64)),
            )
        n = self.epoch.shape[0]
        for name in ("open", "high", "low", "close"):
            if getattr(self, name).shape[0] != n:
                raise ValueError(
                    f"Column '{name}' has length {getattr(self, name).shape[0]}, expected {n}"
                )
        if self.ticks is None:
            self.ticks = np.full(n, np.nan)
        else:
            self.ticks = np.ascontiguousarray(np.asarray(self.ticks, dtype=np.float64))
            if self.ticks.shape[0] != n:
                raise ValueError("Column 'ticks' length mismatch")

    def __len__(self) -> int:
        return int(self.epoch.shape[0])

    def slice(self, start: int, stop: int) -> "Candles":
        """Return a sub-range ``[start, stop)`` as a new Candles object."""
        return Candles(
            self.epoch[start:stop],
            self.open[start:stop],
            self.high[start:stop],
            self.low[start:stop],
            self.close[start:stop],
            self.ticks[start:stop],
            self.symbol,
            self.granularity,
            self.synthetic,
        )

    def to_records(self) -> list[dict[str, Any]]:
        """Return the candles in the shared candle JSON format."""
        out = []
        for i in range(len(self)):
            rec: dict[str, Any] = {
                "epoch": int(self.epoch[i]),
                "open": _num(self.open[i]),
                "high": _num(self.high[i]),
                "low": _num(self.low[i]),
                "close": _num(self.close[i]),
            }
            if math.isfinite(self.ticks[i]):
                rec["ticks"] = int(self.ticks[i])
            out.append(rec)
        return out

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        symbol: str = "UNKNOWN",
        granularity: int = 3600,
        synthetic: bool = False,
    ) -> "Candles":
        """Build from an iterable of candle dicts (``epoch, open, high, low, close[, ticks]``)."""
        recs = list(records)

        def col(k: str) -> np.ndarray:
            return np.array(
                [np.nan if r.get(k) is None else float(r[k]) for r in recs],
                dtype=np.float64,
            )

        return cls(
            np.array([int(r["epoch"]) for r in recs], dtype=np.int64),
            col("open"),
            col("high"),
            col("low"),
            col("close"),
            np.array(
                [
                    float(r["ticks"]) if r.get("ticks") is not None else np.nan
                    for r in recs
                ]
            ),
            symbol,
            granularity,
            synthetic,
        )


def _num(v: float) -> Optional[float]:
    """JSON-safe float: NaN/inf become ``None`` (null)."""
    v = float(v)
    return v if math.isfinite(v) else None


@dataclass
class IndicatorResult:
    """Outputs of one indicator run in the Tideglass standard format."""

    indicator: str
    params: Dict[str, Any]
    outputs: Dict[str, np.ndarray]
    warmup: int
    backend: str = "python"
    labels: Dict[str, Dict[int, str]] = field(default_factory=dict)
    text: Dict[str, list] = field(default_factory=dict)

    def __getitem__(self, key: str) -> np.ndarray:
        return self.outputs[key]

    def to_json_dict(self, candles: Optional[Candles] = None) -> dict[str, Any]:
        """Serialise following ``schemas/indicator_output.schema.json``."""
        doc: dict[str, Any] = {
            "format": "tideglass.indicator_output",
            "format_version": 1,
            "suite_version": __version__,
            "indicator": self.indicator,
            "backend": self.backend,
            "params": self.params,
            "warmup": int(self.warmup),
            "length": int(next(iter(self.outputs.values())).shape[0])
            if self.outputs
            else 0,
            "outputs": {k: [_num(x) for x in v] for k, v in self.outputs.items()},
        }
        if self.labels:
            doc["labels"] = {
                k: {str(code): name for code, name in m.items()}
                for k, m in self.labels.items()
            }
        if self.text:
            doc["text"] = self.text
        if candles is not None:
            doc["symbol"] = candles.symbol
            doc["granularity"] = candles.granularity
            doc["synthetic"] = candles.synthetic
            doc["epoch"] = [int(e) for e in candles.epoch]
        return doc

    def to_json(
        self, candles: Optional[Candles] = None, indent: Optional[int] = None
    ) -> str:
        return json.dumps(self.to_json_dict(candles), indent=indent)
