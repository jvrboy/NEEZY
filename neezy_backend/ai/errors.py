"""Result type and exception hierarchy for the AI layer.

Kept dependency-free so every other ``ai`` submodule (and the resilient
client wrapper) can import them without cycles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AIResult:
    """Successful completion plus the rotation trace."""

    text: str
    provider: str
    model: str
    key_id: str
    key_label: str
    latency_ms: int
    attempts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "key_id": self.key_id,
            "key_label": self.key_label,
            "latency_ms": self.latency_ms,
            "attempts": list(self.attempts),
            "usage": self.usage,
        }


class AIError(RuntimeError):
    """Base class for provider problems."""


class NoAPIKeys(AIError):
    """No usable key is configured for the requested provider."""


class AllKeysFailed(AIError):
    """Every key was tried and none completed the request."""

    def __init__(self, message: str, attempts: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(message)
        self.attempts = [dict(attempt) for attempt in attempts]
