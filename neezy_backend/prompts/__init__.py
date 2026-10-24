"""Prompt registry: versioned, auditable system prompts (roadmap #advanced)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROMPT_REGISTRY: dict[str, dict[str, Any]] = {
    "analysis_v1": {
        "version": 1,
        "role": "analysis",
        "template": (
            "You are NEEZY, an educational market analyst. "
            "Symbol: {symbol}. Context: {context}"
        ),
        "variables": ["symbol", "context"],
    },
    "research_v1": {
        "version": 1,
        "role": "research",
        "template": "Research task: {goal}. Markets: {symbols}. Timeframe: {timeframe}",
        "variables": ["goal", "symbols", "timeframe"],
    },
    "risk_v1": {
        "version": 1,
        "role": "risk",
        "template": (
            "Evaluate risk for {symbol} with balance {balance} "
            "and risk {risk}%. Trade plan: {plan}"
        ),
        "variables": ["symbol", "balance", "risk", "plan"],
    },
}


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    role: str
    template: str
    variables: tuple[str, ...]


def get_prompt(prompt_id: str) -> Prompt | None:
    entry = PROMPT_REGISTRY.get(prompt_id)
    if entry is None:
        return None
    return Prompt(
        id=prompt_id,
        version=int(entry["version"]),
        role=str(entry["role"]),
        template=str(entry["template"]),
        variables=tuple(entry["variables"]),
    )


def list_prompts() -> list[Prompt]:
    return [
        get_prompt(pid)
        for pid in sorted(PROMPT_REGISTRY)
        if get_prompt(pid) is not None
    ]  # type: ignore[misc]


def render(prompt_id: str, **kwargs: Any) -> str:
    p = get_prompt(prompt_id)
    if p is None:
        raise KeyError(f"unknown prompt {prompt_id!r}")
    missing = [v for v in p.variables if v not in kwargs]
    if missing:
        raise ValueError(f"missing variables for {prompt_id}: {missing}")
    return p.template.format(**kwargs)


def registry_snapshot() -> dict[str, dict[str, Any]]:
    return dict(PROMPT_REGISTRY)
