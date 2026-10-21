# CHANGELOG

## [1.6.0] - Confluence Engine, Data Providers and Card Workspace

### Added
- **Multi-factor confluence engine** (`neezy_backend/confluence.py`): every
  backend tool - EMA stack, MACD, RSI, ADX, Bollinger extremes, all named
  strategies, divergence and the shipped learned edge weights - votes with a
  weight; the weighted net becomes one BUY/SELL verdict with ENTRY, SL (ATR
  stop multiple), TP (ATR target multiple) and a win rate.
- **Win-rate replay**: the engine is trained further on history by finding bars
  whose per-bar confluence proxies match the current reading and replaying each
  analog forward; hit-TP-first versus hit-SL-first counts become the card's WIN
  RATE (sample count and basis are reported, not a forecast).
- **Strict plus search passes**: signals below the strict threshold are
  re-scanned in relaxed search mode, so a scan always yields cardable signals;
  markets with too few candles are reported as errors instead of guessing.
- **Five new named strategies**: ICHIMOKU, STOCH_RSI, MOMENTUM (ROC+ADX),
  RSI_REVERSAL and CCI_REVERSION join the registry and the confluence vote.
- **Market-data providers** (`neezy_backend/providers.py`): Deriv (default
  public WebSocket), Alpha Vantage, Finnhub, Binance and Twelve Data, with
  symbol translation, interval mapping, validated candle normalization and a
  local owner-only `provider-keys.json` key store (environment fallback).
- **Backend analysis agent** (`neezy_backend/scanner.py`):
  `ConfluenceAnalyzer` scans a whole watchlist strict-first, reports per-market
  errors separately, and offers `full_analysis()` strict + search.
- **SIGNALS tab redesign**: signal cards now show exactly INSTRUMENT, BUY/SELL,
  ENTRY, SL, TP, WIN RATE, plus an always-on **ANALYSIS** button that runs the
  full backend over the watchlist, persists every card locally and updates the
  overview counters.
- **HISTORY tab redesign**: the same card fields plus one of exactly two
  outcomes, TP or SL (the stop fills first when both levels sit inside one
  candle); pending cards resolve automatically from locally stored candles and
  the store refuses any third outcome value.
- **SETTINGS > DATA PROVIDERS tab**: provider selector, local API-key save/scan,
  provider test, fetched-candle count, and six persisted confluence controls
  (strict score, search score, ATR stop/target multiples, outcome horizon,
  minimum analog samples) validated in `AppSettings`.

### Verification
- 367 tests pass (2 environment skips); ruff lint and format clean; full
  compile clean; fake-tk app construction passes with the new tabs and cards.

## [1.5.1] - Imported Knowledge Base and Second Training Capture

### Added
- Ten new knowledge datasets built from the user-supplied DATA.zip knowledge
  base (fundamentals, risk, Deriv synthetics incl. DSI, correlation, strategy
  hypothesis library, validation method, psychology, decision rules, 55 Q&A
  pairs, index) with per-file provenance hashes and sourced enrichment.
- Second fresh-data training capture (33,000 new candles, 22 staged MLP refits,
  6 re-run Forex pair experiments) with re-verified raw OHLC hashes.

### Verification and caveats
- All datasets parse, are deduplicated by id/question, and symbols referenced
  by the Deriv synthetic dataset resolve in the bundled catalogue.
- DSI20 again led screening at 66.85% held-out balanced accuracy; directional
  screening is not a profitability or significance test. DSI remains
  history-only access. All six FX pair simulations remained net negative after
  assumed costs; no trades were executed.


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
