"""Dataset-backed insights: blend shipped knowledge with learned weights.

The offline assistant and the UI insights page consume this module. It joins
the curated market knowledge (``datasets.py``) with the per-symbol edge
weights derived from NEEZY's train-then-validate study records so the plain
offline answer can carry one extra, honest line of context.

Everything here is descriptive. A positive edge weight means the studied
rule set cleared its out-of-sample bar on past candles; it is not a
forecast.
"""

from __future__ import annotations

from typing import Any

from .datasets import (
    MARKET_KNOWLEDGE,
    MODEL_WEIGHTS,
    STRATEGY_PLAYBOOK,
    dataset_summary,
    indicator_names,
    market_knowledge,
    strategy_playbook,
    weight_for,
)

__all__ = [
    "insight_for",
    "insight_line",
    "knowledge_brief",
    "playbook_entry",
]


def playbook_entry(strategy: str) -> dict[str, Any] | None:
    """The playbook reference for one named strategy, or None."""
    for entry in strategy_playbook().get("strategies", []):
        if str(entry.get("name", "")).upper() == strategy.upper():
            return dict(entry)
    return None


def insight_line(symbol: str) -> str | None:
    """One caveated sentence about a symbol's learned weight, or None."""
    record = weight_for(symbol)
    if record is None:
        return None
    weight = record.get("edge_weight", 0.0)
    verdict = record.get("verdict", "unknown")
    confidence = record.get("confidence", 0.0)
    lean = "positive" if weight > 0.15 else "negative" if weight < -0.15 else "neutral"
    return (
        f"Learned context for {symbol}: {lean} edge weight {weight:+.2f} "
        f"(verdict {verdict}, sample-coverage score {confidence:.0%}) "
        "from out-of-sample backtests on past candles; not a forecast."
    )


def insight_for(symbol: str) -> dict[str, Any] | None:
    """Structured insight for one symbol: weight, playbook lean and caveat."""
    record = weight_for(symbol)
    if record is None:
        return None
    return {
        "symbol": symbol,
        "edge_weight": record.get("edge_weight"),
        "confidence": record.get("confidence"),
        "verdict": record.get("verdict"),
        "caveat": (
            "Weights derive from backtests over historical candles with a "
            "charged spread; out-of-sample for that window only."
        ),
    }


def knowledge_brief() -> dict[str, Any]:
    """What the offline assistant knows from the shipped datasets."""
    summary = dataset_summary()
    knowledge = market_knowledge()
    playbook = strategy_playbook()
    return {
        "datasets": sorted(summary.get("datasets", {})),
        "weighted_symbols": summary.get("weighted_symbols", 0),
        "indicators": indicator_names(),
        "patterns": [entry.get("name") for entry in knowledge.get("patterns", [])],
        "strategies": [entry.get("name") for entry in playbook.get("strategies", [])],
        "sources": [MARKET_KNOWLEDGE, STRATEGY_PLAYBOOK, MODEL_WEIGHTS],
    }
