"""Runtime capability flags (roadmap update #33).

One place answers "is X available on this machine?" so UI and CLI code stops
scattering try/except imports. Every flag is computed at import time from
the local environment and never performs network calls.
"""

from __future__ import annotations

from typing import Any


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


_mt5 = _optional_module("MetaTrader5")
_kivy = _optional_module("kivy")
_numpy = _optional_module("numpy")

#: Is the MetaTrader 5 terminal bridge package importable (Windows only)?
MT5_AVAILABLE = _mt5 is not None

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
}


def feature_report() -> dict[str, bool]:
    """A copy of the capability snapshot (safe to log or serialize)."""
    return dict(BACKEND_FEATURES)
