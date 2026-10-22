"""Local, dependency-free persistence for settings and signal history."""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppSettings
from .sandbox import PathNotAllowedError, resolve_within


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

    Thin wrapper over :func:`neezy_backend.sandbox.resolve_within`, which is the
    single traversal guard for the whole app. Two behavioural additions are
    kept for backward compatibility:

    - ``expanduser()`` is applied first, so ``~``-relative paths work;
    - ``allow_absolute=True`` is an explicit escape hatch that returns the
      resolved path even when it lives outside the sandbox root (null bytes
      are still rejected). Never enable it for model- or user-supplied paths
      unless the caller has an independent reason to trust them.

    If base_dir is None, get_data_dir() is used as the sandbox boundary.
    """
    root = (base_dir or get_data_dir()).resolve()
    candidate = Path(path).expanduser()
    try:
        return resolve_within(root, candidate)
    except PathNotAllowedError as err:
        if "\0" in str(candidate):
            raise
        if allow_absolute:
            anchored = candidate if candidate.is_absolute() else root / candidate
            return anchored.resolve()
        msg = f"Path traversal blocked: '{path}' is outside sandboxed root '{root}'"
        raise ValueError(msg) from err


def create_local_backup(
    destination: str | Path | None = None,
    *,
    base_dir: Path | None = None,
    max_backups: int = 20,
) -> Path:
    """Create a zipped local backup bundle of all local NEEZY state files.

    Includes sqlite3 db, settings.json, ai-keys.json, signal history, and alerts.
    After writing, older backups beyond ``max_backups`` (roadmap #143) are
    pruned oldest-first so the backups directory can never grow unbounded.
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

    prune_backups(dest_path.parent, keep=max_backups)
    return dest_path


def prune_backups(directory: Path, *, keep: int = 20) -> list[Path]:
    """Delete the oldest backups beyond ``keep``; returns the removed paths."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    directory = Path(directory)
    if not directory.is_dir():
        return []
    backups = sorted(
        (item for item in directory.glob("neezy_backup_*.zip") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for stale in backups[keep:]:
        try:
            stale.unlink()
            removed.append(stale)
        except OSError:
            continue
    return removed


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

    logger = logging.getLogger("neezy.settings")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "settings.json"

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("Settings file must contain a JSON object")
            loaded = AppSettings.from_dict(data)
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            # A corrupt/old config must never prevent the app from starting.
            self.logger.warning(
                "settings file %s could not be fully applied (%s); "
                "falling back to defaults",
                self.path,
                error,
            )
            return AppSettings()
        unknown = sorted(set(data) - set(AppSettings.__dataclass_fields__))
        if unknown:
            self.logger.warning(
                "settings file has unknown fields (kept for forward compatibility): %s",
                ", ".join(unknown),
            )
        return loaded

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
        compact_on_init: bool = True,
    ) -> None:
        if max_bytes < 1 or keep_records < 1:
            raise ValueError("max_bytes and keep_records must be positive")
        self.path = path or get_data_dir() / "signal-history.jsonl"
        self.max_bytes = max_bytes
        self.keep_records = keep_records
        # Roadmap #145: an oversized file left by an interrupted session is
        # compacted at construction (bounded work: at most one rewrite of the
        # newest keep_records records) instead of only on the next append.
        if compact_on_init:
            try:
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self.compact()
            except OSError:
                pass  # a maintenance pass will retry later

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

    def append_signal(self, signal: Any) -> dict[str, Any]:
        """Persist a :class:`ConfluenceSignal` through the typed protocol.

        Roadmap #3: the signal dataclass is the contract between confluence,
        the UI, and this store; hand-built record dicts are no longer needed
        on the write path. The import is local to keep storage importable
        without pulling the strategy stack.
        """
        from .confluence import ConfluenceSignal

        if not isinstance(signal, ConfluenceSignal):
            raise TypeError("append_signal expects a ConfluenceSignal")
        return self.append(signal.as_history_record())

    def read_signals(self, limit: int = 1000) -> list[Any]:
        """Read recent records back as typed signals (newest last).

        Corrupt lines are already skipped by :meth:`read`; records that pass
        the REQUIRED check but still fail typed validation are skipped here
        as well, mirroring the store's tolerant-read philosophy.
        """
        from .confluence import ConfluenceSignal

        signals: list[ConfluenceSignal] = []
        for record in self.read(limit):
            try:
                signals.append(ConfluenceSignal.from_history_record(record))
            except ValueError:
                continue
        return signals

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
