"""Validated application settings kept separate from the Tkinter view."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AppSettings:
    auto_refresh: bool = True
    alerts_enabled: bool = True
    compact_mode: bool = False
    theme: str = "Liquid dark"
    polling_ms: int = 100
    candle_limit: int = 300

    def updated(self, **changes: object) -> "AppSettings":
        candidate = replace(self, **changes)
        if candidate.theme not in {"Liquid dark", "Midnight blue", "High contrast"}:
            raise ValueError("Unsupported theme preset")
        if not 50 <= candidate.polling_ms <= 2000:
            raise ValueError("Polling interval must be between 50 and 2000 ms")
        if not 60 <= candidate.candle_limit <= 1000:
            raise ValueError("Candle limit must be between 60 and 1000")
        return candidate
