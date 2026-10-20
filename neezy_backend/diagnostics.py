"""Support bundle: a redacted zip users can attach to a bug report.

Everything is scrubbed of API keys and tokens before it is written, and nothing
is uploaded: the zip is only created where the user chooses.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

REDACTED = "***"
_SENSITIVE_KEY = re.compile(
    r"api[_-]?key|secret|password|authorization|(^|_)token($|_)", re.IGNORECASE
)
_LOG_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b(\s*[=:]\s*)(\S+)"
)
_KNOWN_SECRET = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"
)


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with secret-looking fields masked."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if _SENSITIVE_KEY.search(str(key)) and item not in (None, "")
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def redact_text(text: str) -> str:
    """Mask ``key=value`` style secrets and well-known key formats in logs."""
    text = _LOG_ASSIGNMENT.sub(rf"\1\2{REDACTED}", text)
    return _KNOWN_SECRET.sub(REDACTED, text)


def tail_text(path: Path, max_bytes: int) -> str:
    """Read at most the last ``max_bytes`` of a text file."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def system_info() -> dict[str, str]:
    try:
        version = metadata.version("neezy-market-workspace")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return {
        "neezy_version": version,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def build_bundle(
    destination: Path | str,
    *,
    data_dir: Path | str,
    settings: Any = None,
    db_stats: Mapping[str, Any] | None = None,
    max_log_bytes: int = 200_000,
) -> Path:
    """Write the redacted support zip and return its path."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("system.json", json.dumps(system_info(), indent=2))
        if settings is not None:
            body = json.dumps(redact(settings), indent=2, default=str)
            bundle.writestr("settings.json", body)
        if db_stats is not None:
            body = json.dumps(redact(db_stats), indent=2, default=str)
            bundle.writestr("database.json", body)
        for log in sorted(Path(data_dir).glob("*.log"))[:10]:
            text = redact_text(tail_text(log, max_log_bytes))
            bundle.writestr(f"logs/{log.name}", text)
    return target
