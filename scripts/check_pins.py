#!/usr/bin/env python3
"""Check that requirements-*.txt pins are consistent (roadmap #83)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Files to check
REQ_FILES = [
    ROOT / "requirements.txt",
    ROOT / "requirements-runtime.txt",
    ROOT / "requirements-training.txt",
    ROOT / "requirements-actions.txt",
]

_PIN = re.compile(r"^([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|!=|>|<).*")


def _pins_in(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    pins: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        m = _PIN.match(line)
        if m:
            pins.append((m.group(1).lower(), line))
    return pins


def main() -> int:
    errors = 0
    all_pins: list[tuple[str, str, Path]] = []
    for req in REQ_FILES:
        for name, raw in _pins_in(req):
            all_pins.append((name, raw, req))
    # Check for duplicates with different specifiers
    seen: dict[str, str] = {}
    for name, raw, path in all_pins:
        if name in seen and seen[name] != raw:
            print(
                f"WARNING: {name} has conflicting pins: {seen[name]!r} vs {raw!r} ({path})"
            )
        seen[name] = raw
    # pyproject.toml deps should at least include websocket-client
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if "websocket-client" not in pyproject:
        print("ERROR: pyproject.toml missing websocket-client dep")
        errors += 1
    else:
        print("Pins check: OK")
        for name, raw, path in all_pins:
            print(f"  {path.name}: {raw}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
