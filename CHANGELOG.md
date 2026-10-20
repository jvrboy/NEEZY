# CHANGELOG

## [1.3.0] - Autonomous Upgrade Release

### Added
- **Local CI Verification Script** (`local_ci.py`): One-command local build verification running syntax compilation, linter checks, and pytest test suite.
- **Local Security & Path Sandboxing** (`neezy_backend/storage.py`): Added `sanitize_path` to prevent path traversal attacks outside `NEEZY_HOME`. Added `create_local_backup` and `restore_local_backup` zip utilities.
- **Agent Tool Registry** (`neezy_backend/tools.py`): Typed `ToolRegistry` with schema validation, permission tiers (`READ_ONLY`, `WRITE`, `DESTRUCTIVE`), and dry-run execution mode.
- **Planner/Executor Agent Loop** (`neezy_backend/agent.py`): Multi-step `AgentPlanner` managing goal decomposition, tool execution, and step status tracking.
- **Long-Term Memory Search** (`neezy_backend/database.py`): SQLite FTS5 virtual table (`memory_fts`) for offline keyword and BM25 memory retrieval.
- **Local Evaluation Suite** (`/evals/`): Added benchmark tasks in `evals/tasks.json` and harness runner in `evals/run_evals.py`.
- **Comprehensive Documentation**: Added `docs/ARCHITECTURE.md`, `docs/AGENT.md`, `docs/UI.md`, `docs/LOCAL_SECURITY.md`, `AUDIT.md`, `DECISIONS.md`, `PROGRESS.md`, and `PLAN.md`.
