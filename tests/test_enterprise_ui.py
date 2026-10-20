"""Headless tests for the pure helpers in the enterprise UI layer."""

import pytest

pytest.importorskip("tkinter")

from neezy_app.enterprise import (  # noqa: E402
    GLYPHS,
    PAGE_TITLES,
    filter_commands,
)
from neezy_app.ui import NAV  # noqa: E402


def _noop() -> None:
    return None


COMMANDS = [
    ("Go to Chart", _noop),
    ("Go to Settings", _noop),
    ("Open chart · EUR/USD", _noop),
    ("Theme · High contrast", _noop),
]


def test_filter_empty_query_returns_everything():
    assert filter_commands(COMMANDS, "") == COMMANDS


def test_filter_is_case_insensitive_and_token_based():
    labels = [label for label, _ in filter_commands(COMMANDS, "CHART go")]
    assert labels == ["Go to Chart"]


def test_filter_no_match():
    assert filter_commands(COMMANDS, "zzz") == []


def test_every_nav_entry_has_glyph_and_title():
    assert set(NAV) <= set(GLYPHS)
    assert set(NAV) <= set(PAGE_TITLES)
