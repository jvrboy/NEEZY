# NEEZY — 500-Update Engineering Roadmap

Exactly 500 numbered, substantial updates, ordered foundations-first
(architecture, tests, config → engine → capabilities → operations → polish).
Each entry: title, category, what it does, why it matters, areas affected,
difficulty (Easy / Medium / Hard / Expert). Status is marked in place as
batches complete: `[x]` done, `[ ]` pending, `[~]` in progress, `[!]` blocked.

Legend at a glance:

- Waves: 1 Foundations (1-100) · 2 Engine (101-200) · 3 Capabilities (201-300)
  · 4 Operations (301-400) · 5 Polish (401-500)
- Batches: each batch implements a coherent set of roadmap updates and is
  committed and pushed to `main` with tests, docs, and changelog updates.


---

## Wave 1 — Foundations: architecture, testing, developer experience, configuration

### 1. [ ] Split CLI monolith into command modules
- **Category:** Architecture & refactoring
- **What:** Break neezy_backend/cli.py (2,070 lines) into a package: cli/__init__.py with main(), cli/research.py, cli/mt5.py, cli/ai.py, cli/db.py, cli/mcp.py, cli/menu_bridge.py etc., one module per command family.
- **Why:** The 25 command groups in one file are hard to navigate, review, and test in isolation; a package allows parallel work and per-group unit tests.
- **Areas:** neezy_backend/cli.py, tests/test_*cli*.py, pyproject.toml (entry point unchanged)
- **Difficulty:** Medium

### 2. [ ] Extract a candle accessor layer
- **Category:** Architecture & refactoring
- **What:** Introduce neezy_backend/candles.py as the single API (fetch, cache, persist, read) that today is spread across stream.py, database.py, providers.py and research paths.
- **Why:** Four modules currently hand-roll candle retrieval; one accessor removes duplicated validation and lets storage backends swap in later.
- **Areas:** neezy_backend/{stream,database,providers,research}.py, consumers in cli.py and ui panels
- **Difficulty:** Hard

### 3. [ ] Define a Signal dataclass protocol
- **Category:** Architecture & refactoring
- **What:** Replace ad-hoc signal dicts flowing between confluence, alerts, history, UI, and exporters with a frozen Signal dataclass plus to_dict/from_dict.
- **Why:** Dict key typos are invisible until runtime; a typed contract catches them at construction and documents the schema once.
- **Areas:** neezy_backend/{confluence,alerts,outcomes,exporters,dm}.py, neezy_app/ui_panels/signals.py, history.py
- **Difficulty:** Medium

### 4. [ ] Unify the two path-jail implementations
- **Category:** Architecture & refactoring
- **What:** Make sandbox.resolve_within the only traversal guard; storage.sanitize_path becomes a thin wrapper over it (keeping its allow_absolute flag as an explicit, tested escape hatch).
- **Why:** Two divergent security-critical implementations can drift; one core with a documented wrapper is safer and clearer.
- **Areas:** neezy_backend/{sandbox,storage}.py, tests/test_sandbox.py
- **Difficulty:** Medium

### 5. [ ] Introduce a repository layer over SQLite
- **Category:** Architecture & refactoring
- **What:** Wrap database.py raw SQL in typed repository classes (CandleRepo, SignalRepo, SnapshotRepo, UsageRepo) with explicit method contracts and no SQL in callers.
- **Why:** Callers currently build SQL strings; a repository boundary enables schema migration tests and future storage engines.
- **Areas:** neezy_backend/database.py, cli/db command, ui_panels/database.py
- **Difficulty:** Hard

### 6. [ ] Create a backend service context object
- **Category:** Architecture & refactoring
- **What:** Bundle the shared runtime handles (event bus, stores, settings, tool registry) into one ServiceContext passed explicitly instead of module-level globals.
- **Why:** Globals (e.g. get_global_mt5_bridge) complicate tests and lifetime management; a context makes ownership visible.
- **Areas:** neezy_backend/*.py (progressive), tests
- **Difficulty:** Hard

### 7. [ ] Decouple UI mixins from concrete stores
- **Category:** Architecture & refactoring
- **What:** Panel mixins currently instantiate stores directly; inject them via App.__init__ wiring so fake-tk tests can pass in-memory fakes.
- **Why:** Injection removes filesystem side effects from UI tests and shortens the test suite.
- **Areas:** neezy_app/ui.py, neezy_app/ui_panels/*.py, tests/test_ui_smoke.py
- **Difficulty:** Medium

### 8. [ ] Extract UI theme into a separate module
- **Category:** Architecture & refactoring
- **What:** Move the color/typography tokens and theme application from ui.py App into neezy_app/theme.py with Theme dataclass and apply(widget) helpers.
- **Why:** Three themes are currently defined inline in the 789-line shell; a module makes theming testable and previews possible.
- **Areas:** neezy_app/ui.py, neezy_app/ui_panels/constants.py, tests/test_ui_style.py
- **Difficulty:** Easy

### 9. [ ] Standardize provider abstraction
- **Category:** Architecture & refactoring
- **What:** Give every market-data provider (deriv, alpha_vantage, finnhub, binance, twelve_data) a common Provider protocol: fetch_candles(symbol, tf, count) -> list[Candle] plus health().
- **Why:** confluence.py branches on provider names; a protocol removes isinstance/name checks and lets new providers drop in.
- **Areas:** neezy_backend/providers.py, confluence.py, ui_panels/data_providers.py
- **Difficulty:** Medium

### 10. [ ] Extract MT5 bridge connection state machine
- **Category:** Architecture & refactoring
- **What:** Formalize connect/disconnect/health of MT5Bridge into an explicit state enum with guarded transitions instead of the connected boolean.
- **Why:** Boolean state lets calls race (connect while disconnecting); a state machine makes invalid transitions loud.
- **Areas:** neezy_backend/mt5_bridge.py, tests/test_mt5*.py
- **Difficulty:** Medium

### 11. [ ] Move menu command table to data
- **Category:** Architecture & refactoring
- **What:** Express MENU entries and their argv builders as a declarative table (id, label, group, builder) instead of if-chains in _argv_for.
- **Why:** The dispatch if-chain grows linearly; a table makes new commands one-line additions and enables the / filter to show groups.
- **Areas:** neezy_backend/menu.py, tests/test_menu.py
- **Difficulty:** Easy

### 12. [ ] Extract AI provider transport from prompt logic
- **Category:** Architecture & refactoring
- **What:** Split ai.py into ai/ package: providers (HTTP transports), prompts (message assembly), and client (failover + caching) layers.
- **Why:** ai.py at 834 lines mixes three concerns; separation allows retry policies to evolve without touching prompt code.
- **Areas:** neezy_backend/ai.py, ai_cache.py, ai_resilient.py
- **Difficulty:** Medium

### 13. [ ] Introduce ports/adapters for notifications
- **Category:** Architecture & refactoring
- **What:** Unify telegram.py and dm.py under a Notifier protocol with a fan-out CompositeNotifier; UI and alerts talk only to the interface.
- **Why:** Alerts currently import concrete senders; a port makes adding Discord/email trivial and lets tests intercept notifications.
- **Areas:** neezy_backend/{telegram,dm,alerts}.py, ui_panels/telegram.py
- **Difficulty:** Medium

### 14. [ ] Partition research pipeline stages
- **Category:** Architecture & refactoring
- **What:** research.py and study.py share fetch/label/train/validate stages; extract a ResearchPipeline with stage objects that can be composed and checkpointed.
- **Why:** Shared stage logic is copy-pasted between ML and pair research; stages enable the checkpoint roadmap items.
- **Areas:** neezy_backend/{research,study}.py, tests/test_study*.py
- **Difficulty:** Hard

### 15. [ ] Make event payload types explicit
- **Category:** Architecture & refactoring
- **What:** Type the EventBus payloads (TypedDict per event kind: message, error, connected, reconnecting, closed, stopped) and validate at publish in debug mode.
- **Why:** Payload shape drift between publisher and subscriber is currently caught only by manual testing.
- **Areas:** neezy_backend/events.py, stream.py, consumers
- **Difficulty:** Medium

### 16. [ ] Extract chart rendering from market panel
- **Category:** Architecture & refactoring
- **What:** Move canvas drawing (candles, overlays, crosshair) into neezy_app/chart.py with a pure layout function plus a thin Tk renderer.
- **Why:** Drawing logic embedded in the panel mixin cannot be unit-tested headless; pure layout functions can be golden-tested.
- **Areas:** neezy_app/ui_panels/market.py, tests/test_ui_smoke.py
- **Difficulty:** Medium

### 17. [ ] Create ui_panels base class
- **Category:** Architecture & refactoring
- **What:** Give all 17 mixins a shared PanelBase with common helpers (worker-thread spawn, toast, settings access) instead of copy-pasted utilities per mixin.
- **Why:** Every panel re-implements threading and toasts slightly differently; a base removes drift and shrinks code.
- **Areas:** neezy_app/ui_panels/*.py
- **Difficulty:** Medium

### 18. [ ] Isolate Kivy mobile services behind an interface
- **Category:** Architecture & refactoring
- **What:** neezy_mobile/services.py currently reaches into backend modules directly; define MobileService interfaces so screens depend on abstractions.
- **Why:** The Android port breaks whenever backend signatures change; interfaces decouple release cadence.
- **Areas:** neezy_mobile/{services,screens}.py
- **Difficulty:** Medium

### 19. [ ] Version the JSON datasets schema
- **Category:** Architecture & refactoring
- **What:** Add a schema_version field to every neezy_backend/data/*.json and a loader that migrates old versions forward.
- **Why:** Shipped knowledge currently has no versioning; future edits silently change behavior of older installs.
- **Areas:** neezy_backend/datasets.py, data/*.json, tests/test_datasets.py
- **Difficulty:** Medium

### 20. [ ] Deduplicate OHLC tuple handling
- **Category:** Architecture & refactoring
- **What:** One Candle NamedTuple (epoch, o, h, l, c) with parsing, validation, and conversion helpers used by stream, providers, database, research.
- **Why:** Five modules define their own tuple conventions and converters; a single type removes conversion bugs.
- **Areas:** neezy_backend/{stream,providers,database,research,confluence}.py
- **Difficulty:** Medium

### 21. [ ] Extract risk calculators from CLI
- **Category:** Architecture & refactoring
- **What:** cmd_risk and cmd_decision_metrics embed presentation with math; move pure calculators into risk.py/quant.py functions with their own tests.
- **Why:** Math embedded in CLI handlers is untested at the unit level today.
- **Areas:** neezy_backend/cli.py, risk.py, tests
- **Difficulty:** Easy

### 22. [ ] Fold duplicate strategy registry lookups
- **Category:** Architecture & refactoring
- **What:** strategies.py, config.py STRATEGIES frozenset, and menu references each hard-code the list; derive config's set from the engine registry.
- **Why:** Adding a strategy requires touching three files; derivation makes it one.
- **Areas:** neezy_backend/{strategies,config}.py, tests/test_platform.py
- **Difficulty:** Easy

### 23. [ ] Introduce a unit-of-work for history writes
- **Category:** Architecture & refactoring
- **What:** Signal history JSONL writes and outcome updates share open-append logic; wrap in a HistoryWriter with transaction semantics (append, resolve, compact).
- **Why:** Compact and append race today; a single writer object can serialize them safely.
- **Areas:** neezy_backend/storage.py, outcomes.py
- **Difficulty:** Medium

### 24. [ ] Extract snapshot capture logic
- **Category:** Architecture & refactoring
- **What:** The snapshot save path mixes file management with serialization; separate SnapshotStore (paths, retention) from serializers.
- **Why:** Retention and path rules are testable apart from data shaping.
- **Areas:** neezy_backend/{storage,database}.py
- **Difficulty:** Easy

### 25. [ ] Standardize module entry points
- **Category:** Architecture & refactoring
- **What:** Give every backend module a coherent public __all__ and mark internal helpers with a leading underscore consistently.
- **Why:** Public surface is implicit today; explicit exports make the API reviewable.
- **Areas:** neezy_backend/*.py (sweep)
- **Difficulty:** Easy

### 26. [ ] Kill the compatibility launcher indirection
- **Category:** Architecture & refactoring
- **What:** Keep forex_signals.py as a two-line shim forever, but move its test coverage to assert the shim calls launcher.main with no logic of its own.
- **Why:** Guarantees the legacy entry keeps working while staying zero-maintenance.
- **Areas:** forex_signals.py, tests/test_platform.py
- **Difficulty:** Easy

### 27. [ ] Move MT5 read tools into one surface
- **Category:** Architecture & refactoring
- **What:** mt5_bridge, mt5_preflight, mt5_orders share environment checks; consolidate shared connect helpers into mt5_common.py.
- **Why:** Three modules duplicate availability checks; consolidation prevents divergent behavior between read and order paths.
- **Areas:** neezy_backend/mt5_*.py
- **Difficulty:** Medium

### 28. [ ] Extract insights aggregation queries
- **Category:** Architecture & refactoring
- **What:** insights.py mixes SQL, aggregation, and formatting; split into query functions and formatters.
- **Why:** Formatter changes currently risk breaking queries; separation tests each independently.
- **Areas:** neezy_backend/insights.py, ui_panels/insights.py
- **Difficulty:** Medium

### 29. [ ] Introduce an app lifecycle object for the desktop
- **Category:** Architecture & refactoring
- **What:** Replace implicit startup ordering in App.__init__ with an explicit Lifecycle (init stores, start stream, load settings, bind panels, on_close).
- **Why:** Startup ordering bugs (settings loaded after stream start) are currently silent; explicit phases make them testable.
- **Areas:** neezy_app/ui.py
- **Difficulty:** Hard

### 30. [ ] Make menu rendering data-driven for width
- **Category:** Architecture & refactoring
- **What:** panel() in ui_style hard-codes widths per column; compute from content and allow narrow terminals.
- **Why:** 80-column terminals truncate today; dynamic sizing fixes CLI usability.
- **Areas:** neezy_backend/ui_style.py, menu.py
- **Difficulty:** Easy

### 31. [ ] Collapse duplicated test fixtures
- **Category:** Architecture & refactoring
- **What:** tests re-implement fake buses, fake stores, temp NEEZY_HOME per file; create tests/helpers.py with shared fakes.
- **Why:** Fixture duplication slows suite growth; shared fakes cut new test cost.
- **Areas:** tests/*.py
- **Difficulty:** Easy

### 32. [ ] Define backend version capability flags
- **Category:** Architecture & refactoring
- **What:** Expose BACKEND_FEATURES mapping (feature name -> available bool) computed from imports/deps so UI and CLI can adapt cleanly (e.g. MetaTrader5 absent).
- **Why:** Feature detection is scattered try/except imports; flags centralize it.
- **Areas:** neezy_backend/capabilities.py (new), consumers
- **Difficulty:** Easy

### 33. [ ] Separate decision-rule data from evaluator
- **Category:** Architecture & refactoring
- **What:** data/decision_rules.json and its evaluation code in dm.py evolve together; extract a RuleEvaluator that takes rules + metrics dict.
- **Why:** Rule logic changes can be property-tested against fixture rule sets.
- **Areas:** neezy_backend/dm.py, data/decision_rules.json
- **Difficulty:** Medium

### 34. [ ] Extract correlation window math
- **Category:** Architecture & refactoring
- **What:** correlation_window/baseline handling is repeated across analytics.py, divergence.py, and quant.py; unify in one module.
- **Why:** Three correlation implementations risk subtle disagreement; one is testable against known values.
- **Areas:** neezy_backend/{analytics,divergence,quant}.py
- **Difficulty:** Medium

### 35. [ ] Type-check the whole backend with mypy --strict (gradual)
- **Category:** Architecture & refactoring
- **What:** Add mypy config and annotate the pure modules first (quant, indicators, risk), expanding to I/O modules; fail CI only on annotated files initially.
- **Why:** Typed core math catches None/float mixups that unit tests miss at boundaries.
- **Areas:** pyproject.toml, neezy_backend/{quant,indicators,risk,trend}.py, new CI job
- **Difficulty:** Expert

### 36. [ ] Add contract tests for every exported backend function
- **Category:** Testing
- **What:** For each module in neezy_backend, a test asserts the documented signature (params, defaults, return type) to lock the public API.
- **Why:** Prevents accidental breaking changes to importers (desktop, mobile, kaggle).
- **Areas:** tests/test_api_contracts.py (new)
- **Difficulty:** Medium

### 37. [ ] Property-based tests for indicator math
- **Category:** Testing
- **What:** Hypothesis-style generators (pure stdlib: random with fixed seeds) asserting invariants: EMA within min/max of inputs, RSI in [0,100], ATR non-negative.
- **Why:** Edge inputs (flat series, spikes, NaN adjacency) break indicators silently today.
- **Areas:** tests/test_indicator_properties.py (new)
- **Difficulty:** Medium

### 38. [ ] Fuzz parse_candle and history responses
- **Category:** Testing
- **What:** Randomized mutation testing on parse_candle/parse_history_response: mutated JSON must raise ValueError/RuntimeError, never crash uncaught.
- **Why:** The websocket boundary is the highest-risk parser; fuzzing hardens it.
- **Areas:** tests/test_fuzz_stream.py (new)
- **Difficulty:** Medium

### 39. [ ] Golden-file tests for CLI outputs
- **Category:** Testing
- **What:** Snapshot the plain and JSON output of every read-only CLI command against fixtures; diffs on change force conscious updates.
- **Why:** Output regressions (column drift, missing fields) currently ship unnoticed.
- **Areas:** tests/golden/*.txt, tests/test_cli_golden.py (new)
- **Difficulty:** Medium

### 40. [ ] End-to-end offline scenario test
- **Category:** Testing
- **What:** Scripted session: start fake stream, receive N candles, trigger strategy flip, verify alert, history append, outcome resolution — all with fakes.
- **Why:** The full pipeline is only covered piecewise; one e2e test catches wiring regressions.
- **Areas:** tests/test_e2e_pipeline.py (new)
- **Difficulty:** Hard

### 41. [ ] Race-condition stress tests for stream client
- **Category:** Testing
- **What:** Threads calling start/stop/send concurrently under a fake WebSocketApp; assert no deadlock and clean shutdown within timeout.
- **Why:** Lifecycle races are reported in the audit as unverified; stress tests make them reproducible.
- **Areas:** tests/test_stream_races.py (new)
- **Difficulty:** Hard

### 42. [ ] UI thread-affinity assertions
- **Category:** Testing
- **What:** Instrument fake-tk so widget method calls from non-main threads raise; run the chat/backtest/scanner paths under it.
- **Why:** Enforces the App.after rule automatically instead of by inspection.
- **Areas:** tests/test_ui_thread_safety.py (new), tests/helpers
- **Difficulty:** Hard

### 43. [ ] Mutation testing pilot on quant.py
- **Category:** Testing
- **What:** Introduce mutmut-style guidance (manual or scripted) for quant.py: seeded source mutations must each fail at least one test.
- **Why:** Measures real coverage of the risk math; gaps show which assertions are weak.
- **Areas:** scripts/mutation_pilot.py (new), CI optional job
- **Difficulty:** Expert

### 44. [ ] Coverage reporting in CI
- **Category:** Testing
- **What:** Run unittest with trace/coverage, upload summary artifact, fail under a floor (e.g. 80%) with a ratchet file.
- **Why:** Coverage visibility prevents whole modules silently untested.
- **Areas:** .github/workflows/ci.yml, coverage config
- **Difficulty:** Medium

### 45. [ ] Table-driven strategy tests
- **Category:** Testing
- **What:** One test generator over a matrix (strategy x fixture-series x expected vote) replacing per-strategy hand tests.
- **Why:** 12 strategies x edge cases today rely on few fixtures; tables make every combination cheap.
- **Areas:** tests/test_strategies_table.py (new), tests/fixtures/*.json
- **Difficulty:** Medium

### 46. [ ] Deterministic seeds everywhere in tests
- **Category:** Testing
- **What:** Sweep tests for unseeded random usage; add a conftest-style helper that fails when random is called without a seed.
- **Why:** Flaky tests erode trust in CI; determinism guarantees reproducibility.
- **Areas:** tests/*.py
- **Difficulty:** Easy

### 47. [ ] Test the test harness: fake-tk self-check
- **Category:** Testing
- **What:** Fake-tk widget gets a test asserting it raises on unknown options like real Tk would for the options used by the app.
- **Why:** A too-permissive fake hides real Tk breakages.
- **Areas:** tests/helpers, tests/test_fake_tk.py (new)
- **Difficulty:** Medium

### 48. [ ] Alert rule evaluation tests
- **Category:** Testing
- **What:** Every alert operator (threshold, direction, symbol filter) gets boundary tests (at, above, below, exactly-on).
- **Why:** Alert logic firing off-by-one is a user-visible bug class.
- **Areas:** tests/test_alerts_matrix.py (new)
- **Difficulty:** Easy

### 49. [ ] Outcome resolver boundary tests
- **Category:** Testing
- **What:** Candle sequences where TP and SL are inside the same bar, gap opens beyond TP, and identical close/entry; assert the conservative stop-first rule.
- **Why:** Outcome resolution drives win-rate displays; boundary behavior must be pinned.
- **Areas:** tests/test_outcomes_edges.py (new)
- **Difficulty:** Medium

### 50. [ ] Settings validation exhaustive test
- **Category:** Testing
- **What:** Generate every field of AppSettings with values one step outside each bound; assert the specific error message names the field.
- **Why:** Validation coverage today samples fields; exhaustive generation finds gaps.
- **Areas:** tests/test_settings_exhaustive.py (new)
- **Difficulty:** Easy

### 51. [ ] MCP server integration test
- **Category:** Testing
- **What:** Start the MCP HTTP server on an ephemeral port with a fake registry; exercise initialize, tools/list, tools/call, auth failure, and concurrency cap.
- **Why:** Only unit pieces are tested; the protocol layer over HTTP is untested.
- **Areas:** tests/test_mcp_http.py (new)
- **Difficulty:** Medium

### 52. [ ] Telegram command parser tests
- **Category:** Testing
- **What:** Command grammar (status, signals, mute) with valid, ambiguous, hostile inputs; assert unknown commands are refused.
- **Why:** Parser handles remote user input; needs adversarial coverage.
- **Areas:** tests/test_telegram_parser.py (new)
- **Difficulty:** Medium

### 53. [ ] MT5 bridge mock-socket tests
- **Category:** Testing
- **What:** Fake MetaTrader5 module exercising connect failures, timeout, partial account info, and order rejection paths.
- **Why:** Failure paths of the bridge are currently untested at the protocol level.
- **Areas:** tests/test_mt5_failures.py (new)
- **Difficulty:** Medium

### 54. [ ] Provider HTTP failure matrix tests
- **Category:** Testing
- **What:** urlopen mocked to return 401/403/429/500/broken-JSON/timeout for each provider; assert typed errors and no key leakage in messages.
- **Why:** Provider errors surface to users; uncontrolled ones leak keys in URLs.
- **Areas:** tests/test_provider_errors.py (new)
- **Difficulty:** Medium

### 55. [ ] Database migration tests
- **Category:** Testing
- **What:** For each migration step: build a DB at version N, run migrations, assert schema version and data preservation.
- **Why:** Migrations today are forward-only tested; round-trips catch data loss.
- **Areas:** tests/test_migrations_full.py (new), migrations.py
- **Difficulty:** Medium

### 56. [ ] Backtest determinism test
- **Category:** Testing
- **What:** Run the same backtest twice with the same candles; assert byte-identical reports.
- **Why:** Nondeterministic backtests (dict ordering, float summation order) undermine research.
- **Areas:** tests/test_backtest_determinism.py (new)
- **Difficulty:** Easy

### 57. [ ] Knowledge-base round-trip tests
- **Category:** Testing
- **What:** knowledge.save then load for records with unicode, long strings, and version fields; assert fidelity and compaction.
- **Why:** Knowledge is long-lived state; corruption bugs compound.
- **Areas:** tests/test_knowledge_roundtrip.py (new)
- **Difficulty:** Easy

### 58. [ ] Menu filter/search tests
- **Category:** Testing
- **What:** filter_menu with partial matches, unicode, case, empty query, and unknown tokens.
- **Why:** The / filter is new; edge behaviors (invisible matches) annoy users.
- **Areas:** tests/test_menu.py (extend)
- **Difficulty:** Easy

### 59. [ ] Exporter schema stability tests
- **Category:** Testing
- **What:** CSV header and JSON keys asserted equal to documented schema constants; new fields must update the schema doc.
- **Why:** Downstream consumers (spreadsheets) break on column drift.
- **Areas:** tests/test_exporters_schema.py (new)
- **Difficulty:** Easy

### 60. [ ] CLI exit-code contract tests
- **Category:** Testing
- **What:** Every command documents and tests its exit codes (0 ok, 1 error, 2 usage); a table test enforces it.
- **Why:** Scripts built on neezy-cli need stable exit codes.
- **Areas:** tests/test_cli_exit_codes.py (new)
- **Difficulty:** Medium

### 61. [ ] Sandbox escape test suite
- **Category:** Testing
- **What:** resolve_within against symlink farms, .. chains, null bytes, case tricks on Windows, and absolute paths.
- **Why:** The path jail is security-critical; adversarial tests belong in CI.
- **Areas:** tests/test_sandbox_escape.py (new)
- **Difficulty:** Medium

### 62. [ ] Config file corruption recovery tests
- **Category:** Testing
- **What:** Truncated, empty, wrong-type, and hostile settings.json files; app must start with defaults and log a warning.
- **Why:** Corrupt configs currently silently reset; the behavior should be intentional and tested.
- **Areas:** tests/test_settings_recovery.py (new)
- **Difficulty:** Easy

### 63. [ ] Resource-leak test gate
- **Category:** Testing
- **What:** Run the suite with warnings-as-errors for ResourceWarning; close remaining unclosed stores/databases in tests.
- **Why:** Audit item: unclosed database warnings mask real leaks.
- **Areas:** tests/*.py sweep, tests/__init__.py warning filter
- **Difficulty:** Easy

### 64. [ ] Performance regression smoke tests
- **Category:** Testing
- **What:** Time-boxed assertions: indicator suite on 5k candles under X ms, confluence analysis under Y ms; generous ceilings to catch order-of-magnitude regressions.
- **Why:** Performance rot is invisible until users feel it; ceilings catch it in CI.
- **Areas:** tests/test_perf_smoke.py (new)
- **Difficulty:** Medium

### 65. [ ] Kaggle notebook execution smoke test
- **Category:** Testing
- **What:** Execute notebook code cells with a fake neezy module in a subprocess; assert no cell raises.
- **Why:** Notebook currently only lints and parses; executing catches drift after backend changes.
- **Areas:** tests/test_kaggle_notebook.py (extend)
- **Difficulty:** Medium

### 66. [ ] Mobile services test harness
- **Category:** Testing
- **What:** Kivy-free import tests for services.py and screens.py logic via headless stubs (Kivy not installed in CI).
- **Why:** Mobile code rots invisibly because tests cannot import Kivy today.
- **Areas:** tests/test_mobile_logic.py (new), neezy_mobile (import guards)
- **Difficulty:** Medium

### 67. [ ] Doctest gate for math modules
- **Category:** Testing
- **What:** Enable doctest collection for quant.py, risk.py, indicators docstring examples; add examples where missing.
- **Why:** Doc examples that can rot are worse than none; doctests pin them.
- **Areas:** tests, neezy_backend/{quant,risk}.py
- **Difficulty:** Easy

### 68. [ ] Error-message quality tests
- **Category:** Testing
- **What:** Assert user-facing exceptions contain the failing field/value and an actionable hint (grep-able contract).
- **Why:** Vague errors ('invalid value') are the top support burden.
- **Areas:** tests/test_error_messages.py (new), error paths
- **Difficulty:** Medium

### 69. [ ] Chaos test: stream drop mid-analysis
- **Category:** Testing
- **What:** Fake stream closes while confluence analysis runs; assert analysis aborts cleanly and UI shows reconnect state.
- **Why:** Network drops during compute leave orphan threads/stale UI today.
- **Areas:** tests/test_chaos_stream.py (new)
- **Difficulty:** Hard

### 70. [ ] Recorded-fixture corpus replay tests
- **Category:** Testing
- **What:** Record real candle sessions into fixture files; a runner replays them through the full pipeline and asserts stable signal counts.
- **Why:** Real-world shapes (gaps, spikes, decimal shifts) beat synthetic data for regressions.
- **Areas:** tests/fixtures/corpus/ (new), tests/test_corpus_replay.py
- **Difficulty:** Medium

### 71. [ ] One-command dev environment script
- **Category:** Developer experience
- **What:** scripts/dev_setup.sh (and .ps1): create venv, install -e .[dev], run local_ci; document in README quickstart.
- **Why:** New contributors need three READMEs today to get running.
- **Areas:** scripts/ (new), README.md
- **Difficulty:** Easy

### 72. [ ] Pre-commit hooks config
- **Category:** Developer experience
- **What:** .pre-commit-config.yaml running ruff check + format on staged files; optional local test subset.
- **Why:** Catches lint issues before they reach CI, keeping main green.
- **Areas:** .pre-commit-config.yaml (new)
- **Difficulty:** Easy

### 73. [ ] Makefile with common tasks
- **Category:** Developer experience
- **What:** Targets: make test, make lint, make format, make ci (local_ci.py), make run, make clean.
- **Why:** Reduces 'how do I...' friction; standard entry for newcomers.
- **Areas:** Makefile (new)
- **Difficulty:** Easy

### 74. [ ] Structured issue/PR templates
- **Category:** Developer experience
- **What:** GitHub templates: bug (repro, NEEZY_HOME OS, version), feature (use case), PR checklist (tests, changelog, docs).
- **Why:** Consistent intake improves triage speed and completeness.
- **Areas:** .github/ISSUE_TEMPLATE/, .github/PULL_REQUEST_TEMPLATE.md (new)
- **Difficulty:** Easy

### 75. [ ] RELEASING.md runbook
- **Category:** Developer experience
- **What:** Document version bump, changelog discipline, tag, release workflow, and artifact verification steps.
- **Why:** Releases currently rely on memory; a runbook makes them repeatable.
- **Areas:** RELEASING.md (new)
- **Difficulty:** Easy

### 76. [ ] Contributing guide with code map
- **Category:** Developer experience
- **What:** CONTRIBUTING.md pairing the ARCHITECTURE.md map with where-to-start pointers per area.
- **Why:** Lowers the barrier for first contributions.
- **Areas:** CONTRIBUTING.md (new)
- **Difficulty:** Easy

### 77. [ ] CLI --json consistency audit tool
- **Category:** Developer experience
- **What:** A dev-only command that runs every read command with --json and validates output parses and has stable top-level keys.
- **Why:** Machine consumers need stable JSON; the audit automates the check.
- **Areas:** neezy_backend/cli.py (dev hidden command)
- **Difficulty:** Medium

### 78. [ ] Interactive API docs for the backend
- **Category:** Developer experience
- **What:** Generate a static markdown API reference (function, signature, docstring) for neezy_backend into docs/API.md via a small script.
- **Why:** The backend surface is large; generated docs never drift from code.
- **Areas:** scripts/gen_api_docs.py (new), docs/API.md (generated)
- **Difficulty:** Medium

### 79. [ ] Debug flag with verbose diagnostics
- **Category:** Developer experience
- **What:** neezy-cli --debug prints full tracebacks, timing of each stage, and stream message counts for a session.
- **Why:** Support conversations today lack the detail to reproduce issues.
- **Areas:** neezy_backend/cli.py, menu.py
- **Difficulty:** Easy

### 80. [ ] Shell completion for the CLI
- **Category:** Developer experience
- **What:** argparse completion registration (bash/zsh) for commands and common option values (symbols, timeframes).
- **Why:** Typing long option names is the top CLI friction.
- **Areas:** neezy_backend/cli.py, docs
- **Difficulty:** Medium

### 81. [ ] Timing instrumentation behind env flag
- **Category:** Developer experience
- **What:** NEEZY_TIMING=1 wraps key stages (fetch, analyze, render) with monotonic timing logs.
- **Why:** Cheap profiling without a profiler attached.
- **Areas:** neezy_backend (cross-cutting), diagnostics.py
- **Difficulty:** Easy

### 82. [ ] Test output summary artifact
- **Category:** Developer experience
- **What:** CI uploads a junit-style summary and a readable pass/fail table per module.
- **Why:** Finding a failing module in 500+ tests output is slow.
- **Areas:** .github/workflows/ci.yml, scripts/summarize_tests.py
- **Difficulty:** Easy

### 83. [ ] Dependency pinning check
- **Category:** Developer experience
- **What:** pip-audit style script (offline manifest) verifying websocket-client and ruff versions against known-good pins.
- **Why:** One runtime dep and dev tools; drift check prevents surprise breakage.
- **Areas:** scripts/check_pins.py (new), CI
- **Difficulty:** Easy

### 84. [ ] Docker dev container
- **Category:** Developer experience
- **What:** .devcontainer with Python 3.12, tkinter libs, and task definitions for test/lint.
- **Why:** Gives contributors an identical environment in one click.
- **Areas:** .devcontainer/ (new)
- **Difficulty:** Medium

### 85. [ ] Local CI parity with GitHub CI
- **Category:** Developer experience
- **What:** local_ci.py gains a --full flag matching the GitHub job exactly (same lint paths incl. kaggle, same env).
- **Why:** Audit item: local and remote gates diverge; parity prevents 'passed locally' surprises.
- **Areas:** local_ci.py, .github/workflows/ci.yml
- **Difficulty:** Easy

### 86. [ ] Changelog enforcement in CI
- **Category:** Developer experience
- **What:** CI checks that PR-sized commits to neezy_backend/ also touch CHANGELOG.md (skip-able label).
- **Why:** Keeps the changelog honest as a habit, not a chore at release time.
- **Areas:** .github/workflows/ci.yml (new step)
- **Difficulty:** Medium

### 87. [ ] Settings schema documentation generator
- **Category:** Configuration & settings
- **What:** Script emitting docs/SETTINGS.md listing every AppSettings field: default, range, meaning, UI location.
- **Why:** 78 fields are undocumented centrally; generated docs cannot drift.
- **Areas:** scripts/gen_settings_docs.py (new), docs/SETTINGS.md
- **Difficulty:** Easy

### 88. [ ] Settings profiles (workspace presets)
- **Category:** Configuration & settings
- **What:** Save/load named settings profiles (conservative, active, research) as JSON presets with a profile switcher in Settings.
- **Why:** Users flip many fields between modes; presets remove error-prone manual toggling.
- **Areas:** neezy_backend/config.py, storage.py, ui_panels/settings.py
- **Difficulty:** Medium

### 89. [ ] Environment variable overrides for all settings
- **Category:** Configuration & settings
- **What:** NEEZY_<FIELD> env override validated and applied on load; documented in one table.
- **Why:** Enables headless/kiosk and testing scenarios without editing settings.json.
- **Areas:** neezy_backend/config.py, storage.py
- **Difficulty:** Medium

### 90. [ ] Validate on load, not only construct
- **Category:** Configuration & settings
- **What:** SettingsStore.load logs which fields failed validation and fell back to defaults, once per field.
- **Why:** Silent resets confuse users; named warnings make the fallback visible.
- **Areas:** neezy_backend/storage.py, tests
- **Difficulty:** Easy

### 91. [ ] Config migration versioning
- **Category:** Configuration & settings
- **What:** settings.json gains a version integer with forward migration (field renames, moved sections).
- **Why:** Future renames currently break older files silently via from_dict filtering.
- **Areas:** neezy_backend/{config,storage}.py, tests/test_migrations.py
- **Difficulty:** Medium

### 92. [ ] Per-feature config sections
- **Category:** Configuration & settings
- **What:** Group AppSettings fields into nested dataclasses (WorkspaceConfig, AIConfig, MT5Config, ConfluenceConfig) while keeping flat serialization.
- **Why:** 78 flat fields are error-prone; grouping matches mental model and UI sections.
- **Areas:** neezy_backend/config.py (structure only, serialized flat)
- **Difficulty:** Hard

### 93. [ ] Deriv endpoint candidate editor
- **Category:** Configuration & settings
- **What:** Settings UI list for ws candidate endpoints with add/remove/test buttons; stored as ordered list.
- **Why:** Failover list is currently implicit; users cannot manage it.
- **Areas:** neezy_backend/{config,markets,stream}.py, ui_panels/settings.py
- **Difficulty:** Medium

### 94. [ ] Watchlist import/export in UI
- **Category:** Configuration & settings
- **What:** Import/export watchlist_extra and symbol sets as JSON/text from the Symbols page.
- **Why:** Users rebuild watchlists by hand across machines.
- **Areas:** neezy_app/ui_panels/market.py, exporters.py
- **Difficulty:** Easy

### 95. [ ] Timezone display setting
- **Category:** Configuration & settings
- **What:** Display timezone option (local/UTC/exchange) applied consistently to timestamps in UI and exports.
- **Why:** Timestamps currently mix local and UTC origins; one knob fixes it.
- **Areas:** neezy_backend (format helpers), ui panels, exporters.py
- **Difficulty:** Medium

### 96. [ ] Risk defaults per symbol class
- **Category:** Configuration & settings
- **What:** Risk percent and drawdown limits per symbol class (major/minor/synthetic) with sane defaults.
- **Why:** One global risk knob mis-sizes synthetic indices.
- **Areas:** neezy_backend/config.py, risk.py, dm.py
- **Difficulty:** Medium

### 97. [ ] Theme custom tokens
- **Category:** Configuration & settings
- **What:** Allow overriding base/accent colors of the three themes, persisted in settings.
- **Why:** Users request subtle branding tweaks without new full themes.
- **Areas:** neezy_app/theme extraction (see arch item), config.py
- **Difficulty:** Medium

### 98. [ ] Keyboard shortcut map in settings
- **Category:** Configuration & settings
- **What:** Editable shortcut table (accelerator, action) stored in settings; conflict detection on edit.
- **Why:** Shortcuts are currently hard-coded; power users expect remapping.
- **Areas:** neezy_app/ui.py, config.py
- **Difficulty:** Medium

### 99. [ ] First-run onboarding config
- **Category:** Configuration & settings
- **What:** A first_run flag driving a guided setup checklist (provider, watchlist, theme) persisted after completion.
- **Why:** New users face a full settings page; guided flow lifts activation.
- **Areas:** neezy_app (new panel), config.py
- **Difficulty:** Medium

### 100. [ ] Dry-run mode flag for order paths
- **Category:** Configuration & settings
- **What:** Global 'training mode' setting that forces all order entry points to dry-run regardless of confirmations.
- **Why:** A safe practice switch for users learning the order desk.
- **Areas:** neezy_backend/mt5_orders.py, config.py, ui_panels/orders.py
- **Difficulty:** Easy


---

## Wave 2 — Engine: performance, caching & storage, concurrency, data models, scalability

### 101. [ ] Incremental indicator computation
- **Category:** Performance & speed
- **What:** Cache indicator state (EMA, ATR, Supertrend) per symbol/timeframe and update on new candle instead of full-series recompute.
- **Why:** Every poll recomputes hundreds of candles; incremental cuts CPU ~10x on live charts.
- **Areas:** neezy_backend/indicators.py, market panel polling
- **Difficulty:** Hard

### 102. [ ] Sliding-window candle buffers
- **Category:** Performance & speed
- **What:** Replace full list scans with bounded deques for the live candle window; O(1) append with automatic eviction.
- **Why:** Live windows currently copy lists per tick; deque removes allocations.
- **Areas:** neezy_backend (stream consumer), indicators.py
- **Difficulty:** Medium

### 103. [ ] Vectorize confluence analog search
- **Category:** Performance & speed
- **What:** Precompute normalized feature vectors once per series; reuse across analog queries instead of per-query normalization.
- **Why:** Analog replay dominates analysis time on long histories.
- **Areas:** neezy_backend/confluence.py
- **Difficulty:** Medium

### 104. [ ] Lazy strategy evaluation
- **Category:** Performance & speed
- **What:** Skip strategy votes whose indicator dependencies are already computed and neutral (cache dependency graph).
- **Why:** Twelve strategies recompute shared inputs (EMA, RSI) independently.
- **Areas:** neezy_backend/strategies.py, confluence.py
- **Difficulty:** Medium

### 105. [ ] Debounce UI polling per symbol
- **Category:** Performance & speed
- **What:** Coalesce rapid candle updates for the same symbol before triggering panel refresh (trailing 100ms debounce).
- **Why:** Bursty synthetic ticks cause redundant full-panel redraws.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Easy

### 106. [ ] Chart redraw dirty regions
- **Category:** Performance & speed
- **What:** Only redraw canvas items that changed (last candle, overlay) instead of clearing the canvas each tick.
- **Why:** Full-canvas clear flickers and costs; item-level updates are smooth.
- **Areas:** neezy_app/ui_panels/market.py, chart extraction
- **Difficulty:** Medium

### 107. [ ] History pagination for UI reads
- **Category:** Performance & speed
- **What:** Load history pages (100 rows) on scroll instead of reading the entire JSONL on open.
- **Why:** History files grow to 5000 records; initial open slows linearly.
- **Areas:** neezy_backend/storage.py, ui_panels/history.py
- **Difficulty:** Medium

### 108. [ ] SQLite prepared statement reuse
- **Category:** Performance & speed
- **What:** Cache cursor SQL texts per connection via a statement factory; batch candle inserts with executemany.
- **Why:** Per-row execute is the hottest DB path for candle storage.
- **Areas:** neezy_backend/database.py
- **Difficulty:** Easy

### 109. [ ] WAL checkpoint tuning
- **Category:** Performance & speed
- **What:** Set wal_autocheckpoint and busy_timeout tuned for the write pattern; expose a maintenance vacuum command.
- **Why:** Long-running WAL files grow unchecked today.
- **Areas:** neezy_backend/database.py, cli/db.py
- **Difficulty:** Easy

### 110. [ ] FTS memory search lazy loading
- **Category:** Performance & speed
- **What:** Open the FTS5 handle lazily and keep the index warm across queries instead of reconnecting per query.
- **Why:** Memory queries pay connection overhead each time.
- **Areas:** neezy_backend/database.py (memory store)
- **Difficulty:** Easy

### 111. [ ] AI response streaming
- **Category:** Performance & speed
- **What:** Stream provider completions token-by-token into the chat panel when the provider supports SSE.
- **Why:** Time-to-first-token drops from seconds to near-instant for long answers.
- **Areas:** neezy_backend/ai.py, ui_panels/chat.py
- **Difficulty:** Hard

### 112. [ ] Backtest warm cache of OHLC arrays
- **Category:** Performance & speed
- **What:** Backtester converts candle tuples to arrays per run; cache per symbol/tf across runs in the same process.
- **Why:** Repeat backtests pay conversion each time.
- **Areas:** neezy_backend/backtest.py
- **Difficulty:** Easy

### 113. [ ] Pattern scan early exits
- **Category:** Performance & speed
- **What:** Support/resistance scans can stop early once levels saturate the window; add bounds checks in inner loops.
- **Why:** Scan cost scales with history; early exit bounds it.
- **Areas:** neezy_backend/patterns.py
- **Difficulty:** Medium

### 114. [ ] CLI startup lazy imports
- **Category:** Performance & speed
- **What:** Import command modules lazily in main() so neezy-cli --version starts in <100ms.
- **Why:** Heavy optional imports (matplotlib-free but kivy-adjacent paths) slow every invocation.
- **Areas:** neezy_backend/cli.py, __init__.py
- **Difficulty:** Medium

### 115. [ ] Reduce per-candle validation overhead
- **Category:** Performance & speed
- **What:** parse_candle does per-field try/float; hoist to tuple ops with single validation pass and local variable binds.
- **Why:** Called for every candle in every page; micro-cost adds up at 5k candles.
- **Areas:** neezy_backend/stream.py
- **Difficulty:** Easy

### 116. [ ] Drawdown and Sharpe single-pass
- **Category:** Performance & speed
- **What:** Merge drawdown_stats, sharpe, sortino loops into one pass over returns where callers need all metrics (risk_report).
- **Why:** risk_report walks the returns list four times.
- **Areas:** neezy_backend/quant.py
- **Difficulty:** Easy

### 117. [ ] Event bus zero-copy handoff
- **Category:** Performance & speed
- **What:** Pass parsed message references and drain in batches to reduce queue churn under tick bursts.
- **Why:** Per-tick queue ops dominate profile during bursts.
- **Areas:** neezy_backend/events.py
- **Difficulty:** Medium

### 118. [ ] Sparkline point decimation
- **Category:** Performance & speed
- **What:** Decimate sparkline/market rows to widget pixel width before drawing (LTTB-style selection).
- **Why:** Canvas items beyond pixel count waste draw time.
- **Areas:** neezy_app/glass.py, market.py
- **Difficulty:** Easy

### 119. [ ] Config asdict caching
- **Category:** Performance & speed
- **What:** to_dict() rebuilds the dict on every save poll; cache and invalidate via updated().
- **Why:** Save loops call asdict repeatedly for unchanged settings.
- **Areas:** neezy_backend/config.py
- **Difficulty:** Easy

### 120. [ ] Watchlist quote batch request
- **Category:** Performance & speed
- **What:** Deriv supports subscribe arrays; batch symbol subscriptions in one message per refresh cycle.
- **Why:** Per-symbol subscribe bursts at startup with 25 symbols.
- **Areas:** neezy_backend/stream.py, market.py
- **Difficulty:** Medium

### 121. [ ] Research feature caching
- **Category:** Performance & speed
- **What:** Cache labeled feature matrices on disk keyed by (symbol, tf, horizon, seed); invalidate on config change.
- **Why:** Research reruns re-label identical data every time.
- **Areas:** neezy_backend/research.py
- **Difficulty:** Medium

### 122. [ ] Insights SQL indices
- **Category:** Performance & speed
- **What:** Add covering indices for the insights and analytics query patterns (symbol, ts) and verify with EXPLAIN QUERY PLAN.
- **Why:** Insight queries scan growing tables today.
- **Areas:** neezy_backend/{database,insights}.py
- **Difficulty:** Medium

### 123. [ ] Toast animation frame cap
- **Category:** Performance & speed
- **What:** Cap toast/sheen animation steps to a fixed budget and pause when the window is minimized.
- **Why:** Background animations burn CPU while the window is hidden.
- **Areas:** neezy_app/glass.py, enterprise.py
- **Difficulty:** Easy

### 124. [ ] Chart crosshair event coalescing
- **Category:** Performance & speed
- **What:** Motion handlers throttle to one redraw per frame via after-idle deduplication.
- **Why:** Fast mouse movement queues redundant redraws.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Easy

### 125. [ ] Memory compaction scheduling
- **Category:** Performance & speed
- **What:** Compact memory JSONL on size threshold in the background between queries, not inline with a write.
- **Why:** Compaction currently blocks the writing path at inconvenient times.
- **Areas:** neezy_backend/database.py (memory)
- **Difficulty:** Medium

### 126. [ ] Symbol catalog load-once
- **Category:** Performance & speed
- **What:** SYMBOLS/TIMEFRAMES parsed per import in several modules; parse once at module import and share frozen dicts.
- **Why:** Minor but free startup win across CLI invocations.
- **Areas:** neezy_backend/markets.py, consumers
- **Difficulty:** Easy

### 127. [ ] Bulk outcome resolution
- **Category:** Performance & speed
- **What:** Resolve outcomes for a batch of pending signals in one pass with candle pre-fetch per symbol.
- **Why:** Per-signal fetches duplicate candle reads.
- **Areas:** neezy_backend/outcomes.py
- **Difficulty:** Medium

### 128. [ ] JSON parse fast path
- **Category:** Performance & speed
- **What:** Skip double-parsing in stream (json.loads result reused), avoid re-serializing for bus consumers that need strings.
- **Why:** Profile shows repeated serialize/parse round-trips.
- **Areas:** neezy_backend/stream.py, events.py
- **Difficulty:** Medium

### 129. [ ] History table widget virtualization
- **Category:** Performance & speed
- **What:** Render only visible rows in the history table (Treeview virtual scroll or paginated canvas).
- **Why:** Large histories freeze the UI thread at 1000+ rows.
- **Areas:** neezy_app/ui_panels/history.py
- **Difficulty:** Hard

### 130. [ ] Perf micro-benchmark suite
- **Category:** Performance & speed
- **What:** tests/benchmarks with timeit-based baselines for indicators, confluence, and DB insert; trend report in CI artifacts.
- **Why:** Makes regressions visible before they compound.
- **Areas:** tests/benchmarks/ (new)
- **Difficulty:** Medium

### 131. [ ] On-disk candle cache layer
- **Category:** Caching & storage
- **What:** SQLite-backed candle cache keyed by (symbol, tf) with freshness windows; providers and Deriv reads consult cache first.
- **Why:** Repeated fetches of the same history waste bandwidth and rate limits.
- **Areas:** neezy_backend (new cache.py), providers.py, stream.py
- **Difficulty:** Medium

### 132. [ ] Provider response cache with TTL
- **Category:** Caching & storage
- **What:** In-memory TTL cache (default 30s) in front of provider fetches, keyed by request tuple, with explicit invalidate.
- **Why:** Analysis button spam hits providers with identical requests.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Easy

### 133. [ ] AI prompt context cache
- **Category:** Caching & storage
- **What:** Reuse market snapshot context across chat turns within a short window (symbol/tf unchanged) instead of rebuilding.
- **Why:** Context build hits the DB and indicators per message.
- **Areas:** neezy_backend/context.py, ai_cache.py
- **Difficulty:** Easy

### 134. [ ] Keyed knowledge base caching
- **Category:** Caching & storage
- **What:** Load knowledge JSON once per process with mtime-based invalidation on file change.
- **Why:** Knowledge reads re-parse JSON per lookup today.
- **Areas:** neezy_backend/knowledge.py
- **Difficulty:** Easy

### 135. [ ] Analysis result cache
- **Category:** Caching & storage
- **What:** Cache confluence results keyed by (symbol, tf, last candle epoch, settings hash) for instant re-display.
- **Why:** UI re-analysis of unchanged data is a common action.
- **Areas:** neezy_backend/confluence.py, ui_panels/signals.py
- **Difficulty:** Medium

### 136. [ ] Export file deduplication
- **Category:** Caching & storage
- **What:** Deduplicate identical exports by content hash; link rather than rewrite.
- **Why:** Users export the same report repeatedly; hashing avoids file spam.
- **Areas:** neezy_backend/exporters.py
- **Difficulty:** Easy

### 137. [ ] Backup retention policy
- **Category:** Caching & storage
- **What:** Cap backups/ directory by count and age with configurable retention and oldest-first pruning.
- **Why:** Backups grow unbounded today.
- **Areas:** neezy_backend/storage.py, config.py
- **Difficulty:** Easy

### 138. [ ] Snapshot rotation in DB
- **Category:** Caching & storage
- **What:** Prune snapshot rows older than retention_days during maintenance window with batched deletes.
- **Why:** Snapshots accumulate silently in the DB.
- **Areas:** neezy_backend/database.py, cli/db.py
- **Difficulty:** Easy

### 139. [ ] Signal history compaction on startup
- **Category:** Caching & storage
- **What:** Compact oversized history files at app start (bounded time budget) rather than only on append overflow.
- **Why:** Files grow until a write triggers slow compaction mid-session.
- **Areas:** neezy_backend/storage.py
- **Difficulty:** Easy

### 140. [ ] Model weights metadata index
- **Category:** Caching & storage
- **What:** Index imported model weights with metadata (type, trained-on, metrics) in the DB for listing without filesystem scans.
- **Why:** Model listing scans directories today.
- **Areas:** neezy_backend/local_llm.py, database.py
- **Difficulty:** Medium

### 141. [ ] AI usage analytics retention
- **Category:** Caching & storage
- **What:** Aggregate usage rows older than 90 days into daily rollups to bound table growth.
- **Why:** Usage table grows unbounded with heavy chat use.
- **Areas:** neezy_backend/database.py (usage), analytics.py
- **Difficulty:** Medium

### 142. [ ] Template string interning
- **Category:** Caching & storage
- **What:** Intern repeated prompt template fragments and style strings (Theme lookups) to reduce allocations.
- **Why:** Micro-optimization for hot render paths.
- **Areas:** neezy_backend/{ai,ui_style}.py
- **Difficulty:** Easy

### 143. [ ] Knowledge corpus preindex
- **Category:** Caching & storage
- **What:** Prebuild the FTS index over shipped knowledge datasets at first launch instead of per query assembly.
- **Why:** First insights query is noticeably slow.
- **Areas:** neezy_backend/{knowledge,insights}.py
- **Difficulty:** Medium

### 144. [ ] Configurable cache directory
- **Category:** Caching & storage
- **What:** Dedicated NEEZY_HOME/cache directory with size cap setting and a clear-cache command.
- **Why:** Cache growth becomes visible and manageable.
- **Areas:** neezy_backend/storage.py, cli.py
- **Difficulty:** Easy

### 145. [ ] Offline candle warmup
- **Category:** Caching & storage
- **What:** On startup, immediately serve last-known candles from cache while the stream connects.
- **Why:** Panels show empty until first live tick today.
- **Areas:** neezy_backend (cache), market.py
- **Difficulty:** Medium

### 146. [ ] Research artifact manifest
- **Category:** Caching & storage
- **What:** Manifest of research artifacts with inputs hash, enabling skip-if-same reruns.
- **Why:** Repetitive study commands redo identical training.
- **Areas:** neezy_backend/{research,study}.py
- **Difficulty:** Medium

### 147. [ ] Alert evaluation dedup window
- **Category:** Caching & storage
- **What:** Suppress duplicate alert firings within a cooldown window per rule (configurable).
- **Why:** Flapping conditions spam notifications today.
- **Areas:** neezy_backend/alerts.py, config.py
- **Difficulty:** Easy

### 148. [ ] AI key rotation cache
- **Category:** Caching & storage
- **What:** Remember recently failed keys per provider with cool-down timestamps to avoid retry storms.
- **Why:** Failover currently re-tries a dead key in a tight window.
- **Areas:** neezy_backend/ai.py
- **Difficulty:** Easy

### 149. [ ] UI icon/glyph cache
- **Category:** Caching & storage
- **What:** Pre-render nav glyphs and badge fonts once per theme application.
- **Why:** Theme switches re-create fonts per widget.
- **Areas:** neezy_app/enterprise.py
- **Difficulty:** Easy

### 150. [ ] Telegram send backoff
- **Category:** Caching & storage
- **What:** Exponential backoff per chat on API errors with reset on success; persist state across restarts.
- **Why:** Rate limits cause burst retries and further limits.
- **Areas:** neezy_backend/telegram.py
- **Difficulty:** Medium

### 151. [ ] Disk space guard for storage writes
- **Category:** Caching & storage
- **What:** Check available space before large writes (exports, backups); degrade gracefully with a UI warning.
- **Why:** Full disks corrupt append-only files mid-write.
- **Areas:** neezy_backend/storage.py
- **Difficulty:** Medium

### 152. [ ] Candle dedupe on merge
- **Category:** Caching & storage
- **What:** When merging fetched history with stored history, dedupe by epoch in SQL rather than Python lists.
- **Why:** Merges copy full series into memory today.
- **Areas:** neezy_backend/database.py
- **Difficulty:** Medium

### 153. [ ] Settings write coalescing
- **Category:** Caching & storage
- **What:** Debounce settings.json writes (500ms trailing) when many fields change in a settings session.
- **Why:** Sliders currently trigger a write per movement.
- **Areas:** neezy_backend/storage.py, ui_panels/settings.py
- **Difficulty:** Easy

### 154. [ ] Export directory structure convention
- **Category:** Caching & storage
- **What:** Date-stamped subfolders for exports with an index file listing recent exports.
- **Why:** Flat export directories become unmanageable.
- **Areas:** neezy_backend/exporters.py, config.py
- **Difficulty:** Easy

### 155. [ ] Cache statistics command
- **Category:** Caching & storage
- **What:** neezy-cli cache stats: hit/miss counts, sizes, and ages of every cache layer.
- **Why:** Operability: users can see what caches are doing.
- **Areas:** neezy_backend/cli.py, cache modules
- **Difficulty:** Medium

### 156. [ ] Central worker thread pool
- **Category:** Concurrency & async
- **What:** One bounded ThreadPoolExecutor for UI background work with named tasks, queue depth visibility, and cancel on close.
- **Why:** Ad-hoc threads per action make overload and shutdown races invisible.
- **Areas:** neezy_app (panel base), neezy_backend (services)
- **Difficulty:** Medium

### 157. [ ] Cancelable long operations
- **Category:** Concurrency & async
- **What:** Backtest, research, and bulk analysis accept a cancel token checked between stages; UI cancel button wired to it.
- **Why:** Users cannot abort runaway research today without killing the app.
- **Areas:** neezy_backend/{research,study,backtest}.py, insights panel
- **Difficulty:** Medium

### 158. [ ] Stream subscription manager
- **Category:** Concurrency & async
- **What:** Track active symbol subscriptions with refcounts so panels can share one connection without subscribe leaks.
- **Why:** Switching symbols repeatedly leaks subscriptions on the socket.
- **Areas:** neezy_backend/stream.py, market.py
- **Difficulty:** Medium

### 159. [ ] Shutdown drain protocol
- **Category:** Concurrency & async
- **What:** On app close: stop accepting new work, drain queued callbacks, join threads with timeout, then close stores.
- **Why:** Current close path races background writers (unclosed DB warnings).
- **Areas:** neezy_app/ui.py, neezy_backend (lifecycle)
- **Difficulty:** Medium

### 160. [ ] Provider request queue with rate limiter
- **Category:** Concurrency & async
- **What:** Token-bucket limiter per provider domain serializing fetches with configurable rates.
- **Why:** Parallel analysis bursts violate provider rate limits.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Medium

### 161. [ ] Event bus bounded backlog metrics
- **Category:** Concurrency & async
- **What:** Expose queue depth gauges and drop counters on the event bus; warn in diagnostics when saturated.
- **Why:** Slow consumers silently fall behind during bursts today.
- **Areas:** neezy_backend/events.py, diagnostics.py
- **Difficulty:** Easy

### 162. [ ] MT5 bridge lock discipline
- **Category:** Concurrency & async
- **What:** Guard MT5 calls with a single reentrant lock per bridge instance; document thread ownership.
- **Why:** MT5 API is not thread-safe; concurrent reads/orders can interleave.
- **Areas:** neezy_backend/mt5_bridge.py
- **Difficulty:** Easy

### 163. [ ] Background maintenance scheduler
- **Category:** Concurrency & async
- **What:** Recurring low-priority thread for retention pruning, compaction, and rollups during idle periods.
- **Why:** Maintenance currently happens inline at arbitrary times.
- **Areas:** neezy_backend (new scheduler), storage.py, database.py
- **Difficulty:** Medium

### 164. [ ] Concurrent symbol analysis with cap
- **Category:** Concurrency & async
- **What:** Scanner analyzes watchlist symbols in parallel bounded workers instead of serial loop.
- **Why:** Watchlist analysis latency scales with symbol count today.
- **Areas:** neezy_backend/scanner.py
- **Difficulty:** Medium

### 165. [ ] Thread-safe settings hot-reload
- **Category:** Concurrency & async
- **What:** Atomic swap of the settings object on save with a version counter readers can check.
- **Why:** Settings are read concurrently while being replaced today.
- **Areas:** neezy_backend/config.py, storage.py
- **Difficulty:** Medium

### 166. [ ] MCP server worker isolation
- **Category:** Concurrency & async
- **What:** Tool invocations in MCP run with per-request timeouts and cannot starve the semaphore.
- **Why:** A slow tool currently blocks other MCP clients.
- **Areas:** neezy_backend/mcp.py, tools.py
- **Difficulty:** Medium

### 167. [ ] Agent plan execution concurrency
- **Category:** Concurrency & async
- **What:** AgentPlanner executes independent plan steps in parallel with dependency ordering.
- **Why:** Sequential steps waste wall-clock on I/O-bound tools.
- **Areas:** neezy_backend/agent.py
- **Difficulty:** Hard

### 168. [ ] Telegram long-poll in dedicated thread
- **Category:** Concurrency & async
- **What:** Isolate the polling loop with its own lifecycle and graceful stop; restart on error with backoff.
- **Why:** Polling restarts currently entangle with the UI loop.
- **Areas:** neezy_backend/telegram.py
- **Difficulty:** Medium

### 169. [ ] Watchdog for stream thread
- **Category:** Concurrency & async
- **What:** A monitor restarts the stream thread if it dies without stop() being called.
- **Why:** Silent stream death shows stale data with no reconnect.
- **Areas:** neezy_backend/stream.py, diagnostics.py
- **Difficulty:** Medium

### 170. [ ] UI after-callback flood control
- **Category:** Concurrency & async
- **What:** Coalesce pending after callbacks per target; drop intermediate updates keeping only latest.
- **Why:** Bursts queue hundreds of UI updates that are instantly stale.
- **Areas:** neezy_app (panel base), ui.py
- **Difficulty:** Medium

### 171. [ ] Database single-writer pattern
- **Category:** Concurrency & async
- **What:** Route all SQLite writes through one writer thread with a queue; readers keep WAL snapshots.
- **Why:** Concurrent writers cause busy errors under load.
- **Areas:** neezy_backend/database.py
- **Difficulty:** Hard

### 172. [ ] Test-only thread leak detector
- **Category:** Concurrency & async
- **What:** Test helper asserts no non-daemon threads outlive a test (joinable snapshot before/after).
- **Why:** Thread leaks surface as cross-test flakiness today.
- **Areas:** tests/helpers (new)
- **Difficulty:** Easy

### 173. [ ] Async-friendly provider API
- **Category:** Concurrency & async
- **What:** Optional asyncio wrappers for provider fetches usable from async tools without blocking the loop.
- **Why:** Enables future async UI and MCP integrations.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Medium

### 174. [ ] Atomic app-state snapshot for UI
- **Category:** Concurrency & async
- **What:** Publish immutable analysis snapshots to the UI instead of mutable shared dicts.
- **Why:** UI can render a dict mid-mutation today.
- **Areas:** neezy_backend/confluence.py, ui panels
- **Difficulty:** Medium

### 175. [ ] Timeouts on every blocking I/O call
- **Category:** Concurrency & async
- **What:** Audit and add explicit timeouts to urlopen, websocket recv, subprocess, and file locks; no infinite waits.
- **Why:** Unbounded blocking calls freeze panels and tests.
- **Areas:** neezy_backend sweep (providers, mt5, local_llm, tunnel)
- **Difficulty:** Medium

### 176. [ ] Strict candle schema at boundaries
- **Category:** Data models & validation
- **What:** Validate candle rows once at ingestion (DB write) with clear errors; downstream assumes valid data.
- **Why:** Double validation across layers costs and hides which layer owns correctness.
- **Areas:** neezy_backend/{stream,database}.py
- **Difficulty:** Easy

### 177. [ ] Signal record schema constants
- **Category:** Data models & validation
- **What:** Single SIGNAL_FIELDS tuple used by storage, exporters, UI, and tests; changes propagate everywhere.
- **Why:** Field lists are re-declared in five places today.
- **Areas:** neezy_backend/{storage,exporters}.py
- **Difficulty:** Easy

### 178. [ ] Typed timeframe model
- **Category:** Data models & validation
- **What:** Timeframe dataclass (code, seconds, mt5_name) replacing parallel tuples and string codes.
- **Why:** Mapping 5m -> 300 is re-derived in cli, ui, mt5 modules.
- **Areas:** neezy_backend/markets.py, consumers
- **Difficulty:** Medium

### 179. [ ] Order result object
- **Category:** Data models & validation
- **What:** MT5 order results as a dataclass (ok, ticket, price, message) instead of dict unions across paths.
- **Why:** Order paths merge mock/real dicts with different keys today.
- **Areas:** neezy_backend/mt5_orders.py, mt5_bridge.py
- **Difficulty:** Easy

### 180. [ ] Alert rule validation on save
- **Category:** Data models & validation
- **What:** Validate alert rules (fields, ranges, symbol existence) when persisted with field-level errors.
- **Why:** Invalid rules fail silently at evaluation time today.
- **Areas:** neezy_backend/alerts.py, ui_panels/alerts.py
- **Difficulty:** Easy

### 181. [ ] Provider key file schema validation
- **Category:** Data models & validation
- **What:** Validate provider-keys.json structure on load; unknown providers or malformed entries warn with names.
- **Why:** Malformed key files currently fail at first use.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Easy

### 182. [ ] Backtest report schema
- **Category:** Data models & validation
- **What:** Versioned, documented backtest report dict with a schema constant and validator used by knowledge ingestion.
- **Why:** Knowledge writes assume report fields exist; drift corrupts knowledge.
- **Areas:** neezy_backend/{backtest,knowledge}.py
- **Difficulty:** Medium

### 183. [ ] Research config dataclass
- **Category:** Data models & validation
- **What:** All ML/pair knobs as one validated ResearchConfig derived from AppSettings with explicit units.
- **Why:** Scattered field access from settings invites typos.
- **Areas:** neezy_backend/{research,study}.py, config.py
- **Difficulty:** Medium

### 184. [ ] Normalize symbol aliasing
- **Category:** Data models & validation
- **What:** One canonical symbol table with aliases (frxEURUSD/EURUSD) and single resolve functions for UI, MT5, providers.
- **Why:** Mapping logic exists in mt5_bridge and markets separately today.
- **Areas:** neezy_backend/markets.py, mt5_bridge.py
- **Difficulty:** Medium

### 185. [ ] Usage record schema
- **Category:** Data models & validation
- **What:** AI usage rows as a typed record with provider, model, tokens, latency, and cache flag validated on insert.
- **Why:** Analytics queries assume columns that evolve ad hoc.
- **Areas:** neezy_backend/database.py (usage), analytics.py
- **Difficulty:** Easy

### 186. [ ] Snapshot payload versioning
- **Category:** Data models & validation
- **What:** Snapshots carry a schema version and loader migrates them.
- **Why:** Old snapshots become unreadable after format changes today.
- **Areas:** neezy_backend/database.py
- **Difficulty:** Medium

### 187. [ ] Decision metrics schema
- **Category:** Data models & validation
- **What:** Typed decision-metric rows with validation shared by dm.py and the CLI exporter.
- **Why:** Metric dicts flow untyped across three modules.
- **Areas:** neezy_backend/dm.py, cli.py
- **Difficulty:** Easy

### 188. [ ] Menu item model
- **Category:** Data models & validation
- **What:** MenuItem dataclass (id, label, group, argv builder, danger flag) powering rendering and dispatch.
- **Why:** Removes positional-tuple fragility in MENU.
- **Areas:** neezy_backend/menu.py
- **Difficulty:** Easy

### 189. [ ] Telegram update model
- **Category:** Data models & validation
- **What:** Typed Telegram update/message structures with safe parsing; unknown shapes become no-ops with a log.
- **Why:** Hand-rolled dict walks tolerate malformed payloads unpredictably.
- **Areas:** neezy_backend/telegram.py
- **Difficulty:** Medium

### 190. [ ] JSON column hygiene
- **Category:** Data models & validation
- **What:** All JSON serialized with ensure_ascii and explicit sort_keys for diffable outputs.
- **Why:** Mixed serialization makes file diffs noisy.
- **Areas:** neezy_backend sweep (storage, knowledge, exporters)
- **Difficulty:** Easy

### 191. [ ] Environment capability snapshot
- **Category:** Data models & validation
- **What:** Structured capabilities dict (python version, optional deps, platform) emitted by doctor and attached to bug reports.
- **Why:** Support lacks environment context today.
- **Areas:** neezy_backend/diagnostics.py, cli.py (doctor)
- **Difficulty:** Easy

### 192. [ ] Knowledge record types
- **Category:** Data models & validation
- **What:** Knowledge records as typed records with feature/limit fields validated on save and load.
- **Why:** Free-form records allow silent data corruption.
- **Areas:** neezy_backend/knowledge.py
- **Difficulty:** Medium

### 193. [ ] Numeric range types for prices
- **Category:** Data models & validation
- **What:** Price/qty new types (non-negative finite floats) used at order and risk boundaries.
- **Why:** Bad sizing inputs flow into order preview text today.
- **Areas:** neezy_backend/{risk,mt5_orders}.py
- **Difficulty:** Medium

### 194. [ ] Watchlist entry model
- **Category:** Data models & validation
- **What:** Watchlist items as (symbol, enabled, note) records with UI editing.
- **Why:** Plain symbol strings prevent per-item metadata.
- **Areas:** neezy_backend/config.py, market.py
- **Difficulty:** Medium

### 195. [ ] Error taxonomy codes
- **Category:** Data models & validation
- **What:** Stable error codes (E-NET-01 style) attached to exception classes for scripts and localization.
- **Why:** Scripts cannot match on messages reliably today.
- **Areas:** neezy_backend (error base module), cli.py
- **Difficulty:** Medium

### 196. [ ] Candle table partitioning strategy
- **Category:** Scalability
- **What:** Design document and prototype for time-partitioned candle storage (per-month tables or ATTACH shards) with transparent queries.
- **Why:** Years of multi-symbol storage slows queries linearly today.
- **Areas:** neezy_backend/database.py (prototype), docs
- **Difficulty:** Expert

### 197. [ ] Streaming CSV export
- **Category:** Scalability
- **What:** Export candles/history as a generator writing rows incrementally instead of building the full string in memory.
- **Why:** Large exports allocate hundreds of MB today.
- **Areas:** neezy_backend/exporters.py
- **Difficulty:** Medium

### 198. [ ] Batch history fetch pagination window
- **Category:** Scalability
- **What:** fetch_history pages of 5000 with adaptive page sizes based on response time.
- **Why:** Fixed page sizing wastes round trips on fast endpoints.
- **Areas:** neezy_backend/stream.py (fetch_history)
- **Difficulty:** Medium

### 199. [ ] Symbol fan-out load test
- **Category:** Scalability
- **What:** Scripted load test driving the stream client with 100 fake symbols; measure memory and CPU; document limits.
- **Why:** Capacity is unknown today; users discover limits by failure.
- **Areas:** tests/load/ (new), docs
- **Difficulty:** Medium

### 200. [ ] Memory store pagination
- **Category:** Scalability
- **What:** Memory search returns pages with total counts; UI lazy-loads results.
- **Why:** Large memories slow the first results page.
- **Areas:** neezy_backend/database.py (memory), ui_panels/chat.py
- **Difficulty:** Medium


---

## Wave 3 — Capabilities: advanced features, AI & agentic abilities, plugins, CLI

### 201. [ ] Multi-timeframe confluence view
- **Category:** Advanced features
- **What:** Analyze one symbol across 1m/5m/15m/1h/4h simultaneously and show an aligned-timeframe score matrix.
- **Why:** Single-timeframe signals miss higher-timeframe context; the matrix surfaces alignment at a glance.
- **Areas:** neezy_backend/confluence.py, ui_panels/signals.py
- **Difficulty:** Hard

### 202. [ ] Strategy parameter optimizer
- **Category:** Advanced features
- **What:** Grid/random search over strategy parameters against backtests with a results table and best-set export.
- **Why:** Manual parameter tweaking is slow and unguided today.
- **Areas:** neezy_backend/{backtest,research}.py, cli.py (new command)
- **Difficulty:** Hard

### 203. [ ] Walk-forward analysis report
- **Category:** Advanced features
- **What:** Rolling train/validate windows with equity curve and stability metrics per strategy.
- **Why:** Single backtests overstate edge; walk-forward is the honest version.
- **Areas:** neezy_backend/backtest.py, insights.py
- **Difficulty:** Hard

### 204. [ ] Position size calculator widget
- **Category:** Advanced features
- **What:** TOOLS page calculator: balance, risk %, entry/stop -> lots, pip value, R multiples, per-symbol metadata.
- **Why:** Risk planning is the most-used manual math traders do.
- **Areas:** neezy_app/ui_panels/tools_page.py, neezy_backend/risk.py
- **Difficulty:** Easy

### 205. [ ] Correlation heat matrix
- **Category:** Advanced features
- **What:** Watchlist correlation grid with color coding and period selector (20/50/200).
- **Why:** Pair selection today requires reading numeric lists.
- **Areas:** neezy_backend/{analytics,divergence}.py, insights panel
- **Difficulty:** Medium

### 206. [ ] Session clock & volatility profile
- **Category:** Advanced features
- **What:** Tokyo/London/NY session bars with per-session volatility stats overlay.
- **Why:** Session awareness explains signal quality variation.
- **Areas:** neezy_app/ui_panels/market.py, neezy_backend/analytics.py
- **Difficulty:** Medium

### 207. [ ] Economic-event calendar (offline bundle)
- **Category:** Advanced features
- **What:** Importable ICS/CSV event calendar rendered on the chart with severity filters; no live feeds.
- **Why:** Event context matters for signal interpretation while keeping local-first.
- **Areas:** neezy_backend (new events_calendar.py), market.py
- **Difficulty:** Medium

### 208. [ ] Drawdown guard alerts
- **Category:** Advanced features
- **What:** Track cumulative strategy performance and alert/notify at drawdown thresholds.
- **Why:** Users discover losing streaks late today.
- **Areas:** neezy_backend/{outcomes,alerts}.py
- **Difficulty:** Medium

### 209. [ ] Signal confidence history chart
- **Category:** Advanced features
- **What:** Plot score/win-rate history for a symbol to visualize engine calibration over time.
- **Why:** Calibration drift is invisible without history.
- **Areas:** neezy_app/ui_panels/insights.py, database.py
- **Difficulty:** Medium

### 210. [ ] Portfolio risk aggregation
- **Category:** Advanced features
- **What:** Aggregate open MT5 positions into portfolio VaR and correlation-adjusted exposure.
- **Why:** Per-position risk hides concentration today.
- **Areas:** neezy_backend/{quant,mt5_bridge}.py, orders panel
- **Difficulty:** Hard

### 211. [ ] Custom indicator scripting (sandboxed)
- **Category:** Advanced features
- **What:** Safe mini-expression DSL (e.g. EMA(14) - EMA(50)) compiled to indicator pipeline stages.
- **Why:** Users constantly request one-off indicator combos without code access.
- **Areas:** neezy_backend (new expr.py), strategies.py
- **Difficulty:** Expert

### 212. [ ] Signal notes and journaling
- **Category:** Advanced features
- **What:** Attach notes/outcome reflection to signals in history; journal view with export.
- **Why:** Discipline journaling is a core trading habit the app lacks.
- **Areas:** neezy_backend (history store), ui_panels/history.py
- **Difficulty:** Medium

### 213. [ ] Watchlist column sorting
- **Category:** Advanced features
- **What:** Click-to-sort on score, change, sparkline trend in the symbols table.
- **Why:** Finding the best setup among 25 symbols needs sorting.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Easy

### 214. [ ] Chart measure tool
- **Category:** Advanced features
- **What:** Drag-to-measure price/percentage/time between two points with annotation.
- **Why:** Basic charting affordance traders expect.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Medium

### 215. [ ] Price level alerts
- **Category:** Advanced features
- **What:** Horizontal line alerts: notify when price crosses a level, drawn on the chart.
- **Why:** Most common alert type for discretionary traders.
- **Areas:** neezy_backend/alerts.py, market.py
- **Difficulty:** Medium

### 216. [ ] Trailing-stop simulator
- **Category:** Advanced features
- **What:** Simulate trailing stops against historical candles for chosen parameters.
- **Why:** Users ask what trailing settings would have done.
- **Areas:** neezy_backend/backtest.py, tools_page.py
- **Difficulty:** Medium

### 217. [ ] Multi-account MT5 profiles
- **Category:** Advanced features
- **What:** Named MT5 connection profiles with quick switch and per-profile safety settings.
- **Why:** Demo/live switching currently requires editing fields.
- **Areas:** neezy_backend/mt5_bridge.py, ui_panels/integrations.py
- **Difficulty:** Medium

### 218. [ ] Order history journal with filters
- **Category:** Advanced features
- **What:** MT5 deal history with date/symbol/side filters and CSV export.
- **Why:** Terminal history is hard to audit in-app today.
- **Areas:** neezy_backend/mt5_bridge.py, orders panel
- **Difficulty:** Easy

### 219. [ ] Keyboard-first chart navigation
- **Category:** Advanced features
- **What:** Home/End/PgUp/PgDn pan and zoom the chart; +/- zoom keys.
- **Why:** Chart navigation currently requires the mouse wheel only.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Easy

### 220. [ ] Dark/light auto theme by OS
- **Category:** Advanced features
- **What:** Detect OS preference (Windows app mode / env) and follow it for theme selection.
- **Why:** Theme selection is manual even when the OS signals preference.
- **Areas:** neezy_app (theme module), launcher.py
- **Difficulty:** Easy

### 221. [ ] Compact density mode refinement
- **Category:** Advanced features
- **What:** compact_mode actually changes paddings, row heights, and font sizes across all panels.
- **Why:** The flag exists but the layout barely changes today.
- **Areas:** neezy_app/ui.py + panels sweep
- **Difficulty:** Medium

### 222. [ ] Sound alert hooks
- **Category:** Advanced features
- **What:** Optional local sound files for alert/signal events with mute schedule.
- **Why:** Audio feedback matters for users running NEEZY in the background.
- **Areas:** neezy_backend/alerts.py, ui_panels/settings.py
- **Difficulty:** Easy

### 223. [ ] Symbol details sheet
- **Category:** Advanced features
- **What:** Per-symbol drawer: pip size, trading hours (static), typical spread from history, recent volatility.
- **Why:** Context users currently look up externally.
- **Areas:** neezy_app/ui_panels/market.py, markets.py
- **Difficulty:** Medium

### 224. [ ] Strategy disagreement explorer
- **Category:** Advanced features
- **What:** When strategies conflict, show the per-strategy vote breakdown and the deciding factors.
- **Why:** Confluence hides disagreement behind a single score today.
- **Areas:** neezy_backend/confluence.py, signals panel
- **Difficulty:** Medium

### 225. [ ] Backtest equity curve chart
- **Category:** Advanced features
- **What:** Render equity and drawdown curves (Tk canvas) for the latest backtest.
- **Why:** Tables hide path dependency; curves expose it.
- **Areas:** neezy_app/ui_panels/insights.py, backtest.py
- **Difficulty:** Medium

### 226. [ ] Risk-per-trade consistency check
- **Category:** Advanced features
- **What:** Warn when consecutive order sizes deviate from the configured risk model.
- **Why:** Discipline enforcement users ask for.
- **Areas:** neezy_backend/mt5_orders.py, orders panel
- **Difficulty:** Medium

### 227. [ ] Data quality indicator
- **Category:** Advanced features
- **What:** Per-symbol badge: candle gaps, stale ticks, or outages detected in the incoming stream.
- **Why:** Signals computed on stale data look valid today.
- **Areas:** neezy_backend/stream.py, market.py
- **Difficulty:** Medium

### 228. [ ] Local time-shifted replay
- **Category:** Advanced features
- **What:** Replay historical candles at chosen speed with the live UI for practice.
- **Why:** Bar-replay is a flagship practice feature of trading tools.
- **Areas:** neezy_app (market panel), stream consumer
- **Difficulty:** Hard

### 229. [ ] Session performance breakdown
- **Category:** Advanced features
- **What:** Outcomes split by session and weekday in the insights page.
- **Why:** Reveals time-of-day edge users suspect.
- **Areas:** neezy_backend/insights.py, outcomes.py
- **Difficulty:** Medium

### 230. [ ] Clipboard monitor widget
- **Category:** Advanced features
- **What:** Paste symbol/level text into a mini box that parses to chart/watchlist actions.
- **Why:** Fast capture of levels shared in chats.
- **Areas:** neezy_app/ui_panels/tools_page.py
- **Difficulty:** Easy

### 231. [ ] Print-friendly report view
- **Category:** Advanced features
- **What:** Print/PDF-ready daily summary (signals, outcomes, risk) via HTML export.
- **Why:** Users share summaries with mentors/groups.
- **Areas:** neezy_backend/exporters.py (HTML)
- **Difficulty:** Medium

### 232. [ ] Alert quiet hours
- **Category:** Advanced features
- **What:** Per-channel schedule windows during which notifications are suppressed (logged, not sent).
- **Why:** Overnight alerts burn goodwill.
- **Areas:** neezy_backend/{alerts,telegram,dm}.py, config.py
- **Difficulty:** Easy

### 233. [ ] Multi-watchlist support
- **Category:** Advanced features
- **What:** Named watchlists with quick switching and per-list scan settings.
- **Why:** One flat list forces mixing strategies/styles today.
- **Areas:** neezy_backend/config.py, market.py, scanner.py
- **Difficulty:** Medium

### 234. [ ] Symbol search palette (Ctrl+P)
- **Category:** Advanced features
- **What:** Fuzzy symbol finder overlay bound to a global shortcut.
- **Why:** Finding among hundreds of Deriv symbols is the top navigation cost.
- **Areas:** neezy_app (palette overlay), markets.py
- **Difficulty:** Medium

### 235. [ ] Trade checklist gate
- **Category:** Advanced features
- **What:** Optional pre-order checklist dialog (user-defined items) before confirming any order.
- **Why:** Process enforcement for discretionary safety.
- **Areas:** neezy_backend/mt5_orders.py, ui_panels/orders.py
- **Difficulty:** Easy

### 236. [ ] Engine self-calibration report
- **Category:** Advanced features
- **What:** Periodic report comparing signal win-rates against analog-replay expectations with drift flags.
- **Why:** Engine quality becomes measurable over time.
- **Areas:** neezy_backend/insights.py, outcomes.py
- **Difficulty:** Hard

### 237. [ ] Candle gap visualization
- **Category:** Advanced features
- **What:** Mark session gaps and data holes on the chart.
- **Why:** Indicators mislead across invisible gaps today.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Easy

### 238. [ ] Strategy heat on watchlist rows
- **Category:** Advanced features
- **What:** Per-symbol dot colored by current multi-strategy agreement.
- **Why:** Fast scanning aid beyond the score column.
- **Areas:** neezy_app/ui_panels/market.py, confluence.py
- **Difficulty:** Easy

### 239. [ ] Custom column layout
- **Category:** Advanced features
- **What:** Users choose visible columns and order in watchlist/history tables, persisted.
- **Why:** Screen real estate differs wildly across users.
- **Areas:** neezy_app/ui_panels/{market,history}.py, config.py
- **Difficulty:** Medium

### 240. [ ] MT5 quote stream into chart
- **Category:** Advanced features
- **What:** Optionally chart MT5 live ticks for mapped symbols when the bridge is connected.
- **Why:** Users trading via MT5 want its prices charted.
- **Areas:** neezy_backend/mt5_bridge.py, market.py
- **Difficulty:** Medium

### 241. [ ] News-free sentiment placeholder discipline
- **Category:** Advanced features
- **What:** Explicit 'no news in engine' banner plus optional manual sentiment tag per signal note.
- **Why:** Honesty about scope prevents misuse of signals as complete analysis.
- **Areas:** neezy_app/ui_panels/signals.py, history.py
- **Difficulty:** Easy

### 242. [ ] Historical analog browser
- **Category:** Advanced features
- **What:** For each signal, show the historical analogs the engine matched with their outcomes.
- **Why:** Win-rate becomes explainable and checkable.
- **Areas:** neezy_backend/confluence.py, signals panel
- **Difficulty:** Hard

### 243. [ ] Export to TradingView watchlist
- **Category:** Advanced features
- **What:** Export watchlist/symbols in TradingView-compatible text format.
- **Why:** Users work across tools; interop reduces re-entry.
- **Areas:** neezy_backend/exporters.py, cli.py
- **Difficulty:** Easy

### 244. [ ] Random-string safe file names
- **Category:** Advanced features
- **What:** All exports/exports paths sanitized with a shared slug helper (unicode, separators).
- **Why:** Symbol names with dots/slashes create odd files today.
- **Areas:** neezy_backend/{storage,exporters}.py
- **Difficulty:** Easy

### 245. [ ] Strategy parameter preset library
- **Category:** Advanced features
- **What:** Curated, documented parameter presets per strategy (default, fast, conservative) selectable in settings and CLI.
- **Why:** Parameter tuning is expert work; presets give users safe starting points.
- **Areas:** neezy_backend/{strategies,config}.py, settings panel, docs
- **Difficulty:** Medium

### 246. [ ] Tool call result streaming to UI
- **Category:** AI & agentic
- **What:** Agent tool executions push progress lines into the chat transcript as they run.
- **Why:** Multi-step plans look frozen today while tools execute.
- **Areas:** neezy_backend/agent.py, ui_panels/chat.py
- **Difficulty:** Medium

### 247. [ ] Agent plan preview before execution
- **Category:** AI & agentic
- **What:** Show the planned steps with a confirm/abort toggle (respecting the WRITE/DESTRUCTIVE tiers).
- **Why:** Users cannot see intent before effects today.
- **Areas:** neezy_backend/agent.py, tools.py, chat.py
- **Difficulty:** Medium

### 248. [ ] Memory pinning and importance decay
- **Category:** AI & agentic
- **What:** Pinned memories never compact; unpinned decay by age and use count.
- **Why:** Memory quality degrades as volume grows today.
- **Areas:** neezy_backend/database.py (memory), agent.py
- **Difficulty:** Medium

### 249. [ ] Per-conversation memory scoping
- **Category:** AI & agentic
- **What:** Optionally scope retrieval to the current chat thread or a project tag.
- **Why:** Cross-topic contamination reduces answer quality.
- **Areas:** neezy_backend/database.py (memory), context.py
- **Difficulty:** Medium

### 250. [ ] Structured tool argument validation
- **Category:** AI & agentic
- **What:** JSON-schema validate model-provided tool args before invocation with repair-by-reprompt on failure.
- **Why:** Malformed tool calls fail opaquely today.
- **Areas:** neezy_backend/tools.py, agent.py
- **Difficulty:** Medium

### 251. [ ] Agentic research mode
- **Category:** AI & agentic
- **What:** A guided flow: agent proposes analysis steps (scan, backtest, read knowledge), user approves once, report is assembled.
- **Why:** Connects the agent to the research pipeline safely.
- **Areas:** neezy_backend/agent.py, research.py, chat.py
- **Difficulty:** Hard

### 252. [ ] Model routing policy
- **Category:** AI & agentic
- **What:** Route by task type: fast models for quick lookups, stronger for analysis; user-configurable table.
- **Why:** Cost/latency/quality tradeoffs are per-question today.
- **Areas:** neezy_backend/ai.py, ai_settings panel
- **Difficulty:** Medium

### 253. [ ] Prompt template registry
- **Category:** AI & agentic
- **What:** Named, versioned prompt templates in one module with a diff viewer when they change.
- **Why:** Prompts are string literals scattered in ai.py today.
- **Areas:** neezy_backend (new prompts.py), ai.py
- **Difficulty:** Medium

### 254. [ ] Local-evals harness (evals/)
- **Category:** AI & agentic
- **What:** The promised evals/ harness from the old plan: task set, runner against offline rules or a provider, JSON/markdown scorecard.
- **Why:** Prompt changes are currently unmeasured before shipping.
- **Areas:** evals/ (new), tests/test_evals.py
- **Difficulty:** Medium

### 255. [ ] Answer citation of context
- **Category:** AI & agentic
- **What:** AI answers include which data (snapshot fields, knowledge records) supported them.
- **Why:** Trust and debuggability of copilot answers.
- **Areas:** neezy_backend/{context,ai}.py, chat.py
- **Difficulty:** Medium

### 256. [ ] Streaming tool output into provider messages
- **Category:** AI & agentic
- **What:** Long tool outputs are chunked into provider-safe summaries with truncation policy.
- **Why:** Large tool results overflow context windows today.
- **Areas:** neezy_backend/{tools,agent,ai}.py
- **Difficulty:** Medium

### 257. [ ] Command palette actions from chat
- **Category:** AI & agentic
- **What:** Chat can trigger whitelisted UI actions (switch symbol, open page) as tools.
- **Why:** Conversational navigation lowers friction.
- **Areas:** neezy_backend/tools.py, ui_panels/chat.py
- **Difficulty:** Medium

### 258. [ ] Tool timeout and retry policy
- **Category:** AI & agentic
- **What:** Per-tool timeout defaults with one bounded retry for READ_ONLY tools; WRITE never auto-retries.
- **Why:** A hanging tool stalls the whole agent loop today.
- **Areas:** neezy_backend/tools.py, agent.py
- **Difficulty:** Easy

### 259. [ ] Session transcript export
- **Category:** AI & agentic
- **What:** Export chat sessions (including tool calls) as markdown/JSON.
- **Why:** Users document workflows and share debugging.
- **Areas:** neezy_backend (session store), exporters.py
- **Difficulty:** Easy

### 260. [ ] Multi-key rotation status UI
- **Category:** AI & agentic
- **What:** AI settings shows per-key health (ok/cooldown), last error, and manual test button.
- **Why:** Key failover is invisible until it breaks today.
- **Areas:** neezy_backend/ai.py, ui_panels/ai_settings.py
- **Difficulty:** Easy

### 261. [ ] Context budget meter
- **Category:** AI & agentic
- **What:** Show approximate token usage of the assembled prompt before send.
- **Why:** Users hit context limits surprisingly today.
- **Areas:** neezy_backend/context.py, chat.py
- **Difficulty:** Easy

### 262. [ ] Ollama model catalog fetch
- **Category:** AI & agentic
- **What:** List local Ollama models for the model picker instead of manual entry.
- **Why:** Typing model IDs by hand is error-prone.
- **Areas:** neezy_backend/ai.py, ai_settings panel
- **Difficulty:** Easy

### 263. [ ] Guardrail for order-related chat
- **Category:** AI & agentic
- **What:** Chat/system prompts explicitly refuse to place orders; enforcement test asserts no order tool is registered to the agent.
- **Why:** Defense-in-depth for the no-agent-orders invariant.
- **Areas:** neezy_backend/{tools,agent}.py, prompts, tests
- **Difficulty:** Medium

### 264. [ ] Daily digest agent
- **Category:** AI & agentic
- **What:** Optional scheduled local summary (signals, outcomes, market regime) delivered to Telegram/webhook on demand.
- **Why:** Users want end-of-day recap without watching the app.
- **Areas:** neezy_backend (scheduler + notifier), telegram.py
- **Difficulty:** Medium

### 265. [ ] Knowledge base editing UI
- **Category:** AI & agentic
- **What:** Read-only viewer today; add safe editing (add/annotate/disable records) with audit trail.
- **Why:** Users need to correct learned knowledge.
- **Areas:** neezy_backend/knowledge.py, ui_panels/insights.py
- **Difficulty:** Medium

### 266. [ ] MCP server tool listing page parity
- **Category:** AI & agentic
- **What:** The MCP page shows the same tool descriptions the registry serves, generated from one source.
- **Why:** Docs and served schema drift today.
- **Areas:** neezy_backend/{mcp,mcp_tools}.py, ui_panels/mcp.py
- **Difficulty:** Easy

### 267. [ ] Tool call audit log
- **Category:** AI & agentic
- **What:** Append-only log of tool invocations (name, args summary, permission, result code) viewable in TOOLS page.
- **Why:** Agent transparency and forensics for a local tool.
- **Areas:** neezy_backend/tools.py, database.py
- **Difficulty:** Medium

### 268. [ ] Provider cost estimation
- **Category:** AI & agentic
- **What:** Per-provider rough token cost tracking in usage analytics (local table, no cloud).
- **Why:** BYOK users need spend visibility.
- **Areas:** neezy_backend/{ai,database}.py, analytics.py
- **Difficulty:** Medium

### 269. [ ] Retry-aware streaming UX states
- **Category:** AI & agentic
- **What:** Chat shows connecting/retrying/failed distinctly with retry button.
- **Why:** Failover feels like hangs today.
- **Areas:** neezy_app/ui_panels/chat.py, ai_resilient.py
- **Difficulty:** Easy

### 270. [ ] Offline fallback answer style
- **Category:** AI & agentic
- **What:** When AI is disabled/unreachable, the copilot answers with deterministic local analysis text.
- **Why:** The chat is dead weight offline today.
- **Areas:** neezy_backend/context.py, chat.py
- **Difficulty:** Medium

### 271. [ ] Webhook-in commands (opt-in)
- **Category:** AI & agentic
- **What:** Extend the Telegram command surface to a generic webhook receiver with the same allow-list and audit log.
- **Why:** Users integrate NEEZY into their own tooling safely.
- **Areas:** neezy_backend/{remote,telegram}.py, dm.py
- **Difficulty:** Medium

### 272. [ ] Agent checkpoint/resume
- **Category:** AI & agentic
- **What:** Long agent plans persist progress and can resume after app restart.
- **Why:** Multi-step research dies with the window today.
- **Areas:** neezy_backend/agent.py, database.py
- **Difficulty:** Hard

### 273. [ ] Prompt variable preview
- **Category:** AI & agentic
- **What:** Preview the exact prompt (variables expanded) before sending.
- **Why:** Debugging prompt issues currently requires guesswork.
- **Areas:** neezy_app/ui_panels/ai_settings.py, context.py
- **Difficulty:** Easy

### 274. [ ] Model response caching by prompt hash
- **Category:** AI & agentic
- **What:** Extend ai_cache with a prompt-hash mode for identical repeated questions within TTL.
- **Why:** Repeat questions cost full provider calls today.
- **Areas:** neezy_backend/ai_cache.py
- **Difficulty:** Easy

### 275. [ ] Safety tier visualization in tools page
- **Category:** AI & agentic
- **What:** TOOLS page groups tools by permission tier with icons and explanations.
- **Why:** Permission model is invisible to users today.
- **Areas:** neezy_app/ui_panels/tools_page.py, tools.py
- **Difficulty:** Easy

### 276. [ ] Plugin discovery contract
- **Category:** Plugin systems
- **What:** Define a Plugin protocol (id, version, provides) and scan NEEZY_HOME/plugins for local modules.
- **Why:** Third entry point for community features without forking.
- **Areas:** neezy_backend (new plugins.py), launcher
- **Difficulty:** Hard

### 277. [ ] Strategy plugin interface
- **Category:** Plugin systems
- **What:** Strategies implement a Strategy protocol with name/params/vote; registration from core or plugins.
- **Why:** Custom strategies are the most requested extension.
- **Areas:** neezy_backend/strategies.py, config.py
- **Difficulty:** Medium

### 278. [ ] Provider plugin interface
- **Category:** Plugin systems
- **What:** Market-data providers as plugins implementing the Provider protocol with capability flags.
- **Why:** Broker-specific data sources drop in without core edits.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Medium

### 279. [ ] Notifier plugin interface
- **Category:** Plugin systems
- **What:** Notification channels (Discord, email) as plugins behind the Notifier port.
- **Why:** The two built-ins (Telegram/webhook) hard-code structure today.
- **Areas:** neezy_backend/{telegram,dm}.py, (new notifier port)
- **Difficulty:** Medium

### 280. [ ] UI panel plugin slots
- **Category:** Plugin systems
- **What:** Panels can register extra TOOLS-page widgets through a safe registration API (no NAV changes).
- **Why:** Extensions without touching the shell.
- **Areas:** neezy_app (panel base), tools_page.py
- **Difficulty:** Medium

### 281. [ ] Alert condition plugins
- **Category:** Plugin systems
- **What:** Custom alert predicates (beyond threshold rules) as registered callables with metadata.
- **Why:** Power users want composite conditions.
- **Areas:** neezy_backend/alerts.py
- **Difficulty:** Medium

### 282. [ ] Exporter plugins
- **Category:** Plugin systems
- **What:** Export formats as pluggable serializers (CSV/JSON built-in, community: XLSX, Markdown).
- **Why:** Export requests vary per user workflow.
- **Areas:** neezy_backend/exporters.py
- **Difficulty:** Easy

### 283. [ ] Command plugins for the CLI
- **Category:** Plugin systems
- **What:** neezy-cli discovers user commands in NEEZY_HOME/plugins/commands with manifest validation.
- **Why:** Automation glue without polluting core.
- **Areas:** neezy_backend/cli.py, plugins.py
- **Difficulty:** Medium

### 284. [ ] Plugin sandboxing rules
- **Category:** Plugin systems
- **What:** Plugins run with declared permissions (read-market, write-files, none) enforced by the tool registry.
- **Why:** Extensibility must not break the local-first security model.
- **Areas:** neezy_backend/{plugins,tools,sandbox}.py
- **Difficulty:** Hard

### 285. [ ] Plugin manifest and versioning
- **Category:** Plugin systems
- **What:** Manifest format (id, version, entry, permissions, min-app-version) with loader validation.
- **Why:** Stable contract for third parties.
- **Areas:** neezy_backend/plugins.py, docs
- **Difficulty:** Medium

### 286. [ ] Plugin settings namespace
- **Category:** Plugin systems
- **What:** Plugins get namespaced settings storage (plugins.<id>.*.) exposed in a settings tab.
- **Why:** Plugin config without schema collisions.
- **Areas:** neezy_backend/{config,storage}.py, plugins.py
- **Difficulty:** Medium

### 287. [ ] Plugin dependency isolation
- **Category:** Plugin systems
- **What:** Guidance + loader checks that plugins import lazily and never assume optional deps exist.
- **Why:** A broken plugin must never break startup.
- **Areas:** neezy_backend/plugins.py
- **Difficulty:** Medium

### 288. [ ] Plugin lifecycle hooks
- **Category:** Plugin systems
- **What:** on_start/on_stop/on_settings_change hooks with timeout guards.
- **Why:** Orderly integration with app lifecycle.
- **Areas:** neezy_backend/plugins.py, lifecycle
- **Difficulty:** Medium

### 289. [ ] Community plugin index doc
- **Category:** Plugin systems
- **What:** Docs page listing the contract, examples, and submission etiquette (no auto-install).
- **Why:** Discoverability without a marketplace.
- **Areas:** docs/PLUGINS.md
- **Difficulty:** Easy

### 290. [ ] Plugin smoke-test harness
- **Category:** Plugin systems
- **What:** Test that loads example plugins against the contract and asserts isolation failures are caught.
- **Why:** Contract without tests will drift.
- **Areas:** tests/test_plugins.py (new)
- **Difficulty:** Medium

### 291. [ ] Structured logging mode
- **Category:** CLI & automation
- **What:** neezy-cli --log-format=json emits structured events for scripting pipelines.
- **Why:** Cron/CI users parse output today with fragile grep.
- **Areas:** neezy_backend/cli.py, logging module
- **Difficulty:** Medium

### 292. [ ] Watch mode for signals
- **Category:** CLI & automation
- **What:** neezy-cli signals --watch streams new signals to stdout until interrupted.
- **Why:** Terminal-native signal monitoring without the desktop.
- **Areas:** neezy_backend/cli.py, alerts pipeline
- **Difficulty:** Medium

### 293. [ ] Exit-code consolidation for automation
- **Category:** CLI & automation
- **What:** Documented exit code table (0/1/2/3) implemented uniformly and tested per command.
- **Why:** Scripts need dependable machine-readable outcomes.
- **Areas:** neezy_backend/cli.py, tests
- **Difficulty:** Medium

### 294. [ ] Signals filter flags
- **Category:** CLI & automation
- **What:** --symbol/--min-score/--side/--since filters on the signals command.
- **Why:** Output shaping without post-processing tools.
- **Areas:** neezy_backend/cli.py
- **Difficulty:** Easy

### 295. [ ] Cron recipe docs
- **Category:** CLI & automation
- **What:** docs/AUTOMATION.md with cron/systemd/Task Scheduler examples for common jobs.
- **Why:** Automation is a top CLI use case with no recipes today.
- **Areas:** docs/AUTOMATION.md (new)
- **Difficulty:** Easy

### 296. [ ] Config get/set commands
- **Category:** CLI & automation
- **What:** neezy-cli config get <field> / set <field> <value> with validation, removing manual JSON edits.
- **Why:** The #1 support friction: users hand-edit settings.json today.
- **Areas:** neezy_backend/cli.py, config.py
- **Difficulty:** Easy

### 297. [ ] Headless doctor with JSON output
- **Category:** CLI & automation
- **What:** doctor --json machine-readable environment report incl. stream probe results.
- **Why:** Remote support and kiosk setups need parseable diagnostics.
- **Areas:** neezy_backend/{cli,diagnostics}.py
- **Difficulty:** Easy

### 298. [ ] Batch scan with exit threshold
- **Category:** CLI & automation
- **What:** scan --all --min-score X exits nonzero when nothing qualifies (for alerting pipelines).
- **Why:** Enables external schedulers to gate on scan results.
- **Areas:** neezy_backend/cli.py, scanner.py
- **Difficulty:** Easy

### 299. [ ] Signal webhook-out command
- **Category:** CLI & automation
- **What:** cli command that POSTs the latest signals JSON to a user webhook (reuses dm.py client).
- **Why:** Scripted notification routing without the UI.
- **Areas:** neezy_backend/cli.py, dm.py
- **Difficulty:** Medium

### 300. [ ] Command groups in help
- **Category:** CLI & automation
- **What:** Help organized by group (market, research, mt5, ai, system) with examples per command.
- **Why:** 25+ commands bury the important ones in --help today.
- **Areas:** neezy_backend/cli.py, ui_style.py
- **Difficulty:** Easy


---

## Wave 4 — Operations: security hardening, resilience, observability, CI/CD, packaging, interoperability

### 301. [ ] MT5 password into OS keychain
- **Category:** Security hardening
- **What:** Move mt5_password out of settings.json into OS keyring (keyring lib optional) with settings holding a reference; fallback keeps 0600 file.
- **Why:** Audit item #4: plain-text broker credentials on disk are the top security debt.
- **Areas:** neezy_backend/{config,storage}.py, mt5_bridge.py, packaging deps
- **Difficulty:** Hard

### 302. [ ] Secret redaction in logs
- **Category:** Security hardening
- **What:** Central log filter masks patterns (api keys, tokens, Authorization headers) before any write.
- **Why:** Debug output today can paste keys into logs.
- **Areas:** neezy_backend (logging module), diagnostics.py
- **Difficulty:** Medium

### 303. [ ] Webhook URL allow-list validation
- **Category:** Security hardening
- **What:** dm webhook targets validated against allow-list (https-only, optional domain restrictions) with clear refusal.
- **Why:** The app will POST anywhere today, including to http and file-like URLs.
- **Areas:** neezy_backend/dm.py, config.py
- **Difficulty:** Easy

### 304. [ ] MCP token rotation command
- **Category:** Security hardening
- **What:** neezy-cli mcp rotate-token generates a new bearer and updates the config atomically.
- **Why:** Long-lived static tokens accumulate risk.
- **Areas:** neezy_backend/{mcp,cli}.py
- **Difficulty:** Easy

### 305. [ ] Tunnel read-only assertion test
- **Category:** Security hardening
- **What:** Test that the public tunnel endpoint class only exposes read-only tool subset and separate token.
- **Why:** The invariant is documented but not enforced by test today.
- **Areas:** neezy_backend/tunnel.py, tests/test_tunnel.py
- **Difficulty:** Medium

### 306. [ ] File permission sweep on NEEZY_HOME
- **Category:** Security hardening
- **What:** Startup check: settings/secrets files not world/group readable; repair to 0600 with a log line.
- **Why:** Restores or migrations can leave loose perms.
- **Areas:** neezy_backend/storage.py, diagnostics.py
- **Difficulty:** Easy

### 307. [ ] Dependency CVE watch workflow
- **Category:** Security hardening
- **What:** Weekly GitHub Action running pip-audit against requirements; issues opened on findings.
- **Why:** Supply-chain visibility without runtime additions.
- **Areas:** .github/workflows/security.yml (new)
- **Difficulty:** Easy

### 308. [ ] Input length caps on remote commands
- **Category:** Security hardening
- **What:** Telegram/webhook command strings capped and stripped of control chars before parsing.
- **Why:** Remote inputs reach the parser unbounded today.
- **Areas:** neezy_backend/telegram.py, remote.py
- **Difficulty:** Easy

### 309. [ ] SSRF-safe provider URL construction
- **Category:** Security hardening
- **What:** Provider base URLs validated (https, public host) and request URLs built without user-controlled scheme/host.
- **Why:** Misconfigured base URLs could target internal hosts.
- **Areas:** neezy_backend/providers.py, ai.py
- **Difficulty:** Medium

### 310. [ ] Local LLM weight provenance check
- **Category:** Security hardening
- **What:** Model import records origin path and hash; loading verifies hash before unpickling weights.
- **Why:** Tampered weight files are code execution risk.
- **Areas:** neezy_backend/local_llm.py
- **Difficulty:** Medium

### 311. [ ] Sandbox escape regression CI
- **Category:** Security hardening
- **What:** The escape test suite from wave 1 runs with symlinks enabled and case-trick matrices on CI.
- **Why:** Path jail integrity is a standing guarantee.
- **Areas:** tests/test_sandbox_escape.py, ci.yml
- **Difficulty:** Easy

### 312. [ ] Order-path SQL/argv injection audit
- **Category:** Security hardening
- **What:** Scripted review + tests proving no f-string SQL and no shell=True in any order path.
- **Why:** Defense documentation for the money-touching path.
- **Areas:** neezy_backend/{database,mt5_orders}.py, tests
- **Difficulty:** Easy

### 313. [ ] Kaggle notebook secret hygiene
- **Category:** Security hardening
- **What:** Notebook never echoes env values; add a test scanning cell sources for key-print patterns.
- **Why:** User API keys leak via notebook output cells easily.
- **Areas:** kaggle/NEEZY_on_Kaggle.ipynb, tests/test_kaggle_notebook.py
- **Difficulty:** Easy

### 314. [ ] Token file atomic creation mode
- **Category:** Security hardening
- **What:** Create token/secret files with os.open mode 0600 from the start (no chmod window).
- **Why:** Closes the create-then-chmod race.
- **Areas:** neezy_backend/{mcp,telegram,ai,providers}.py
- **Difficulty:** Medium

### 315. [ ] Key-logging-resistant prompt previews
- **Category:** Security hardening
- **What:** Prompt previews redact secret values (provider keys) from the rendered template.
- **Why:** Previews currently render raw context which can include sensitive config.
- **Areas:** neezy_app/ui_panels/ai_settings.py, context.py
- **Difficulty:** Easy

### 316. [ ] Bridge path validation
- **Category:** Security hardening
- **What:** mt5_path and mcp_tunnel_executable validated as existing, absolute, and (on Windows) .exe.
- **Why:** Path fields feed subprocess spawns today.
- **Areas:** neezy_backend/{config,mt5_bridge,tunnel}.py
- **Difficulty:** Medium

### 317. [ ] Timeout on all outbound HTTP
- **Category:** Security hardening
- **What:** urlopen calls carry explicit timeouts from config (provider, AI, webhook) with no default-infinite.
- **Why:** Hung sockets tie up workers indefinitely.
- **Areas:** neezy_backend/{providers,ai,dm,telegram}.py
- **Difficulty:** Easy

### 318. [ ] Dangerous-tool double confirmation
- **Category:** Security hardening
- **What:** DESTRUCTIVE tools require confirm=True AND a typed phrase matching the tool name.
- **Why:** Stronger friction for the highest-tier actions.
- **Areas:** neezy_backend/tools.py, agent.py
- **Difficulty:** Medium

### 319. [ ] MCP CORS/origin policy
- **Category:** Security hardening
- **What:** MCP HTTP server rejects cross-origin browser requests (Origin header allow-list).
- **Why:** A local port can be reached from any web page the user visits otherwise.
- **Areas:** neezy_backend/mcp.py, tests/test_mcp_http.py
- **Difficulty:** Medium

### 320. [ ] Audit log tamper-evidence
- **Category:** Security hardening
- **What:** Tool audit log entries chained with a running hash (tamper makes verification fail loudly).
- **Why:** Local forensics integrity for a trust-sensitive app.
- **Areas:** neezy_backend/tools.py, database.py
- **Difficulty:** Hard

### 321. [ ] Settings file ownership check (multi-user boxes)
- **Category:** Security hardening
- **What:** On POSIX, warn when settings.json is owned by another user.
- **Why:** Shared machines are a real deployment for families/offices.
- **Areas:** neezy_backend/storage.py, diagnostics.py
- **Difficulty:** Easy

### 322. [ ] Optional app-lock passphrase
- **Category:** Security hardening
- **What:** Optional passphrase lock for opening the app (stretches via hashlib; no cloud).
- **Why:** Shoulder-surfing / shared-computer protection.
- **Areas:** neezy_app (lock screen), storage.py
- **Difficulty:** Medium

### 323. [ ] Dependencies pinned to hashes in release workflow
- **Category:** Security hardening
- **What:** Release builds install with --require-hashes from a generated lock.
- **Why:** Build reproducibility and supply-chain integrity for shipped binaries.
- **Areas:** .github/workflows/release.yml, scripts/gen_lock.py
- **Difficulty:** Medium

### 324. [ ] Webhook egress logging
- **Category:** Security hardening
- **What:** Every outbound webhook logged (target host, size) in the audit trail without payloads.
- **Why:** Exfiltration visibility for a local app.
- **Areas:** neezy_backend/{dm,telegram,ai}.py
- **Difficulty:** Easy

### 325. [ ] Security policy and reporting doc
- **Category:** Security hardening
- **What:** SECURITY.md with supported versions, safe reporting guidance, and threat model summary.
- **Why:** Standard repo hygiene expected for any trading tool.
- **Areas:** SECURITY.md (new), docs
- **Difficulty:** Easy

### 326. [ ] Typed exception hierarchy
- **Category:** Error handling & resilience
- **What:** Base NeezyError with domain subclasses (DataError, ProviderError, BridgeError, ConfigError); CLI renders friendly text per type.
- **Why:** Generic ValueErrors/RuntimeErrors blur recovery paths.
- **Areas:** neezy_backend (errors.py new), all modules
- **Difficulty:** Medium

### 327. [ ] Retry with jitter for provider fetches
- **Category:** Error handling & resilience
- **What:** Bounded exponential backoff + jitter honoring Retry-After for 429/5xx.
- **Why:** Thundering retries after outages worsen them.
- **Areas:** neezy_backend/providers.py, ai_resilient.py
- **Difficulty:** Medium

### 328. [ ] Circuit breaker per provider
- **Category:** Error handling & resilience
- **What:** Open circuit after N consecutive failures; half-open probe after cooldown.
- **Why:** Dead providers slow every scan today.
- **Areas:** neezy_backend/providers.py
- **Difficulty:** Medium

### 329. [ ] Graceful DB degradation mode
- **Category:** Error handling & resilience
- **What:** If SQLite fails (locked/corrupt), run in memory-only mode with a persistent warning banner and retry reattach.
- **Why:** DB problems currently abort features wholesale.
- **Areas:** neezy_backend/database.py, ui banner
- **Difficulty:** Hard

### 330. [ ] Settings write failure recovery
- **Category:** Error handling & resilience
- **What:** Failed settings writes keep the in-memory object and retry with a toast; never silently drop.
- **Why:** Full disks silently discard settings changes today.
- **Areas:** neezy_backend/storage.py, settings panel
- **Difficulty:** Medium

### 331. [ ] Stream zombie detection
- **Category:** Error handling & resilience
- **What:** No messages for X minutes triggers forced reconnect with a reconnecting banner.
- **Why:** Half-dead sockets show stale prices silently today.
- **Areas:** neezy_backend/stream.py, market.py
- **Difficulty:** Medium

### 332. [ ] Provider key validation on save
- **Category:** Error handling & resilience
- **What:** Test-key button in settings performs a minimal authorized call and reports per-key status.
- **Why:** Bad keys surface minutes later during analysis today.
- **Areas:** neezy_backend/providers.py, data_providers panel
- **Difficulty:** Easy

### 333. [ ] Bulk operation partial-failure reporting
- **Category:** Error handling & resilience
- **What:** Scanner/multi-symbol operations collect per-symbol errors and summarize instead of aborting on first.
- **Why:** One bad symbol kills the whole scan today.
- **Areas:** neezy_backend/{scanner,confluence}.py
- **Difficulty:** Medium

### 334. [ ] Disk-full behavior tests
- **Category:** Error handling & resilience
- **What:** Simulate ENOSPC on history/settings/exports; assert graceful messages and no data loss beyond the failed write.
- **Why:** Full-disk behavior is currently untested chaos.
- **Areas:** tests/test_disk_full.py (new)
- **Difficulty:** Medium

### 335. [ ] Corrupt history file quarantine
- **Category:** Error handling & resilience
- **What:** On JSONL parse failure, quarantine the file (.corrupt timestamp rename) and start fresh while keeping the old.
- **Why:** One corrupt line poisons reads forever today.
- **Areas:** neezy_backend/storage.py
- **Difficulty:** Medium

### 336. [ ] Backpressure on UI floods
- **Category:** Error handling & resilience
- **What:** When UI updates queue beyond a threshold, batch-render the latest state and log a dropped-count metric.
- **Why:** Bursty markets can freeze the UI thread today.
- **Areas:** neezy_app (panel base), events.py
- **Difficulty:** Medium

### 337. [ ] AI provider fallback chain
- **Category:** Error handling & resilience
- **What:** User-ordered provider fallback (primary -> secondary -> offline local answer) with visible mode in the transcript.
- **Why:** Single-provider outages kill the copilot today.
- **Areas:** neezy_backend/ai.py, chat.py
- **Difficulty:** Medium

### 338. [ ] Telegram send retry with dead-letter
- **Category:** Error handling & resilience
- **What:** Failed sends retry with backoff; persistent failures park in a dead-letter list with UI view and manual resend.
- **Why:** Notification loss is silent today.
- **Areas:** neezy_backend/telegram.py, alerts.py
- **Difficulty:** Medium

### 339. [ ] Startup self-check gate
- **Category:** Error handling & resilience
- **What:** App start runs quick checks (dirs writable, ports free, imports ok) and shows a diagnostic card on failure with fixes.
- **Why:** Startup failures currently end in a silent exit or traceback.
- **Areas:** neezy_app/launcher.py, diagnostics.py
- **Difficulty:** Medium

### 340. [ ] Watchdog restart of workers
- **Category:** Error handling & resilience
- **What:** Worker threads that die unexpectedly are restarted with a restart counter and eventual user warning.
- **Why:** Background death = silent feature loss today.
- **Areas:** neezy_backend (thread pool), scheduler
- **Difficulty:** Hard

### 341. [ ] MCP malformed request tolerance
- **Category:** Error handling & resilience
- **What:** Protocol-level fuzz: malformed JSON-RPC gets clean error codes, never a crash or hang.
- **Why:** A local server still faces hostile input from browsers/ports.
- **Areas:** neezy_backend/mcp.py, tests/test_mcp_http.py
- **Difficulty:** Medium

### 342. [ ] OOM guard for research
- **Category:** Error handling & resilience
- **What:** Estimate memory before training (samples x features) and refuse with guidance when over budget.
- **Why:** Big histories can OOM the desktop app today.
- **Areas:** neezy_backend/research.py
- **Difficulty:** Medium

### 343. [ ] Export path failure handling
- **Category:** Error handling & resilience
- **What:** Export to unwritable/read-only locations produces actionable errors and a safe fallback to NEEZY_HOME.
- **Why:** Users pick bad paths; today they get tracebacks.
- **Areas:** neezy_backend/exporters.py, storage.py
- **Difficulty:** Easy

### 344. [ ] Consistent Unicode error messages
- **Category:** Error handling & resilience
- **What:** User-facing errors ASCII-safe with no raw tracebacks (tracebacks only in debug mode).
- **Why:** Windows consoles choke on mixed-encoding output today.
- **Areas:** neezy_backend/cli.py, ui_style.py
- **Difficulty:** Easy

### 345. [ ] Chaos harness for stream/provider failures
- **Category:** Error handling & resilience
- **What:** A scripted fault-injection runner: kill stream mid-backtest, provider 500s during scan; asserts UI stability.
- **Why:** Resilience features need adversarial rehearsal.
- **Areas:** tests/chaos/ (new)
- **Difficulty:** Hard

### 346. [ ] Structured logging foundation
- **Category:** Logging & diagnostics
- **What:** Replace print/scattered writes with a logging package: named loggers, levels, and a JSON formatter option.
- **Why:** Log behavior is ad hoc per module today.
- **Areas:** neezy_backend (new logging.py), all modules
- **Difficulty:** Medium

### 347. [ ] Rotating file logs
- **Category:** Logging & diagnostics
- **What:** NEEZY_HOME/logs/neezy.log with size-rotating handler (configurable), auto-pruned old files.
- **Why:** Unbounded logs today; no files at all in the desktop app.
- **Areas:** neezy_backend/logging.py, storage.py
- **Difficulty:** Easy

### 348. [ ] Correlation IDs across pipeline
- **Category:** Logging & diagnostics
- **What:** An analysis request carries an ID from UI click -> fetch -> compute -> render -> log.
- **Why:** Following one action through today's logs is guesswork.
- **Areas:** neezy_backend (events, confluence, panels)
- **Difficulty:** Medium

### 349. [ ] Trace spans for research stages
- **Category:** Logging & diagnostics
- **What:** research/study emit stage durations (fetch/label/train/validate) into a trace file per run.
- **Why:** Slow-stage attribution for heavy jobs.
- **Areas:** neezy_backend/{research,study}.py
- **Difficulty:** Easy

### 350. [ ] Doctor command upgrade
- **Category:** Logging & diagnostics
- **What:** doctor aggregates: env, deps, perms, config sanity, stream probe, DB integrity check, last errors.
- **Why:** One command to attach to bug reports.
- **Areas:** neezy_backend/{cli,diagnostics}.py
- **Difficulty:** Medium

### 351. [ ] Error frequency counters
- **Category:** Logging & diagnostics
- **What:** In-app counters per error type (window 24h) surfaced in settings > diagnostics.
- **Why:** Recurring background errors are invisible today.
- **Areas:** neezy_backend (logging), diagnostics.py
- **Difficulty:** Easy

### 352. [ ] Safe error reporting bundle
- **Category:** Logging & diagnostics
- **What:** neezy-cli doctor --bundle writes a zip (env, redacted config, recent logs) for support.
- **Why:** Manual copy-paste support flow today.
- **Areas:** neezy_backend/{diagnostics,cli}.py
- **Difficulty:** Easy

### 353. [ ] Log level runtime control
- **Category:** Logging & diagnostics
- **What:** Settings and CLI control log level without restart.
- **Why:** Enabling debug after an issue requires restart today (losing the moment).
- **Areas:** neezy_backend/logging.py, settings panel
- **Difficulty:** Easy

### 354. [ ] Stream event counters
- **Category:** Logging & diagnostics
- **What:** Per-symbol message counts, reconnect counts, and last-message age in diagnostics.
- **Why:** Feed health visibility without debug builds.
- **Areas:** neezy_backend/stream.py, diagnostics.py
- **Difficulty:** Easy

### 355. [ ] UI freeze detector
- **Category:** Logging & diagnostics
- **What:** A watchdog notes main-loop stalls > 500ms with the stack of the offending callback.
- **Why:** Freezes are reported by users, never captured.
- **Areas:** neezy_app/ui.py, diagnostics.py
- **Difficulty:** Hard

### 356. [ ] SQLite query timing (debug)
- **Category:** Logging & diagnostics
- **What:** Debug mode wraps repository calls with duration logs; slow-query threshold warning.
- **Why:** DB slowdowns otherwise need external profiling.
- **Areas:** neezy_backend/database.py, logging.py
- **Difficulty:** Easy

### 357. [ ] MT5 bridge call log
- **Category:** Logging & diagnostics
- **What:** Every bridge call (method, duration, ok) logged locally with symbol redaction option.
- **Why:** Disputed order issues need local evidence.
- **Areas:** neezy_backend/mt5_bridge.py, logging.py
- **Difficulty:** Easy

### 358. [ ] Agent decision trace view
- **Category:** Logging & diagnostics
- **What:** The TOOLS page shows the last agent plan with step results and timings.
- **Why:** Agent behavior debuggability for users.
- **Areas:** neezy_backend/agent.py, tools_page.py
- **Difficulty:** Medium

### 359. [ ] Startup timing breakdown
- **Category:** Logging & diagnostics
- **What:** Log stage durations at startup (imports, stores, panels) when timing flag set.
- **Why:** Slow-startup complaints are currently unattributable.
- **Areas:** neezy_app/launcher.py, diagnostics.py
- **Difficulty:** Easy

### 360. [ ] Notification delivery log
- **Category:** Logging & diagnostics
- **What:** Every alert notification records channel, latency, and outcome in a queryable table.
- **Why:** Users dispute missed alerts; evidence helps.
- **Areas:** neezy_backend/{alerts,telegram,dm}.py, database.py
- **Difficulty:** Medium

### 361. [ ] Crash-safe last-state snapshot
- **Category:** Logging & diagnostics
- **What:** On unhandled exception, dump last events and analysis state to NEEZY_HOME/crashes/<ts>.json.
- **Why:** Post-mortem of real crashes currently impossible.
- **Areas:** neezy_app/launcher.py, logging.py
- **Difficulty:** Medium

### 362. [ ] Rate metric for provider calls
- **Category:** Logging & diagnostics
- **What:** Calls-per-minute per provider with a settings-page sparkline.
- **Why:** Rate-limit awareness before hitting limits.
- **Areas:** neezy_backend/providers.py, analytics.py
- **Difficulty:** Easy

### 363. [ ] Log viewer panel
- **Category:** Logging & diagnostics
- **What:** SETTINGS > Diagnostics tab: filterable tail of the rotating log with level filter.
- **Why:** Users should not open files for support.
- **Areas:** neezy_app/ui_panels/settings.py (new tab)
- **Difficulty:** Medium

### 364. [ ] One-line session summary
- **Category:** Logging & diagnostics
- **What:** On clean exit, log one line: duration, signals computed, alerts fired, errors count.
- **Why:** Session health at a glance in logs.
- **Areas:** neezy_app/ui.py (close), logging.py
- **Difficulty:** Easy

### 365. [ ] Export diagnostics as metrics
- **Category:** Logging & diagnostics
- **What:** doctor --metrics in Prometheus text format for local scraping.
- **Why:** Power users already run local collectors.
- **Areas:** neezy_backend/diagnostics.py
- **Difficulty:** Medium

### 366. [ ] CI job for notebook execution
- **Category:** CI/CD & release
- **What:** GitHub Action executes the kaggle notebook cells against a stubbed install (no network) nightly.
- **Why:** Notebook rot discovered by users today.
- **Areas:** .github/workflows/notebook.yml (new)
- **Difficulty:** Medium

### 367. [ ] Matrix add Python 3.13
- **Category:** CI/CD & release
- **What:** Add 3.13 to the CI matrix (experimental allow-fail initially).
- **Why:** Forward compatibility visibility before users hit it.
- **Areas:** .github/workflows/ci.yml
- **Difficulty:** Easy

### 368. [ ] Nightly full chaos run
- **Category:** CI/CD & release
- **What:** Scheduled job running the chaos/fuzz suites with more iterations than PR CI.
- **Why:** Deeper adversarial coverage off the critical path.
- **Areas:** .github/workflows/nightly.yml (new)
- **Difficulty:** Easy

### 369. [ ] Release notes from CHANGELOG automation
- **Category:** CI/CD & release
- **What:** Release workflow extracts the version section from CHANGELOG.md into the GitHub release body.
- **Why:** Manual paste today; notes drift from changelog.
- **Areas:** .github/workflows/release.yml, scripts/release_notes.py
- **Difficulty:** Easy

### 370. [ ] Artifact checksums and signing
- **Category:** CI/CD & release
- **What:** Release artifacts get SHA256SUMS file; optional minisign sig if key provided as secret.
- **Why:** Binary provenance for a trading app.
- **Areas:** .github/workflows/release.yml
- **Difficulty:** Medium

### 371. [ ] CI runtime budget assertion
- **Category:** CI/CD & release
- **What:** Fail CI if the suite runtime grows beyond a threshold budget (ratchet down over time).
- **Why:** Suite creep is silent; budget makes it visible.
- **Areas:** .github/workflows/ci.yml, tests
- **Difficulty:** Easy

### 372. [ ] PR-size and test-impact labels
- **Category:** CI/CD & release
- **What:** Action labels PRs by size and lists touched-module test coverage in a comment.
- **Why:** Review routing and risk awareness.
- **Areas:** .github/workflows/triage.yml (new)
- **Difficulty:** Medium

### 373. [ ] Tag-then-build release flow
- **Category:** CI/CD & release
- **What:** Releases build on vX.Y tags (plus manual dispatch) instead of every main push; retain last-N releases.
- **Why:** Every-push releases bloat storage and invite confusion.
- **Areas:** .github/workflows/release.yml
- **Difficulty:** Easy

### 374. [ ] Wheel size budget check
- **Category:** CI/CD & release
- **What:** CI fails if wheel grows beyond a size budget with an allow-list for data additions.
- **Why:** Data files silently bloat installs.
- **Areas:** .github/workflows/ci.yml, scripts
- **Difficulty:** Easy

### 375. [ ] Build reproducibility check
- **Category:** CI/CD & release
- **What:** Weekly job builds the wheel twice; hashes must match (SOURCE_DATE_EPOCH).
- **Why:** Reproducible builds anchor trust and debugging.
- **Areas:** .github/workflows/nightly.yml
- **Difficulty:** Medium

### 376. [ ] Smoke-test the APK in CI
- **Category:** CI/CD & release
- **What:** Headless Android emulator step that installs the APK and checks the main activity starts.
- **Why:** APK breakage ships silently today.
- **Areas:** .github/workflows/release.yml
- **Difficulty:** Hard

### 377. [ ] EXE launch assertion upgrade
- **Category:** CI/CD & release
- **What:** Windows smoke step also asserts the CLI inside the bundle responds (--version) after build.
- **Why:** Windowed EXE may start but have broken console entry.
- **Areas:** .github/workflows/release.yml
- **Difficulty:** Easy

### 378. [ ] Dependabot config (pip + actions)
- **Category:** CI/CD & release
- **What:** Weekly pip and actions updates with grouped PRs and auto-merge for patch bumps after CI.
- **Why:** Manual dependency upkeep rots pins.
- **Areas:** .github/dependabot.yml (new)
- **Difficulty:** Easy

### 379. [ ] Release canary script
- **Category:** CI/CD & release
- **What:** scripts/verify_release.sh downloads artifacts from a release, checks sums, launches, and reports.
- **Why:** Post-release verification is manual eyeballing today.
- **Areas:** scripts/verify_release.sh (new)
- **Difficulty:** Medium

### 380. [ ] GitHub Pages docs site
- **Category:** CI/CD & release
- **What:** Publish docs/ as a static Pages site on release (mkdocs-style or plain markdown index).
- **Why:** Docs discoverability outside the repo.
- **Areas:** .github/workflows/docs.yml, docs/
- **Difficulty:** Medium

### 381. [ ] Linux AppImage / binary
- **Category:** Packaging & installers
- **What:** Build a self-contained Linux binary (PyInstaller on Ubuntu LTS) in release workflow.
- **Why:** Linux users run from source today.
- **Areas:** .github/workflows/release.yml, packaging/linux/
- **Difficulty:** Medium

### 382. [ ] macOS app bundle (unsigned, documented)
- **Category:** Packaging & installers
- **What:** Build a .app for macOS with an unsigned-warning doc section and notarization how-to.
- **Why:** Mac users run from source today.
- **Areas:** packaging/macos/, release.yml
- **Difficulty:** Medium

### 383. [ ] pipx install support test
- **Category:** Packaging & installers
- **What:** Verify pipx install works (isolated env) and document as the primary install path.
- **Why:** pipx is the cleanest CLI install; untested today.
- **Areas:** pyproject.toml, docs
- **Difficulty:** Easy

### 384. [ ] Dependency groups metadata (PEP 735)
- **Category:** Packaging & installers
- **What:** Adopt dependency-groups for dev/local-models extras where setuptools supports it.
- **Why:** Modern packaging metadata aligns tooling.
- **Areas:** pyproject.toml
- **Difficulty:** Easy

### 385. [ ] Uninstaller hygiene
- **Category:** Packaging & installers
- **What:** Document and script clean removal (paths, config backup prompt) for each platform.
- **Why:** Users uninstalling leave NEEZY_HOME behind unknowingly.
- **Areas:** packaging/, docs
- **Difficulty:** Easy

### 386. [ ] JSONL output streaming for signals
- **Category:** CLI & automation
- **What:** signals --jsonl emits one JSON object per line for tail -f pipelines.
- **Why:** Line-delimited is the unix streaming convention.
- **Areas:** neezy_backend/cli.py
- **Difficulty:** Easy

### 387. [ ] Output template snippets
- **Category:** CLI & automation
- **What:** User-defined output templates for scan/history in a templates file with variables.
- **Why:** Custom report formatting without code.
- **Areas:** neezy_backend/cli.py, ui_style.py
- **Difficulty:** Medium

### 388. [ ] Interactive symbol picker
- **Category:** CLI & automation
- **What:** neezy-cli analyze with no symbol opens a searchable numbered list.
- **Why:** Discoverability for hundreds of symbols.
- **Areas:** neezy_backend/{cli,menu}.py
- **Difficulty:** Easy

### 389. [ ] Shell history file for menu
- **Category:** CLI & automation
- **What:** Menu input persists history (readline where available) across sessions.
- **Why:** Menu retyping is tedious today.
- **Areas:** neezy_backend/menu.py
- **Difficulty:** Easy

### 390. [ ] Exit-time summary table
- **Category:** CLI & automation
- **What:** On menu exit, print session stats (commands run, duration).
- **Why:** Terminal UX polish.
- **Areas:** neezy_backend/menu.py
- **Difficulty:** Easy

### 391. [ ] Progress bars for long ops
- **Category:** CLI & automation
- **What:** Backtest/history fetch show progress lines (percent, ETA) on TTY only.
- **Why:** Long silent waits look hung.
- **Areas:** neezy_backend/cli.py, ui_style.py
- **Difficulty:** Easy

### 392. [ ] --no-color respected everywhere
- **Category:** CLI & automation
- **What:** NO_COLOR/--plain unified across all output paths incl. prompts.
- **Why:** Consistency for piped/scripted contexts.
- **Areas:** neezy_backend/{ui_style,cli,menu}.py
- **Difficulty:** Easy

### 393. [ ] Command timing footer
- **Category:** CLI & automation
- **What:** Optional --timing footer with wall time per stage in machine-readable comment.
- **Why:** Script benchmarking aid.
- **Areas:** neezy_backend/cli.py
- **Difficulty:** Easy

### 394. [ ] Config diff command
- **Category:** CLI & automation
- **What:** neezy-cli config diff compares live settings to defaults or a file.
- **Why:** Users cannot see drifted settings today.
- **Areas:** neezy_backend/{cli,config}.py
- **Difficulty:** Easy

### 395. [ ] Watchlist add/remove commands
- **Category:** CLI & automation
- **What:** neezy-cli watchlist add/remove frxEURUSD for scripted watchlist management.
- **Why:** Enables provisioning scripts.
- **Areas:** neezy_backend/cli.py, config.py
- **Difficulty:** Easy

### 396. [ ] DB inspect subcommands
- **Category:** CLI & automation
- **What:** neezy-cli db stats/tables/integrity with human + JSON output.
- **Why:** Storage ops today require sqlite3 CLI knowledge.
- **Areas:** neezy_backend/{cli,database}.py
- **Difficulty:** Easy

### 397. [ ] Alert test command
- **Category:** CLI & automation
- **What:** neezy-cli alerts test fires a sample notification through each enabled channel.
- **Why:** Channel setup verification in one line.
- **Areas:** neezy_backend/{cli,alerts,telegram,dm}.py
- **Difficulty:** Easy

### 398. [ ] Startup environment report on first run
- **Category:** CLI & automation
- **What:** First CLI run prints a short environment sanity block and config path.
- **Why:** Orient new users without reading docs.
- **Areas:** neezy_backend/cli.py, storage.py
- **Difficulty:** Easy

### 399. [ ] Interactive confirmations flag
- **Category:** CLI & automation
- **What:** --yes global flag for scripted destructive ops with audit log entries.
- **Why:** Automation needs non-interactive paths with accountability.
- **Areas:** neezy_backend/cli.py, tools.py
- **Difficulty:** Easy

### 400. [ ] Man-page style docs for core commands
- **Category:** CLI & automation
- **What:** neezy-cli help <cmd> shows usage, examples, exit codes, related commands.
- **Why:** Deep help without leaving the terminal.
- **Areas:** neezy_backend/cli.py
- **Difficulty:** Easy

### 401. [ ] MT5 trade history import
- **Category:** Import/export & interoperability
- **What:** Import broker deal history (from MT5 reports) into outcomes for unified stats.
- **Why:** Real fills beat simulated outcomes for analysis.
- **Areas:** neezy_backend/{outcomes,mt5_bridge}.py, exporters.py
- **Difficulty:** Medium

### 402. [ ] Candles CSV import
- **Category:** Import/export & interoperability
- **What:** Import OHLC CSVs (with column mapper) into the candle store for backtests.
- **Why:** Users have their own historical datasets.
- **Areas:** neezy_backend/database.py, cli.py (import command)
- **Difficulty:** Medium

### 403. [ ] Settings import/export file
- **Category:** Import/export & interoperability
- **What:** Export/import full settings as a portable JSON with validation and diff preview.
- **Why:** Machine migration is manual file copying today.
- **Areas:** neezy_backend/{config,storage}.py, settings panel
- **Difficulty:** Easy

### 404. [ ] Signal history to DataFrame-friendly JSON
- **Category:** Import/export & interoperability
- **What:** History export as records-oriented JSON arrays for pandas-friendly load.
- **Why:** Analysis in external notebooks is common.
- **Areas:** neezy_backend/exporters.py
- **Difficulty:** Easy

### 405. [ ] Backtest report to markdown
- **Category:** Import/export & interoperability
- **What:** Render backtest reports as markdown tables with a metrics header for sharing.
- **Why:** Sharing results in chats/PRs.
- **Areas:** neezy_backend/exporters.py, backtest.py
- **Difficulty:** Easy


---

## Wave 5 — Polish: enterprise UI/UX, monitoring dashboards, docs, offline robustness, remaining interop

### 406. [ ] Global command palette (Ctrl+K)
- **Category:** Enterprise UI/UX
- **What:** Fuzzy-action palette: navigate pages, switch symbols, run commands, search history.
- **Why:** Power users navigate by keyboard in every modern trading tool.
- **Areas:** neezy_app (palette overlay), ui.py
- **Difficulty:** Hard

### 407. [ ] Toast notification system v2
- **Category:** Enterprise UI/UX
- **What:** Stacking toasts with severity icons, actions (view/dismiss), and auto-duration by severity.
- **Why:** Current toasts are minimal and untyped.
- **Areas:** neezy_app/enterprise.py, glass.py
- **Difficulty:** Medium

### 408. [ ] Consistent loading states
- **Category:** Enterprise UI/UX
- **What:** Every async panel action shows skeleton/spinner state with cancellation where supported.
- **Why:** Users cannot tell working from hung today.
- **Areas:** neezy_app (panel base), all panels
- **Difficulty:** Medium

### 409. [ ] Empty states with guidance
- **Category:** Enterprise UI/UX
- **What:** Empty tables get explanatory cards: why empty, what to do (enable storage, wait for candles).
- **Why:** Blank panels confuse new users.
- **Areas:** neezy_app/ui_panels/*.py sweep
- **Difficulty:** Easy

### 410. [ ] Error states with retry
- **Category:** Enterprise UI/UX
- **What:** Failed loads show inline error cards with retry buttons and error codes.
- **Why:** Failures currently leave panels in limbo.
- **Areas:** neezy_app/ui_panels/*.py sweep
- **Difficulty:** Medium

### 411. [ ] High-contrast theme polish
- **Category:** Enterprise UI/UX
- **What:** Audit the High contrast theme for WCAG-AA text contrast on every surface, fix violations.
- **Why:** Accessibility commitment users depend on.
- **Areas:** neezy_app (theme tokens), ui.py
- **Difficulty:** Medium

### 412. [ ] Dyslexia-friendly font option
- **Category:** Enterprise UI/UX
- **What:** Option to select system font/size for UI text (incl. larger target sizes).
- **Why:** Accessibility beyond contrast.
- **Areas:** neezy_app (theme), settings panel
- **Difficulty:** Medium

### 413. [ ] Keyboard navigation matrix
- **Category:** Enterprise UI/UX
- **What:** Tab order documented and fixed; arrow navigation in tables; Enter/Space semantics.
- **Why:** Keyboard users hit traps in canvas-heavy panels today.
- **Areas:** neezy_app sweep, docs/UI.md
- **Difficulty:** Medium

### 414. [ ] Shortcut cheat-sheet overlay
- **Category:** Enterprise UI/UX
- **What:** A '?' key opens a keyboard overlay listing all shortcuts contextually.
- **Why:** Discoverability of shortcuts without docs.
- **Areas:** neezy_app (overlay), ui.py
- **Difficulty:** Easy

### 415. [ ] Window geometry persistence
- **Category:** Enterprise UI/UX
- **What:** Remember size/position across restarts (multi-monitor safe).
- **Why:** Users re-layout every launch today.
- **Areas:** neezy_app/ui.py, storage.py
- **Difficulty:** Easy

### 416. [ ] Panel layout resize polish
- **Category:** Enterprise UI/UX
- **What:** Panels reflow gracefully at small window sizes (min sizes, scrollable regions).
- **Why:** Half-maximized windows currently overlap controls.
- **Areas:** neezy_app/ui.py, panels
- **Difficulty:** Medium

### 417. [ ] Status bar
- **Category:** Enterprise UI/UX
- **What:** Persistent bottom bar: stream state, last update age, DB usage, clock (config tz).
- **Why:** Global state visibility users currently infer from panels.
- **Areas:** neezy_app/ui.py, diagnostics.py
- **Difficulty:** Medium

### 418. [ ] Symbol tab pinning
- **Category:** Enterprise UI/UX
- **What:** Pin favorite symbols as chart tabs for one-click switching.
- **Why:** Frequent symbol switching is the main navigation loop.
- **Areas:** neezy_app/ui_panels/market.py, config.py
- **Difficulty:** Medium

### 419. [ ] Drag-to-reorder watchlist
- **Category:** Enterprise UI/UX
- **What:** Reorder watchlist rows with drag and drop, persisted.
- **Why:** Order matters to users; manual re-entry today.
- **Areas:** neezy_app/ui_panels/market.py
- **Difficulty:** Medium

### 420. [ ] Signals card grouping
- **Category:** Enterprise UI/UX
- **What:** Group signal cards by direction/symbol with collapse.
- **Why:** Long flat lists are hard to scan.
- **Areas:** neezy_app/ui_panels/signals.py
- **Difficulty:** Easy

### 421. [ ] History date-range filter UI
- **Category:** Enterprise UI/UX
- **What:** Date-range and symbol filters with quick presets (today/week).
- **Why:** Finding past signals is manual scroll today.
- **Areas:** neezy_app/ui_panels/history.py, storage.py
- **Difficulty:** Medium

### 422. [ ] Chart legend and axis options
- **Category:** Enterprise UI/UX
- **What:** Toggleable legend, price/grid axis density, crosshair readout formatting.
- **Why:** Chart readability controls traders expect.
- **Areas:** neezy_app/ui_panels/market.py, chart module
- **Difficulty:** Medium

### 423. [ ] Theme live preview
- **Category:** Enterprise UI/UX
- **What:** Theme picker applies changes live with an undo toast instead of requiring restart or apply button.
- **Why:** Committing to a theme blind is annoying.
- **Areas:** neezy_app/ui_panels/settings.py, theme.py
- **Difficulty:** Medium

### 424. [ ] Scaling for HiDPI displays
- **Category:** Enterprise UI/UX
- **What:** Detect DPI and scale fonts/canvas (Tk scaling factor) with a manual override.
- **Why:** Windows laptops render tiny or blurry today.
- **Areas:** neezy_app/ui.py, launcher.py
- **Difficulty:** Medium

### 425. [ ] Reduced-motion mode
- **Category:** Enterprise UI/UX
- **What:** A setting that disables sheen/spark/animations for accessibility and battery.
- **Why:** Animations can be harmful and distracting for some users.
- **Areas:** neezy_app/glass.py, config.py
- **Difficulty:** Easy

### 426. [ ] Onboarding tour overlay
- **Category:** Enterprise UI/UX
- **What:** First-run spotlight tour of the 10 NAV pages with skip/replay in settings.
- **Why:** Feature depth is invisible to new users.
- **Areas:** neezy_app (tour overlay), config.py
- **Difficulty:** Medium

### 427. [ ] Contextual help widgets
- **Category:** Enterprise UI/UX
- **What:** Hover '?' chips on dense controls explaining the field in plain language.
- **Why:** Domain-heavy settings need inline education.
- **Areas:** neezy_app/enterprise.py (chip widget), panels sweep
- **Difficulty:** Medium

### 428. [ ] Notification center panel
- **Category:** Enterprise UI/UX
- **What:** Unified in-app feed of alerts, errors, and completed jobs with filters.
- **Why:** Missed toasts are gone forever today.
- **Areas:** neezy_app (new panel or drawer), events.py
- **Difficulty:** Medium

### 429. [ ] Batch export dialog
- **Category:** Enterprise UI/UX
- **What:** Multi-select signals/history rows and export selection.
- **Why:** Export currently all-or-nothing per page.
- **Areas:** neezy_app/ui_panels/{signals,history}.py, exporters.py
- **Difficulty:** Medium

### 430. [ ] Compact/comfortable table modes
- **Category:** Enterprise UI/UX
- **What:** Row density toggle per table, persisted.
- **Why:** Screen-size and eyesight differ across users.
- **Areas:** neezy_app/enterprise.py (table helper), panels
- **Difficulty:** Easy

### 431. [ ] Monospace numeric alignment
- **Category:** Enterprise UI/UX
- **What:** Numeric columns use tabular figures (font metrics) for scan-ability.
- **Why:** Misaligned digits slow visual comparison.
- **Areas:** neezy_app (theme fonts), tables
- **Difficulty:** Easy

### 432. [ ] Color-blind safe palette option
- **Category:** Enterprise UI/UX
- **What:** Alternative BUY/SELL colors (blue/orange) selectable per theme.
- **Why:** Red/green defaults exclude a large user group.
- **Areas:** neezy_app (theme tokens), config.py
- **Difficulty:** Easy

### 433. [ ] Dialog consistency pass
- **Category:** Enterprise UI/UX
- **What:** All modal dialogs share header/body/actions styling with standard spacing tokens.
- **Why:** Ad-hoc dialogs look unpolished and vary.
- **Areas:** neezy_app/enterprise.py, panels sweep
- **Difficulty:** Medium

### 434. [ ] Window title context
- **Category:** Enterprise UI/UX
- **What:** Title shows app + active symbol + connection state.
- **Why:** Orientation when multitasking across windows.
- **Areas:** neezy_app/ui.py, market.py
- **Difficulty:** Easy

### 435. [ ] Copy actions on data surfaces
- **Category:** Enterprise UI/UX
- **What:** Right-click copy on signal rows, quotes, and metrics with clean formatting.
- **Why:** Users manually retype values into notes today.
- **Areas:** neezy_app/ui_panels/{signals,market,tools}.py
- **Difficulty:** Easy

### 436. [ ] Sparkline tooltips
- **Category:** Enterprise UI/UX
- **What:** Hover on watchlist sparklines shows start/end/high/low values.
- **Why:** Charts without readouts force guesses.
- **Areas:** neezy_app/glass.py, market.py
- **Difficulty:** Easy

### 437. [ ] Multi-select filters on insights
- **Category:** Enterprise UI/UX
- **What:** Insights tables get multi-select filters (symbols, strategies, dates).
- **Why:** Dense research tables need shaping.
- **Areas:** neezy_app/ui_panels/insights.py
- **Difficulty:** Medium

### 438. [ ] Order desk form validation UX
- **Category:** Enterprise UI/UX
- **What:** Live field validation with inline errors and a summary before confirm.
- **Why:** Order entry is the highest-stakes form.
- **Areas:** neezy_app/ui_panels/orders.py
- **Difficulty:** Medium

### 439. [ ] Settings search
- **Category:** Enterprise UI/UX
- **What:** Settings page search box jumping to matching fields.
- **Why:** 78 fields; findability is the top settings complaint.
- **Areas:** neezy_app/ui_panels/settings.py
- **Difficulty:** Medium

### 440. [ ] Restart-required settings marker
- **Category:** Enterprise UI/UX
- **What:** Fields needing restart are flagged and summarized on change.
- **Why:** Users change connection settings and expect them to apply.
- **Areas:** neezy_app/ui_panels/settings.py, config.py
- **Difficulty:** Easy

### 441. [ ] Idle-state dimming
- **Category:** Enterprise UI/UX
- **What:** When the feed is disconnected, panels dim slightly and show a reconnect ribbon (non-blocking).
- **Why:** Stale-data misreads are the top incident class.
- **Areas:** neezy_app/ui.py, panels
- **Difficulty:** Medium

### 442. [ ] Personal analytics dashboard page
- **Category:** Monitoring & analytics
- **What:** INSIGHTS gains a dashboard: signals/day, hit rate, avg score, alert volumes with period selector.
- **Why:** Users quantify their own usage and engine health today via manual math.
- **Areas:** neezy_app/ui_panels/insights.py, database.py
- **Difficulty:** Hard

### 443. [ ] Outcome win-rate tiles
- **Category:** Monitoring & analytics
- **What:** TP/SL/resolved counts and hit-rate by period on the history page.
- **Why:** Core question: is the engine working?
- **Areas:** neezy_app/ui_panels/history.py, outcomes.py
- **Difficulty:** Medium

### 444. [ ] Engine calibration chart
- **Category:** Monitoring & analytics
- **What:** Predicted win-rate (analog replay) vs realized outcomes over time.
- **Why:** Calibration drift is the engine's key health metric.
- **Areas:** neezy_backend/insights.py, insights panel
- **Difficulty:** Hard

### 445. [ ] Data freshness monitor
- **Category:** Monitoring & analytics
- **What:** Table of symbols with last candle age and gap counts; stale ones highlighted.
- **Why:** Data rot kills signal quality silently.
- **Areas:** neezy_backend/database.py, diagnostics, market panel
- **Difficulty:** Medium

### 446. [ ] Alert effectiveness stats
- **Category:** Monitoring & analytics
- **What:** Per-rule firing counts and outcome linkage.
- **Why:** Alert fatigue tuning needs data.
- **Areas:** neezy_backend/{alerts,outcomes}.py, alerts panel
- **Difficulty:** Medium

### 447. [ ] Usage dashboards for AI
- **Category:** Monitoring & analytics
- **What:** Per-day provider calls, tokens, errors, and cache hit rate.
- **Why:** BYOK spend visibility.
- **Areas:** neezy_backend/database.py (usage), analytics.py, settings panel
- **Difficulty:** Medium

### 448. [ ] MT5 bridge health card
- **Category:** Monitoring & analytics
- **What:** Integrations page card: connection uptime, last error, latency.
- **Why:** Bridge flakiness is opaque today.
- **Areas:** neezy_backend/mt5_bridge.py, integrations panel
- **Difficulty:** Easy

### 449. [ ] Storage growth charts
- **Category:** Monitoring & analytics
- **What:** DB/history/logs size over time with projections and cleanup action.
- **Why:** Disk creep surprise prevention.
- **Areas:** neezy_backend/database.py, settings/diagnostics panel
- **Difficulty:** Medium

### 450. [ ] Stream quality metrics
- **Category:** Monitoring & analytics
- **What:** Reconnects/hour, messages/second, error counts per endpoint.
- **Why:** Feed health beyond a binary connected state.
- **Areas:** neezy_backend/stream.py, diagnostics.py
- **Difficulty:** Medium

### 451. [ ] Session activity log page
- **Category:** Monitoring & analytics
- **What:** Filterable app event history (analysis runs, exports, order attempts).
- **Why:** What did the app do while I was away?
- **Areas:** neezy_backend/database.py (events), tools page
- **Difficulty:** Medium

### 452. [ ] KPI export
- **Category:** Monitoring & analytics
- **What:** One-click export of all dashboard metrics as JSON/CSV for external reporting.
- **Why:** Users share stats in communities.
- **Areas:** neezy_backend/exporters.py, insights panel
- **Difficulty:** Easy

### 453. [ ] Performance panel (debug)
- **Category:** Monitoring & analytics
- **What:** Debug page: stage timings, memory usage, thread count.
- **Why:** In-app visibility replaces external profilers for first-line triage.
- **Areas:** neezy_backend/diagnostics.py, new debug panel
- **Difficulty:** Medium

### 454. [ ] Rule-based health score
- **Category:** Monitoring & analytics
- **What:** Composite app health indicator (feed fresh, storage ok, errors low) with color state.
- **Why:** One glance vs. ten panels.
- **Areas:** neezy_backend/diagnostics.py, status bar
- **Difficulty:** Medium

### 455. [ ] Threshold breach badges
- **Category:** Monitoring & analytics
- **What:** Badges on settings/diagnostics when values leave recommended ranges.
- **Why:** Configuration drift visibility.
- **Areas:** neezy_app (badges), diagnostics.py
- **Difficulty:** Easy

### 456. [ ] Local metrics API (read-only)
- **Category:** Monitoring & analytics
- **What:** Optional read-only /metrics endpoint on the MCP port with the same bearer token.
- **Why:** Local collectors (Prometheus) can scrape NEEZY without new surface area.
- **Areas:** neezy_backend/mcp.py, diagnostics.py
- **Difficulty:** Medium

### 457. [ ] README quickstart rewrite
- **Category:** Documentation & onboarding
- **What:** One-screen quickstart: install, first run, first signal, first export; move depth to docs/.
- **Why:** 41KB README hides the 5-minute path.
- **Areas:** README.md, docs/
- **Difficulty:** Medium

### 458. [ ] User guide (docs/guide)
- **Category:** Documentation & onboarding
- **What:** Task-oriented guide: alerts, orders (safety model), research, AI setup, troubleshooting.
- **Why:** Feature docs exist but are scattered.
- **Areas:** docs/guide/*.md
- **Difficulty:** Medium

### 459. [ ] Glossary of trading terms
- **Category:** Documentation & onboarding
- **What:** Glossary for SL/TP/ATR/confluence/analogs as used by NEEZY specifically.
- **Why:** App terminology differs subtly from generic usage.
- **Areas:** docs/GLOSSARY.md
- **Difficulty:** Easy

### 460. [ ] In-app help menu with links
- **Category:** Documentation & onboarding
- **What:** Help menu: docs links, version, support bundle button, tour replay.
- **Why:** Support self-service entry point.
- **Areas:** neezy_app/ui.py
- **Difficulty:** Easy

### 461. [ ] Sample data pack (optional)
- **Category:** Documentation & onboarding
- **What:** Optional download-free sample candles bundled for offline demo mode on first run.
- **Why:** Empty charts on first open lose users.
- **Areas:** neezy_backend/data/, launcher
- **Difficulty:** Medium

### 462. [ ] VIDEO-free walkthrough docs
- **Category:** Documentation & onboarding
- **What:** ASCII/visual walkthroughs per page in docs/UI.md screenshots-free (text mocks).
- **Why:** Docs that render everywhere including terminals.
- **Areas:** docs/UI.md
- **Difficulty:** Easy

### 463. [ ] Settings field cross-links
- **Category:** Documentation & onboarding
- **What:** Each generated SETTINGS.md row links to the deeper guide section.
- **Why:** From field to explanation in one hop.
- **Areas:** docs/SETTINGS.md (generated), docs/guide
- **Difficulty:** Easy

### 464. [ ] CHANGELOG categories and dates
- **Category:** Documentation & onboarding
- **What:** Enforce Keep-a-Changelog sections and dates; script checks format.
- **Why:** Changelog currently mixes granularities and undated sections.
- **Areas:** CHANGELOG.md, scripts/check_changelog.py
- **Difficulty:** Easy

### 465. [ ] docs/DECISIONS index update
- **Category:** Documentation & onboarding
- **What:** DECISIONS.md gains an index table with status per decision (open/amended/superseded).
- **Why:** Six long decisions are hard to scan today.
- **Areas:** DECISIONS.md
- **Difficulty:** Easy

### 466. [ ] Old docs/ cleanup
- **Category:** Documentation & onboarding
- **What:** Mark pre-split docs (ARCHITECTURE etc.) as historical or fold into new docs; fix links.
- **Why:** Audit item: stale docs mislead contributors.
- **Areas:** docs/*.md
- **Difficulty:** Easy

### 467. [ ] Kaggle notebook narrative pass
- **Category:** Documentation & onboarding
- **What:** Reflow notebook prose to match current UI/features after the wave 3-4 changes.
- **Why:** Notebook predates several new features.
- **Areas:** kaggle/NEEZY_on_Kaggle.ipynb
- **Difficulty:** Easy

### 468. [ ] Accessibility statement
- **Category:** Documentation & onboarding
- **What:** docs/ACCESSIBILITY.md: targets, current status, shortcut list, feedback path.
- **Why:** Commitment and clarity for a11y work.
- **Areas:** docs/ACCESSIBILITY.md (new)
- **Difficulty:** Easy

### 469. [ ] Troubleshooting decision tree
- **Category:** Documentation & onboarding
- **What:** Symptom -> check -> fix tree for the top 20 support flows.
- **Why:** Support burden reduction.
- **Areas:** docs/guide/TROUBLESHOOTING.md
- **Difficulty:** Easy

### 470. [ ] Version compatibility matrix
- **Category:** Documentation & onboarding
- **What:** Supported Python/platform/packaging matrix with test evidence per release.
- **Why:** Expectation setting for contributors and users.
- **Areas:** docs/COMPATIBILITY.md (new)
- **Difficulty:** Easy

### 471. [ ] Doc build gate
- **Category:** Documentation & onboarding
- **What:** CI validates generated docs are current (API/settings) and links resolve.
- **Why:** Generated docs that lag code are worse than none.
- **Areas:** .github/workflows/docs.yml, scripts
- **Difficulty:** Easy

### 472. [ ] Alert rules import/export
- **Category:** Import/export & interoperability
- **What:** Move alert rules between installs as JSON.
- **Why:** Rule setup is laborious to redo.
- **Areas:** neezy_backend/alerts.py, storage.py
- **Difficulty:** Easy

### 473. [ ] Watchlist/symbol-set exchange format
- **Category:** Import/export & interoperability
- **What:** JSON format for watchlists incl. notes, import with merge/replace modes.
- **Why:** Community sharing of focused lists.
- **Areas:** neezy_backend (watchlist model), market panel
- **Difficulty:** Easy

### 474. [ ] Telegram bot config export
- **Category:** Import/export & interoperability
- **What:** Export non-secret telegram wiring (chat ids, flags) for re-setup; secrets stay local.
- **Why:** New-machine setup friction reduction.
- **Areas:** neezy_backend/telegram.py, storage.py
- **Difficulty:** Easy

### 475. [ ] Round-trip export/import test for all stores
- **Category:** Import/export & interoperability
- **What:** Property-style test: export then import of each store preserves data.
- **Why:** Interop guarantees are only as good as their tests.
- **Areas:** tests/test_interop_roundtrip.py (new)
- **Difficulty:** Medium

### 476. [ ] Journal/day-summary to PDF
- **Category:** Import/export & interoperability
- **What:** Print-friendly daily journal PDF via HTML export and system print.
- **Why:** Sharing with mentors/coaches.
- **Areas:** neezy_backend/exporters.py (HTML print CSS)
- **Difficulty:** Medium

### 477. [ ] CSV dialect tolerance on import
- **Category:** Import/export & interoperability
- **What:** Candle import handles comma/semicolon/tab and header variations via sniffer.
- **Why:** Real-world CSVs are messy.
- **Areas:** neezy_backend (import path), cli.py
- **Difficulty:** Medium

### 478. [ ] Clipboard copy for charts
- **Category:** Import/export & interoperability
- **What:** Copy chart canvas to clipboard as PNG for pasting into notes.
- **Why:** Shareable visuals without files.
- **Areas:** neezy_app/ui_panels/market.py (postscript/eps conversion)
- **Difficulty:** Medium

### 479. [ ] Offline mode banner and behavior
- **Category:** Offline robustness & recovery
- **What:** Explicit offline state in the UI; actions requiring network disable cleanly with guidance.
- **Why:** Ambiguous failures when the network drops today.
- **Areas:** neezy_app (status), diagnostics.py
- **Difficulty:** Medium

### 480. [ ] Last-known data badges
- **Category:** Offline robustness & recovery
- **What:** Panels show data age stamps so users know what is stale.
- **Why:** Stale data must be legible.
- **Areas:** neezy_app/ui_panels/{market,signals}.py
- **Difficulty:** Easy

### 481. [ ] Queue alerts during outages
- **Category:** Offline robustness & recovery
- **What:** Notification channels buffer to disk and flush on reconnect with dedupe.
- **Why:** Alerts fired while offline are lost today.
- **Areas:** neezy_backend/{alerts,telegram,dm}.py, storage.py
- **Difficulty:** Medium

### 482. [ ] Settings backup on every save
- **Category:** Offline robustness & recovery
- **What:** Keep last N settings versions for one-click rollback in settings page.
- **Why:** Bad config states are hard to undo today.
- **Areas:** neezy_backend/storage.py, settings panel
- **Difficulty:** Easy

### 483. [ ] DB integrity check and repair
- **Category:** Offline robustness & recovery
- **What:** Startup quick_check; on failure attempt REINDEX/export path with user-visible report.
- **Why:** Corruption currently kills the app or silently loses data.
- **Areas:** neezy_backend/database.py, diagnostics.py
- **Difficulty:** Hard

### 484. [ ] Export journal for crash recovery
- **Category:** Offline robustness & recovery
- **What:** Append-only intent journal for exports; incomplete exports resumable.
- **Why:** Interrupted large exports waste everything today.
- **Areas:** neezy_backend/exporters.py
- **Difficulty:** Medium

### 485. [ ] Network state detection
- **Category:** Offline robustness & recovery
- **What:** Lightweight connectivity probes (DNS + endpoint ping) driving status bar and auto-retry policy.
- **Why:** Reconnect storms today; better backoff with state knowledge.
- **Areas:** neezy_backend/stream.py, diagnostics.py
- **Difficulty:** Medium

### 486. [ ] Crash-safe history appends
- **Category:** Offline robustness & recovery
- **What:** JSONL append wrapped with size+write verification and rollback on partial line.
- **Why:** Partial lines from crashes corrupt history reads today.
- **Areas:** neezy_backend/storage.py
- **Difficulty:** Medium

### 487. [ ] App self-update checker (informational)
- **Category:** Offline robustness & recovery
- **What:** Optional manual 'check for updates' comparing releases via GitHub API, no auto-download.
- **Why:** Users run old builds unknowingly; respect local-first by being informational only.
- **Areas:** neezy_backend (update check), settings panel
- **Difficulty:** Easy

### 488. [ ] Graceful degradation matrix doc
- **Category:** Offline robustness & recovery
- **What:** Docs table: feature vs required resource (net/DB/AI key) and behavior when missing.
- **Why:** Sets expectations; guides tests.
- **Areas:** docs/guide/DEGRADATION.md, tests
- **Difficulty:** Easy

### 489. [ ] Offline test mode for CI
- **Category:** Offline robustness & recovery
- **What:** Run the full suite with network interfaces blocked in the runner (unshare/none).
- **Why:** Proves the offline-first promise.
- **Areas:** .github/workflows/ci.yml (job), scripts
- **Difficulty:** Medium

### 490. [ ] State snapshot on crash for resume
- **Category:** Offline robustness & recovery
- **What:** App writes periodic lightweight state (open symbol, filters) and restores after crash.
- **Why:** Crashes cost users their workspace context.
- **Areas:** neezy_app/ui.py, storage.py
- **Difficulty:** Medium

### 491. [ ] Windows MSI installer
- **Category:** Packaging & installers
- **What:** WiX-based MSI with per-user install, uninstaller, and file associations.
- **Why:** EXE-only distribution lacks install/uninstall hygiene.
- **Areas:** packaging/windows/msi/ (new), release.yml
- **Difficulty:** Hard

### 492. [ ] Portable zip layout (Windows)
- **Category:** Packaging & installers
- **What:** Release a portable zip with EXE, README, and data dir beside it (NEEZY_HOME honored).
- **Why:** Users without install rights; USB-stick usage.
- **Areas:** packaging/windows/, release.yml
- **Difficulty:** Easy

### 493. [ ] Android split-ABI builds
- **Category:** Packaging & installers
- **What:** Buildozer splits armeabi-v7a/arm64-v8a APKs to shrink download sizes.
- **Why:** Smaller APKs improve install rates.
- **Areas:** packaging/android/buildozer.spec, release.yml
- **Difficulty:** Medium

### 494. [ ] Version-embedded builds
- **Category:** Packaging & installers
- **What:** Inject git describe + version into builds; About dialog and --version match release artifacts.
- **Why:** Support asks 'which build?' too often today.
- **Areas:** packaging/*, release.yml, pyproject.toml
- **Difficulty:** Easy

### 495. [ ] Startup crash dialog for packaged apps
- **Category:** Packaging & installers
- **What:** Packaged entry points catch startup exceptions and show a dialog with the support bundle path.
- **Why:** Packaged failures are invisible today (silent exits).
- **Areas:** packaging/windows/neezy_entry.py, android main.py
- **Difficulty:** Medium

### 496. [ ] Data dir migration on version change
- **Category:** Packaging & installers
- **What:** First-run migration of NEEZY_HOME structures across breaking format changes with backup.
- **Why:** Upgrades with old data otherwise break confusingly.
- **Areas:** neezy_backend/{storage,migrations}.py
- **Difficulty:** Hard

### 497. [ ] Install verification smoke script per platform
- **Category:** Packaging & installers
- **What:** Scripts/CI steps that install each artifact into a clean VM/container and run --version + doctor.
- **Why:** Artifact-level verification closes the release loop.
- **Areas:** scripts/, .github/workflows/release.yml
- **Difficulty:** Medium

### 498. [ ] Memory search index pagination UI
- **Category:** Scalability
- **What:** Memory UI results render in pages with counts and fast jumps.
- **Why:** Memory growth degrades chat helper UX today.
- **Areas:** neezy_app/ui_panels/chat.py, database.py
- **Difficulty:** Easy

### 499. [ ] Candle store partition docs and defaults
- **Category:** Scalability
- **What:** Ship the partition design defaults (retention pruning by partition) after the wave-2 prototype.
- **Why:** Years-scale usability without re-engineering.
- **Areas:** neezy_backend/database.py, docs
- **Difficulty:** Hard

### 500. [ ] Concurrent user profiles (single machine)
- **Category:** Scalability
- **What:** NEEZY_USER/profile name env to isolate multiple NEEZY_HOME trees on one machine cleanly.
- **Why:** Households/offices share machines; isolation avoids data bleed.
- **Areas:** neezy_backend/storage.py, launcher
- **Difficulty:** Medium
