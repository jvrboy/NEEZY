"""Deriv instrument catalogue, read from the bundled ``data/deriv_symbols.json``.

The snapshot lists every symbol Deriv's public endpoint returned for
``active_symbols``. Refresh it with ``neezy-cli catalog refresh`` when Deriv adds
or retires instruments; the app works offline from the bundled copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

_FILE = "deriv_symbols.json"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    market: str
    submarket: str
    tick_size: float
    open: bool

    @property
    def decimals(self) -> int:
        """Price precision implied by the tick size (0.0001 -> 4, 0.01 -> 2)."""
        text = f"{self.tick_size:.10f}".rstrip("0")
        return len(text.split(".", 1)[1]) if "." in text else 0

    @property
    def is_forex(self) -> bool:
        return self.market == "forex"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "submarket": self.submarket,
            "tick_size": self.tick_size,
            "open": self.open,
        }


def _parse(document: dict[str, Any]) -> dict[str, Instrument]:
    catalogue: dict[str, Instrument] = {}
    for row in document["instruments"]:
        instrument = Instrument(
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            market=str(row["market"]),
            submarket=str(row["submarket"]),
            tick_size=float(row["tick_size"]),
            open=bool(row["open"]),
        )
        if instrument.symbol in catalogue:
            raise ValueError(f"duplicate instrument {instrument.symbol!r}")
        if instrument.tick_size <= 0:
            raise ValueError(f"tick size for {instrument.symbol} must be positive")
        catalogue[instrument.symbol] = instrument
    return catalogue


@lru_cache(maxsize=1)
def load_document() -> dict[str, Any]:
    """The raw catalogue document, including source and capture date."""
    text = resources.files("neezy_backend").joinpath("data", _FILE).read_text("utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def instruments() -> dict[str, Instrument]:
    """Every instrument in the bundled catalogue, keyed by Deriv symbol."""
    return _parse(load_document())


def instrument(symbol: str) -> Instrument | None:
    return instruments().get(symbol)


def markets() -> list[str]:
    return sorted({item.market for item in instruments().values()})


def by_market(market: str) -> list[Instrument]:
    return [item for item in instruments().values() if item.market == market]
