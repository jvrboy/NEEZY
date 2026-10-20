"""Local, dependency-free persistence for settings and signal history."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppSettings


def get_data_dir() -> Path:
    """Return the per-user application data directory, honoring NEEZY_HOME."""
    override = os.environ.get("NEEZY_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            / "NEEZY"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NEEZY"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "neezy"


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class SettingsStore:
    """Read/write user settings without risking a partially-written config."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "settings.json"

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("Settings file must contain a JSON object")
            return AppSettings.from_dict(data)
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A corrupt/old config must never prevent the app from starting.
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        _atomic_json_write(self.path, settings.to_dict())


class SignalHistoryStore:
    """Append-only JSONL history with bounded reads, clear, and CSV export."""

    FIELDS = ("timestamp", "symbol", "previous", "current", "price", "score")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "signal-history.jsonl"

    def append(
        self, *, symbol: str, previous: str, current: str, price: float, score: int
    ) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbol": symbol,
            "previous": previous,
            "current": current,
            "price": float(price),
            "score": int(score),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read(self, limit: int = 1000) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit must not be negative")
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError):
            return []
        records = []
        for line in lines[-limit:] if limit else []:
            try:
                record = json.loads(line)
                if isinstance(record, dict) and all(
                    key in record for key in self.FIELDS
                ):
                    records.append(record)
            except (json.JSONDecodeError, TypeError):
                continue
        return records

    def clear(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def export_csv(
        self, destination: Path, records: Iterable[dict[str, Any]] | None = None
    ) -> int:
        rows = list(records) if records is not None else self.read(limit=100_000)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=self.FIELDS, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)
