"""Planner/Executor loop with multi-step plan execution and step state."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .ai import AIClient
from .markets import SYMBOLS, TIMEFRAMES
from .tools import DEFAULT_REGISTRY, ToolRegistry


@dataclass
class PlanStep:
    step_id: int
    task: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: str | None = None


class AgentPlanner:
    """Planner and Executor loop for complex task decomposition and tool usage."""

    def __init__(
        self,
        ai_client: AIClient | None = None,
        registry: ToolRegistry = DEFAULT_REGISTRY,
        max_steps: int = 10,
    ) -> None:
        self.ai_client = ai_client
        self.registry = registry
        self.max_steps = max_steps

    def create_plan(self, user_goal: str) -> list[PlanStep]:
        """Decompose a high-level goal into bounded tool-backed steps."""
        # Optional structured LLM decomposition if a callable/configured client exists.
        if callable(self.ai_client):
            try:
                raw = str(self.ai_client(user_goal))
                match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
                if match:
                    items = json.loads(match.group(0))
                    if isinstance(items, list) and items:
                        parsed_steps = [
                            PlanStep(
                                step_id=idx,
                                task=str(item.get("task", f"Step {idx}")),
                                tool_name=item.get("tool_name"),
                                tool_args=dict(item.get("tool_args") or {}),
                            )
                            for idx, item in enumerate(items[: self.max_steps], start=1)
                            if isinstance(item, dict)
                        ]
                        if parsed_steps:
                            return parsed_steps
            except Exception:  # noqa: BLE001
                pass

        upper = user_goal.upper()
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
        matched_symbols: list[str] = []
        for code in SYMBOLS:
            if code.upper() in upper and code not in matched_symbols:
                matched_symbols.append(code)
        for token, code in aliases.items():
            if token in upper and code in SYMBOLS and code not in matched_symbols:
                matched_symbols.append(code)
        if not matched_symbols:
            matched_symbols = ["frxEURUSD"]

        timeframe = "15m"
        for tf in TIMEFRAMES:
            if re.search(rf"\b{re.escape(tf.lower())}\b", f" {user_goal.lower()} "):
                timeframe = tf
                break

        steps: list[PlanStep] = []
        for sym in matched_symbols[: self.max_steps]:
            steps.append(
                PlanStep(
                    step_id=len(steps) + 1,
                    task=(
                        f"Analyze market data for goal: {user_goal} ({sym} {timeframe})"
                    ),
                    tool_name="read_market",
                    tool_args={"symbol": sym, "timeframe": timeframe},
                )
            )
        return steps[: self.max_steps]

    def execute_plan(
        self, steps: list[PlanStep], dry_run: bool = False, confirm: bool = False
    ) -> list[PlanStep]:
        """Execute a list of planned steps in order.

        WRITE/DESTRUCTIVE tools only run when ``confirm`` is true; otherwise the
        step fails with a PermissionError message and nothing is changed.
        """
        for step in steps[: self.max_steps]:
            step.status = "running"
            if step.tool_name:
                try:
                    step.result = self.registry.execute(
                        step.tool_name,
                        dry_run=dry_run,
                        confirm=confirm,
                        **step.tool_args,
                    )
                    step.status = "completed"
                except Exception as err:  # noqa: BLE001 - step execution error capture
                    step.status = "failed"
                    step.error = str(err)
            else:
                step.status = "completed"
                step.result = f"Completed task: {step.task}"
        return steps
