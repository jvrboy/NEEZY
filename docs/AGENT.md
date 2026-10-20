# NEEZY Agent Architecture, Tools, Memory, Evals & Local Training

## Overview

The NEEZY agent is a local, privacy-first quantitative market copilot built directly into the desktop workspace.

---

## Agent Capabilities & Planner Loop

The agent utilizes a structured **Planner/Executor** design pattern (`neezy_backend/agent.py`):
1. **Goal Decomposition**: Deconstructs high-level queries into sequential, typed `PlanStep` objects.
2. **Tool Selection**: Queries the `ToolRegistry` (`neezy_backend/tools.py`) for available schema-validated tools.
3. **Execution & Guardrails**: Executes steps with explicit permission checks (`READ_ONLY`, `WRITE`, `DESTRUCTIVE`) and support for dry-run simulation mode.

---

## Long-Term Memory (SQLite + FTS5)

- Stored in the local `neezy.sqlite3` database under `memory_items` and `memory_fts`.
- Utilizes SQLite FTS5 full-text indexing for fast, offline BM25 keyword and context retrieval.
- `search_memory(query)` retrieves relevant historical trade notes, market snapshots, and user interaction history.

---

## Local Evaluation Harness (`/evals`)

- **Tasks Benchmark**: Defined in `evals/tasks.json` with expected outputs and evaluation criteria.
- **Harness Runner**: Executed via `evals/run_evals.py` or local CI checks.
- **Scoring**: Computes pass/fail rates across tasks to track agent response regression across updates.
