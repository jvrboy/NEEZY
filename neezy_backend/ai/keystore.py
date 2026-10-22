"""Local key vault: many keys per provider, with health and cooldown state."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..storage import _atomic_json_write, get_data_dir
from .providers import PROVIDERS, mask_secret, resolve_provider, validate_secret


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class KeyStatus:
    """Public, safe view of one stored key."""

    id: str
    provider: str
    label: str
    hint: str
    enabled: bool
    failures: int
    uses: int
    exhausted_until: str | None
    last_error: str
    last_used: str | None

    def usable(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if not self.exhausted_until:
            return True
        try:
            until = datetime.fromisoformat(self.exhausted_until)
        except ValueError:
            return True
        return (now or _utc_now()) >= until

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "hint": self.hint,
            "enabled": self.enabled,
            "failures": self.failures,
            "uses": self.uses,
            "exhausted_until": self.exhausted_until,
            "last_error": self.last_error,
            "last_used": self.last_used,
            "usable": self.usable(now),
        }


def _status_from_record(provider: str, record: Mapping[str, Any]) -> KeyStatus:
    return KeyStatus(
        id=str(record.get("id", "")),
        provider=provider,
        label=str(record.get("label") or "key"),
        hint=mask_secret(str(record.get("secret", ""))),
        enabled=bool(record.get("enabled", True)),
        failures=int(record.get("failures", 0)),
        uses=int(record.get("uses", 0)),
        exhausted_until=record.get("exhausted_until"),
        last_error=str(record.get("last_error") or ""),
        last_used=record.get("last_used"),
    )


class AIKeyStore:
    """Local key vault: many keys per provider, with health and cooldown state."""

    VERSION = 1

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else get_data_dir() / "ai-keys.json"
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ internals
    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": self.VERSION, "keys": {}}
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {"version": self.VERSION, "keys": {}}
        if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
            return {"version": self.VERSION, "keys": {}}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(self.path, data)
        try:
            self.path.chmod(0o600)
        except OSError:
            # Windows relies on the per-user ACL of %APPDATA% instead.
            pass

    def _records(self, data: dict[str, Any], provider: str) -> list[dict[str, Any]]:
        entries = data["keys"].get(provider, [])
        return entries if isinstance(entries, list) else []

    # --------------------------------------------------------------------- public
    def providers(self) -> list[str]:
        with self._lock:
            data = self._read()
        return [name for name, entries in data["keys"].items() if entries]

    def add(
        self,
        provider: str,
        secret: str,
        label: str = "",
        *,
        replace_duplicate: bool = True,
    ) -> KeyStatus:
        spec = resolve_provider(provider)
        cleaned = validate_secret(spec.key, secret)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            for record in records:
                if record.get("secret") == cleaned:
                    if not replace_duplicate:
                        raise ValueError("this key is already stored for that provider")
                    record["enabled"] = True
                    record["exhausted_until"] = None
                    record["last_error"] = ""
                    self._write(data)
                    return _status_from_record(spec.key, record)
            record = {
                "id": uuid.uuid4().hex[:10],
                "secret": cleaned,
                "label": (label or f"key {len(records) + 1}").strip()[:60],
                "enabled": True,
                "failures": 0,
                "uses": 0,
                "exhausted_until": None,
                "last_error": "",
                "last_used": None,
                "added_at": _utc_now().isoformat(timespec="seconds"),
            }
            records.append(record)
            data["keys"][spec.key] = records
            self._write(data)
        return _status_from_record(spec.key, record)

    def remove(self, provider: str, key_id: str) -> bool:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            remaining = [record for record in records if record.get("id") != key_id]
            if len(remaining) == len(records):
                return False
            data["keys"][spec.key] = remaining
            self._write(data)
        return True

    def set_enabled(self, provider: str, key_id: str, enabled: bool) -> bool:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") == key_id:
                    record["enabled"] = bool(enabled)
                    if enabled:
                        record["exhausted_until"] = None
                    self._write(data)
                    return True
        return False

    def statuses(self, provider: str) -> list[KeyStatus]:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
        return [_status_from_record(spec.key, record) for record in records]

    def secrets(self, provider: str) -> list[tuple[str, str]]:
        """``(key_id, secret)`` pairs in rotation order; never log this output."""
        spec = resolve_provider(provider)
        now = _utc_now()
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            usable = [
                record
                for record in records
                if _status_from_record(spec.key, record).usable(now)
            ]
            usable.sort(key=lambda record: record.get("last_used") or "")
        return [(str(record["id"]), str(record["secret"])) for record in usable]

    def count(self, provider: str) -> int:
        spec = resolve_provider(provider)
        with self._lock:
            return len(self._records(self._read(), spec.key))

    def usable_count(self, provider: str) -> int:
        return len(self.secrets(provider))

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "keys": self.count(name),
                "usable": self.usable_count(name),
            }
            for name in PROVIDERS
        }

    def mark_success(self, provider: str, key_id: str) -> None:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") == key_id:
                    record["failures"] = 0
                    record["uses"] = int(record.get("uses", 0)) + 1
                    record["last_used"] = _utc_now().isoformat(timespec="seconds")
                    record["last_error"] = ""
                    record["exhausted_until"] = None
            self._write(data)

    def mark_failure(
        self,
        provider: str,
        key_id: str,
        reason: str,
        *,
        cooldown_seconds: float,
    ) -> None:
        """Park a key for a cooldown after a quota, auth, or network failure."""
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") != key_id:
                    continue
                record["failures"] = int(record.get("failures", 0)) + 1
                record["last_error"] = str(reason)[:200]
                until = _utc_now() + timedelta(seconds=max(0.0, cooldown_seconds))
                record["exhausted_until"] = until.isoformat(timespec="seconds")
            self._write(data)

    def reset(self, provider: str | None = None) -> int:
        """Clear cooldowns and failure counters (keys themselves are kept)."""
        with self._lock:
            data = self._read()
            targets = [provider] if provider else list(data["keys"])
            changed = 0
            for name in targets:
                for record in self._records(data, name):
                    record["failures"] = 0
                    record["exhausted_until"] = None
                    record["last_error"] = ""
                    changed += 1
            self._write(data)
        return changed
