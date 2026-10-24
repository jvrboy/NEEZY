"""Configuration discovery, loading and validation.

Search order for the ``config`` and ``schemas`` directories:

1. ``$TIDEGLASS_HOME`` (a directory containing ``config/`` and ``schemas/``)
2. the source checkout (``<repo>/config``) when running from the repository
3. the copies bundled into the installed package (``tideglass/resources``)

Every config file is validated against its JSON Schema at load time, and the
parameter defaults/ranges are cross-checked semantically (default within
range, ``mid < long`` and so on).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .schema import SchemaError, validate

log = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent


def find_home() -> Path:
    """Return the directory that holds ``config/`` and ``schemas/``."""
    env = os.environ.get("TIDEGLASS_HOME")
    candidates = [Path(env)] if env else []
    candidates += [_PKG.parents[1], _PKG / "resources"]
    for c in candidates:
        if (c / "config" / "indicators.json").is_file() and (c / "schemas").is_dir():
            return c
    raise FileNotFoundError(
        "Could not locate Tideglass config/ and schemas/ directories. Set TIDEGLASS_HOME to the "
        "project root (the folder containing config/ and schemas/)."
    )


@dataclass
class SuiteConfig:
    """Validated configuration bundle."""

    home: Path
    indicators: Dict[str, Any]
    weights: Dict[str, Any]
    symbols: Dict[str, Any]

    def defaults(self, indicator: str) -> Dict[str, Any]:
        """Default parameter values for ``indicator``."""
        spec = self.indicators["indicators"][indicator]["params"]
        return {k: v["default"] for k, v in spec.items()}

    def param_spec(self, indicator: str) -> Dict[str, Any]:
        return self.indicators["indicators"][indicator]["params"]

    def symbol_info(self, symbol: str) -> Dict[str, Any]:
        for s in self.symbols["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise KeyError(f"Symbol {symbol!r} is not listed in config/symbols.json")

    def enabled_symbols(self) -> list[str]:
        return [s["symbol"] for s in self.symbols["symbols"] if s.get("enabled", True)]

    def validate_params(
        self, indicator: str, params: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Merge ``params`` over defaults and range-check every value."""
        spec = self.param_spec(indicator)
        merged = self.defaults(indicator)
        for k, v in params.items():
            if k not in spec:
                raise ValueError(
                    f"{indicator}: unknown parameter '{k}'. Valid: {sorted(spec)}"
                )
            merged[k] = v
        for k, v in merged.items():
            s = spec[k]
            if s["type"] == "integer_array":
                vals = [int(x) for x in v]
                if not (
                    s.get("min_items", 1) <= len(vals) <= s.get("max_items", 10**6)
                ):
                    raise ValueError(
                        f"{indicator}.{k}: needs {s.get('min_items')}..{s.get('max_items')} items"
                    )
                if (
                    any(x < s["min"] or x > s["max"] for x in vals)
                    or sorted(set(vals)) != vals
                ):
                    raise ValueError(
                        f"{indicator}.{k}: values must be unique, ascending, in [{s['min']}, {s['max']}]"
                    )
                merged[k] = tuple(vals)
                continue
            if s["type"] == "integer":
                if float(v) != int(v):
                    raise ValueError(f"{indicator}.{k}: must be an integer, got {v!r}")
                v = int(v)
            else:
                v = float(v)
            if not (s["min"] <= v <= s["max"]):
                raise ValueError(
                    f"{indicator}.{k}={v} outside valid range [{s['min']}, {s['max']}]"
                )
            merged[k] = v
        _cross_check(indicator, merged)
        return merged


def _cross_check(indicator: str, p: Mapping[str, Any]) -> None:
    if indicator == "VBO" and not (p["short"] < p["mid"] < p["long"]):
        raise ValueError("VBO: require short < mid < long")
    if indicator == "VBO" and p["horizon"] >= p["hist"]:
        raise ValueError("VBO: horizon must be smaller than hist")
    if indicator == "TIS" and p["dirty"] > p["clean"]:
        raise ValueError("TIS: dirty threshold must not exceed clean threshold")
    if indicator == "TDGZ" and p["min_bars"] > p["lookback"]:
        raise ValueError("TDGZ: min_bars must not exceed lookback")


def _load(home: Path, name: str, schema: str) -> Dict[str, Any]:
    path = home / "config" / name
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(home / "schemas" / schema, encoding="utf-8") as fh:
        sch = json.load(fh)
    validate(doc, sch, str(path))
    return doc


@lru_cache(maxsize=4)
def _load_cached(home: str) -> SuiteConfig:
    h = Path(home)
    cfg = SuiteConfig(
        home=h,
        indicators=_load(h, "indicators.json", "indicators_config.schema.json"),
        weights=_load(h, "confluence_weights.json", "confluence_weights.schema.json"),
        symbols=_load(h, "symbols.json", "symbols.schema.json"),
    )
    for name in cfg.indicators["indicators"]:
        cfg.validate_params(name, {})  # defaults must satisfy their own ranges
    log.debug("Loaded Tideglass config from %s", h)
    return cfg


def load_config(home: Optional[Path | str] = None) -> SuiteConfig:
    """Load and validate all configuration files (cached per directory)."""
    return _load_cached(str(Path(home).resolve() if home else find_home()))


__all__ = ["SuiteConfig", "load_config", "find_home", "SchemaError"]
