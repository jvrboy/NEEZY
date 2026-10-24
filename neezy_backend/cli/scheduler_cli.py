"""Scheduler & queue CLI (Batch 8)."""

from __future__ import annotations

import json
from typing import Any

from ..job_queue import JobQueue
from ..scheduler import Scheduler


def cmd_scheduler(args: Any) -> int:
    action = getattr(args, "action", "list")
    sched = Scheduler()
    if action == "list":
        if getattr(args, "json", False):
            print(json.dumps(sched.list_jobs(), indent=2))
        else:
            print(f"{len(sched.jobs)} scheduled jobs")
        return 0
    if action == "add":
        name = getattr(args, "name", "demo")
        job = sched.add_job(
            name, interval_seconds=int(getattr(args, "interval", 60) or 60)
        )
        print(
            json.dumps(job.to_dict(), indent=2)
            if getattr(args, "json", False)
            else f"added {job.id} for {name}"
        )
        return 0
    if action == "tick":
        fired = sched.tick()
        print(
            json.dumps([j.to_dict() for j in fired], indent=2)
            if getattr(args, "json", False)
            else f"fired {len(fired)} jobs"
        )
        return 0
    print("usage: scheduler <list|add|tick>")
    return 1


def cmd_queue(args: Any) -> int:
    action = getattr(args, "action", "stats")
    q = JobQueue()
    if action == "stats":
        print(
            json.dumps(q.stats(), indent=2)
            if getattr(args, "json", False)
            else str(q.stats())
        )
        return 0
    if action == "enqueue":
        name = getattr(args, "name", "task")
        job = q.enqueue(name, priority=int(getattr(args, "priority", 5) or 5))
        print(
            json.dumps(
                {"id": job.id, "name": job.name, "priority": job.priority}, indent=2
            )
        )
        return 0
    if action == "drain":
        jobs = q.drain(limit=int(getattr(args, "limit", 5) or 5))
        print(json.dumps([{"id": j.id, "name": j.name} for j in jobs], indent=2))
        return 0
    print("usage: queue <stats|enqueue|drain>")
    return 1
