# NEEZY Autonomous Upgrade Roadmap & Execution Plan

## Roadmap Batches

### Batch 1: Safety Net, Quality & Local CI Script Setup
- Implement `local_ci.py` script running syntax compilation, ruff linting, and pytest suite.
- Status: Completed.

### Batch 2: Local Security, Path Sandboxing & Backup Infrastructure
- Enhance `neezy_backend/storage.py` with `sanitize_path`, `create_local_backup`, and `restore_local_backup`.
- Status: Completed.

### Batch 3: Backend Agent Tool Registry & Capability Tools
- Implement `ToolRegistry` and `ToolPermission` in `neezy_backend/tools.py`.
- Status: Completed.

### Batch 4: Planner/Executor Agent Loop & Hybrid Memory Engine
- Implement `AgentPlanner` in `neezy_backend/agent.py` and FTS5 memory search in `neezy_backend/database.py`.
- Status: Completed.

### Batch 5: Local Evals Harness & Training/Improvement Pipeline
- Add benchmark evaluation harness in `evals/run_evals.py` and tasks in `evals/tasks.json`.
- Status: Completed.

### Batch 6 & 7: Enterprise Design System, Shell & Modern Screens
- Modernize theme tokens, layouts, and desktop views in `neezy_app/ui.py`.
- Status: Completed.

### Batch 8: Documentation Deliverables
- Populate `docs/ARCHITECTURE.md`, `docs/AGENT.md`, `docs/UI.md`, `docs/LOCAL_SECURITY.md`, `CHANGELOG.md`, `PLAN.md`, and `README.md`.
- Status: Completed.
