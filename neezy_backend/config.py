"""Validated application settings kept separate from the Tkinter view."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

THEMES = frozenset({"Liquid dark", "Midnight blue", "High contrast"})
STRATEGIES = frozenset(
    {
        "SUPERTREND",
        "EMA_PULLBACK",
        "DIVERGENCE",
        "DONCHIAN",
        "SQUEEZE",
        "MACD",
        "KELTNER",
    }
)
AI_PROVIDERS = frozenset({"gemini", "grok", "openrouter", "ollama"})


def _require_bool(field_name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")


def _require_int(field_name: str, value: object, low: int, high: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{field_name} must be between {low} and {high}")


def _require_float(field_name: str, value: object, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not low <= float(value) <= high:
        raise ValueError(f"{field_name} must be between {low:g} and {high:g}")


@dataclass(frozen=True, slots=True)
class AppSettings:
    """User-configurable settings with validation at every construction point.

    Older config files keep working: :meth:`from_dict` ignores unknown keys and
    any missing key falls back to the defaults declared here.
    """

    # Workspace
    auto_refresh: bool = True
    alerts_enabled: bool = True
    compact_mode: bool = False
    theme: str = "Liquid dark"
    polling_ms: int = 100
    candle_limit: int = 300
    alert_min_score: int = 2

    # Strategy engine
    strategy: str = "SUPERTREND"
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    divergence_lookback: int = 5
    correlation_window: int = 50
    correlation_baseline: int = 200
    show_strategy_overlay: bool = True

    # Local storage
    store_candles: bool = True
    retention_days: int = 90
    save_snapshots: bool = True

    # AI providers
    ai_enabled: bool = False
    ai_provider: str = "openrouter"
    ai_model: str = ""
    ai_base_url: str = ""
    ai_temperature: float = 0.3
    ai_max_tokens: int = 700
    ai_timeout: float = 45.0
    ai_system_prompt: str = ""

    def __post_init__(self) -> None:
        if self.theme not in THEMES:
            raise ValueError(f"Unsupported theme preset: {self.theme!r}")
        _require_int("polling_ms", self.polling_ms, 50, 2000)
        _require_int("candle_limit", self.candle_limit, 60, 1000)
        _require_int("alert_min_score", self.alert_min_score, 1, 4)
        for field_name in (
            "auto_refresh",
            "alerts_enabled",
            "compact_mode",
            "show_strategy_overlay",
            "store_candles",
            "save_snapshots",
            "ai_enabled",
        ):
            _require_bool(field_name, getattr(self, field_name))
        if self.strategy not in STRATEGIES:
            raise ValueError(
                f"Unsupported strategy {self.strategy!r}; "
                f"choose from {', '.join(sorted(STRATEGIES))}"
            )
        _require_int("supertrend_period", self.supertrend_period, 2, 100)
        _require_float("supertrend_multiplier", self.supertrend_multiplier, 0.5, 10.0)
        _require_int("divergence_lookback", self.divergence_lookback, 1, 30)
        _require_int("correlation_window", self.correlation_window, 10, 500)
        _require_int("correlation_baseline", self.correlation_baseline, 20, 2000)
        if self.correlation_baseline < self.correlation_window:
            raise ValueError("correlation baseline must be at least the window")
        _require_int("retention_days", self.retention_days, 1, 3650)
        if self.ai_provider not in AI_PROVIDERS:
            raise ValueError(f"Unsupported AI provider {self.ai_provider!r}")
        _require_float("ai_temperature", self.ai_temperature, 0.0, 2.0)
        _require_int("ai_max_tokens", self.ai_max_tokens, 64, 8192)
        _require_float("ai_timeout", self.ai_timeout, 5.0, 300.0)
        for field_name in (
            "ai_model",
            "ai_base_url",
            "ai_system_prompt",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")

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
