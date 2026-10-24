"""Runtime capability flags (roadmap update #33).

One place answers "is X available on this machine?" so UI and CLI code stops
scattering try/except imports. Every flag is computed at import time from
the local environment and never performs network calls.
"""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any

from .mt5_compat import current_selection

try:
    VERSION: str = metadata.version("neezy-market-workspace")
except metadata.PackageNotFoundError:
    VERSION = "0.0.0-dev"

API_VERSION: int = 1

BUILD_INFO: dict[str, str] = {
    "version": VERSION,
    "api_version": str(API_VERSION),
}


def _optional_module(name: str) -> Any | None:
    try:
        return __import__(name)
    except ImportError:
        return None


def _fts5_available() -> bool:
    import sqlite3

    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        finally:
            connection.close()
        return True
    except sqlite3.OperationalError:
        return False


def _llm_available() -> bool:
    return (
        _optional_module("llama_cpp") is not None
        or _optional_module("transformers") is not None
    )


_kivy = _optional_module("kivy")
_numpy = _optional_module("numpy")

#: Is a MetaTrader 5 backend selected (native package or RPyC terminal)?
#: Native MetaTrader5 is Windows-only; mt5_compat adds the remote path.
MT5_AVAILABLE = current_selection().backend != "none"

#: Is Kivy importable (used by the Android port tooling, never on CI)?
KIVY_AVAILABLE = _kivy is not None

#: Is numpy present (optional acceleration for research paths)?
NUMPY_AVAILABLE = _numpy is not None

BACKEND_FEATURES: dict[str, bool] = {
    "mt5_bridge": MT5_AVAILABLE,
    "kivy_mobile": KIVY_AVAILABLE,
    "numpy_math": NUMPY_AVAILABLE,
    "sqlite_fts5": _fts5_available(),
    "local_llm": _llm_available(),
    "coverage": _optional_module("coverage") is not None,
    "notifiers": True,
    "watchlist_io": True,
    "snapshots": True,
    "reasoning_engine": True,
    "neural_v2": True,
    "neuro_search": True,
    "scheduler": True,
    "job_queue": True,
    "metrics_tracing": True,
    "orchestrator": True,
    "signal_fusion": True,
    "dashboard": True,
}

CAPABILITY_FLAGS: dict[str, bool] = dict(BACKEND_FEATURES)


def feature_report() -> dict[str, bool]:
    """A copy of the capability snapshot (safe to log or serialize)."""
    return dict(BACKEND_FEATURES)


def version_report() -> dict[str, str]:
    """Version and API compatibility snapshot."""
    return dict(BUILD_INFO)


def build_info() -> dict[str, str]:
    """Alias for :func:`version_report`."""
    return version_report()


def accessibility_report() -> dict[str, object]:
    """Keyboard and terminal accessibility snapshot (no network calls).

    Answers the questions the BTOKEN layer and the UI theme engine ask:
    is btoken mode active, is colour forced off, which theme is selected,
    and how wide is the output device.
    """
    from .ui_style import DEFAULT_THEME, resolve_theme

    return {
        "btoken_mode": bool(os.environ.get("NEEZY_BTOKEN", "")),
        "color_disabled": bool(os.environ.get("NO_COLOR", "")),
        "color_forced": bool(os.environ.get("FORCE_COLOR", "")),
        "theme": resolve_theme(),
        "theme_default": DEFAULT_THEME,
        "screen_reader_friendly": bool(os.environ.get("NEEZY_SCREEN_READER", "")),
    }
