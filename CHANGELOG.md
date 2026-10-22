# CHANGELOG

## [Unreleased] — Batch 5: stream hardening & event contracts (roadmap #15,#38,#41; total 51/500)

### Changed
- `neezy_backend/stream.py`: the websocket boundary parsers were hardened.
  `parse_candle` now converts missing/invalid fields (including the
  `OverflowError` from `int(inf)` and `TypeError` from non-mapping input)
  into `ValueError` with a clear message, and `parse_history_response`
  rejects non-object payloads up front. Mutated wire data can no longer
  escape the parser as an arbitrary `KeyError`/`TypeError`/`OverflowError`.
- `neezy_backend/events.py`: every core event kind now has an explicit
  payload contract (`PAYLOAD_CONTRACTS`, plus a `ClosedPayload` TypedDict).
  `EventBus(validate_payloads=True)` — or the new `debug_bus()` factory —
  enforces the contracts at publish time for tests and development runs;
  production buses keep the historical unchecked behaviour.

### Added
- `tests/test_fuzz_stream.py`: 27 seeded mutation-fuzz tests over
  `parse_candle`/`parse_history_response` (value junk, missing fields,
  structural mutants, OHLC consistency swaps, API error shapes). The fuzz
  run found and fixed a real parser gap (`epoch: inf` escaping as
  `OverflowError`).
- `tests/test_event_contracts.py`: 11 tests pinning the contract table,
  validation-mode failures (with kind/expected/actual in the message), and
  the open-for-extension rule for app-level event kinds.
- `tests/test_stream_races.py`: 6 lifecycle stress tests against a fake
  `WebSocketApp` — concurrent start/stop/send from six threads, idempotent
  stop, stop-from-callback (no self-join), send-after-stop, exactly-once
  `stopped` event, and restart cycles.

### Fixed
- `tests/test_cli_golden.py`: JSON golden snapshots now compare with
  float tolerance (`math.isclose`, rel 1e-9) after CI exposed that
  `statistics`-based correlation values drift 1-2 ULPs between Python
  3.10/3.11 and 3.12. Structure, strings, and plain-text fixtures stay
  byte-exact; failures now report the first differing JSON path.

### Verified
- Full local CI (`local_ci.py --full`): compile, ruff check, ruff format,
  and **869 tests OK** (842 → +27), fully offline.

## [Unreleased] — Batch 4: foundations wave wrap-up (roadmap #1-#40, 8 items; total 48/500)

### Changed — architecture
- `neezy_backend/cli.py` (2,081 lines) became the `neezy_backend/cli/` package:
  `common` (output/argument helpers), `parser` (argparse construction),
  `analysis`, `backtest`, `research`, `db`, `alerts`, `ai`, `mt5`, `mcp`,
  `dm`, and `menu_bridge` — one module per command family. The console
  script (`neezy_backend.cli:main`), every public name, and the
  `mock.patch.object(cli, ...)` targets used by the tests are unchanged.
- `neezy_backend/ai.py` (834 lines) became the `neezy_backend/ai/` package:
  `errors` (result + exception hierarchy), `prompts`, `providers`
  (catalogue), `keystore` (key vault), `transport` (injectable HTTP layer,
  request building, response parsing), and `client` (key-rotating
  failover). The historical public surface is re-exported; `ai_cache` and
  `ai_resilient` continue to work on top unchanged.
- `storage.sanitize_path` is now a thin wrapper over
  `sandbox.resolve_within`, making the sandbox the single traversal guard.
  The `allow_absolute` escape hatch is kept, documented, and tested. The
  unification tests caught a real wrapper bug (relative paths in the escape
  hatch resolved against the CWD instead of the sandbox root) — fixed.
- `ConfluenceSignal`/`ConfluenceFactor` gained `from_dict` /
  `from_history_record` constructors with per-field validation and
  forward-compatible unknown-key tolerance; `ConfluenceHistoryStore` gained
  typed `append_signal`/`read_signals` accessors and the signals panel now
  writes through them.
- `neezy_backend/datasets.py` is a versioned, migrating loader:
  `schema_version: 1` stamped into all 27 shipped datasets (including
  `research_candles/*`), legacy files migrate forward in memory, and future
  versions fail loudly with file/version/max-supported in the message.

### Added — testing
- `tests/test_indicator_properties.py`: 80 stdlib-random property tests for
  the indicator math (bounds, length contracts, Wilder-recurrence oracles,
  flat/spike/short-series edges). Four known quirks pinned with notes.
- `tests/test_cli_golden.py` + `tests/golden/` (48 fixtures, 27 tests):
  golden snapshots of every read-only CLI command, plain and JSON, with a
  deterministic seeded fetcher and `NEEZY_UPDATE_GOLDEN=1` regen mode.
- `tests/test_e2e_pipeline.py`: 9-test scripted offline session — stream
  candle validation, engine + confluence flip across a trend reversal, an
  alert that fires exactly once, card-history round-trip, outcome
  resolution (SL and TP), and CLI JSON payload equality.
- `tests/test_signal_protocol.py` (21 tests) and
  `tests/test_storage_sanitize.py` (11 tests) pin the new contracts.

### Verified
- Full local CI (`local_ci.py --full`): compile, ruff check, ruff format,
  and **842 tests OK** (682 at batch start → +160), fully offline.

## [Unreleased] — Batch 3: caching & storage hygiene (roadmap #105-#164, 8 items; total 40/500)

### Added
- `neezy_backend/providers.py`: `ProviderResponseCache` — a 30 s TTL,
  bounded-size cache in front of live provider fetches (injected test
  fetchers bypass it). Repeated analysis inside the window no longer hammers
  provider rate limits; `invalidate()` and `stats()` included.
- `LocalDatabase.maintenance()`: one cheap maintenance pass — truncates the
  WAL (`PRAGMA wal_checkpoint(TRUNCATE)`) and rotates snapshot rows older than
  the retention window. Safe on a timer or before backups.
- `tests/test_perf_smoke.py`: generous ceilings that catch order-of-magnitude
  regressions (indicator analysis 5 k candles < 2 s, bulk insert < 3 s, cache
  hits) plus `ProviderResponseCache` unit tests (TTL expiry, eviction, copy
  isolation).

### Changed
- `LocalDatabase` connection setup now sets `wal_autocheckpoint=1000` and
  `busy_timeout=10000` so the WAL cannot grow unbounded between prunes.
- `create_local_backup` prunes the backups directory oldest-first beyond 20
  archives (`prune_backups`, configurable) — the directory can no longer grow
  unbounded.
- `SignalHistoryStore` compacts an oversized history file at construction
  (bounded to one rewrite of the newest records) instead of only on the next
  append.

### Verified closed (no change needed)
- Roadmap #133 (config `to_dict` caching): exactly one call site and 91 scalar
  fields — caching would be premature; decision documented in code.
- Roadmap #136 (symbol catalog load-once): already implemented via
  `lru_cache(maxsize=1)` in `neezy_backend/catalog.py`.

## [Unreleased] — Batch 2: architecture & tooling (roadmap #8-#87, 12 items; total 32/500)

### Added
- `neezy_app/theme.py`: the three theme palettes extracted from the App shell
  into testable design tokens (`THEME_PALETTES`, `palette_for`, `validate_palette`);
  nine new theme tests.
- `neezy_backend/capabilities.py`: runtime feature flags (MT5, Kivy, numpy,
  FTS5, local LLM) with a `feature_report()` snapshot for doctor/diagnostics.
- `tests/test_api_contracts.py`: locks every public export and key signature of
  the `neezy_backend` package against accidental breaking changes.
- MCP protocol robustness tests (malformed JSON, GET on POST endpoint,
  oversized bodies, wrong content type, survival after hostile input).
- `tests/test_provider_errors.py`: provider HTTP failure matrix (401/403/429/
  500, timeouts, network errors) proving typed `ProviderError`s that never leak
  the API key into messages.
- `tests/test_doctests.py`: doctest gate plus runnable examples in `quant.py`
  and `risk.py` (Kelly fraction, VaR, efficiency ratio, ATR levels).
- `tests/test_error_messages.py`: error-quality contract (fields named, bounds
  stated, guidance included).
- `RELEASING.md` (release runbook) and `CONTRIBUTING.md` (code map + rules).
- `scripts/gen_settings_docs.py` + generated `docs/SETTINGS.md`: every one of
  the 91 settings fields documented with default and UI location.

### Changed
- `neezy_backend/menu.py`: the palette dispatch if-chain is now the
  `ARGV_BUILDERS` table — adding a menu entry is one entry, not one branch.
- `local_ci.py`: `--full` widens lint to the whole tree (kaggle notebook
  included), and all child processes run with stdin=/dev/null so menu tests
  can never hang a headless run (parity with CI).

## [Unreleased] — Batch 1: foundations (roadmap updates #21-#90, 20 items)

### Fixed
- `neezy_backend/exporters.py` `signals_to_csv` (and `export_bundle`) crashed
  with `TypeError: 'newlines' is an invalid keyword argument for StringIO()` —
  shipped broken since the enterprise-exporters commit; no test covered it.
  The CSV exporter now works and its schema is pinned by tests.
- `neezy_backend/knowledge.py` `record_for` returned a shallow copy, so
  mutating nested `train`/`test` stats leaked into the shared document; it
  now returns a deep copy.
- `neezy-cli risk` without `--stop`/`--direction`/`--atr` now exits 2 (usage
  error, consistent with the documented exit-code contract) instead of 1.

### Changed
- `neezy_backend/config.py` `STRATEGIES` is now derived from the engine's
  single-market strategy registry (`SINGLE_MARKET_STRATEGIES`) instead of a
  hand-maintained duplicate; adding a strategy no longer needs three edits.
- `neezy_backend/risk.py` gains `resolve_stop()` (explicit-stop or
  ATR-derived levels with validation); `cmd_risk` uses it instead of inline
  logic.
- `SettingsStore.load` logs a warning (logger `neezy.settings`) when the
  settings file is corrupt, invalid, or contains unknown fields, instead of
  silently falling back to defaults.
- `neezy-cli --debug` prints the full traceback for command failures.

### Added
- Nine new test modules (+95 tests, suite now 630): alert operator matrix,
  outcome boundary (stop-first rule), exhaustive settings bounds, backtest
  determinism, knowledge round-trip, exporter schema stability, CLI exit-code
  contract, sandbox escape attempts, settings corruption recovery.
- `tests/__init__.py` promotes `ResourceWarning` to an error so unclosed
  stores/databases fail CI (suite is clean).
- Developer tooling: `scripts/dev_setup.sh` + `scripts/dev_setup.ps1`
  (one-command environment), `Makefile` (test/lint/format/ci/run/clean),
  `.pre-commit-config.yaml` (ruff gates), and `.github` issue + PR templates.

## [Unreleased] - Autonomous engineering run (Phase 2: quality gates restored)

### Fixed
- CI is green again: all 24 ruff errors in the CI lint path resolved
  (`neezy_app/glass.py`, `neezy_backend/quant.py`, `neezy_backend/exporters.py`)
  and the 4 unformatted files reformatted. `ruff check .` (whole tree, including
  the kaggle notebook) is clean.
- `tests/test_enterprise_ui.py` failure: `PAGE_TITLES` in
  `neezy_app/enterprise.py` lacked the `ORDERS` entry added with the ORDERS
  page; it now maps to "ORDER DESK".
- `neezy_backend/menu.py` `run_menu` bound the builtin `input` as a default
  argument at import time, so `mock.patch("builtins.input")` had no effect and
  interactive-stdin environments hung in a prompt loop. The default is now
  resolved at call time. Regression test added.
- `neezy_backend/storage.py` `SettingsStore.save` now chmods `settings.json`
  to 0o600 on POSIX (the file stores the MT5 password), matching every other
  secret store. Regression test added.
- `neezy_backend/quant.py`: redundant `int()` casts around `math.floor`
  removed; `zip(..., strict=True)` where lengths must match;
  `itertools.pairwise` for successive pairs; long lines split.
- `kaggle/NEEZY_on_Kaggle.ipynb`: 19 lint findings fixed (line length,
  blind-except noqa, unused loop variable, iterable unpacking).

### Added
- Root `ARCHITECTURE.md`: authoritative architecture reference verified
  against this tree (supersedes `docs/ARCHITECTURE.md`).
- Root `AUDIT.md`: refreshed with this run's measured baseline and findings.
- `HANDOFF.md`: run memory for the 500-update engineering program.

## [Unreleased] - Neural model types

### Added
- Desktop ORDERS page (`neezy_app/ui_panels/orders.py`). It places a live MT5
  market order after a confirmation dialog that defaults to No. It refuses
  unless the saved MT5 bridge toggle is on and the terminal is live. Preview is
  local and sends nothing.
- `neezy_backend/mt5_orders.py` holds the live-order gate, shared by the CLI and
  the desktop. The CLI's `mt5 order --confirm` path now uses the same terminal
  check. Its refusal messages are unchanged.
- `tests/test_mt5_orders.py` covers the ticket parser, the terminal gate, the
  send refusals, and the confirmation text. It uses a fake `mt5` module, so no
  test reaches a real terminal.

### Changed
- DECISIONS.md Decision 6 is amended to allow desktop placement behind the
  confirmation dialog and the bridge toggle.

### Notes
- The ORDERS page was not run in a real window. The sandbox has no display.
  Its tests cover the gate and the send path, and the Tk wiring is checked by
  import only.

### Added (neural model types)
- `train_model(..., model_type=...)` in `neezy_backend/brain.py` now accepts two
  new layouts next to the default `neezy_mlp_v1`:
  - `neezy_mlp_ensemble_v1` (`members`, 2 to 25, default 5): bagged MLPs, each
    trained on a bootstrap resample of the training partition. Prediction is the
    member average. `probability_spread` (standard deviation across members) is
    reported as a rough uncertainty estimate.
  - `neezy_seq_mlp_v1` (`window`, 2 to 40, default 10): an MLP over the last
    `window` log returns, each divided by the current ATR as a fraction of price,
    plus the eight v1 features.
- `validate_model` accepts the three types and rejects anything else. Ensemble
  members and sequence windows are checked for dimensions and finite weights.
- `sequence_feature_names(window)` describes the sequence feature layout.

### Notes
- `neezy_mlp_v1` is unchanged. Training with the same seed produces the same
  model document as before; the report gains a `model_type` field.
- All three types share the same chronological split, purge, scaling, and
  deployment gate.
- The deployment gate is unchanged. A new type is not `deployment_ready` unless
  its held-out test set clears the same thresholds as v1.
- Only the Python API selects a model type. The CLI, menu, and desktop panels
  still train `neezy_mlp_v1`.
- `probability_spread` is shown in `predict` output but does not yet gate the
  BUY/SELL direction. A wide spread does not turn a signal into NEUTRAL.

## [Unreleased] - Market regime and correlation snapshot

### Added
- `neezy_backend/regime.py`: `market_regime(candles)` labels a market
  `trend_up`, `trend_down`, `range`, `squeeze`, or `unknown` (fewer than 60
  closed candles), with an ATR-ratio volatility label. Uses closed candles only.
  Thresholds are fixed (ADX 25, bottom-20% bandwidth) and named in the module.
- `correlation_snapshot` in `neezy_backend/analytics.py`: matrix and strongest
  pairs over a window of log returns, rounded for display.
- `neezy-cli regime SYMBOL [-t TF] [-n N] [--json]` and menu key `r`.
- Read-only agent tools `market_regime` and `correlation_snapshot` (the latter
  takes up to 8 comma-separated markets; defaults to the five Forex majors).
- Private MCP tools `get_market_regime` and `get_correlation_snapshot` on stored
  candles. They are not on the public tunnel allow-list.

### Notes
- `analyze` already prints a `regime` label (Trending, Ranging, Squeeze). The
  new classifier adds direction and a bandwidth percentile, so the two can
  disagree near thresholds. Both are descriptive, not signals.
- ADX reads 25 or higher fairly often on random-walk data. Treat a trend label
  as a description of recent directional movement, not a forecast.

## [Unreleased] - CLI menu styling

### Changed
- **`neezy-cli menu` redesigned**: header panel with a status bar, a grouped
  palette (System, MT5 read-only, MT5 orders, MCP, Exit), and a prompt.
  Type `/text` to filter the palette, `?` for help, `q` to quit. Each run
  echoes its command and ends with an `[exit N]` badge.
- Enter on an empty line redraws the palette. It used to quit. `q`, `0`,
  `quit`, Ctrl-C and end-of-input all exit cleanly.
- Styling is ASCII only and follows `NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`,
  and whether the stream is a TTY. `neezy-cli menu --plain` turns colour off.
  JSON output from other commands is not styled.

### Added
- `neezy_backend/ui_style.py`: colour decision, Windows VT enablement, panel
  and key-line helpers. Stdlib only.

## [Unreleased] - Gated MT5 bridge and UI split

### Changed
- **Live MT5 orders are gated**: `neezy-cli mt5 order` requires `--confirm`;
  `--dry-run` previews without contacting the terminal. `place_order` refuses
  when MT5 is disconnected instead of returning a fake success.
- **Agent and MCP paths are read-only for orders**: WRITE and DESTRUCTIVE tools
  raise `PermissionError` unless `confirm=True`; `dry_run` never calls the tool.
- **MT5 reads fail closed**: when the terminal is not connected, account, quote,
  candle and position reads return an error, not sample data. Simulated output
  is labelled `[SIMULATED - bridge in mock mode]`.
- **Desktop UI split**: `neezy_app/ui.py` delegates each screen to a module in
  `neezy_app/ui_panels/`. Behaviour is unchanged.
- **README and DECISIONS** corrected: NEEZY can place MT5 orders, but only
  behind the confirmation gate.

### Added
- `neezy-cli menu`: terminal menu. Live orders need the typed word `SEND`.
- `neezy-cli mt5 preflight`: checks the terminal without placing orders or
  printing passwords.
- `neezy-cli mcp list | show | config`: catalogues six third-party MCP servers.
  Catalogued only; nothing is installed or run.
- Read-only MT5 tools `mt5_positions`, `mt5_candles`, `mt5_account_history`
  (MCP) and `mt5_history` (agent). None are on the public tunnel.

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
