"""Remote panels for the NEEZY desktop window."""

from __future__ import annotations

from typing import Any

from neezy_backend.alerts import (
    AlertRule,
)
from neezy_backend.brain import predict as predict_brain
from neezy_backend.context import market_snapshot
from neezy_backend.knowledge import load_knowledge
from neezy_backend.markets import (
    SYMBOLS,
)
from neezy_backend.strategies import (
    STRATEGIES,
    consensus,
    run_all,
)


class RemoteMixin:
    """Methods for the remote screen; mixed into App."""

    def _remote_market_candles(self, symbol, timeframe):
        if symbol == self.selected and timeframe == self.tf.get():
            candles = list(self.candles.get(symbol, []))
        else:
            candles = (
                self.db.load_candles(symbol, timeframe, limit=2000)
                if self.db is not None
                else []
            )
        if len(candles) < 61:
            raise ValueError(
                f"not enough locally saved candles for {symbol} {timeframe}; "
                "wait for the live feed and keep candle storage enabled"
            )
        return candles

    def _remote_settings(self):
        fields = (
            "auto_refresh",
            "alerts_enabled",
            "compact_mode",
            "theme",
            "polling_ms",
            "candle_limit",
            "alert_min_score",
            "retention_days",
            "store_candles",
            "save_snapshots",
            "default_timeframe",
            "strategy",
            "show_strategy_overlay",
            "use_knowledge",
            "use_memory",
            "use_brain_model",
        )
        return {field: getattr(self.settings, field) for field in fields}

    def _handle_remote_command(self, action, arguments):
        if action == "app_status":
            current = self.results.get(self.selected) or {}
            return {
                "app": "NEEZY",
                "connection": self.conn.cget("text")
                if hasattr(self, "conn")
                else "unknown",
                "last_market_update": self.last_message_at,
                "selected_symbol": self.selected,
                "timeframe": self.tf.get(),
                "tracked_markets": len(self.candles),
                "current_signal": current.get("signal", "unavailable"),
                "signal_score": current.get("score"),
                "trade_execution": False,
            }
        if action == "get_app_settings":
            return self._remote_settings()
        if action == "analyze_market":
            symbol, timeframe = arguments["symbol"], arguments["timeframe"]
            candles = self._remote_market_candles(symbol, timeframe)
            brain = None
            if self.settings.use_brain_model:
                model = self._get_brain_model(symbol, timeframe)
                if isinstance(model, dict):
                    brain = predict_brain(
                        candles, model, minimum_probability=self.settings.ml_probability
                    )
            return market_snapshot(
                candles,
                symbol=symbol,
                timeframe=timeframe,
                strategy=self.settings.strategy,
                supertrend_period=self.settings.supertrend_period,
                supertrend_multiplier=self.settings.supertrend_multiplier,
                divergence_lookback=self.settings.divergence_lookback,
                knowledge=load_knowledge() if self.settings.use_knowledge else None,
                brain=brain,
            )
        if action == "scan_market":
            symbol, timeframe = arguments["symbol"], arguments["timeframe"]
            candles = self._remote_market_candles(symbol, timeframe)
            signals = run_all(candles)
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "strategies": [signal.to_dict() for signal in signals],
                "consensus": consensus(signals),
            }
        if action == "list_alert_rules":
            return [
                {
                    "rule_id": rule.rule_id,
                    "symbol": rule.symbol,
                    "metric": rule.metric,
                    "operator": rule.operator,
                    "value": rule.value,
                    "enabled": rule.enabled,
                    "note": rule.note,
                }
                for rule in self.alert_engine.rules
            ]
        if action == "create_alert_rule":
            rule = AlertRule(**arguments)
            updated = [*self.alert_engine.rules, rule]
            self.alert_store.save(updated)
            self.alert_engine.rules = updated
            self._render_rules()
            return {
                "created": True,
                "rule_id": rule.rule_id,
                "description": rule.describe(),
            }
        if action == "delete_alert_rule":
            rule_id = arguments["rule_id"]
            updated = [
                rule for rule in self.alert_engine.rules if rule.rule_id != rule_id
            ]
            if len(updated) == len(self.alert_engine.rules):
                raise ValueError(f"no alert rule with id {rule_id!r}")
            self.alert_store.save(updated)
            self.alert_engine.rules = updated
            self._render_rules()
            return {"deleted": True, "rule_id": rule_id}
        if action == "update_app_settings":
            updates = arguments["updates"]
            candidate = self.settings.updated(**updates)
            variables = {
                "auto_refresh": self.auto_refresh,
                "alerts_enabled": self.alerts_enabled,
                "compact_mode": self.compact_mode,
                "theme": self.theme_var,
                "polling_ms": self.polling_var,
                "candle_limit": self.candle_limit_var,
                "alert_min_score": self.alert_min_score_var,
                "retention_days": self.retention_var,
                "store_candles": self.store_candles_var,
                "save_snapshots": self.snapshots_var,
                "show_strategy_overlay": self.overlay_var,
                "use_knowledge": self.use_knowledge_var,
                "use_memory": self.use_memory_var,
                "use_brain_model": self.use_brain_var,
            }
            for key, value in updates.items():
                if key == "strategy":
                    spec = STRATEGIES[value]
                    self.strategy_var.set(f"{value} · {spec.label}")
                else:
                    variables[key].set(value)
            self._settings_changed()
            if self.settings != candidate:
                raise OSError("settings could not be saved; no remote changes applied")
            return self._remote_settings()
        if action == "set_active_market":
            self._set_selected(arguments["symbol"])
            return {"selected_symbol": self.selected}
        if action == "set_active_timeframe":
            timeframe = arguments["timeframe"]
            self.default_tf_var.set(timeframe)
            candidate = self.settings.updated(default_timeframe=timeframe)
            self._settings_changed()
            if self.settings != candidate:
                raise OSError("timeframe setting could not be saved")
            self.tf.set(timeframe)
            self._tf_changed()
            return {"timeframe": timeframe, "updated": True}
        if action == "ask_copilot":
            return self._answer(arguments["question"])
        raise ValueError(f"unsupported remote action: {action}")

    @staticmethod
    def _resolve_telegram_symbol(value):
        raw = value.strip()
        if raw in SYMBOLS:
            return raw
        normalized = raw.upper().replace("/", "").replace(" ", "")
        for symbol, name in SYMBOLS.items():
            symbol_normalized = symbol.upper().replace("FRX", "").replace("/", "")
            name_normalized = name.upper().replace("/", "").replace(" ", "")
            if normalized in {symbol_normalized, name_normalized}:
                return symbol
        raise ValueError(
            f"unknown market {raw!r}; use a market symbol such as frxEURUSD"
        )

    def _telegram_command(self, text, chat_id):
        del chat_id  # authorization is checked by TelegramBotService before dispatch
        parts = text.strip().split()
        if not parts:
            return "Send /help to see available commands."
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]
        writes = self.settings.telegram_allow_commands
        try:
            if command in {"/start", "/help"}:
                write_help = (
                    "\n/alert, /remember, /set, /delete-alert (write permission on)"
                    if writes
                    else "\nWrite commands are disabled in Settings → Telegram."
                )
                return (
                    "NEEZY commands: /status, /markets [filter], /signals [symbol], "
                    "/analyze [symbol] [timeframe], /scan [symbol] [timeframe], "
                    "/ask question, /alerts, /help" + write_help
                )
            if command == "/status":
                status = self.remote_registry.execute("app_status")
                return (
                    f"NEEZY · {status['connection']}\n{status['selected_symbol']} "
                    f"{status['timeframe']} · {status['current_signal']} "
                    f"(score {status['signal_score']})\n"
                    f"Tracking {status['tracked_markets']} market(s) · "
                    "no trade execution"
                )
            if command == "/markets":
                query = " ".join(args)
                markets = self.remote_registry.execute("list_markets", market=query)[
                    :25
                ]
                return "Markets:\n" + "\n".join(
                    f"{item['symbol']} · {item['name']}" for item in markets
                )
            if command == "/signals":
                symbol = self._resolve_telegram_symbol(args[0]) if args else ""
                records = self.remote_registry.execute(
                    "get_recent_signals", limit=10, symbol=symbol
                )
                if not records:
                    return "No saved signal transitions yet."
                return "Recent signals:\n" + "\n".join(
                    f"{row['symbol']} {row['timeframe']} · {row['signal']} "
                    f"score {row['score']:+.1f}"
                    for row in records[:10]
                )
            if command in {"/analyze", "/scan"}:
                status = self.remote_registry.execute("app_status")
                symbol = (
                    self._resolve_telegram_symbol(args[0])
                    if args
                    else status["selected_symbol"]
                )
                timeframe = args[1] if len(args) > 1 else status["timeframe"]
                tool = "analyze_market" if command == "/analyze" else "scan_market"
                result = self.remote_registry.execute(
                    tool, symbol=symbol, timeframe=timeframe
                )
                if command == "/analyze":
                    return (
                        f"{result['name']} {timeframe} · {result['signal']} "
                        f"score {result['score']:+d}/4\nTrend {result['trend']} · "
                        f"{result['regime']} · RSI {result['rsi']:.1f} · "
                        f"ATR {result['atr_pct']:.2f}%\n"
                        "Educational read only; not a forecast."
                    )
                consensus_result = result["consensus"]
                lines = [
                    f"{symbol} {timeframe} · consensus {consensus_result['label']} "
                    f"({consensus_result['confidence']:.0f}%)"
                ]
                lines.extend(
                    f"{item['strategy']}: {item['label']} {item['confidence']:.0f}%"
                    for item in result["strategies"]
                )
                return "\n".join(lines)
            if command == "/ask":
                question = " ".join(args).strip()
                if not question:
                    return "Usage: /ask what is the trend?"
                return self.remote_registry.execute("ask_copilot", question=question)
            if command == "/alerts":
                rules = self.remote_registry.execute("list_alert_rules")
                if not rules:
                    return "No alert rules configured."
                return "Alert rules:\n" + "\n".join(
                    f"{row['rule_id']} · {row['symbol']} {row['metric']} "
                    f"{row['operator']} {row['value']}"
                    for row in rules[:30]
                )
            if command in {"/alert", "/remember", "/set", "/delete-alert"}:
                if not writes:
                    return (
                        "Write commands are disabled. Turn them on in "
                        "Settings → Telegram."
                    )
                if command == "/alert":
                    if len(args) < 4:
                        return (
                            "Usage: /alert SYMBOL METRIC OPERATOR VALUE "
                            "(e.g. /alert frxEURUSD rsi > 70)"
                        )
                    operator = args[2]
                    value_start = 3
                    if operator.lower() == "crosses" and len(args) > 4:
                        operator = f"crosses {args[3].lower()}"
                        value_start = 4
                    created = self.remote_registry.execute(
                        "create_alert_rule",
                        symbol=args[0],
                        metric=args[1].lower(),
                        operator=operator,
                        value=" ".join(args[value_start:]),
                    )
                    return (
                        f"Alert created: {created['description']} · "
                        f"id {created['rule_id']}"
                    )
                if command == "/remember":
                    content = " ".join(args).strip()
                    if not content:
                        return "Usage: /remember your note here"
                    saved = self.remote_registry.execute(
                        "save_memory", content=content, category="telegram"
                    )
                    return f"Saved local memory note #{saved['id']}."
                if command == "/set":
                    if len(args) < 2:
                        return (
                            "Usage: /set timeframe 15m | /set market frxEURUSD | "
                            "/set strategy MACD"
                        )
                    key, raw_value = args[0].lower(), " ".join(args[1:])
                    if key in {"timeframe", "tf"}:
                        result = self.remote_registry.execute(
                            "set_active_timeframe", timeframe=raw_value
                        )
                        return f"Active timeframe set to {result['timeframe']}."
                    if key in {"market", "symbol"}:
                        result = self.remote_registry.execute(
                            "set_active_market",
                            symbol=self._resolve_telegram_symbol(raw_value),
                        )
                        return f"Active market set to {result['selected_symbol']}."
                    normalized_key = {
                        "brain": "use_brain_model",
                        "memory": "use_memory",
                        "knowledge": "use_knowledge",
                        "min_score": "alert_min_score",
                    }.get(key, key)
                    if normalized_key in {
                        "auto_refresh",
                        "alerts_enabled",
                        "compact_mode",
                        "show_strategy_overlay",
                        "use_knowledge",
                        "use_memory",
                        "use_brain_model",
                        "store_candles",
                        "save_snapshots",
                    }:
                        if raw_value.lower() not in {
                            "on",
                            "off",
                            "true",
                            "false",
                            "1",
                            "0",
                        }:
                            raise ValueError("boolean settings need on/off")
                        value: Any = raw_value.lower() in {"on", "true", "1"}
                    elif normalized_key in {
                        "alert_min_score",
                        "polling_ms",
                        "candle_limit",
                        "retention_days",
                    }:
                        value = int(raw_value)
                    elif normalized_key in {"theme", "strategy"}:
                        value = raw_value
                    else:
                        raise ValueError("setting is not remotely changeable")
                    saved = self.remote_registry.execute(
                        "update_app_settings", updates={normalized_key: value}
                    )
                    return f"Updated {normalized_key} to {saved[normalized_key]}"
                rule_id = args[0] if args else ""
                if not rule_id:
                    return "Usage: /delete-alert RULE_ID"
                deleted = self.remote_registry.execute(
                    "delete_alert_rule", rule_id=rule_id
                )
                return f"Deleted alert {deleted['rule_id']}."
            return "Unknown command. Send /help for the command list."
        except Exception as error:  # noqa: BLE001 - no Telegram token or traceback in reply
            return f"Command error: {str(error)[:350]}"
