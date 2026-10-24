"""Orchestrator: DAG execution for multi-model neural and reasoning pipelines."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TaskFn = Callable[[dict[str, Any]], Any]


@dataclass
class Task:
    id: str
    name: str
    depends_on: list[str] = field(default_factory=list)
    fn: TaskFn | None = None
    timeout_seconds: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "depends_on": self.depends_on,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class RunResult:
    task_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


class Orchestrator:
    """Simple DAG executor with parallel groups (sequential for determinism)."""

    def __init__(self, max_parallel: int = 4) -> None:
        self.max_parallel = max_parallel
        self.tasks: dict[str, Task] = {}

    def add_task(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"task {task.id!r} already exists")
        self.tasks[task.id] = task

    def topological_order(self) -> list[str]:
        visited: set[str] = set()
        temp: set[str] = set()
        order: list[str] = []

        def visit(n: str) -> None:
            if n in temp:
                raise ValueError(f"cycle detected at {n!r}")
            if n in visited:
                return
            temp.add(n)
            task = self.tasks.get(n)
            if task is None:
                raise KeyError(f"unknown task {n!r}")
            for dep in task.depends_on:
                visit(dep)
            temp.remove(n)
            visited.add(n)
            order.append(n)

        for tid in list(self.tasks):
            visit(tid)
        return order

    def run(self, context: dict[str, Any] | None = None) -> dict[str, RunResult]:
        ctx = dict(context or {})
        results: dict[str, RunResult] = {}
        order = self.topological_order()
        for tid in order:
            task = self.tasks[tid]
            start = time.time()
            try:
                # If any dependency failed, skip
                if any(not results[d].ok for d in task.depends_on if d in results):
                    results[tid] = RunResult(
                        task_id=tid, ok=False, error="dependency failed"
                    )
                    continue
                out = task.fn(ctx) if task.fn else {"task": task.name}
                # Allow task to write to shared context
                if isinstance(out, dict) and "context_update" in out:
                    ctx.update(out["context_update"])
                results[tid] = RunResult(
                    task_id=tid,
                    ok=True,
                    output=out,
                    duration_ms=int((time.time() - start) * 1000),
                )
            except Exception as exc:
                results[tid] = RunResult(
                    task_id=tid,
                    ok=False,
                    error=str(exc),
                    duration_ms=int((time.time() - start) * 1000),
                )
        return results

    def summary(self, results: dict[str, RunResult]) -> dict[str, Any]:
        ok = sum(1 for r in results.values() if r.ok)
        return {
            "total": len(results),
            "ok": ok,
            "failed": len(results) - ok,
            "ids": list(results),
        }
