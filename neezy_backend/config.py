"""Validated application settings kept separate from the Tkinter view."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

THEMES = frozenset({"Liquid dark", "Midnight blue", "High contrast"})


@dataclass(frozen=True, slots=True)
class AppSettings:
    """User-configurable settings with validation at every construction point."""

    auto_refresh: bool = True
    alerts_enabled: bool = True
    compact_mode: bool = False
    theme: str = "Liquid dark"
    polling_ms: int = 100
    candle_limit: int = 300
    alert_min_score: int = 2

    def __post_init__(self) -> None:
        if self.theme not in THEMES:
            raise ValueError(f"Unsupported theme preset: {self.theme!r}")
        if not isinstance(self.polling_ms, int) or isinstance(self.polling_ms, bool):
            raise TypeError("Polling interval must be an integer")
        if not 50 <= self.polling_ms <= 2000:
            raise ValueError("Polling interval must be between 50 and 2000 ms")
        if not isinstance(self.candle_limit, int) or isinstance(
            self.candle_limit, bool
        ):
            raise TypeError("Candle limit must be an integer")
        if not 60 <= self.candle_limit <= 1000:
            raise ValueError("Candle limit must be between 60 and 1000")
        if not isinstance(self.alert_min_score, int) or isinstance(
            self.alert_min_score, bool
        ):
            raise TypeError("Alert score threshold must be an integer")
        if not 1 <= self.alert_min_score <= 4:
            raise ValueError("Alert score threshold must be between 1 and 4")
        for field_name in ("auto_refresh", "alerts_enabled", "compact_mode"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean")

    def updated(self, **changes: Any) -> AppSettings:
        """Return a new validated settings object."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> AppSettings:
        """Load known fields only, making older config files forward compatible."""
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})
