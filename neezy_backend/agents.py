"""Multi-agent team: role-based analysts sharing a blackboard.

A small, deterministic orchestration layer on top of the existing single
planner (:mod:`neezy_backend.agent`). Five roles cooperate:

- ``scout``     - resolves the request into markets and a timeframe
- ``analyst``   - computes the advanced indicator suite for each market
- ``risk``      - sizes a demo plan and flags volatility concerns
- ``archivist`` - pulls anything the local knowledge base already knows
- ``reporter``  - assembles the final briefing text

Agents exchange :class:`AgentMessage` notes and read/write a thread-safe
:class:`Blackboard`. The whole run is one function call - no threads, no
sleeping loops - so tests, the ``agents`` CLI command, and the agent tool
share one deterministic path. An optional AI client (any callable taking
a prompt) lets the reporter phrase the summary; without one the report is
rule-based, so the feature works fully offline.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

Fetcher = Callable[[str, int, int], list[tuple[int, float, float, float, float]]]

TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """One note passed between agents (or broadcast with recipient ``*``)."""

    sender: str
    recipient: str
    kind: str  # "finding", "request", "risk", "summary"
    payload: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Blackboard:
    """Thread-safe shared state: sections of facts written by agents."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sections: dict[str, dict[str, Any]] = {}
        self.messages: list[AgentMessage] = []

    def post(self, section: str, key: str, value: Any) -> None:
        with self._lock:
            self._sections.setdefault(section, {})[key] = value

    def section(self, name: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._sections.get(name, {}))

    def sections(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                name: {
                    key: (
                        list(value)
                        if isinstance(value, list)
                        else dict(value)
                        if isinstance(value, dict)
                        else value
                    )
                    for key, value in values.items()
                }
                for name, values in self._sections.items()
            }

    def send(self, message: AgentMessage) -> None:
        with self._lock:
            self.messages.append(message)

    def inbox(self, recipient: str) -> list[AgentMessage]:
        with self._lock:
            return [
                message
                for message in self.messages
                if message.recipient in (recipient, "*")
            ]


@dataclass(frozen=True, slots=True)
class Agent:
    """One role in the team."""

    agent_id: str
    role: str
    description: str
    process: Callable[[Blackboard, TeamContext], None]


@dataclass
class TeamContext:
    """Inputs for one team run."""

    goal: str
    fetch: Fetcher | None = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    symbols: tuple[str, ...] = ()
    timeframe: str = "15m"
    candles: int = 300
    balance: float = 10_000.0
    risk_percent: float = 1.0
    ai_client: Callable[[str], str] | None = None

    def fetch_candles(
        self, symbol: str
    ) -> list[tuple[int, float, float, float, float]]:
        if self.fetch is None:
            raise RuntimeError("no market data fetcher configured")
        seconds = TIMEFRAME_SECONDS.get(self.timeframe, 900)
        return self.fetch(symbol, seconds, self.candles)


# ---------------------------------------------------------------------------
# Role implementations
# ---------------------------------------------------------------------------


def _extract_symbols(goal: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Pick up to three known markets mentioned in the goal text."""
    from .markets import SYMBOLS

    upper = goal.upper()
    aliases = {
        "EURUSD": "frxEURUSD",
        "EUR/USD": "frxEURUSD",
        "GBPUSD": "frxGBPUSD",
        "GBP/USD": "frxGBPUSD",
        "USDJPY": "frxUSDJPY",
        "USD/JPY": "frxUSDJPY",
        "XAUUSD": "frxXAUUSD",
        "GOLD": "frxXAUUSD",
        "BTCUSD": "cryBTCUSD",
        "BTC": "cryBTCUSD",
        "ETHUSD": "cryETHUSD",
        "ETH": "cryETHUSD",
    }
    found: list[str] = []
    for code in SYMBOLS:
        if code in upper and code not in found:
            found.append(code)
    for token, code in aliases.items():
        if token in upper and code in SYMBOLS and code not in found:
            found.append(code)
    if found:
        return tuple(found[:3])
    return fallback or ("frxEURUSD",)


def _agent_scout(board: Blackboard, context: TeamContext) -> None:
    symbols = context.symbols or _extract_symbols(context.goal, ())
    board.post("facts", "symbols", list(symbols))
    board.post("facts", "timeframe", context.timeframe)
    board.post("facts", "goal", context.goal)
    board.send(
        AgentMessage(
            sender="scout",
            recipient="analyst",
            kind="request",
            payload=f"analyse {', '.join(symbols)} on {context.timeframe}",
        )
    )


def _agent_analyst(board: Blackboard, context: TeamContext) -> None:
    from .indicators import advanced_suite, analyze

    symbols = board.section("facts").get("symbols", [])
    for symbol in symbols:
        try:
            candles = context.fetch_candles(symbol)
        except (OSError, RuntimeError, ValueError) as error:
            board.post("metrics", symbol, {"error": str(error)[:100]})
            continue
        core = analyze(candles)
        advanced = advanced_suite(candles)
        entry = {"core": _slim(core), "advanced": advanced}
        board.post("metrics", symbol, entry)
        board.send(
            AgentMessage(
                sender="analyst",
                recipient="*",
                kind="finding",
                payload=f"{symbol}: core signal {core['signal'] if core else 'n/a'}",
            )
        )
        if core and core.get("score", 0) >= 3:
            board.post("risks", symbol, "high conviction score; check sizing")


def _slim(core: dict[str, Any] | None) -> dict[str, Any]:
    if not core:
        return {}
    keys = ("signal", "score", "rsi", "atr", "atr_pct", "macd_histogram", "trend")
    return {key: core.get(key) for key in keys}


def _agent_risk(board: Blackboard, context: TeamContext) -> None:
    from .indicators import atr

    metrics = board.section("metrics")
    for symbol, entry in metrics.items():
        if not isinstance(entry, dict) or "error" in entry:
            continue
        advanced = entry.get("advanced") or {}
        try:
            candles = context.fetch_candles(symbol)
        except (OSError, RuntimeError, ValueError):
            continue
        if len(candles) < 31:
            continue
        closed = candles[:-1]
        stop_distance = atr(
            [row[2] for row in closed],
            [row[3] for row in closed],
            [row[4] for row in closed],
        )
        if stop_distance is None or not closed[-1][4]:
            continue
        entry_price = float(closed[-1][4])
        risk_amount = context.balance * context.risk_percent / 100.0
        stop = entry_price - 1.5 * stop_distance
        if stop >= entry_price:
            continue
        distance = entry_price - stop
        units = risk_amount / distance if distance > 0 else 0.0
        board.post(
            "risks",
            symbol,
            (
                f"1.5-ATR stop {stop:.5f}; risk {risk_amount:.2f} "
                f"({context.risk_percent:.1f}% of {context.balance:.0f}) "
                f"-> {units:.0f} units"
            ),
        )
        chop = advanced.get("choppiness") if isinstance(advanced, dict) else None
        if isinstance(chop, (int, float)) and chop > 61.8:
            board.post(
                "risks", f"{symbol}_warning", "choppiness above 61.8: range-bound"
            )


def _agent_archivist(board: Blackboard, context: TeamContext) -> None:
    del context
    try:
        from .knowledge import load_knowledge
    except ImportError:  # pragma: no cover - knowledge module is always present
        return
    symbols = board.section("facts").get("symbols", [])
    try:
        knowledge = load_knowledge()
    except (OSError, ValueError):
        return
    for symbol in symbols:
        record = knowledge.get(symbol) if isinstance(knowledge, dict) else None
        if record:
            board.post("notes", symbol, "local study knowledge available")
        else:
            board.post("notes", symbol, "no local study knowledge yet")


def _agent_reporter(board: Blackboard, context: TeamContext) -> None:
    facts = board.section("facts")
    metrics = board.section("metrics")
    risks = board.section("risks")
    notes = board.section("notes")
    lines = [f"Team briefing for: {facts.get('goal', context.goal)}"]
    lines.append(
        f"Markets: {', '.join(facts.get('symbols', []))} on {facts.get('timeframe')}"
    )
    for symbol, entry in metrics.items():
        if not isinstance(entry, dict):
            continue
        core = entry.get("core") or {}
        advanced = entry.get("advanced") or {}
        values = advanced.get("values", {}) if isinstance(advanced, dict) else {}
        if "error" in entry:
            lines.append(f"- {symbol}: unavailable ({entry['error']})")
            continue
        signal = core.get("signal", "n/a")
        score = core.get("score", 0)
        lines.append(f"- {symbol}: {signal} (score {score})")
        cci = values.get("cci")
        chop = values.get("choppiness")
        if isinstance(cci, (int, float)):
            lines.append(
                f"  CCI {cci:.0f}",
            )
        if isinstance(chop, (int, float)):
            lines.append(f"  choppiness {chop:.0f}")
    for symbol, note in risks.items():
        lines.append(f"- risk [{symbol}]: {note}")
    if notes:
        lines.append(f"- archive: {len(notes)} notes")
    report = "\n".join(lines)

    if context.ai_client is not None:
        try:
            enhanced = str(
                context.ai_client(f"Summarise this briefing concisely:\n{report}")
            ).strip()
            if enhanced:
                report = enhanced
        except Exception:  # noqa: BLE001 - AI is optional polish, never required
            pass

    board.post("summary", "report", report)
    board.send(
        AgentMessage(sender="reporter", recipient="*", kind="summary", payload=report)
    )


def default_team() -> list[Agent]:
    """The shipped five-role roster."""
    return [
        Agent(
            agent_id="scout",
            role="scout",
            description="Resolve the goal into markets and a timeframe.",
            process=_agent_scout,
        ),
        Agent(
            agent_id="analyst",
            role="analyst",
            description="Advanced indicator suite for every requested market.",
            process=_agent_analyst,
        ),
        Agent(
            agent_id="risk",
            role="risk",
            description="Demo position sizing and volatility warnings.",
            process=_agent_risk,
        ),
        Agent(
            agent_id="archivist",
            role="archivist",
            description="Check the local knowledge base for prior studies.",
            process=_agent_archivist,
        ),
        Agent(
            agent_id="reporter",
            role="reporter",
            description="Assemble the final team briefing.",
            process=_agent_reporter,
        ),
    ]


class AgentTeam:
    """Runs a fixed roster of agents over a shared blackboard."""

    def __init__(self, agents: list[Agent] | None = None) -> None:
        self.agents = agents if agents is not None else default_team()

    def roster(self) -> list[dict[str, str]]:
        return [
            {
                "id": agent.agent_id,
                "role": agent.role,
                "description": agent.description,
            }
            for agent in self.agents
        ]

    def run(self, context: TeamContext) -> dict[str, Any]:
        """Execute the full pipeline once and return the structured result."""
        board = Blackboard()
        phases: list[dict[str, Any]] = []
        for agent in self.agents:
            agent.process(board, context)
            phases.append({"agent": agent.agent_id, "role": agent.role})
        return {
            "goal": context.goal,
            "phases": phases,
            "facts": board.section("facts"),
            "metrics": board.section("metrics"),
            "risks": board.section("risks"),
            "notes": board.section("notes"),
            "report": board.section("summary").get("report", ""),
            "messages": [
                {
                    "from": message.sender,
                    "to": message.recipient,
                    "kind": message.kind,
                    "payload": message.payload[:200],
                }
                for message in board.messages
            ],
        }
