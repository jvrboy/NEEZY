# NEEZY Autonomous Upgrade Roadmap & Execution Plan

> Truthful status as of 2026-10-24. The older `docs/ARCHITECTURE.md` is superseded by root `ARCHITECTURE.md`.
> `evals/` and `neezy_backend/prompts/` do not exist yet — they are tracked in `ROADMAP.md`, not claimed complete.

## Roadmap Batches (completed)

### Batch 1: Safety Net, Quality & Local CI Script Setup
- `local_ci.py` (compile + ruff + unittest), Makefile, pre-commit.
- **Status:** Completed (57/500 → baseline for autonomous run).

### Batch 2: Local Security, Path Sandboxing & Backup Infrastructure
- `storage.sanitize_path` → `sandbox.resolve_within`, backups, chmod 0600.
- **Status:** Completed.

### Batch 3: Backend Agent Tool Registry & Capability Tools
- `ToolRegistry` + `ToolPermission` tiers, sandbox path jail.
- **Status:** Completed.

### Batch 4: Planner/Executor Agent Loop & Hybrid Memory Engine
- `AgentPlanner` + FTS5 memory (BM25 + TF-IDF fallback).
- **Status:** Completed.

### Batch 5: Cloud/Light-Executor + Confluence + Scanner
- Cloud executor, confluence engine, providers, SCANNER, cloud ops guide.
- **Status:** Completed (branch `arena/55d4b77d-neezy`, documented in `PROGRESS.md`).

### Batch 6: Foundations & DevEx sweep (this branch, `arena/b490d7c9-neezy`)
- Notifier ports/adapters (#13), snapshot helper (#24), launcher deprecation (#26), menu width (#30), capability flags (#32), coverage (#44), API docs (#78), timing (#81), summary artifact (#82), pin check (#83), devcontainer (#84), changelog gate (#86), config migration (#91), watchlist I/O (#94), timezone helper (#95), dry-run flag (#100), prepared cache (#108), WAL checkpoint (#109).
- **Status:** In progress (18 items, see `IMPLEMENTATION_PLAN.md`).

## Remaining work

- **Batches 7–13:** 425 items across testing, architecture, caching, config, AI, security, packaging, polish — tracked in `ROADMAP.md` (single source of truth) and `IMPLEMENTATION_PLAN.md`.

## How we work

1. One batch = one coherent PR to `main`, green gates (`python local_ci.py --full` + CI).
2. Mark each ROADMAP entry `[x]` with a one-line note; append `CHANGELOG.md`.
3. `HANDOFF.md` records the next step for autonomous handoff.
4. PLAN.md is the narrative; ROADMAP.md is the ledger.

## Known deferred dirs

- `evals/` (benchmark harness) — not yet created; use `python -m unittest discover -s tests` per `docs/AGENT.md`.
- `neezy_backend/prompts/` — not yet created; DECISIONS.md tracks intent.
