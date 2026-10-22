"""Insights panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import sqlite3
import threading
import tkinter as tk

from neezy_backend.analytics import (
    correlation_matrix,
    rank_opportunities,
    strongest_pairs,
)
from neezy_backend.brain import train_model as train_brain_model
from neezy_backend.datasets import model_weights, research_report, shipped_brain_model
from neezy_backend.insights import knowledge_brief
from neezy_backend.markets import (
    SYMBOLS,
)
from neezy_backend.research import DEFAULT_RESEARCH_SYMBOLS, pair_research, training_run
from neezy_backend.storage import (
    get_data_dir,
)
from neezy_backend.strategies import (
    STRATEGIES,
    consensus,
    run_all,
)

logger = logging.getLogger(__name__)


class InsightsMixin:
    """Methods for the insights screen; mixed into App."""

    def _insights_page(self):
        p = self.pages["INSIGHTS"]
        bar = tk.Frame(p, bg=self.BG)
        bar.pack(fill="x", pady=(5, 12))
        self._label(bar, "Dataset insights", 16).pack(side="left")
        self._label(
            bar,
            "What the shipped knowledge datasets and learned weights say.",
            10,
            self.MUTED,
        ).pack(side="left", padx=12)
        self.insights_output = self._output(p, height=8)
        self._action_button(p, "REFRESH INSIGHTS", self._refresh_insights)
        self._combo_row(
            p,
            "ML research market (DSI: history-only access verified)",
            self.research_market_var,
            list(DEFAULT_RESEARCH_SYMBOLS),
        )
        self._action_button(
            p, "TRAIN RESEARCH MARKET ON FRESH PUBLIC DATA", self._train_live_research
        )
        self._combo_row(
            p,
            "FX comparison leg",
            self.pair_reference_var,
            [symbol for symbol in SYMBOLS if symbol.startswith("frx")],
        )
        self._action_button(p, "RESEARCH SELECTED FX PAIR", self._research_fx_pair)
        self.research_status_label = self._label(
            p, "Ready · research only", 10, self.MUTED
        )
        self.research_status_label.pack(anchor="w", padx=16, pady=6)
        self._refresh_insights()

    def _get_brain_model(self, symbol, timeframe):
        model = (
            self.db.get_value(f"brain:model:{symbol}:{timeframe}") if self.db else None
        )
        return (
            model if isinstance(model, dict) else shipped_brain_model(symbol, timeframe)
        )

    def _train_live_research(self):
        if self._research_running:
            return
        self._research_running = True
        symbol = self.research_market_var.get()
        timeframe, settings = self.tf.get(), self.settings
        self.research_status_label.config(text=f"Fetching and training {symbol}…")

        def work():
            try:
                path = get_data_dir() / "research" / f"{symbol}-{timeframe}.json"
                result = training_run(
                    [symbol],
                    timeframe=timeframe,
                    settings=settings,
                    checkpoint=str(path),
                )
                record = result["symbols"][symbol]
                if record["status"] != "trained":
                    raise ValueError(record["error"])
                if self.db:
                    self.db.set_value(
                        f"brain:model:{symbol}:{timeframe}", record["model"]
                    )
                metrics = record["report"]["test"]
                score = metrics.get("balanced_accuracy")
                message = (
                    f"{symbol}: {record['candles']} fresh candles, "
                    f"test balanced accuracy {score}, "
                    f"qualified={record['report']['deployment_ready']}. Research only."
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                message = f"Research unavailable: {error}"
            self.after(0, lambda text=message: self._finish_live_research(text))

        threading.Thread(target=work, name="neezy-public-ml", daemon=True).start()

    def _finish_live_research(self, message):
        self._research_running = False
        self.research_status_label.config(text=message)

    def _research_fx_pair(self):
        left, right = self.selected, self.pair_reference_var.get()
        if not left.startswith("frx") or left == right:
            self.research_status_label.config(
                text="Select two distinct Forex markets first."
            )
            return
        if self.db is None:
            self.research_status_label.config(text="Local database is unavailable.")
            return
        try:
            rows = [
                self.db.load_candles(
                    symbol, self.tf.get(), limit=self.settings.ml_history_candles
                )
                for symbol in (left, right)
            ]
            result = pair_research(*rows, settings=self.settings)
            result.pop("path")
            self._write(
                self.insights_output,
                f"{left} vs {right} (saved closed candles)\n"
                + "\n".join(f"{key}: {value}" for key, value in result.items()),
            )
        except (sqlite3.Error, ValueError) as error:
            self.research_status_label.config(
                text=f"Pair research unavailable: {error}"
            )

    def _refresh_insights(self):
        """Render a read-only digest of the shipped knowledge datasets."""
        try:
            brief = knowledge_brief()
            weights = model_weights()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self._write(self.insights_output, f"Could not load datasets: {error}")
            return
        lines = [
            "SHIPPED KNOWLEDGE DATASETS",
            "  " + ", ".join(brief.get("datasets", [])),
            "",
            "INDICATORS COVERED",
        ]
        names = brief.get("indicators", [])
        for start in range(0, len(names), 6):
            lines.append("  " + ", ".join(names[start : start + 6]))
        lines += [
            "",
            "PATTERNS: " + ", ".join(brief.get("patterns", [])),
            "",
            "NAMED STRATEGIES: " + ", ".join(brief.get("strategies", [])),
            "",
            f"LEARNED WEIGHTS: {brief.get('weighted_symbols', 0)} symbols "
            "with out-of-sample edge weights.",
            "",
            "SYMBOL LEAN (edge weight from past-candle studies; not a forecast)",
        ]
        leans = []
        for symbol, record in weights.get("symbols", {}).items():
            weight = record.get("edge_weight", 0.0)
            if weight > 0.15 or weight < -0.15:
                leans.append(
                    (
                        weight,
                        f"  {symbol:<12} {weight:+.2f}  "
                        f"({record.get('verdict', 'unknown')})",
                    )
                )
        if leans:
            lines += [
                text
                for _, text in sorted(leans, reverse=True)[
                    : self.settings.insights_max_rows
                ]
            ]
        else:
            lines.append("  No strong weights learned yet.")
        lines += [
            "",
            "Backtests use historical candles with a charged spread; "
            "out-of-sample for that window only. Not financial advice.",
        ]
        report = research_report()
        lines += [
            "",
            "FRESH PUBLIC-DATA ML (chronological test, directional accuracy only)",
        ]
        for symbol, record in list(report.get("symbols", {}).items())[
            : self.settings.insights_max_rows
        ]:
            metrics = record.get("report", {}).get("test", {})
            lines.append(
                f"  {symbol}: balanced accuracy={metrics.get('balanced_accuracy')}, "
                f"qualified={record.get('report', {}).get('deployment_ready', False)}"
            )
        lines.append("FX pair simulations include assumed costs, not broker fills.")
        for pair, result in report.get("forex_pairs", {}).items():
            lines.append(f"  {pair}: net log return={result.get('net_log_return')}")
        self._write(self.insights_output, "\n".join(lines))

    def _refresh_ranking(self):
        if not self.results:
            self._write(self.rank_out, "Collecting live candles…")
            return
        lines = ["TOP SETUPS"]
        for item in rank_opportunities(self.results, include_neutral=True):
            lines.append(
                f"  {SYMBOLS[item['symbol']]:<15}{item['signal']:<12}"
                f"{item['opportunity']:>5.1f}"
            )
        closes = {s: [row[4] for row in c[:-1]] for s, c in self.candles.items()}
        win = self.settings.correlation_window
        base_win = self.settings.correlation_baseline
        short_mat = correlation_matrix(closes, window=win)
        base_mat = correlation_matrix(closes, window=base_win)
        pairs = strongest_pairs(short_mat, limit=6)
        lines.append(f"\nSTRONGEST CORRELATIONS (w={win} vs base={base_win})")
        for a, b, value in pairs:
            base_val = (base_mat.get(a) or {}).get(b)
            delta = (
                f" (Δ {value - base_val:+.2f})"
                if isinstance(base_val, (int, float))
                else ""
            )
            lines.append(f"  {SYMBOLS[a]} / {SYMBOLS[b]}  {value:+.2f}{delta}")
        lines.append("\nRank 0-100 blends score, ADX, and RSI room.")
        self._write(self.rank_out, "\n".join(lines))

    def _strategy_name(self):
        raw = self.strategy_var.get()
        return raw.split("·")[0].strip() or "SUPERTREND"

    def _strategy_description(self):
        spec = STRATEGIES.get(self._strategy_name())
        if spec is None:
            return ""
        return f"{spec.label}: {spec.description}"

    def _strategy_changed(self):
        if hasattr(self, "strategy_help"):
            self.strategy_help.config(text=self._strategy_description())
        self._settings_changed()

    def _scan_strategies(self):
        candles = self.candles.get(self.selected, [])
        if len(candles) < 40:
            self._write(
                self.engine_out,
                f"{SYMBOLS[self.selected]} is still collecting closed candles.",
            )
            return
        signals = run_all(candles)
        verdict = consensus(signals)
        lines = [
            f"{SYMBOLS[self.selected]} · {self.tf.get()} · {len(candles)} candles",
            "",
        ]
        for signal in signals:
            lines.append(
                f"{signal.strategy:<14} {signal.label:<8} "
                f"{signal.confidence:>5.0f}%  {signal.summary}"
            )
        lines.append("")
        lines.append(
            f"Consensus {verdict['label']} ({verdict['confidence']:.0f}%) "
            f"- buy {verdict['votes']['buy']}, sell {verdict['votes']['sell']}, "
            f"neutral {verdict['votes']['neutral']}"
        )
        self._write(self.engine_out, "\n".join(lines))

    def _train_brain(self):
        if self._brain_training:
            return
        if self.db is None:
            self.brain_status_label.config(
                text="Local database is unavailable.", fg=self.RED
            )
            return
        symbol, timeframe = self.selected, self.tf.get()
        try:
            candles = self.db.load_candles(
                symbol, timeframe, limit=self.settings.ml_history_candles
            )
        except sqlite3.Error as error:
            self.brain_status_label.config(
                text=f"Could not read saved candles: {error}", fg=self.RED
            )
            return
        if len(candles) < 300:
            self.brain_status_label.config(
                text=(
                    f"Only {len(candles)} candles saved for {symbol} {timeframe}; "
                    "keep local candle storage on and collect more."
                ),
                fg=self.MUTED,
            )
            return
        self._brain_training = True
        arch = self.settings.ml_model_architecture
        self.brain_status_label.config(
            text=(f"Training {arch} research model on {len(candles)} saved candles…"),
            fg=self.MUTED,
        )

        def work():
            try:
                model_type_map = {
                    "v1": "neezy_mlp_v1",
                    "ensemble": "neezy_mlp_ensemble_v1",
                    "sequence": "neezy_seq_mlp_v1",
                }
                trained = train_brain_model(
                    candles,
                    symbol=symbol,
                    timeframe=timeframe,
                    horizon=self.settings.ml_horizon,
                    deadband_atr=self.settings.ml_deadband_atr,
                    min_samples=self.settings.ml_min_samples,
                    epochs=self.settings.ml_epochs,
                    seed=self.settings.ml_seed,
                    model_type=model_type_map.get(arch, "neezy_mlp_v1"),
                    members=self.settings.ml_ensemble_members,
                    window=self.settings.ml_sequence_window,
                )
                self.db.set_value(f"brain:model:{symbol}:{timeframe}", trained["model"])
                report = trained["report"]
                metrics = report["test"]
                accuracy = metrics.get("balanced_accuracy")
                message = (
                    f"{symbol} {timeframe} ({arch}): {report['labeled_examples']} "
                    "labeled examples · "
                    f"{metrics['samples']} untouched test samples · balanced accuracy "
                    f"{accuracy:.1%}"
                    if accuracy is not None
                    else (
                        f"{symbol} {timeframe}: model trained; "
                        "held-out score unavailable."
                    )
                )
                message += (
                    " · validated candidate"
                    if report["deployment_ready"]
                    else " · research-only; not validated"
                )
                color = self.GREEN if report["deployment_ready"] else "#f0bd62"
            except Exception as error:
                logger.exception("Local neural training failed")
                message, color = f"Training unavailable: {error}", self.RED
            self.after(0, lambda: self._finish_brain_training(message, color))

        threading.Thread(target=work, name="neezy-brain-train", daemon=True).start()

    def _finish_brain_training(self, message, color):
        self._brain_training = False
        self.brain_status_label.config(text=message, fg=color)
