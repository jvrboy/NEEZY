"""Local, dependency-free persistence for settings and signal history."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppSettings


def get_data_dir() -> Path:
    """Return the per-user application data directory, honoring NEEZY_HOME."""
    override = os.environ.get("NEEZY_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            / "NEEZY"
        ).resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "NEEZY").resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return (Path(xdg) / "neezy").resolve()


def sanitize_path(
    path: str | Path,
    *,
    base_dir: Path | None = None,
    allow_absolute: bool = False,
) -> Path:
    """Sanitize and sandbox a file path to prevent directory traversal outside base_dir.

    If base_dir is None, get_data_dir() is used as the sandbox boundary.
    """
    root = (base_dir or get_data_dir()).resolve()
    candidate = Path(path).expanduser()

    if not candidate.is_absolute():
        candidate = root / candidate

    resolved = candidate.resolve()

    try:
        resolved.relative_to(root)
    except ValueError as err:
        if not allow_absolute:
            msg = f"Path traversal blocked: '{path}' is outside sandboxed root '{root}'"
            raise ValueError(msg) from err

    return resolved


def create_local_backup(
    destination: str | Path | None = None,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Create a zipped local backup bundle of all local NEEZY state files.

    Includes sqlite3 db, settings.json, ai-keys.json, signal history, and alerts.
    """
    data_dir = (base_dir or get_data_dir()).resolve()
    if not destination:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        destination = data_dir / "backups" / f"neezy_backup_{stamp}.zip"

    dest_path = Path(destination).expanduser().resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    files_to_backup = [
        "neezy.sqlite3",
        "settings.json",
        "ai-keys.json",
        "signal-history.jsonl",
        "alerts.json",
        "local-models.json",
    ]

    with zipfile.ZipFile(dest_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in files_to_backup:
            file_path = data_dir / filename
            if file_path.exists() and file_path.is_file():
                archive.write(file_path, arcname=filename)

    return dest_path


def restore_local_backup(
    backup_zip: str | Path,
    *,
    base_dir: Path | None = None,
) -> list[str]:
    """Restore local configuration and data files from a backup zip archive.

    Returns list of filenames restored.
    """
    data_dir = (base_dir or get_data_dir()).resolve()
    zip_path = Path(backup_zip).expanduser().resolve()

    if not zip_path.exists():
        raise FileNotFoundError(f"Backup archive '{zip_path}' not found")

    restored = []
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            # Prevent zip slip
            sanitize_path(member.filename, base_dir=data_dir)
            archive.extract(member, path=data_dir)
            restored.append(member.filename)

    return restored


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
        """Persist settings, then tighten permissions (holds the MT5 password)."""
        _atomic_json_write(self.path, settings.to_dict())
        try:
            # Match the other secret stores: owner-only read/write.
            self.path.chmod(0o600)
        except OSError:
            pass  # best effort; some filesystems reject chmod


class SignalHistoryStore:
    """Append-only JSONL history with bounded reads, clear, and CSV export."""

    FIELDS = ("timestamp", "symbol", "previous", "current", "price", "score")

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_bytes: int = 2_000_000,
        keep_records: int = 5000,
    ) -> None:
        if max_bytes < 1 or keep_records < 1:
            raise ValueError("max_bytes and keep_records must be positive")
        self.path = path or get_data_dir() / "signal-history.jsonl"
        self.max_bytes = max_bytes
        self.keep_records = keep_records

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
        try:
            if self.path.stat().st_size > self.max_bytes:
                self.compact()
        except OSError:
            pass
        return record

    def compact(self, keep: int | None = None) -> int:
        """Atomically rewrite the file with only the newest valid records."""
        records = self.read(limit=keep or self.keep_records)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return len(records)

    def summary(self, limit: int = 100_000) -> dict[str, Any]:
        """Transition counts per symbol and per resulting signal."""
        by_symbol: dict[str, int] = {}
        by_signal: dict[str, int] = {}
        records = self.read(limit=limit)
        for record in records:
            by_symbol[record["symbol"]] = by_symbol.get(record["symbol"], 0) + 1
            by_signal[record["current"]] = by_signal.get(record["current"], 0) + 1
        return {"total": len(records), "by_symbol": by_symbol, "by_signal": by_signal}

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


class ConfluenceHistoryStore:
    """Card history: one JSONL record per confluence signal the app produced.

    Card cards show INSTRUMENT, BUY/SELL, ENTRY, SL, TP and WIN RATE; the only
    allowed outcome is exactly ``TP`` or ``SL`` (never a third state). Until a
    record resolves the ``outcome`` key holds ``None``.
    """

    REQUIRED = (
        "timestamp",
        "symbol",
        "instrument",
        "timeframe",
        "direction",
        "entry",
        "stop_loss",
        "take_profit",
        "win_rate",
    )

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_bytes: int = 2_000_000,
        keep_records: int = 5000,
    ) -> None:
        if max_bytes < 1 or keep_records < 1:
            raise ValueError("max_bytes and keep_records must be positive")
        self.path = path or get_data_dir() / "confluence-history.jsonl"
        self.max_bytes = max_bytes
        self.keep_records = keep_records

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        entry = dict(record)
        entry.setdefault("outcome", None)
        entry.setdefault("score", 0.0)
        entry.setdefault("mode", "strict")
        missing = [key for key in self.REQUIRED if key not in entry]
        if missing:
            raise ValueError(f"history record missing fields: {', '.join(missing)}")
        if entry["outcome"] not in (None, "TP", "SL"):
            raise ValueError("outcome must be TP, SL, or None")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            if self.path.stat().st_size > self.max_bytes:
                self.compact()
        except OSError:
            pass
        return entry

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
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(record, dict) and all(key in record for key in self.REQUIRED):
                records.append(record)
        return records

    def update_outcomes(self, resolutions: Mapping[tuple[str, str], str]) -> int:
        """Persist resolved outcomes for (symbol, timestamp) keys atomically.

        Returns the number of records that changed. Only ``TP`` and ``SL`` are
        accepted outcomes; ``None`` keeps a record open for the next render.
        """
        if any(value not in ("TP", "SL") for value in resolutions.values()):
            raise ValueError("resolved outcome must be exactly TP or SL")
        records = self.read(limit=100_000)
        changed = 0
        for record in records:
            key = (record["symbol"], record["timestamp"])
            outcome = resolutions.get(key)
            if outcome and record.get("outcome") != outcome:
                record["outcome"] = outcome
                changed += 1
        if not changed:
            return 0
        records = records[-self.keep_records :]
        self._rewrite(records)
        return changed

    def clear(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def compact(self, keep: int | None = None) -> int:
        """Atomically rewrite the file with only the newest valid records."""
        records = self.read(limit=keep or self.keep_records)
        self._rewrite(records)
        return len(records)
