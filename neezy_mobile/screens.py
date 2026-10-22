"""Tab screens for the Android app, one class per desktop NAV entry.

Ported so far: SIGNALS, CHART, SYMBOLS, HISTORY, TOOLS, SETTINGS, ALERTS,
INSIGHTS. CHAT is a placeholder until the AI client is ported to the bundle.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

from neezy_backend.alerts import METRICS, OPERATORS, AlertRule
from neezy_backend.config import AppSettings
from neezy_backend.indicators import ema
from neezy_backend.insights import insight_for, insight_line, knowledge_brief
from neezy_backend.markets import (
    DEFAULT_WATCHLIST,
    SYMBOLS,
    TIMEFRAMES,
    display_name,
    format_price,
    watchlist,
)
from neezy_backend.risk import atr_levels, position_size

from .ui_kit import (
    AMBER,
    CYAN,
    GREEN,
    MUTED,
    PANEL,
    RED,
    TEXT,
    Card,
    button,
    field,
    label,
    labelled,
    message,
    rgba,
    row,
    run_async,
    scroll_list,
    spinner,
    split_extra,
)

if TYPE_CHECKING:
    from .main import NeezyApp


def market_choices() -> dict[str, str]:
    """Display text -> Deriv symbol, sorted by name. Duplicate names get the code."""
    counts = Counter(SYMBOLS.values())
    choices: dict[str, str] = {}
    for symbol, name in sorted(SYMBOLS.items(), key=lambda item: item[1].lower()):
        key = name if counts[name] == 1 else f"{name} ({symbol})"
        choices[key] = symbol
    return choices


class BaseTab:
    name = "TAB"

    def __init__(self, app: NeezyApp) -> None:
        self.app = app
        self.view = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        self.build()

    @property
    def svc(self) -> Any:
        return self.app.services

    def build(self) -> None:
        """Create the widgets. Called once from ``__init__``."""

    def on_show(self) -> None:
        """Called every time the tab becomes visible."""


class SignalsTab(BaseTab):
    name = "SIGNALS"

    def build(self) -> None:
        self._busy = False
        self.timeframe = spinner(
            list(TIMEFRAMES), self.svc.settings.default_timeframe, size_hint_x=0.35
        )
        self.run_button = button("ANALYSE", self.run, size_hint_x=0.65)
        self.status = label("Tap ANALYSE to scan the watchlist.", MUTED, 13)
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(row(self.timeframe, self.run_button, height=44))
        self.view.add_widget(self.status)
        self.view.add_widget(self.scroll)

    def run(self, *_: Any) -> None:
        if self._busy:
            return
        self._busy = True
        timeframe = self.timeframe.text
        markets = len(self.svc.watch_symbols())
        self.run_button.text = "SCANNING…"
        self.run_button.disabled = True
        self.status.text = f"Scanning {markets} markets on {timeframe}…"
        run_async(
            lambda: self.svc.scan(timeframe),
            lambda result, error: self._finished(result, error, timeframe),
        )

    def _finished(self, result: Any, error: BaseException | None, tf: str) -> None:
        self._busy = False
        self.run_button.text = "ANALYSE"
        self.run_button.disabled = False
        self.list_box.clear_widgets()
        if error is not None:
            self.status.text = f"Scan failed: {error}"
            return
        self.status.text = f"{result.summary()} · {tf}"
        if not result.signals:
            self.list_box.add_widget(label("No setups from this pass.", MUTED))
        for signal in result.signals:
            self.list_box.add_widget(self._card(signal))

    def _card(self, signal: Any) -> Card:
        card = Card()
        colour = GREEN if signal.label == "BUY" else RED
        head = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        head.add_widget(label(signal.instrument, TEXT, 16, bold=True))
        head.add_widget(label(signal.label, colour, 16, bold=True, halign="right"))
        card.add_widget(head)
        sym = signal.symbol
        card.add_widget(
            label(
                f"Entry {format_price(sym, signal.entry)}   "
                f"SL {format_price(sym, signal.stop_loss)}   "
                f"TP {format_price(sym, signal.take_profit)}",
                TEXT,
                13,
            )
        )
        card.add_widget(
            label(
                f"Win rate {signal.win_rate:.1f}%  ·  score {signal.score:.1f}  "
                f"·  {signal.timeframe}  ·  {signal.mode}",
                MUTED,
                12,
            )
        )
        card.add_widget(
            button(
                "Open chart",
                lambda *_: self.app.open_chart(sym, signal.timeframe),
                height=36,
            )
        )
        return card


class ChartCanvas(Widget):
    """Candlesticks with EMA 20 (cyan) and EMA 50 (amber) overlays."""

    VISIBLE = 120

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.candles: list[tuple] = []
        self.bind(pos=self._draw, size=self._draw)

    def set_candles(self, candles: list[tuple]) -> None:
        self.candles = list(candles)
        self._draw()

    def _draw(self, *_: Any) -> None:
        self.canvas.clear()
        with self.canvas:
            Color(*rgba(PANEL))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        data = self.candles[-self.VISIBLE :]
        if len(data) < 2:
            return
        closes = [candle[4] for candle in self.candles]
        ema20 = ema(closes, 20)[-len(data) :]
        ema50 = ema(closes, 50)[-len(data) :]
        high = max(candle[2] for candle in data)
        low = min(candle[3] for candle in data)
        span = (high - low) or 1e-12
        pad_x, pad_y = dp(8), dp(12)
        plot_w = self.width - 2 * pad_x
        plot_h = self.height - 2 * pad_y
        step = plot_w / len(data)
        body_w = max(dp(1.5), step * 0.65)

        def px(index: int) -> float:
            return self.x + pad_x + (index + 0.5) * step

        def py(value: float) -> float:
            return self.y + pad_y + (value - low) / span * plot_h

        with self.canvas:
            for index, (_t, opened, hi, lo, closed) in enumerate(data):
                colour = GREEN if closed >= opened else RED
                x = px(index)
                Color(*rgba(colour))
                Line(points=[x, py(lo), x, py(hi)], width=dp(1))
                top = max(py(opened), py(closed))
                bottom = min(py(opened), py(closed))
                Rectangle(
                    pos=(x - body_w / 2, bottom),
                    size=(body_w, max(top - bottom, dp(1))),
                )
            for series, colour in ((ema20, CYAN), (ema50, AMBER)):
                points: list[float] = []
                for index, value in enumerate(series):
                    points += [px(index), py(value)]
                Color(*rgba(colour))
                Line(points=points, width=dp(1.1))


class ChartTab(BaseTab):
    name = "CHART"

    def build(self) -> None:
        self.choices = market_choices()
        self.key_for = {symbol: key for key, symbol in self.choices.items()}
        default_key = self.key_for.get("frxEURUSD", next(iter(self.choices)))
        self.market = spinner(list(self.choices), default_key, size_hint_x=0.5)
        self.timeframe = spinner(
            list(TIMEFRAMES), self.svc.settings.default_timeframe, size_hint_x=0.22
        )
        self.view.add_widget(
            row(
                self.market,
                self.timeframe,
                button("LOAD", self.load_clicked, size_hint_x=0.28),
            )
        )
        self.info = label("Pick a market and load candles.", MUTED, 13)
        self.chart = ChartCanvas(size_hint_y=1)
        self.view.add_widget(self.info)
        self.view.add_widget(self.chart)

    def open_symbol(self, symbol: str, timeframe: str | None = None) -> None:
        self.market.text = self.key_for.get(symbol, symbol)
        if timeframe:
            self.timeframe.text = timeframe
        self.load_clicked()

    def load_clicked(self, *_: Any) -> None:
        symbol = self.choices.get(self.market.text, self.market.text)
        timeframe = self.timeframe.text
        self.info.text = f"Loading {display_name(symbol)} · {timeframe}…"
        run_async(
            lambda: self.svc.candles(symbol, timeframe),
            lambda candles, error: self._loaded(symbol, timeframe, candles, error),
        )

    def _loaded(
        self,
        symbol: str,
        timeframe: str,
        candles: list[tuple] | None,
        error: BaseException | None,
    ) -> None:
        if error is not None or not candles:
            self.info.text = f"Load failed: {error or 'no candles returned'}"
            return
        self.chart.set_candles(candles)
        last = candles[-1]
        hi = max(candle[2] for candle in candles[-120:])
        lo = min(candle[3] for candle in candles[-120:])
        self.info.text = (
            f"{display_name(symbol)} · {timeframe} · last "
            f"{format_price(symbol, last[4])} · range "
            f"{format_price(symbol, lo)} - {format_price(symbol, hi)}"
        )


class SymbolsTab(BaseTab):
    name = "SYMBOLS"

    def build(self) -> None:
        self.search = field("Search markets")
        self.search.bind(text=lambda *_: self.refresh())
        self.count = label("", MUTED, 12)
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(self.search)
        self.view.add_widget(self.count)
        self.view.add_widget(self.scroll)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text.strip().lower()
        extra = set(split_extra(self.svc.settings.watchlist_extra))
        defaults = set(DEFAULT_WATCHLIST)
        self.list_box.clear_widgets()
        shown = 0
        for symbol, name in sorted(SYMBOLS.items(), key=lambda item: item[1].lower()):
            if query and query not in name.lower() and query not in symbol.lower():
                continue
            shown += 1
            self.list_box.add_widget(self._row(symbol, name, extra, defaults))
        self.count.text = f"{shown} market(s) · {len(watchlist(extra))} on watchlist"

    def _row(self, symbol: str, name: str, extra: set, defaults: set) -> BoxLayout:
        open_btn = button(f"{name}\n{symbol}", lambda *_: self.app.open_chart(symbol))
        if symbol in defaults:
            action: Any = label("Default", MUTED, 12, halign="center")
        elif symbol in extra:
            action = button(
                "Remove",
                lambda _b, s=symbol: self.toggle(s),
                color=RED,
                size_hint_x=0.32,
            )
        else:
            action = button(
                "Watch",
                lambda _b, s=symbol: self.toggle(s),
                color=GREEN,
                size_hint_x=0.32,
            )
        return row(open_btn, action, height=52)

    def toggle(self, symbol: str) -> None:
        extra = split_extra(self.svc.settings.watchlist_extra)
        if symbol in extra:
            extra.remove(symbol)
        else:
            extra.append(symbol)
        try:
            updated = self.svc.settings.updated(watchlist_extra=",".join(extra))
        except ValueError as error:
            message("Watchlist", str(error))
            return
        self.svc.save_settings(updated)
        self.refresh()


class HistoryTab(BaseTab):
    name = "HISTORY"

    def build(self) -> None:
        self.count = label("", MUTED, 13)
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(
            row(
                self.count,
                button("Clear", self.confirm_clear, color=RED, size_hint_x=0.3),
            )
        )
        self.view.add_widget(self.scroll)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        records = self.svc.history.read(limit=200)
        self.list_box.clear_widgets()
        self.count.text = f"{len(records)} saved signal(s)"
        if not records:
            self.list_box.add_widget(
                label("No signals yet. Run ANALYSE on the Signals tab.", MUTED)
            )
        for record in records:
            self.list_box.add_widget(self._card(record))

    def _card(self, record: dict[str, Any]) -> Card:
        card = Card()
        is_buy = record.get("direction", 0) > 0
        side = "BUY" if is_buy else "SELL"
        colour = GREEN if is_buy else RED
        symbol = str(record.get("symbol", ""))
        stamp = str(record.get("timestamp", ""))[:16].replace("T", " ")
        head = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22))
        head.add_widget(
            label(
                f"{record.get('instrument', symbol)} · {record.get('timeframe', '')}",
                TEXT,
                14,
                bold=True,
            )
        )
        head.add_widget(label(side, colour, 14, bold=True, halign="right"))
        card.add_widget(head)
        card.add_widget(
            label(
                f"Entry {format_price(symbol, record.get('entry'))}  "
                f"SL {format_price(symbol, record.get('stop_loss'))}  "
                f"TP {format_price(symbol, record.get('take_profit'))}",
                TEXT,
                12,
            )
        )
        outcome = record.get("outcome") or "open"
        card.add_widget(
            label(
                f"{stamp} · win rate {record.get('win_rate', 0)}% · outcome {outcome}",
                MUTED,
                11,
            )
        )
        return card

    def confirm_clear(self, *_: Any) -> None:
        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        body.add_widget(label("Delete all saved signal history?", TEXT, 14))
        popup = Popup(title="Clear history", content=body, size_hint=(0.85, 0.35))

        def clear_now(*_: Any) -> None:
            self.svc.history.clear()
            popup.dismiss()
            self.refresh()

        body.add_widget(
            row(
                button("Cancel", lambda *_: popup.dismiss(), color=MUTED),
                button("Delete", clear_now, color=RED),
            )
        )
        popup.open()


class ToolsTab(BaseTab):
    name = "TOOLS"

    def build(self) -> None:
        self.choices = market_choices()
        self.key_for = {symbol: key for key, symbol in self.choices.items()}
        self.market = spinner(
            list(self.choices), self.key_for.get("frxEURUSD", next(iter(self.choices)))
        )
        s = self.svc.settings
        self.balance = field("10000", f"{s.account_balance_default:g}", numeric=True)
        self.risk = field("1", f"{s.default_risk_percent:g}", numeric=True)
        self.entry = field("e.g. 1.10000", numeric=True)
        self.stop = field("e.g. 1.09800", numeric=True)
        self.size_result = label("Enter balance, risk %, entry and stop.", MUTED, 13)

        self.direction = spinner(["BUY", "SELL"], "BUY")
        self.atr_entry = field("Entry price", numeric=True)
        self.atr_value = field("ATR value", numeric=True)
        self.atr_mult = field("1.5", f"{s.confluence_atr_stop_mult:g}", numeric=True)
        self.atr_rr = field("2.0", f"{s.default_reward_to_risk:g}", numeric=True)
        self.levels_result = label("ATR stop and target appear here.", MUTED, 13)

        self.scroll, self.list_box = scroll_list(spacing=10)
        for widget in (
            labelled("Market", self.market),
            labelled("Balance", self.balance),
            labelled("Risk %", self.risk),
            labelled("Entry", self.entry),
            labelled("Stop", self.stop),
            button("CALCULATE SIZE", self.calc_size),
            self.size_result,
            labelled("Direction", self.direction),
            labelled("ATR entry", self.atr_entry),
            labelled("ATR value", self.atr_value),
            labelled("Stop x ATR", self.atr_mult),
            labelled("Reward : risk", self.atr_rr),
            button("CALCULATE ATR LEVELS", self.calc_levels),
            self.levels_result,
        ):
            self.list_box.add_widget(widget)
        self.view.add_widget(self.scroll)

    def calc_size(self, *_: Any) -> None:
        symbol = self.choices.get(self.market.text, self.market.text)
        try:
            plan = position_size(
                symbol=symbol,
                balance=float(self.balance.text),
                risk_percent=float(self.risk.text),
                entry=float(self.entry.text),
                stop=float(self.stop.text),
                reward_to_risk=2.0,
            )
        except (ValueError, ZeroDivisionError, TypeError) as error:
            self.size_result.text = f"Check inputs: {error}"
            return
        self.size_result.text = (
            f"{plan.direction} · {plan.lots} lots · {plan.units} units\n"
            f"Target {format_price(symbol, plan.target)} · "
            f"risk {plan.risk_amount:.2f} · reward {plan.reward_amount:.2f}\n"
            f"Stop {plan.stop_pips:.1f} pips · target {plan.target_pips:.1f} pips\n"
            "Pip value assumes 10 per lot (USD-quoted pair, USD account)."
        )

    def calc_levels(self, *_: Any) -> None:
        symbol = self.choices.get(self.market.text, self.market.text)
        try:
            stop, target = atr_levels(
                self.direction.text,
                float(self.atr_entry.text),
                float(self.atr_value.text),
                stop_multiple=float(self.atr_mult.text),
                reward_to_risk=float(self.atr_rr.text),
            )
        except (ValueError, ZeroDivisionError, TypeError) as error:
            self.levels_result.text = f"Check inputs: {error}"
            return
        self.levels_result.text = (
            f"{self.direction.text} · stop {format_price(symbol, stop)} · "
            f"target {format_price(symbol, target)}"
        )


class SettingsTab(BaseTab):
    name = "SETTINGS"

    def build(self) -> None:
        self.scroll, self.list_box = scroll_list(spacing=10)
        self.view.add_widget(self.scroll)

    def on_show(self) -> None:
        self._form(self.svc.settings)

    def _form(self, settings: AppSettings) -> None:
        from neezy_backend.config import SETTINGS_PROFILES, STRATEGIES

        self.list_box.clear_widgets()
        self.profile = spinner(
            ["(keep current)", *sorted(SETTINGS_PROFILES)], "(keep current)"
        )
        self.timeframe = spinner(list(TIMEFRAMES), settings.default_timeframe)
        self.strategy = spinner(list(STRATEGIES), settings.strategy)
        self.history_candles = field(
            "60-1000", str(settings.history_candles), numeric=True
        )
        self.min_score = field(
            "0-100", str(settings.confluence_min_score), numeric=True
        )
        self.risk_pct = field(
            "0.1-100", str(settings.default_risk_percent), numeric=True
        )
        self.reward_rr = field(
            "0.5-20", str(settings.default_reward_to_risk), numeric=True
        )
        self.alert_min = field("1-4", str(settings.alert_min_score), numeric=True)
        self.quiet_start = field("HH:MM", settings.quiet_hours_start)
        self.quiet_end = field("HH:MM", settings.quiet_hours_end)
        self.fetch_timeout = field(
            "1-120", str(settings.ml_fetch_timeout), numeric=True
        )
        self.endpoint = field("empty = default Deriv endpoint", settings.deriv_endpoint)
        self.extra = field("e.g. R_100,frxAUDUSD", settings.watchlist_extra)
        self.status = label("", MUTED, 12)
        for widget in (
            labelled("Preset profile", self.profile),
            labelled("Default timeframe", self.timeframe),
            labelled("Active strategy", self.strategy),
            labelled("History candles", self.history_candles),
            labelled("Min confluence", self.min_score),
            labelled("Risk per trade (%)", self.risk_pct),
            labelled("Reward : risk", self.reward_rr),
            labelled("Min alert score (1-4)", self.alert_min),
            labelled("Quiet hours start", self.quiet_start),
            labelled("Quiet hours end", self.quiet_end),
            labelled("Fetch timeout (s)", self.fetch_timeout),
            labelled("Deriv endpoint", self.endpoint),
            labelled("Extra markets", self.extra),
            button("SAVE SETTINGS", self.save),
            self.status,
            label(
                "Desktop-only in this build: MT5 bridge, local GGUF/transformer "
                "models, MCP server, Telegram and hosted AI key pools.",
                MUTED,
                12,
            ),
        ):
            self.list_box.add_widget(widget)

    def save(self, *_: Any) -> None:
        try:
            base = self.svc.settings
            if self.profile.text and self.profile.text != "(keep current)":
                base = base.apply_profile(self.profile.text)
            updated = base.updated(
                default_timeframe=self.timeframe.text,
                strategy=self.strategy.text,
                history_candles=int(self.history_candles.text),
                confluence_min_score=float(self.min_score.text),
                default_risk_percent=float(self.risk_pct.text),
                default_reward_to_risk=float(self.reward_rr.text),
                alert_min_score=int(float(self.alert_min.text)),
                quiet_hours_start=self.quiet_start.text.strip(),
                quiet_hours_end=self.quiet_end.text.strip(),
                ml_fetch_timeout=float(self.fetch_timeout.text),
                deriv_endpoint=self.endpoint.text.strip(),
                watchlist_extra=self.extra.text.strip(),
            )
            watchlist(updated.watchlist_extra)
        except (ValueError, TypeError) as error:
            self.status.text = f"Not saved: {error}"
            return
        self.svc.save_settings(updated)
        self._form(updated)
        self.status.text = "Saved."


class PlaceholderTab(BaseTab):
    text = ""

    def build(self) -> None:
        self.view.add_widget(label(self.text, MUTED, 14))


class AlertsTab(BaseTab):
    name = "ALERTS"

    def build(self) -> None:
        self.rules: list[AlertRule] = self.svc.alerts.load()
        symbols = list(self.svc.watch_symbols())
        self.symbol = spinner(["*", *symbols], "*", size_hint_x=0.3)
        self.metric = spinner(list(METRICS), "price", size_hint_x=0.35)
        self.operator = spinner(list(OPERATORS), ">", size_hint_x=0.35)
        self.value = field("value, e.g. 1.1000 or a pattern name")
        self.note = field("note (optional)")
        self.status = label(
            "Rules are saved on this device. Firing runs on the desktop app for now.",
            MUTED,
            12,
        )
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(row(self.symbol, self.metric, self.operator))
        self.view.add_widget(self.value)
        self.view.add_widget(self.note)
        self.view.add_widget(button("Add rule", self.add_rule, height=44))
        self.view.add_widget(self.status)
        self.view.add_widget(self.scroll)
        self.refresh()

    def add_rule(self, *_: Any) -> None:
        try:
            rule = AlertRule(
                symbol=self.symbol.text,
                metric=self.metric.text,
                operator=self.operator.text,
                value=self.value.text.strip(),
                note=self.note.text.strip(),
            )
        except (ValueError, TypeError) as error:
            self.status.text = f"Not saved: {error}"
            return
        self.rules = [*self.rules, rule]
        self.svc.alerts.save(self.rules)
        self.value.text = ""
        self.note.text = ""
        self.status.text = f"Added {rule.describe()}"
        self.refresh()

    def _replace(self, rule_id: str, **changes: Any) -> None:
        self.rules = [
            replace(rule, **changes) if rule.rule_id == rule_id else rule
            for rule in self.rules
        ]
        self.svc.alerts.save(self.rules)
        self.refresh()

    def delete(self, rule_id: str) -> None:
        self.rules = [rule for rule in self.rules if rule.rule_id != rule_id]
        self.svc.alerts.save(self.rules)
        self.refresh()

    def refresh(self) -> None:
        self.list_box.clear_widgets()
        if not self.rules:
            self.list_box.add_widget(label("No alert rules yet.", MUTED))
        for rule in self.rules:
            self.list_box.add_widget(self._card(rule))

    def _card(self, rule: AlertRule) -> Card:
        card = Card()
        colour = GREEN if rule.enabled else MUTED
        head = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        head.add_widget(label(rule.describe(), TEXT, 14, bold=True))
        head.add_widget(
            label(
                "ON" if rule.enabled else "OFF", colour, 13, bold=True, halign="right"
            )
        )
        card.add_widget(head)
        if rule.note:
            card.add_widget(label(rule.note, MUTED, 12))
        card.add_widget(
            row(
                button(
                    "Disable" if rule.enabled else "Enable",
                    lambda *_: self._replace(rule.rule_id, enabled=not rule.enabled),
                    height=36,
                ),
                button(
                    "Delete",
                    lambda *_: self.delete(rule.rule_id),
                    color=RED,
                    height=36,
                ),
                height=40,
            )
        )
        return card


class InsightsTab(BaseTab):
    name = "INSIGHTS"

    def build(self) -> None:
        symbols = list(self.svc.watch_symbols())
        self.symbol = spinner(symbols, symbols[0], size_hint_x=0.6)
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(
            row(self.symbol, button("Show", self.refresh, size_hint_x=0.4))
        )
        self.view.add_widget(self.scroll)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self, *_: Any) -> None:
        self.list_box.clear_widgets()
        try:
            brief = knowledge_brief()
        except Exception as error:  # noqa: BLE001 - shown in the UI, never crashes
            self.list_box.add_widget(label(f"Knowledge base unavailable: {error}", RED))
            return
        self.list_box.add_widget(self._knowledge_card(brief))
        self.list_box.add_widget(self._symbol_card(self.symbol.text))

    def _knowledge_card(self, brief: dict[str, Any]) -> Card:
        card = Card()
        card.add_widget(label("Knowledge base", TEXT, 15, bold=True))
        rows = (
            ("Datasets", ", ".join(map(str, brief["datasets"])) or "none"),
            ("Weighted symbols", str(brief["weighted_symbols"])),
            ("Indicators", ", ".join(map(str, brief["indicators"])) or "none"),
            ("Patterns", ", ".join(map(str, brief["patterns"])) or "none"),
            ("Strategies", ", ".join(map(str, brief["strategies"])) or "none"),
        )
        for title, value in rows:
            card.add_widget(label(f"{title}: {value}", MUTED, 12))
        return card

    def _symbol_card(self, symbol: str) -> Card:
        card = Card()
        card.add_widget(label(display_name(symbol), TEXT, 15, bold=True))
        line = insight_line(symbol)
        if line is None:
            card.add_widget(label(f"No learned weight for {symbol} yet.", MUTED, 12))
            return card
        card.add_widget(label(line, TEXT, 12))
        insight = insight_for(symbol) or {}
        card.add_widget(label(str(insight.get("caveat", "")), MUTED, 11))
        return card


class ChatTab(BaseTab):
    name = "CHAT"

    def build(self) -> None:
        from neezy_backend.analytics import rank_opportunities

        self._rank = rank_opportunities
        self.prompt = field("Ask about active setups, trend, RSI, or risk…")
        self.scroll, self.list_box = scroll_list()
        self.view.add_widget(
            row(self.prompt, button("Ask", self.ask, size_hint_x=0.28, height=44))
        )
        self.view.add_widget(self.scroll)
        self._append(
            "NEEZY Copilot",
            "Ask about top setups, trend, RSI, or any watched market using live data.",
            MUTED,
        )

    def _append(self, author: str, body: str, colour: Any = TEXT) -> None:
        card = Card()
        card.add_widget(
            label(author, CYAN if author != "YOU" else MUTED, 12, bold=True)
        )
        card.add_widget(label(body, colour, 13))
        self.list_box.add_widget(card)

    def ask(self, *_: Any) -> None:
        q = self.prompt.text.strip()
        if not q:
            return
        self.prompt.text = ""
        self._append("YOU", q, TEXT)
        low = q.lower()
        results = getattr(self.svc, "results", {}) or {}
        if any(w in low for w in ("best", "top", "rank", "strongest")):
            ranked = self._rank(results)[:3]
            reply = (
                "Strongest current setups: "
                + "; ".join(
                    f"{display_name(i['symbol'])} {i['signal']} "
                    f"({i['opportunity']:.0f})"
                    for i in ranked
                )
                if ranked
                else "No directional setup ready yet — stream candles in SYMBOLS first."
            )
            self._append("NEEZY", reply, TEXT)
            return
        chosen = self.svc.selected
        for sym in self.svc.watch_symbols():
            if sym.lower() in low or display_name(sym).lower() in low:
                chosen = sym
                break
        res = results.get(chosen)
        if not res:
            self._append(
                "NEEZY",
                f"{display_name(chosen)} is still collecting closed candles.",
                MUTED,
            )
            return
        self._append(
            "NEEZY",
            f"{display_name(chosen)}: {res['signal']} (score {res['score']:+d}/4, "
            f"{res['trend'].lower()} trend, RSI {res['rsi']:.1f}, "
            f"ATR {res['atr_pct']:.2f}%). Educational summary only.",
            TEXT,
        )


TAB_CLASSES = (
    ChatTab,
    SymbolsTab,
    ChartTab,
    SignalsTab,
    InsightsTab,
    ToolsTab,
    AlertsTab,
    HistoryTab,
    SettingsTab,
)
