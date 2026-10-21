# CHANGELOG

## [1.5.0] - Fresh Public-Data Research and Settings

### Added
- Real staged MLP training: 11 markets x 3,000 fresh Deriv candles, initial/final
  chronological reports, 11 learned models, source timestamps and raw-data hashes.
- Raw JSON candle snapshots and neural research report included in package data.
- Timestamp-aligned, train-only hedge estimation and lagged, cost-aware Forex pair
  research; six held-out experiments retained, including their negative returns.
- Dedicated history-only DSI research selector, live public-data refit action,
  saved-FX-pair research action, and neural/pair findings in INSIGHTS.
- ML RESEARCH and PAIR RESEARCH settings tabs with 17 validated, persisted controls.
- `neezy-cli research status/train`, same-timeframe shipped-model fallback, and
  three read-only private MCP research tools.

### Fixed
- Prior lint/format regressions, enterprise INSIGHTS glyph/title, initial insight
  loading and numeric ranking; ordinary learned chat context respects opt-in.
- Dataset path/symlink escapes and mutable shared cache results.
- UI regression tests no longer start real connections or leak test sockets.
- Local CI now fails on lint/format errors and does not require undeclared pytest.
- Corrected educational API subscription/granularity/RSI notes; legacy derived
  weights are explicitly labelled heuristics rather than neural training.
- Package metadata/version aligned at 1.5.0 with nested raw-data inclusion.

### Verification and caveats
- 313 tests passed locally with no skips, plus Ruff, syntax, actual Tk enterprise,
  CLI and wheel checks. GitHub-hosted CI failure remains unverified: bridge logs 404.
- DSI10/20/30 passed directional holdout screening, not a profitability test.
  Current DSI candles were available; tick subscriptions rejected those symbols.
- Volatility/Forex neural models remained research-only; all six FX-pair net
  simulations were negative after assumed costs. No trades were executed.


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
