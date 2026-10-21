# CHANGELOG

## [1.4.0] - Knowledge Dataset Release

### Added
- **Knowledge datasets** (`neezy_backend/data/`): `market_knowledge.json` (indicator, pattern, risk, and Deriv API reference), `strategy_playbook.json` (per-strategy regimes and metrics), and `model_weights.json` (per-symbol edge weights and confidence derived from the shipped out-of-sample study records).
- **Dataset loader** (`neezy_backend/datasets.py`): cached, path-traversal-safe loading of every shipped JSON dataset with `dataset_summary`, `weight_for`, and `list_datasets`.
- **Insights engine** (`neezy_backend/insights.py`): `insight_line`, `insight_for`, `playbook_entry`, and `knowledge_brief` blending curated knowledge with learned weights.
- **INSIGHTS UI page**: read-only digest of shipped datasets, indicators, patterns, strategies, and per-symbol edge weights.
- **`neezy-cli datasets`** command: dataset inventory plus per-symbol learned-weight lookup.
- **Offline chat upgrade**: the no-provider fallback answer now includes the symbol's caveated learned edge-weight line.
- **Tests**: `tests/test_datasets.py` (11 cases covering loading, validation, path safety, and insights).


## [1.3.0] - Autonomous Upgrade Release

### Added
- **Local CI Verification Script** (`local_ci.py`): One-command local build verification running syntax compilation, linter checks, and pytest test suite.
- **Local Security & Path Sandboxing** (`neezy_backend/storage.py`): Added `sanitize_path` to prevent path traversal attacks outside `NEEZY_HOME`. Added `create_local_backup` and `restore_local_backup` zip utilities.
- **Agent Tool Registry** (`neezy_backend/tools.py`): Typed `ToolRegistry` with schema validation, permission tiers (`READ_ONLY`, `WRITE`, `DESTRUCTIVE`), and dry-run execution mode.
- **Planner/Executor Agent Loop** (`neezy_backend/agent.py`): Multi-step `AgentPlanner` managing goal decomposition, tool execution, and step status tracking.
- **Long-Term Memory Search** (`neezy_backend/database.py`): SQLite FTS5 virtual table (`memory_fts`) for offline keyword and BM25 memory retrieval.
- **Local Evaluation Suite** (`/evals/`): Added benchmark tasks in `evals/tasks.json` and harness runner in `evals/run_evals.py`.
- **Comprehensive Documentation**: Added `docs/ARCHITECTURE.md`, `docs/AGENT.md`, `docs/UI.md`, `docs/LOCAL_SECURITY.md`, `AUDIT.md`, `DECISIONS.md`, `PROGRESS.md`, and `PLAN.md`.
