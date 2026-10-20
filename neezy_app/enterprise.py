"""Enterprise UI layer for NEEZY.

Subclasses the base :class:`~neezy_app.ui.App` so the proven window logic stays
untouched while adding a design system, toast notifications, a command palette
(Ctrl+K), a live status bar, scrollbars, and several UX fixes.
"""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from collections.abc import Callable
from datetime import datetime, timezone
from tkinter import filedialog, ttk

from neezy_backend.diagnostics import build_bundle
from neezy_backend.markets import SYMBOLS, TIMEFRAMES
from neezy_backend.outcomes import evaluate_outcomes, summarize
from neezy_backend.storage import get_data_dir

from .ui import NAV, App

logger = logging.getLogger(__name__)

AMBER = "#f0bd62"
OUTCOME_HORIZON = 10
THEMES = ("Liquid dark", "Midnight blue", "High contrast")
UI_FONTS = (
    "Segoe UI",
    "SF Pro Text",
    "Inter",
    "Helvetica Neue",
    "Ubuntu",
    "DejaVu Sans",
)
MONO_FONTS = (
    "Cascadia Mono",
    "Consolas",
    "SF Mono",
    "Menlo",
    "DejaVu Sans Mono",
)
GLYPHS = {
    "CHAT": "✦",
    "SYMBOLS": "≡",
    "CHART": "▤",
    "SIGNALS": "◉",
    "TOOLS": "⚙",
    "ALERTS": "◔",
    "HISTORY": "↺",
    "SETTINGS": "☷",
}
PAGE_TITLES = {
    "CHAT": "MARKET COPILOT",
    "SYMBOLS": "WATCHLIST",
    "CHART": "CHART WORKSPACE",
    "SIGNALS": "SIGNALS OVERVIEW",
    "TOOLS": "TRADER TOOLKIT",
    "ALERTS": "ALERT RULES",
    "HISTORY": "SIGNAL HISTORY",
    "SETTINGS": "WORKSPACE SETTINGS",
}
CHAT_CHIPS = (
    ("Best setups", "What are the best setups right now?"),
    ("Risk plan", "Plan my risk size"),
    ("Key levels", "Show support and resistance levels"),
    ("Trend & regime", "What is the trend and regime?"),
    ("Patterns", "Any candlestick pattern?"),
)
_UNSET = object()

Command = tuple[str, Callable[[], None]]


def filter_commands(commands: list[Command], query: str) -> list[Command]:
    """Return commands whose label contains every whitespace-separated token."""
    tokens = query.lower().split()
    return [c for c in commands if all(t in c[0].lower() for t in tokens)]


def format_outcomes(symbol_name: str, timeframe: str, stats: dict[str, float]) -> str:
    """Render outcome statistics for the report panel."""
    if not stats["count"]:
        return (
            f"OUTCOMES · {symbol_name} · {timeframe}\n\n"
            "No resolved signals yet. Keep NEEZY running with candle "
            "storage enabled and check back after a few signals."
        )
    return (
        f"OUTCOMES · {symbol_name} · {timeframe}\n\n"
        f"Signals scored  {stats['count']:.0f}\n"
        f"Win rate        {stats['win_rate']:.1f}%\n"
        f"Avg return      {stats['avg_return_pct']:+.3f}%\n"
        f"Best / worst    {stats['best_pct']:+.2f}% / {stats['worst_pct']:+.2f}%\n"
        f"Horizon         {OUTCOME_HORIZON} candles\n\n"
        "Measured from signal price to the close N candles later."
    )


def pick_fonts(root: tk.Misc) -> tuple[str, str]:
    """Choose the best installed UI and monospace families."""
    installed = {str(f).lower(): str(f) for f in root.tk.call("font", "families")}

    def first(names: tuple[str, ...], default: str) -> str:
        for name in names:
            if name.lower() in installed:
                return installed[name.lower()]
        return default

    return first(UI_FONTS, "Helvetica"), first(MONO_FONTS, "Courier")


def apply_enterprise_style(app: App, ui: str, mono: str) -> None:
    """Extend the base ttk style with enterprise-grade widget treatments."""
    style = ttk.Style(app)
    style.configure("Treeview", font=(ui, 10))
    style.configure(
        "Treeview.Heading",
        background=app.PANEL2,
        foreground=app.MUTED,
        relief="flat",
        borderwidth=0,
        padding=(8, 9),
        font=(ui, 9, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", app.BORDER)])
    style.configure(
        "Vertical.TScrollbar",
        background=app.PANEL2,
        troughcolor=app.BG,
        bordercolor=app.BG,
        lightcolor=app.PANEL2,
        darkcolor=app.PANEL2,
        arrowcolor=app.MUTED,
        relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", app.BORDER)])
    style.configure(
        "TCombobox",
        arrowcolor=app.CYAN,
        bordercolor=app.BORDER,
        lightcolor=app.PANEL2,
        darkcolor=app.PANEL2,
        padding=4,
    )
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("Hidden.TNotebook", background=app.BG, borderwidth=0, tabmargins=0)
    popdown = {
        "background": app.PANEL2,
        "foreground": app.TEXT,
        "selectBackground": app.BORDER,
        "selectForeground": app.CYAN,
    }
    for option, value in popdown.items():
        app.option_add(f"*TCombobox*Listbox.{option}", value)
    app.option_add("*TCombobox*Listbox.font", (ui, 10))


class Toasts:
    """Non-blocking notifications stacked in the bottom-right corner."""

    MAX_VISIBLE = 4

    def __init__(self, app: EnterpriseApp) -> None:
        self.app = app
        self._items: list[tk.Frame] = []

    def show(self, text: str, kind: str = "info", ms: int = 4500) -> None:
        app = self.app
        accent = {
            "info": app.CYAN,
            "success": app.GREEN,
            "warn": AMBER,
            "error": app.RED,
        }.get(kind, app.CYAN)
        frame = tk.Frame(
            app, bg=app.PANEL2, highlightbackground=app.BORDER, highlightthickness=1
        )
        tk.Frame(frame, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(
            frame,
            text=text,
            bg=app.PANEL2,
            fg=app.TEXT,
            font=(app.font_ui, 10),
            justify="left",
            wraplength=320,
            padx=14,
            pady=10,
        ).pack(side="left")
        close = tk.Label(
            frame,
            text="✕",
            bg=app.PANEL2,
            fg=app.MUTED,
            cursor="hand2",
            padx=10,
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._dismiss(frame))
        self._items.append(frame)
        while len(self._items) > self.MAX_VISIBLE:
            self._dismiss(self._items[0])
        self._layout()
        app.after(ms, lambda: self._dismiss(frame))

    def _dismiss(self, frame: tk.Frame) -> None:
        if frame not in self._items:
            return
        self._items.remove(frame)
        frame.destroy()
        self._layout()

    def _layout(self) -> None:
        offset = 44
        for frame in reversed(self._items):
            frame.place(relx=1.0, rely=1.0, x=-24, y=-offset, anchor="se")
            frame.lift()
            frame.update_idletasks()
            offset += frame.winfo_reqheight() + 10


class CommandPalette(tk.Toplevel):
    """Searchable action launcher (Ctrl+K)."""

    WIDTH = 560

    def __init__(self, app: EnterpriseApp, commands: list[Command]) -> None:
        super().__init__(app)
        self.app = app
        self.commands = commands
        self._shown: list[Command] = []
        self.overrideredirect(True)
        self.configure(bg=app.BORDER)
        body = tk.Frame(self, bg=app.PANEL)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        self.query = tk.StringVar()
        self.entry = tk.Entry(
            body,
            textvariable=self.query,
            bg=app.PANEL2,
            fg=app.TEXT,
            insertbackground=app.TEXT,
            relief="flat",
            font=(app.font_ui, 13),
        )
        self.entry.pack(fill="x", padx=12, pady=12, ipady=8)
        self.listbox = tk.Listbox(
            body,
            bg=app.PANEL,
            fg=app.TEXT,
            selectbackground=app.BORDER,
            selectforeground=app.CYAN,
            activestyle="none",
            relief="flat",
            highlightthickness=0,
            height=10,
            font=(app.font_ui, 11),
        )
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        x = app.winfo_rootx() + max((app.winfo_width() - self.WIDTH) // 2, 0)
        self.geometry(f"{self.WIDTH}x340+{x}+{app.winfo_rooty() + 110}")
        self.query.trace_add("write", lambda *_: self._refilter())
        self.entry.bind("<Down>", lambda _e: self._move(1))
        self.entry.bind("<Up>", lambda _e: self._move(-1))
        self.entry.bind("<Return>", lambda _e: self._run())
        self.listbox.bind("<Double-1>", lambda _e: self._run())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<FocusOut>", lambda _e: self.after(120, self._close_if_idle))
        self._refilter()
        self.after(10, self._focus)

    def _focus(self) -> None:
        self.lift()
        self.entry.focus_force()

    def _close_if_idle(self) -> None:
        if self.winfo_exists() and self.focus_displayof() is None:
            self.destroy()

    def _refilter(self) -> None:
        self._shown = filter_commands(self.commands, self.query.get())
        self.listbox.delete(0, "end")
        for label, _action in self._shown:
            self.listbox.insert("end", f"   {label}")
        if self._shown:
            self.listbox.selection_set(0)

    def _move(self, step: int) -> str:
        if not self._shown:
            return "break"
        current = self.listbox.curselection()
        index = (current[0] if current else 0) + step
        index = max(0, min(len(self._shown) - 1, index))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.see(index)
        return "break"

    def _run(self) -> str:
        current = self.listbox.curselection()
        if current:
            action = self._shown[current[0]][1]
            self.destroy()
            self.app.after(20, action)
        return "break"


class EnterpriseApp(App):
    """NEEZY with the enterprise UI layer applied."""

    def __init__(self) -> None:
        super().__init__()
        self.toasts = Toasts(self)
        self._palette: CommandPalette | None = None
        self._enhance_layout()
        self._retheme_fonts()
        self._wrap_alert_engine()
        self._bind_shortcuts()
        self._sync_nav()
        self._tick_status()
        self.after(1200, self._announce_ready)

    def _announce_ready(self) -> None:
        self.toasts.show("Workspace ready · press Ctrl+K for commands", "info")

    # ------------------------------------------------------------- fonts/style
    @property
    def font_ui(self) -> str:
        return self._font_pair()[0]

    @property
    def font_mono(self) -> str:
        return self._font_pair()[1]

    def _font_pair(self) -> tuple[str, str]:
        if not hasattr(self, "_fonts_cache"):
            self._fonts_cache = pick_fonts(self)
        return self._fonts_cache

    def _style(self) -> None:
        super()._style()
        apply_enterprise_style(self, *self._font_pair())

    def _apply_theme(self) -> None:
        super()._apply_theme()
        tree = getattr(self, "tree", None)
        if tree is not None:
            tree.tag_configure("buy", foreground=self.GREEN)
            tree.tag_configure("sell", foreground=self.RED)
        detail = getattr(self, "detail", None)
        if detail is not None:
            detail.tag_configure("buy", foreground=self.GREEN)
            detail.tag_configure("sell", foreground=self.RED)

    def _retheme_fonts(self) -> None:
        ui, mono = self._font_pair()
        families = {"helvetica": ui, "courier": mono}
        for widget in self._walk_widgets(self):
            try:
                spec = self.tk.splitlist(str(widget.cget("font")))
            except tk.TclError:
                continue
            if len(spec) < 2:
                continue
            target = families.get(spec[0].lower())
            if target is None:
                continue
            try:
                widget.configure(font=(target, int(spec[1]), *spec[2:]))
            except (ValueError, tk.TclError):
                continue
        self.detail.tag_configure("big", font=(ui, 22, "bold"))

    # ----------------------------------------------------------------- layout
    def _enhance_layout(self) -> None:
        self.nb.configure(style="Hidden.TNotebook")
        self.nb.bind("<<NotebookTabChanged>>", self._sync_nav, add="+")
        header = self.main.winfo_children()[0]
        self.page_title = header.winfo_children()[0]
        tk.Button(
            header,
            text="Search commands   Ctrl+K",
            command=self.open_palette,
            bg=self.PANEL2,
            fg=self.MUTED,
            activebackground=self.BORDER,
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
        ).pack(side="right", padx=(0, 18))
        for name, button in self.nav.items():
            glyph = GLYPHS.get(name, "•")
            button.configure(text=f"  {glyph}   {name.title()}", cursor="hand2")
            button.bind("<Enter>", lambda _e, n=name: self._hover(n, True))
            button.bind("<Leave>", lambda _e, n=name: self._hover(n, False))
        self._build_status_bar()
        self._add_chat_chips()
        for widget in (
            self.tree,
            self.watch,
            self.hist,
            self.chat,
            self.detail,
            self.risk_out,
            self.test_out,
            self.rank_out,
        ):
            self._attach_scrollbar(widget)
        self.tree.bind("<Double-1>", lambda _e: self._tab("CHART"))
        for widget in self._walk_widgets(self):
            if isinstance(widget, tk.Label) and "x10" in widget.cget("text"):
                widget.configure(text="Temperature (0.0 - 2.0)")

    def _build_status_bar(self) -> None:
        bar = tk.Frame(
            self.main,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        bar.pack(side="bottom", fill="x", before=self.nb)
        self.sb_left = tk.Label(
            bar,
            textvariable=self.status_var,
            bg=self.PANEL,
            fg=self.TEXT,
            font=(self.font_ui, 9),
            padx=14,
            pady=5,
        )
        self.sb_left.pack(side="left")
        self.sb_clock = tk.Label(
            bar, bg=self.PANEL, fg=self.MUTED, font=(self.font_ui, 9), padx=14
        )
        self.sb_clock.pack(side="right")
        self.sb_feed = tk.Label(
            bar, bg=self.PANEL, fg=self.MUTED, font=(self.font_ui, 9), padx=14
        )
        self.sb_feed.pack(side="right")

    def _tick_status(self) -> None:
        if not self.winfo_exists():
            return
        self.sb_feed.config(
            text=(
                f"{SYMBOLS[self.selected]} · {self.tf.get()} · "
                f"{len(self.results)}/{len(self.watch_symbols)} markets analysed · "
                f"last tick {self.last_message_at or '—'}"
            )
        )
        self.sb_clock.config(text=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
        self.after(1000, self._tick_status)

    def _attach_scrollbar(self, widget: tk.Widget) -> None:
        bar = ttk.Scrollbar(widget.master, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y", before=widget)

    def _add_chat_chips(self) -> None:
        row = tk.Frame(self.pages["CHAT"], bg=self.BG)
        row.pack(fill="x", pady=(0, 10), before=self.chat)
        for label, question in CHAT_CHIPS:
            tk.Button(
                row,
                text=label,
                command=lambda q=question: self._quick_ask(q),
                bg=self.PANEL2,
                fg=self.TEXT,
                activebackground=self.BORDER,
                activeforeground=self.CYAN,
                relief="flat",
                bd=0,
                padx=12,
                pady=5,
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

    def _quick_ask(self, question: str) -> None:
        self.prompt.delete(0, "end")
        self.prompt.insert(0, question)
        self._ask()

    # ------------------------------------------------------------ navigation
    def _current_tab(self) -> str:
        return NAV[self.nb.index(self.nb.select())]

    def _tab(self, name: str) -> None:
        self.nb.select(self.pages[name])
        self._sync_nav()

    def _sync_nav(self, _event: object = None) -> None:
        if not hasattr(self, "nav") or not hasattr(self, "page_title"):
            return
        current = self._current_tab()
        for name, button in self.nav.items():
            active = name == current
            button.configure(
                fg=self.CYAN if active else self.MUTED,
                bg=self.PANEL2 if active else self.BG,
            )
        self.page_title.config(text=PAGE_TITLES.get(current, current))
        if current == "CHAT":
            self.prompt.focus_set()

    def _hover(self, name: str, inside: bool) -> None:
        if name == self._current_tab():
            return
        self.nav[name].configure(
            bg=self.PANEL if inside else self.BG,
            fg=self.TEXT if inside else self.MUTED,
        )

    def _open_chart(self, symbol: str) -> None:
        if self.tree.exists(symbol):
            self.tree.selection_set(symbol)
        self._set_selected(symbol)
        self._tab("CHART")

    def _watch_select(self) -> None:
        index = self.watch.curselection()
        if index:
            self._open_chart(list(self.watch_symbols)[index[0]])

    # --------------------------------------------------------------- commands
    def _bind_shortcuts(self) -> None:
        def palette(_event: object) -> str:
            self.open_palette()
            return "break"

        self.bind_all("<Control-k>", palette)
        for widget_class in ("Entry", "Text", "TEntry", "TCombobox", "Spinbox"):
            self.bind_class(widget_class, "<Control-k>", palette)
        for index, name in enumerate(NAV, start=1):
            self.bind_all(f"<Control-Key-{index}>", lambda _e, n=name: self._tab(n))
        self.bind_all("<F5>", lambda _e: self._resubscribe())

    def _resubscribe(self) -> None:
        self._subscribe_all()
        self.toasts.show("Re-subscribed to all market streams", "info")

    def _commands(self) -> list[Command]:
        commands: list[Command] = [
            (f"Go to {name.title()}  (Ctrl+{i})", lambda n=name: self._tab(n))
            for i, name in enumerate(NAV, start=1)
        ]
        commands += [
            (f"Timeframe {label}", lambda t=label: self._set_timeframe(t))
            for label in TIMEFRAMES
        ]
        commands += [
            (f"Open chart · {name}", lambda s=symbol: self._open_chart(s))
            for symbol, name in self.watch_symbols.items()
        ]
        commands += [
            ("Scan selected market (all strategies)", self._scan_from_palette),
            ("Refresh market ranking", self._rank_from_palette),
            ("Signal outcomes report (selected market)", self._show_outcomes),
            ("Export diagnostics bundle (redacted zip)", self._export_diagnostics),
            ("Export signal history as CSV", self._export_history),
            ("Reconnect market streams  (F5)", self._resubscribe),
            ("Toggle compact density", self._toggle_compact),
        ]
        commands += [
            (f"Theme · {preset}", lambda p=preset: self._set_theme(p))
            for preset in THEMES
        ]
        return commands

    def open_palette(self) -> None:
        if self._palette is not None and self._palette.winfo_exists():
            self._palette.destroy()
        self._palette = CommandPalette(self, self._commands())

    def _set_timeframe(self, label: str) -> None:
        self.tf.set(label)
        self._tf_changed()
        self.toasts.show(f"Timeframe set to {label}", "info")

    def _scan_from_palette(self) -> None:
        self._tab("SETTINGS")
        self.settings_notebook.select(1)
        self._scan_strategies()

    def _rank_from_palette(self) -> None:
        self._tab("TOOLS")
        self._refresh_ranking()

    def _toggle_compact(self) -> None:
        self.compact_mode.set(not self.compact_mode.get())
        self._settings_changed()
        state = "on" if self.compact_mode.get() else "off"
        self.toasts.show(f"Compact density {state}", "info")

    def _set_theme(self, preset: str) -> None:
        self.theme_var.set(preset)
        self._settings_changed()
        self.toasts.show(f"Theme: {preset}", "info")

    # --------------------------------------------------------- data tools
    def _show_outcomes(self) -> None:
        self._tab("TOOLS")
        symbol, timeframe = self.selected, self.tf.get()
        if self.db is None:
            self._write(self.rank_out, "Local database unavailable.")
            return
        try:
            signals = [
                row
                for row in self.db.recent_signals(500, symbol=symbol)
                if row.get("timeframe") == timeframe
            ]
            candles = self.db.load_candles(symbol, timeframe, 5000)
        except sqlite3.Error as error:
            self._write(self.rank_out, f"Database error: {error}")
            return
        outcomes = evaluate_outcomes(signals, candles, OUTCOME_HORIZON)
        stats = summarize(outcomes)
        self._write(
            self.rank_out, format_outcomes(SYMBOLS[symbol], timeframe, stats)
        )

    def _export_diagnostics(self) -> None:
        destination = filedialog.asksaveasfilename(
            title="Export diagnostics bundle",
            defaultextension=".zip",
            filetypes=[("Zip archive", "*.zip")],
            initialfile="neezy-diagnostics.zip",
        )
        if not destination:
            return
        try:
            stats = self.db.stats() if self.db is not None else None
            build_bundle(
                destination,
                data_dir=get_data_dir(),
                settings=self.settings,
                db_stats=stats,
            )
        except (OSError, sqlite3.Error) as error:
            logger.exception("Diagnostics export failed")
            self.toasts.show(f"Diagnostics export failed: {error}", "error")
            return
        self.toasts.show("Diagnostics bundle saved (secrets redacted)", "success")

    # ----------------------------------------------------------- notifications
    def _wrap_alert_engine(self) -> None:
        engine = self.alert_engine
        original = engine.evaluate

        def evaluate(symbol, result, price, patterns):
            fired = original(symbol, result, price, patterns)
            for rule in fired or []:
                market = SYMBOLS.get(symbol, symbol)
                self.toasts.show(f"Alert · {market} · {rule.describe()}", "warn")
            return fired

        try:
            engine.evaluate = evaluate
        except (AttributeError, TypeError):
            logger.warning("Alert engine is immutable; toast alerts disabled")

    def _render_history(self) -> None:
        super()._render_history()
        latest = self.history[-1] if self.history else None
        previous = getattr(self, "_last_record", _UNSET)
        self._last_record = latest
        if previous is _UNSET or latest is None or latest is previous:
            return
        if not hasattr(self, "toasts"):
            return
        current = str(latest.get("current", ""))
        if "BUY" in current:
            kind = "success"
        elif "SELL" in current:
            kind = "error"
        else:
            kind = "info"
        market = SYMBOLS.get(latest.get("symbol"), latest.get("symbol", "?"))
        self.toasts.show(f"{market}: {latest.get('previous', '?')} → {current}", kind)

    # ------------------------------------------------------------------ fixes
    def _draw_chart(self) -> None:
        candles = self.candles.get(self.selected, [])
        if hasattr(self, "canvas") and len(candles) < 2:
            self.canvas.delete("all")
            self.canvas.create_text(
                max(self.canvas.winfo_width(), 400) / 2,
                max(self.canvas.winfo_height(), 200) / 2,
                text="Waiting for live chart data…",
                fill=self.MUTED,
                font=(self.font_ui, 11),
            )
            return
        try:
            super()._draw_chart()
        except tk.TclError as error:
            logger.debug("Chart redraw skipped: %s", error)


def main() -> None:
    """Start the enterprise desktop event loop."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        app = EnterpriseApp()
    except tk.TclError as error:
        raise SystemExit(
            f"NEEZY requires a graphical desktop session: {error}"
        ) from error
    app.mainloop()


if __name__ == "__main__":
    main()
