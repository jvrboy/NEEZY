"""Capabilities CLI (roadmap #32)."""

from __future__ import annotations

from typing import Any, TextIO

from ..capabilities import feature_report, version_report
from ..diagnostics import system_info
from .common import _emit, _table


def cmd_capabilities(args: Any, _fetch: Any, out: TextIO) -> int:
    info = {
        "version": version_report(),
        "features": feature_report(),
        "system": system_info(),
    }
    if getattr(args, "json", False):
        _emit(out, info)
        return 0
    _table(
        out,
        ["capability", "available"],
        sorted([(k, str(v)) for k, v in info["features"].items()]),
    )
    ver = info["version"]
    out.write(f"\nVersion: {ver['version']} (API {ver['api_version']})\n")
    return 0
