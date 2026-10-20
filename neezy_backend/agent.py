"""Planner/Executor loop with multi-step plan execution and step state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ai import AIClient
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
        """Decompose a high-level goal into actionable steps."""
        steps = [
            PlanStep(
                step_id=1,
                task=f"Analyze market data for goal: {user_goal}",
                tool_name="read_market",
                tool_args={"symbol": "frxEURUSD", "timeframe": "15m"},
            )
        ]
        return steps

    def execute_plan(
        self, steps: list[PlanStep], dry_run: bool = False
    ) -> list[PlanStep]:
        """Execute a list of planned steps in order."""
        for step in steps[: self.max_steps]:
            step.status = "running"
            if step.tool_name:
                try:
                    step.result = self.registry.execute(
                        step.tool_name, dry_run=dry_run, **step.tool_args
                    )
                    step.status = "completed"
                except Exception as err:  # noqa: BLE001 - step execution error capture
                    step.status = "failed"
                    step.error = str(err)
            else:
                step.status = "completed"
                step.result = f"Completed task: {step.task}"
        return steps
