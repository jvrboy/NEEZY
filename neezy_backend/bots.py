"""Lightweight bot framework: supervised, tick-driven, read-only by design.

Bots are small deterministic workers around the existing NEEZY services:
each ``tick`` reads state (market data, session clock, stored knowledge)
and returns one :class:`BotDecision` describing what it *noticed*. Bots
never place orders, never write outside the local data directory, and
never loop on their own - ``BotManager.run_ticks`` drives a fixed number
of ticks so tests, the CLI, and the agent tooling all share one
deterministic path.

Built-in bots:

- ``scanner``   - rank the watchlist by strategy consensus
- ``sessions``  - announce trading-session opens/closes and overlaps
- ``risk_guard``- ATR-based position sizing advice for a demo balance
- ``scribe``    - heartbeat summary of what the other bots reported
- ``momentum``  - RSI + MACD histogram momentum read on one market
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

Fetcher = Callable[[str, int, int], list[tuple[int, float, float, float, float]]]

#: Default watchlist: liquid majors across forex, metals, and crypto.
WATCHLIST: tuple[str, ...] = (
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
    "frxXAUUSD",
    "cryBTCUSD",
)

DEFAULT_BALANCE = 10_000.0
DEFAULT_RISK_PERCENT = 1.0

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BotDecision:
    """One observation produced by a bot tick."""

    bot_id: str
    action: str  # e.g. "scan", "announce", "warn", "heartbeat"
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Bot:
    """A named worker whose ``tick`` function produces decisions."""

    bot_id: str
    name: str
    role: str
    description: str
    tick: Callable[[BotContext], BotDecision | None]
    state: str = IDLE
    ticks_run: int = 0
    last_decision: BotDecision | None = None

    def run_tick(self, context: BotContext) -> BotDecision | None:
        if self.state in (PAUSED, STOPPED):
            return None
        try:
            decision = self.tick(context)
        except Exception as error:  # noqa: BLE001 - bots must never crash the host
            self.state = FAILED
            self.last_decision = BotDecision(
                bot_id=self.bot_id,
                action="error",
                detail=f"{type(error).__name__}: {error}",
            )
            return self.last_decision
        self.ticks_run += 1
        if decision is not None:
            self.last_decision = decision
        return decision


@dataclass
class BotContext:
    """Everything a bot may touch on one tick. All read-only surfaces."""

    fetch: Fetcher | None = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    balance: float = DEFAULT_BALANCE
    risk_percent: float = DEFAULT_RISK_PERCENT
    watchlist: tuple[str, ...] = WATCHLIST
    timeframe: str = "15m"
    candles: int = 300
    notes: list[str] = field(default_factory=list)

    def fetch_candles(
        self, symbol: str
    ) -> list[tuple[int, float, float, float, float]]:
        if self.fetch is None:
            raise RuntimeError("no market data fetcher configured")
        seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(self.timeframe, 900)
        return self.fetch(symbol, seconds, self.candles)


# ---------------------------------------------------------------------------
# Built-in tick functions
# ---------------------------------------------------------------------------


def _tick_scanner(context: BotContext) -> BotDecision | None:
    """Rank the watchlist by strategy consensus (read-only scan)."""
    from .strategies import consensus, run_all

    rows: list[dict[str, Any]] = []
    for symbol in context.watchlist:
        try:
            candles = context.fetch_candles(symbol)
        except (OSError, RuntimeError, ValueError) as error:
            rows.append({"symbol": symbol, "error": str(error)[:80]})
            continue
        if len(candles) < 61:
            rows.append({"symbol": symbol, "error": "not enough candles"})
            continue
        verdict = consensus(run_all(candles[:-1]))
        rows.append(
            {
                "symbol": symbol,
                "label": verdict["label"],
                "confidence": verdict["confidence"],
                "votes": verdict["votes"],
            }
        )
    tradable = [row for row in rows if "error" not in row]
    if tradable:
        best = max(tradable, key=lambda row: float(row["confidence"]))
        votes = best["votes"] if isinstance(best["votes"], dict) else {}
        tally = "/".join(
            f"{votes.get(side, 0)}{side[0]}" for side in ("buy", "sell", "neutral")
        )
        headline = (
            f"{best['symbol']} strongest: {best['label']} "
            f"{best['confidence']:.0f}% ({tally})"
        )
    else:
        headline = "no market returned enough candles"
    return BotDecision(
        bot_id="scanner",
        action="scan",
        detail=headline,
        data={"rows": rows, "scanned": len(tradable)},
    )


def _tick_sessions(context: BotContext) -> BotDecision:
    """Announce the session clock at this tick."""
    from .sessions import summarize

    line = summarize(context.now())
    return BotDecision(bot_id="sessions", action="announce", detail=line)


def _tick_risk_guard(context: BotContext) -> BotDecision | None:
    """ATR stop + position-size advice for the first tradable market."""
    from .indicators import atr
    from .risk import position_size

    for symbol in context.watchlist:
        try:
            candles = context.fetch_candles(symbol)
        except (OSError, RuntimeError, ValueError):
            continue
        if len(candles) < 31:
            continue
        closed = candles[:-1]
        highs = [row[2] for row in closed]
        lows = [row[3] for row in closed]
        closes = [row[4] for row in closed]
        stop_distance = atr(highs, lows, closes)
        if stop_distance is None or not closes[-1]:
            continue
        entry = closes[-1]
        plan = position_size(
            symbol=symbol,
            balance=context.balance,
            risk_percent=context.risk_percent,
            entry=entry,
            stop=entry - 1.5 * stop_distance,
        )
        data = plan.to_dict()
        return BotDecision(
            bot_id="risk_guard",
            action="advise",
            detail=(
                f"{symbol}: demo plan lots={data['lots']} "
                f"risk={data['risk_amount']:.2f} (1.5 ATR stop)"
            ),
            data=data,
        )
    return BotDecision(
        bot_id="risk_guard",
        action="skip",
        detail="no market returned candles for a risk read",
    )


def _tick_scribe(context: BotContext) -> BotDecision:
    """Heartbeat: timestamp, watchlist size, and any bot notes so far."""
    stamp = context.now().astimezone(timezone.utc).isoformat(timespec="seconds")
    lines = [f"heartbeat at {stamp}"]
    lines.extend(f"note: {note}" for note in context.notes[-3:])
    return BotDecision(
        bot_id="scribe",
        action="heartbeat",
        detail=" | ".join(lines),
        data={"watchlist": list(context.watchlist)},
    )


def _tick_momentum(context: BotContext) -> BotDecision | None:
    """RSI + MACD histogram momentum read on the primary watch symbol."""
    from .indicators import macd_histogram_series, rsi

    symbol = context.watchlist[0]
    try:
        candles = context.fetch_candles(symbol)
    except (OSError, RuntimeError, ValueError) as error:
        return BotDecision(
            bot_id="momentum",
            action="skip",
            detail=f"{symbol} unavailable ({str(error)[:60]})",
        )
    if len(candles) < 40:
        return BotDecision(
            bot_id="momentum", action="skip", detail="not enough candles"
        )
    closes = [row[4] for row in candles[:-1]]
    momentum_rsi = rsi(closes)
    histogram = macd_histogram_series(closes)[-1]
    if momentum_rsi is None:
        return BotDecision(
            bot_id="momentum", action="skip", detail="RSI still warming up"
        )
    state = "up" if histogram > 0 else "down" if histogram < 0 else "flat"
    return BotDecision(
        bot_id="momentum",
        action="read",
        detail=(
            f"{symbol}: RSI {momentum_rsi:.1f}, "
            f"MACD histogram {state} ({histogram:+.5f})"
        ),
        data={"rsi": momentum_rsi, "macd_histogram": histogram, "state": state},
    )


def default_bots() -> list[Bot]:
    """The shipped bot roster, fresh instances each call."""
    return [
        Bot(
            bot_id="scanner",
            name="Watchlist Scanner",
            role="research",
            description="Rank the watchlist by strategy consensus every tick.",
            tick=_tick_scanner,
        ),
        Bot(
            bot_id="sessions",
            name="Session Announcer",
            role="operations",
            description="Report open trading sessions and the next open/close.",
            tick=_tick_sessions,
        ),
        Bot(
            bot_id="risk_guard",
            name="Risk Guard",
            role="risk",
            description="ATR stop and demo position-size advice (plan only).",
            tick=_tick_risk_guard,
        ),
        Bot(
            bot_id="momentum",
            name="Momentum Reader",
            role="research",
            description="RSI and MACD histogram read on the primary market.",
            tick=_tick_momentum,
        ),
        Bot(
            bot_id="scribe",
            name="Scribe",
            role="operations",
            description="Timestamped heartbeat of bot activity.",
            tick=_tick_scribe,
        ),
    ]


class BotManager:
    """Registry + deterministic tick loop for bots. Thread-safe metadata."""

    def __init__(self, bots: list[Bot] | None = None) -> None:
        self._bots: dict[str, Bot] = {}
        self._lock = threading.RLock()
        self.decision_log: list[BotDecision] = []
        for bot in bots if bots is not None else default_bots():
            self.register(bot)

    def register(self, bot: Bot) -> None:
        with self._lock:
            if bot.bot_id in self._bots:
                raise ValueError(f"bot id {bot.bot_id!r} already registered")
            self._bots[bot.bot_id] = bot

    def get(self, bot_id: str) -> Bot | None:
        with self._lock:
            return self._bots.get(bot_id)

    def bots(self) -> list[Bot]:
        with self._lock:
            return list(self._bots.values())

    def start(self, bot_id: str) -> None:
        with self._lock:
            bot = self._require(bot_id)
            if bot.state == FAILED:
                raise ValueError(f"bot {bot_id!r} failed; reset it first")
            bot.state = RUNNING

    def start_all(self) -> None:
        with self._lock:
            for bot_id in self._bots:
                if self._bots[bot_id].state != FAILED:
                    self._bots[bot_id].state = RUNNING

    def stop(self, bot_id: str) -> None:
        with self._lock:
            self._require(bot_id).state = STOPPED

    def stop_all(self) -> None:
        with self._lock:
            for bot in self._bots.values():
                bot.state = STOPPED

    def pause(self, bot_id: str) -> None:
        with self._lock:
            bot = self._require(bot_id)
            if bot.state != RUNNING:
                raise ValueError(f"bot {bot_id!r} is not running")
            bot.state = PAUSED

    def resume(self, bot_id: str) -> None:
        with self._lock:
            bot = self._require(bot_id)
            if bot.state != PAUSED:
                raise ValueError(f"bot {bot_id!r} is not paused")
            bot.state = RUNNING

    def reset(self, bot_id: str) -> None:
        with self._lock:
            bot = self._require(bot_id)
            bot.state = IDLE
            bot.ticks_run = 0
            bot.last_decision = None

    def _require(self, bot_id: str) -> Bot:
        bot = self._bots.get(bot_id)
        if bot is None:
            raise KeyError(f"unknown bot {bot_id!r}")
        return bot

    def run_ticks(
        self,
        ticks: int = 1,
        *,
        context: BotContext | None = None,
        only: str | None = None,
    ) -> list[BotDecision]:
        """Drive ``ticks`` rounds of every running (or selected) bot.

        Deterministic: no timers, no threads, no network beyond the fetcher
        the caller installed on the context.
        """
        if ticks < 1:
            raise ValueError("ticks must be at least 1")
        if ticks > 100:
            raise ValueError("at most 100 ticks per call")
        context = context or BotContext()
        decisions: list[BotDecision] = []
        with self._lock:
            targets = [
                bot
                for bot in self._bots.values()
                if (bot.bot_id == only if only is not None else bot.state == RUNNING)
                and bot.state not in (STOPPED, PAUSED, FAILED)
            ]
        for _ in range(ticks):
            for bot in targets:
                decision = bot.run_tick(context)
                if decision is not None:
                    decisions.append(decision)
                    if decision.bot_id == "scribe" or decision.action != "error":
                        context.notes.append(f"{decision.bot_id}: {decision.detail}")
        self.decision_log.extend(decisions)
        return decisions

    def status(self) -> dict[str, Any]:
        """Snapshot for the CLI, agent tools, and dashboards."""
        with self._lock:
            bots = [
                {
                    "id": bot.bot_id,
                    "name": bot.name,
                    "role": bot.role,
                    "description": bot.description,
                    "state": bot.state,
                    "ticks": bot.ticks_run,
                    "last_decision": (
                        {
                            "action": bot.last_decision.action,
                            "detail": bot.last_decision.detail,
                        }
                        if bot.last_decision
                        else None
                    ),
                }
                for bot in self._bots.values()
            ]
        running = sum(1 for bot in bots if bot["state"] == RUNNING)
        return {
            "bots": bots,
            "running": running,
            "total": len(bots),
            "decisions_logged": len(self.decision_log),
        }
