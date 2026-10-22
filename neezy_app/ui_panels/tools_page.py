"""Tools page panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import threading
import tkinter as tk

from neezy_backend.backtest import BacktestConfig, run_backtest
from neezy_backend.markets import (
    SYMBOLS,
    ws_urls,
)
from neezy_backend.risk import atr_levels, position_size
from neezy_backend.stream import fetch_candles

logger = logging.getLogger(__name__)


class ToolsPageMixin:
    """Methods for the tools page screen; mixed into App."""

    def _tools_page(self):
        page = self.pages["TOOLS"]
        self._label(page, "Trader toolkit", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page,
            "Risk planning, walk-forward backtests, and cross-market ranking "
            "for the selected market.",
            10,
            self.MUTED,
        ).pack(anchor="w", pady=(0, 14))
        grid = tk.Frame(page, bg=self.BG)
        grid.pack(fill="both", expand=True)
        risk, test, rank = self._panel(grid), self._panel(grid), self._panel(grid)
        for index, panel in enumerate((risk, test, rank)):
            panel.pack(
                side="left", fill="both", expand=True, padx=(0 if index == 0 else 6, 0)
            )

        self._label(risk, "RISK PLANNER", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.risk_vars = {
            "balance": tk.StringVar(value=f"{self.settings.account_balance_default:g}"),
            "risk": tk.StringVar(value=f"{self.settings.default_risk_percent:g}"),
            "stop_atr": tk.StringVar(
                value=f"{self.settings.confluence_atr_stop_mult:g}"
            ),
            "reward": tk.StringVar(value=f"{self.settings.default_reward_to_risk:g}"),
            "pip_value": tk.StringVar(
                value=f"{self.settings.default_pip_value_per_lot:g}"
            ),
        }
        for key, label in [
            ("balance", f"Account balance ({self.settings.account_currency})"),
            ("risk", "Risk per trade (%)"),
            ("stop_atr", "Stop distance (x ATR)"),
            ("reward", "Reward : risk"),
            ("pip_value", "Pip value / lot"),
        ]:
            self._field(risk, label, self.risk_vars[key])
        self._action_button(risk, "Plan selected market", self._plan_risk)
        self.risk_out = self._output(risk)

        self._label(test, "BACKTEST", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.test_vars = {
            "min_score": tk.StringVar(value=str(self.settings.alert_min_score)),
            "stop_atr": tk.StringVar(
                value=f"{self.settings.confluence_atr_stop_mult:g}"
            ),
            "reward": tk.StringVar(value=f"{self.settings.default_reward_to_risk:g}"),
            "count": tk.StringVar(value="2000"),
        }
        for key, label in [
            ("min_score", "Min score (1-4)"),
            ("stop_atr", "Stop (x ATR)"),
            ("reward", "Reward : risk"),
            ("count", "History candles"),
        ]:
            self._field(test, label, self.test_vars[key])
        buttons = tk.Frame(test, bg=test.cget("bg"))
        buttons.pack(fill="x")
        self._action_button(buttons, "Run on live buffer", self._backtest_buffer)
        self.fetch_button = self._action_button(
            buttons, "Fetch history & run", self._backtest_fetch
        )
        self.test_out = self._output(test)

        self._label(rank, "MARKET RANKING", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self._action_button(rank, "Refresh ranking", self._refresh_ranking)
        self.rank_out = self._output(rank, height=20)

    def _float_var(self, variables, key, label):
        try:
            return float(variables[key].get())
        except ValueError:
            raise ValueError(f"{label} must be a number") from None

    def _plan_risk(self):
        symbol, result = self.selected, self.results.get(self.selected)
        candles = self.candles.get(symbol, [])
        if not result or not candles or not result.get("atr"):
            self._write(self.risk_out, "Waiting for enough closed candles…")
            return
        try:
            direction = "SELL" if "SELL" in result["signal"] else "BUY"
            entry = candles[-1][4]
            stop, _target = atr_levels(
                direction,
                entry,
                result["atr"],
                self._float_var(self.risk_vars, "stop_atr", "Stop multiple"),
            )
            risk_pct = self._float_var(self.risk_vars, "risk", "Risk")
            plan = position_size(
                symbol=symbol,
                balance=self._float_var(self.risk_vars, "balance", "Balance"),
                risk_percent=risk_pct,
                entry=entry,
                stop=stop,
                reward_to_risk=self._float_var(self.risk_vars, "reward", "Reward"),
                pip_value_per_lot=self._float_var(
                    self.risk_vars, "pip_value", "Pip value"
                ),
            )
        except ValueError as error:
            self._write(self.risk_out, f"Check inputs: {error}")
            return
        f = lambda price: self._fmt(symbol, price)  # noqa: E731
        bias = "" if result["signal"] != "NEUTRAL" else " (neutral bias, long shown)"
        guardrail = ""
        if risk_pct > self.settings.max_drawdown_limit:
            lim = self.settings.max_drawdown_limit
            guardrail = f"\n⚠ Exceeds max drawdown limit ({lim:g}%)!"
        elif risk_pct > self.settings.daily_max_loss_percent:
            lim = self.settings.daily_max_loss_percent
            guardrail = f"\n⚠ Exceeds daily max loss cap ({lim:g}%)!"
        cur = self.settings.account_currency
        self._write(
            self.risk_out,
            f"{SYMBOLS[symbol]} · {plan.direction}{bias}\n\n"
            f"Entry   {f(plan.entry)}\n"
            f"Stop    {f(plan.stop)}  ({plan.stop_pips:.1f} pips)\n"
            f"Target  {f(plan.target)}  ({plan.target_pips:.1f} pips)\n\n"
            f"Size    {plan.lots:.2f} lots\n"
            f"Units   {plan.units:,}\n"
            f"Risk    {plan.risk_amount:,.2f} {cur}\n"
            f"Reward  {plan.reward_amount:,.2f} {cur}{guardrail}\n\n"
            "Planning aid only; verify with your broker.",
        )

    def _backtest_config(self):
        return BacktestConfig(
            min_score=int(self._float_var(self.test_vars, "min_score", "Min score")),
            stop_atr_multiple=self._float_var(self.test_vars, "stop_atr", "Stop"),
            reward_to_risk=self._float_var(self.test_vars, "reward", "Reward"),
        )

    def _backtest_buffer(self):
        candles = self.candles.get(self.selected, [])[:-1]
        try:
            result = run_backtest(candles, self._backtest_config())
        except ValueError as error:
            self._write(self.test_out, f"Check inputs: {error}")
            return
        self._show_backtest(self.selected, self.tf.get(), result)

    def _backtest_fetch(self):
        if self._backtest_running:
            return
        try:
            config = self._backtest_config()
            count = int(self._float_var(self.test_vars, "count", "Candles"))
            if not 100 <= count <= 5000:
                raise ValueError("History candles must be between 100 and 5000")
        except ValueError as error:
            self._write(self.test_out, f"Check inputs: {error}")
            return
        symbol, timeframe, seconds = self.selected, self.tf.get(), self.gran
        endpoints = ws_urls(self.settings.deriv_endpoint)
        self._backtest_running = True
        self.fetch_button.config(state="disabled")
        self._write(self.test_out, f"Fetching {count} {timeframe} candles…")

        def work():
            try:
                candles = fetch_candles(symbol, seconds, count, url=endpoints)
                result = run_backtest(candles[:-1], config)
                self.bus.publish("backtest", (symbol, timeframe, result))
            except (OSError, RuntimeError, ValueError) as error:
                self.bus.publish("backtest_error", str(error))
            except Exception as error:
                logger.exception("Backtest worker failed")
                self.bus.publish("backtest_error", str(error))

        threading.Thread(target=work, name="neezy-backtest", daemon=True).start()

    def _show_backtest(self, symbol, timeframe, result):
        stats = result.stats
        if not stats["trades"]:
            self._write(
                self.test_out,
                f"No trades in {stats['candles_tested']} candles. Load more "
                "history or lower the minimum score.",
            )
            return
        pf = stats["profit_factor"]
        recent = "\n".join(
            f"  {t.direction:<4} {t.reason:<15} {t.r_multiple:+.2f}R"
            for t in result.trades[-6:]
        )
        spread = self.settings.backtest_default_spread_pips
        spread_line = ""
        if spread > 0:
            net_r = stats["total_r"] - stats["trades"] * (spread * 0.05)
            spread_line = f"Net ({spread:g}p)  {net_r:+.2f} R\n"
        self._write(
            self.test_out,
            f"{SYMBOLS[symbol]} · {timeframe} · {stats['candles_tested']} candles\n\n"
            f"Trades        {stats['trades']} "
            f"({stats['long_trades']}L/{stats['short_trades']}S)\n"
            f"Win rate      {stats['win_rate']:.1f}%\n"
            f"Total         {stats['total_r']:+.2f} R\n"
            f"{spread_line}"
            f"Expectancy    {stats['expectancy_r']:+.3f} R\n"
            f"Profit factor {'inf' if pf == float('inf') else f'{pf:.2f}'}\n"
            f"Max drawdown  {stats['max_drawdown_r']:.2f} R\n"
            f"Sharpe/trade  {stats['sharpe_per_trade']:.2f}\n\n"
            f"Recent trades\n{recent}\n\n"
            "Simulated; past results do not predict future results.",
        )
