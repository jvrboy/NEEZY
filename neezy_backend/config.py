"""Validated application settings kept separate from the Tkinter view."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from neezy_backend.markets import SYMBOLS, TIMEFRAMES

THEMES = frozenset({"Liquid dark", "Midnight blue", "High contrast"})
STRATEGIES = frozenset(
    {
        "SUPERTREND",
        "EMA_PULLBACK",
        "DIVERGENCE",
        "DONCHIAN",
        "SQUEEZE",
        "MACD",
        "KELTNER",
        "ICHIMOKU",
        "STOCH_RSI",
        "MOMENTUM",
        "RSI_REVERSAL",
        "CCI_REVERSION",
    }
)
AI_PROVIDERS = frozenset({"gemini", "grok", "openrouter", "ollama"})
# External market-data providers used by the confluence engine.
MARKET_DATA_PROVIDERS = frozenset(
    {"deriv", "alpha_vantage", "finnhub", "binance", "twelve_data"}
)


def _require_bool(field_name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")


def _require_int(field_name: str, value: object, low: int, high: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{field_name} must be between {low} and {high}")


def _require_float(field_name: str, value: object, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not low <= float(value) <= high:
        raise ValueError(f"{field_name} must be between {low:g} and {high:g}")


@dataclass(frozen=True, slots=True)
class AppSettings:
    """User-configurable settings with validation at every construction point.

    Older config files keep working: :meth:`from_dict` ignores unknown keys and
    any missing key falls back to the defaults declared here.
    """

    # Workspace
    auto_refresh: bool = True
    alerts_enabled: bool = True
    compact_mode: bool = False
    theme: str = "Liquid dark"
    polling_ms: int = 100
    candle_limit: int = 300
    alert_min_score: int = 2
    default_timeframe: str = "5m"
    history_candles: int = 300
    # Comma-separated extra Deriv symbols streamed on top of the default
    # watchlist (see markets.DEFAULT_WATCHLIST). Applied at startup.
    watchlist_extra: str = ""

    # Connection (applied when the feed starts; restart NEEZY to change)
    deriv_endpoint: str = ""
    reconnect_seconds: float = 2.0
    max_reconnect_seconds: float = 30.0

    # Strategy engine
    strategy: str = "SUPERTREND"
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    divergence_lookback: int = 5
    correlation_window: int = 50
    correlation_baseline: int = 200
    show_strategy_overlay: bool = True

    # Local storage
    store_candles: bool = True
    retention_days: int = 90
    save_snapshots: bool = True

    # AI providers
    ai_enabled: bool = False
    ai_provider: str = "openrouter"
    ai_model: str = ""
    ai_base_url: str = ""
    ai_temperature: float = 0.3
    ai_max_tokens: int = 700
    ai_timeout: float = 45.0
    ai_system_prompt: str = ""
    # Add each market's backtest record (neezy-cli knowledge) to AI context.
    # Off by default: the records are simulations, not evidence of future profit.
    use_knowledge: bool = False
    # Include relevant on-device notes in provider prompts only when explicitly enabled.
    use_memory: bool = False

    # Optional local neural experiment. It is advisory-only and never changes
    # the deterministic signal score or places trades.
    use_brain_model: bool = False

    # Reproducible public-data research (advisory; never places orders).
    ml_history_candles: int = 3000
    ml_epochs: int = 60
    ml_horizon: int = 5
    ml_deadband_atr: float = 0.1
    ml_min_samples: int = 100
    ml_seed: int = 17
    ml_probability: float = 0.60
    ml_fetch_timeout: float = 15.0
    pair_lookback: int = 60
    pair_min_overlap: int = 300
    pair_entry_z: float = 2.0
    pair_exit_z: float = 0.5
    pair_stop_z: float = 4.0
    pair_cost_bps: float = 2.0
    pair_max_holding: int = 48
    pair_min_correlation: float = 0.3
    insights_max_rows: int = 25

    # Optional local generative model. Imported weights remain where the user
    # selected them; inference is CPU-oriented and never downloads model files.
    local_llm_enabled: bool = False
    local_llm_model_id: str = ""
    local_llm_context_tokens: int = 512
    local_llm_max_tokens: int = 128
    local_llm_threads: int = 1
    local_llm_batch_size: int = 32
    local_llm_disk_offload: bool = False
    local_llm_cpu_memory_mb: int = 512

    # Local Model Context Protocol bridge. The default server binds to loopback.
    # Public access is an opt-in Cloudflare quick tunnel to a separate read-only
    # endpoint with its own bearer token.
    mcp_enabled: bool = False
    mcp_port: int = 8765
    mcp_allow_writes: bool = False
    mcp_tunnel_enabled: bool = False
    mcp_tunnel_executable: str = "cloudflared"

    # Telegram secrets are stored separately in an owner-only file. These
    # non-secret controls remain in settings.json.
    telegram_enabled: bool = False
    telegram_chat_ids: str = ""
    telegram_alerts_enabled: bool = True
    telegram_allow_commands: bool = False

    # MetaTrader 5 Bridge
    mt5_enabled: bool = False
    mt5_server: str = ""
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_path: str = ""
    mt5_magic: int = 123456
    mt5_symbol_map: str = ""
    mt5_auto_sync: bool = False

    # Direct Messaging & Risk
    dm_enabled: bool = False
    dm_webhook_url: str = ""
    dm_min_score: int = 3
    dm_notify_signals: bool = True
    dm_notify_alerts: bool = True
    default_risk_percent: float = 1.0
    max_drawdown_limit: float = 10.0

    # Confluence engine + external data providers (SETTINGS > DATA PROVIDERS)
    market_data_provider: str = "deriv"
    provider_candle_count: int = 300
    confluence_min_score: float = 55.0
    confluence_search_score: float = 30.0
    confluence_atr_stop_mult: float = 1.5
    confluence_atr_tp_mult: float = 2.5
    confluence_horizon: int = 20
    confluence_min_analogs: int = 4

    def __post_init__(self) -> None:
        for field_name, low, high in (
            ("ml_history_candles", 400, 50000),
            ("ml_epochs", 1, 500),
            ("ml_horizon", 1, 100),
            ("ml_min_samples", 60, 10000),
            ("ml_seed", 0, 2147483647),
            ("pair_lookback", 20, 1000),
            ("pair_min_overlap", 100, 20000),
            ("pair_max_holding", 1, 2000),
            ("insights_max_rows", 5, 200),
            ("mt5_login", 0, 2147483647),
            ("mt5_magic", 1, 2147483647),
            ("dm_min_score", 1, 4),
        ):
            _require_int(field_name, getattr(self, field_name), low, high)
        for field_name, low, high in (
            ("ml_deadband_atr", 0.0, 5.0),
            ("default_risk_percent", 0.1, 100.0),
            ("max_drawdown_limit", 0.1, 100.0),
            ("ml_probability", 0.51, 0.99),
            ("ml_fetch_timeout", 2.0, 120.0),
            ("pair_entry_z", 0.5, 6.0),
            ("pair_exit_z", 0.0, 3.0),
            ("pair_stop_z", 1.0, 10.0),
            ("pair_cost_bps", 0.0, 100.0),
            ("pair_min_correlation", 0.0, 1.0),
        ):
            _require_float(field_name, getattr(self, field_name), low, high)
        if not self.pair_exit_z < self.pair_entry_z < self.pair_stop_z:
            raise ValueError("pair thresholds must satisfy exit < entry < stop")
        if self.pair_min_overlap < self.pair_lookback * 3:
            raise ValueError("pair overlap must be at least three lookback windows")
        if self.theme not in THEMES:
            raise ValueError(f"Unsupported theme preset: {self.theme!r}")
        _require_int("polling_ms", self.polling_ms, 50, 2000)
        _require_int("candle_limit", self.candle_limit, 60, 1000)
        _require_int("alert_min_score", self.alert_min_score, 1, 4)
        if self.default_timeframe not in TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe {self.default_timeframe!r}; "
                f"choose from {', '.join(TIMEFRAMES)}"
            )
        _require_int("history_candles", self.history_candles, 60, 1000)
        if self.history_candles > self.candle_limit:
            raise ValueError("history candles cannot exceed max candles in memory")
        if self.market_data_provider not in MARKET_DATA_PROVIDERS:
            raise ValueError(
                f"Unsupported data provider {self.market_data_provider!r}; "
                f"choose from {', '.join(sorted(MARKET_DATA_PROVIDERS))}"
            )
        _require_int("provider_candle_count", self.provider_candle_count, 60, 1000)
        _require_float("confluence_min_score", self.confluence_min_score, 0.0, 100.0)
        _require_float(
            "confluence_search_score", self.confluence_search_score, 0.0, 100.0
        )
        if self.confluence_search_score > self.confluence_min_score:
            raise ValueError(
                "the search threshold cannot exceed the strict confluence threshold"
            )
        _require_float(
            "confluence_atr_stop_mult", self.confluence_atr_stop_mult, 0.5, 6.0
        )
        _require_float("confluence_atr_tp_mult", self.confluence_atr_tp_mult, 0.5, 10.0)
        if self.confluence_atr_tp_mult <= self.confluence_atr_stop_mult:
            raise ValueError("the take-profit multiple must exceed the stop multiple")
        _require_int("confluence_horizon", self.confluence_horizon, 3, 120)
        _require_int("confluence_min_analogs", self.confluence_min_analogs, 2, 100)
        if not isinstance(self.deriv_endpoint, str):
            raise TypeError("deriv_endpoint must be a string")
        endpoint = self.deriv_endpoint.strip()
        if endpoint and (
            not endpoint.startswith(("ws://", "wss://"))
            or any(char.isspace() for char in endpoint)
        ):
            raise ValueError(
                "deriv_endpoint must be a ws:// or wss:// URL with no spaces"
            )
        if not isinstance(self.watchlist_extra, str):
            raise TypeError("watchlist_extra must be a string")
        extras = [part.strip() for part in self.watchlist_extra.split(",")]
        extras = [symbol for symbol in extras if symbol]
        unknown = [symbol for symbol in extras if symbol not in SYMBOLS]
        if unknown:
            raise ValueError(f"unknown extra markets: {', '.join(unknown)}")
        if len(set(extras)) > 25:
            raise ValueError("at most 25 extra markets can be watched")
        _require_float("reconnect_seconds", self.reconnect_seconds, 0.5, 60.0)
        _require_float("max_reconnect_seconds", self.max_reconnect_seconds, 1.0, 600.0)
        if self.max_reconnect_seconds < self.reconnect_seconds:
            raise ValueError("max reconnect delay must be at least the first delay")
        for field_name in (
            "auto_refresh",
            "alerts_enabled",
            "compact_mode",
            "show_strategy_overlay",
            "store_candles",
            "save_snapshots",
            "ai_enabled",
            "use_knowledge",
            "use_memory",
            "use_brain_model",
            "local_llm_enabled",
            "local_llm_disk_offload",
            "mcp_enabled",
            "mcp_allow_writes",
            "mcp_tunnel_enabled",
            "telegram_enabled",
            "telegram_alerts_enabled",
            "telegram_allow_commands",
            "mt5_enabled",
            "mt5_auto_sync",
            "dm_enabled",
            "dm_notify_signals",
            "dm_notify_alerts",
        ):
            _require_bool(field_name, getattr(self, field_name))
        if self.strategy not in STRATEGIES:
            raise ValueError(
                f"Unsupported strategy {self.strategy!r}; "
                f"choose from {', '.join(sorted(STRATEGIES))}"
            )
        _require_int("supertrend_period", self.supertrend_period, 2, 100)
        _require_float("supertrend_multiplier", self.supertrend_multiplier, 0.5, 10.0)
        _require_int("divergence_lookback", self.divergence_lookback, 1, 30)
        _require_int("correlation_window", self.correlation_window, 10, 500)
        _require_int("correlation_baseline", self.correlation_baseline, 20, 2000)
        if self.correlation_baseline < self.correlation_window:
            raise ValueError("correlation baseline must be at least the window")
        _require_int("retention_days", self.retention_days, 1, 3650)
        _require_int("mcp_port", self.mcp_port, 1024, 65535)
        _require_int(
            "local_llm_context_tokens", self.local_llm_context_tokens, 128, 32768
        )
        _require_int("local_llm_max_tokens", self.local_llm_max_tokens, 1, 8192)
        _require_int("local_llm_threads", self.local_llm_threads, 1, 16)
        _require_int("local_llm_batch_size", self.local_llm_batch_size, 1, 1024)
        _require_int(
            "local_llm_cpu_memory_mb", self.local_llm_cpu_memory_mb, 256, 262144
        )
        if (
            not isinstance(self.local_llm_model_id, str)
            or len(self.local_llm_model_id) > 64
        ):
            raise ValueError(
                "local_llm_model_id must be a string of at most 64 characters"
            )
        if not isinstance(self.mcp_tunnel_executable, str):
            raise TypeError("mcp_tunnel_executable must be a string")
        if (
            not self.mcp_tunnel_executable.strip()
            or len(self.mcp_tunnel_executable) > 1024
        ):
            raise ValueError("mcp_tunnel_executable must contain 1 to 1024 characters")
        if any(ord(character) < 32 for character in self.mcp_tunnel_executable):
            raise ValueError("mcp_tunnel_executable cannot contain control characters")
        if not isinstance(self.telegram_chat_ids, str):
            raise TypeError("telegram_chat_ids must be a string")
        if len(self.telegram_chat_ids) > 1000:
            raise ValueError("telegram_chat_ids must be at most 1000 characters")
        if self.ai_provider not in AI_PROVIDERS:
            raise ValueError(f"Unsupported AI provider {self.ai_provider!r}")
        _require_float("ai_temperature", self.ai_temperature, 0.0, 2.0)
        _require_int("ai_max_tokens", self.ai_max_tokens, 64, 8192)
        _require_float("ai_timeout", self.ai_timeout, 5.0, 300.0)
        for field_name in (
            "ai_model",
            "ai_base_url",
            "ai_system_prompt",
            "mt5_server",
            "mt5_password",
            "mt5_path",
            "mt5_symbol_map",
            "dm_webhook_url",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")

    def updated(self, **changes: Any) -> AppSettings:
        """Return a new validated settings object."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> AppSettings:
        """Load known fields only, making older config files forward compatible."""
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})
