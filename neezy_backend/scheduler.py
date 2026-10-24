"""Advanced backend scheduler (Batch 8).

Lightweight cron-like scheduler with in-memory jobs, fixed/cron/backoff policies.
Stdlib only, deterministic tick advancing for tests.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import AppSettings

JobFn = Callable[[], Any]


@dataclass
class Job:
    id: str
    name: str
    policy: str  # fixed, cron, exponential_backoff
    interval_seconds: int
    payload: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    next_run_at: float = 0.0
    runs: int = 0
    failures: int = 0
    last_result: Any = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "policy": self.policy,
            "interval_seconds": self.interval_seconds,
            "payload": self.payload,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at,
            "runs": self.runs,
            "failures": self.failures,
            "last_result": str(self.last_result)[:200] if self.last_result else None,
            "created_at": self.created_at,
        }


class Scheduler:
    """In-memory scheduler; advance via tick()."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()
        self.jobs: dict[str, Job] = {}
        self.handlers: dict[str, JobFn] = {}

    def register(self, name: str, fn: JobFn) -> None:
        self.handlers[name] = fn

    def add_job(
        self,
        name: str,
        *,
        interval_seconds: int | None = None,
        policy: str | None = None,
        payload: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> Job:
        cfg = self.settings
        interval = (
            interval_seconds
            if interval_seconds is not None
            else cfg.scheduler_tick_seconds
        )
        pol = policy or cfg.scheduler_policy
        if pol not in ("fixed", "cron", "exponential_backoff"):
            raise ValueError(f"unknown policy {pol!r}")
        jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
        job = Job(
            id=jid,
            name=name,
            policy=pol,
            interval_seconds=max(5, interval),
            payload=payload or {},
            next_run_at=time.time() + max(5, interval),
        )
        self.jobs[jid] = job
        return job

    def remove(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    def tick(self, now: float | None = None) -> list[Job]:
        """Run due jobs; returns list of jobs that fired."""
        t = now if now is not None else time.time()
        fired: list[Job] = []
        for job in list(self.jobs.values()):
            if not job.enabled or t < job.next_run_at:
                continue
            fn = self.handlers.get(job.name)
            try:
                job.last_result = fn() if fn else {"ok": True, "name": job.name}
                job.runs += 1
                fired.append(job)
            except Exception as exc:
                job.failures += 1
                job.last_result = f"error: {exc}"
            # reschedule
            if job.policy == "exponential_backoff" and job.failures:
                delay = job.interval_seconds * (2 ** min(job.failures, 5))
            else:
                delay = job.interval_seconds
            job.next_run_at = t + delay
        return fired

    def list_jobs(self) -> list[dict[str, Any]]:
        return [j.to_dict() for j in self.jobs.values()]

    def enable(self, job_id: str, enabled: bool = True) -> bool:
        j = self.jobs.get(job_id)
        if j is None:
            return False
        j.enabled = enabled
        return True
