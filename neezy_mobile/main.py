"""NEEZY for Android: Kivy app shell with a scrollable tab strip.

The tab order follows the desktop NAV list in neezy_app/ui.py. Each tab is a
class in ``screens`` that talks to the shared backend through ``Services``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView

from .screens import TAB_CLASSES, BaseTab, ChartTab
from .services import Services
from .ui_kit import BG, CYAN, MUTED, PANEL2, rgba

TAB_BAR_HEIGHT = 46


class NeezyApp(App):
    title = "NEEZY"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.services: Services | None = None
        self.tabs: dict[str, BaseTab] = {}
        self.tab_buttons: dict[str, Button] = {}
        self.current: str | None = None

    def build(self) -> BoxLayout:
        Window.clearcolor = rgba(BG)
        data_dir = Path(self.user_data_dir) / "neezy"
        self.services = Services(data_dir)

        root = BoxLayout(orientation="vertical")
        self.bar_scroll = ScrollView(
            do_scroll_y=False,
            size_hint_y=None,
            height=TAB_BAR_HEIGHT,
        )
        self.bar = BoxLayout(
            orientation="horizontal",
            size_hint_x=None,
            spacing=2,
            padding=[4, 4],
        )
        self.bar.bind(minimum_width=self.bar.setter("width"))
        self.bar_scroll.add_widget(self.bar)
        self.content = BoxLayout(orientation="vertical")
        root.add_widget(self.bar_scroll)
        root.add_widget(self.content)

        for tab_class in TAB_CLASSES:
            tab = tab_class(self)
            self.tabs[tab.name] = tab
            button = Button(
                text=tab.name,
                size_hint_x=None,
                width=112,
                font_size="13sp",
                bold=True,
                background_normal="",
                background_down="",
                background_color=rgba(PANEL2),
                color=rgba(MUTED),
            )
            button.bind(on_release=lambda _b, name=tab.name: self.show(name))
            self.tab_buttons[tab.name] = button
            self.bar.add_widget(button)

        self.show(next(iter(self.tabs)))
        return root

    def show(self, name: str) -> None:
        if name not in self.tabs:
            return
        if self.current is not None:
            self.content.remove_widget(self.tabs[self.current].view)
            self.tab_buttons[self.current].color = rgba(MUTED)
        tab = self.tabs[name]
        self.content.add_widget(tab.view)
        self.tab_buttons[name].color = rgba(CYAN)
        self.current = name
        tab.on_show()

    def open_chart(self, symbol: str, timeframe: str | None = None) -> None:
        """Jump to the CHART tab and load ``symbol``."""
        self.show("CHART")
        chart = self.tabs["CHART"]
        assert isinstance(chart, ChartTab)
        chart.open_symbol(symbol, timeframe)

    def on_pause(self) -> bool:
        # Let Android pause the app without losing the open tab.
        return True
