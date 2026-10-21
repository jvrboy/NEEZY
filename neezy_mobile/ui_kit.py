"""Shared palette and widget helpers for the NEEZY Android screens.

The palette mirrors the desktop app (neezy_app/ui.py) so both front ends read
the same way. Everything here is plain Kivy; no KivyMD dependency.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Any

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

BG = "#08111f"
PANEL = "#101d30"
PANEL2 = "#14253b"
TEXT = "#e6f0ff"
MUTED = "#8ea4bd"
CYAN = "#55d6ff"
GREEN = "#48e6a1"
RED = "#ff718c"
AMBER = "#ffc857"
BORDER = "#203754"


def rgba(hex_color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """Convert ``#rrggbb`` to Kivy's normalised RGBA tuple."""
    digits = hex_color.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return (red, green, blue, alpha)


def label(
    text: str = "",
    color: str = TEXT,
    size: float = 14,
    *,
    bold: bool = False,
    halign: str = "left",
) -> Label:
    """A word-wrapping label whose height follows its text."""
    widget = Label(
        text=text,
        color=rgba(color),
        font_size=sp(size),
        bold=bold,
        halign=halign,
        valign="middle",
        size_hint_y=None,
    )
    widget.bind(width=lambda w, width: setattr(w, "text_size", (width, None)))
    widget.bind(
        texture_size=lambda w, size_px: setattr(w, "height", max(size_px[1], dp(18)))
    )
    return widget


def button(
    text: str,
    on_press: Callable[..., Any],
    *,
    color: str = CYAN,
    height: float = 44,
    size_hint_x: float | None = None,
) -> Button:
    widget = Button(
        text=text,
        font_size=sp(14),
        bold=True,
        color=rgba(color),
        background_normal="",
        background_down="",
        background_color=rgba(PANEL2),
        size_hint_y=None,
        height=dp(height),
    )
    if size_hint_x is not None:
        widget.size_hint_x = size_hint_x
    widget.bind(on_release=on_press)
    return widget


def field(
    hint: str = "",
    text: str = "",
    *,
    numeric: bool = False,
) -> TextInput:
    widget = TextInput(
        hint_text=hint,
        text=text,
        multiline=False,
        write_tab=False,
        background_normal="",
        background_active="",
        background_color=rgba(PANEL2),
        foreground_color=rgba(TEXT),
        hint_text_color=rgba(MUTED),
        cursor_color=rgba(CYAN),
        size_hint_y=None,
        height=dp(42),
        padding=[dp(10), dp(11)],
        font_size=sp(15),
    )
    if numeric:
        widget.input_filter = "float"
    return widget


def spinner(values: Sequence[str], text: str, *, size_hint_x: float = 1.0) -> Spinner:
    widget = Spinner(
        text=text,
        values=list(values),
        background_normal="",
        background_down="",
        background_color=rgba(PANEL2),
        color=rgba(TEXT),
        font_size=sp(14),
        size_hint_y=None,
        height=dp(42),
        size_hint_x=size_hint_x,
    )
    return widget


def row(*widgets: Any, height: float = 44, spacing: float = 8) -> BoxLayout:
    """Horizontal strip of widgets with a fixed height."""
    box = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(height),
        spacing=dp(spacing),
    )
    for widget in widgets:
        box.add_widget(widget)
    return box


def labelled(title: str, widget: Any) -> BoxLayout:
    """A form row: caption on the left, input on the right."""
    box = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(46),
        spacing=dp(8),
    )
    box.add_widget(label(title, MUTED, 13))
    widget.size_hint_x = 0.6
    box.add_widget(widget)
    return box


class Card(BoxLayout):
    """Rounded panel that grows with its children."""

    def __init__(self, *, color: str = PANEL, pad: float = 10, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "vertical")
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.padding = dp(pad)
        self.spacing = dp(4)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*rgba(color))
            self._panel = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(10)]
            )
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_: Any) -> None:
        self._panel.pos = self.pos
        self._panel.size = self.size


def scroll_list(spacing: float = 8) -> tuple[ScrollView, BoxLayout]:
    """Vertical scroll view and the box that holds its rows."""
    scroll = ScrollView(do_scroll_x=False)
    box = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        spacing=dp(spacing),
        padding=[0, 0, 0, dp(12)],
    )
    box.bind(minimum_height=box.setter("height"))
    scroll.add_widget(box)
    return scroll, box


def run_async(
    work: Callable[[], Any],
    done: Callable[[Any, BaseException | None], None],
) -> None:
    """Run ``work`` off the UI thread, then call ``done`` on the UI thread."""

    def worker() -> None:
        result: Any = None
        error: BaseException | None = None
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - reported in the UI, never crashes
            error = exc
        Clock.schedule_once(lambda _dt: done(result, error), 0)

    threading.Thread(target=worker, daemon=True).start()


def message(title: str, text: str) -> None:
    body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
    body.add_widget(label(text, TEXT, 14))
    popup = Popup(title=title, content=body, size_hint=(0.85, 0.4))
    body.add_widget(button("OK", lambda *_: popup.dismiss(), height=40))
    popup.open()


def split_extra(text: str) -> list[str]:
    """Comma-separated symbol list to a clean list."""
    return [part.strip() for part in text.split(",") if part.strip()]
