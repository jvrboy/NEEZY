"""Priority job queue with retries and dead-letter (Batch 8)."""

from __future__ import annotations

import heapq
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import AppSettings


@dataclass(order=True)
class QueuedJob:
    priority: int
    created_at: float = field(compare=False)
    id: str = field(compare=False)
    name: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)
    attempts: int = field(compare=False, default=0)
    max_attempts: int = field(compare=False, default=3)


class JobQueue:
    """Heap-based priority queue with retry/backoff and dead-letter."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()
        self._heap: list[QueuedJob] = []
        self.dead_letter: list[QueuedJob] = []
        self.completed: list[QueuedJob] = []
        self._seen: set[str] = set()

    def enqueue(
        self,
        name: str,
        *,
        priority: int = 5,
        payload: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> QueuedJob:
        if len(self._heap) >= self.settings.queue_max_size:
            raise OverflowError("queue is full")
        jid = job_id or f"q-{uuid.uuid4().hex[:8]}"
        job = QueuedJob(
            priority=priority,
            created_at=time.time(),
            id=jid,
            name=name,
            payload=payload or {},
            max_attempts=self.settings.queue_retry_limit or 3,
        )
        heapq.heappush(self._heap, job)
        self._seen.add(jid)
        return job

    def dequeue(self) -> QueuedJob | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)

    def requeue_failed(self, job: QueuedJob) -> bool:
        """Re-enqueue with backoff penalty; dead-letter if exhausted."""
        job.attempts += 1
        if job.attempts >= job.max_attempts:
            self.dead_letter.append(job)
            return False
        # Demote priority slightly on retry
        job.priority = min(10, job.priority + 1)
        heapq.heappush(self._heap, job)
        return True

    def complete(self, job: QueuedJob) -> None:
        self.completed.append(job)

    def size(self) -> int:
        return len(self._heap)

    def stats(self) -> dict[str, Any]:
        return {
            "pending": len(self._heap),
            "completed": len(self.completed),
            "dead_letter": len(self.dead_letter),
            "max_size": self.settings.queue_max_size,
        }

    def drain(self, limit: int = 10) -> list[QueuedJob]:
        out: list[QueuedJob] = []
        for _ in range(min(limit, len(self._heap))):
            j = self.dequeue()
            if j:
                out.append(j)
        return out
