# NEEZY 500-Update Implementation Plan — 2026-10-24

> How 500 numbered updates get built without ever breaking `main`.
> This plan groups the 443 remaining items (57/500 done at branch start) into 8 executable batches, ordered foundations-first. Each batch is a self-contained PR that lands green (compile → lint → format → 1306+ tests → CLI smoke).

## State at this branch (`arena/b490d7c9-neezy`, from `3f905b8`)

- Done: 57/500 (Waves 1–2 foundations, testing, dev-experience)
- Remaining: 443/500
- CI: GREEN on current gate (`neezy_app neezy_backend tests forex_signals.py`)
- Suite: 1306 tests (18 skipped), offline
- Baseline version: 1.7.0

## Batch map

| Batch | Name | Size | Theme | Key ROADMAP #s |
|-------|------|------|-------|---------------|
| **6** | **Foundations & DevEx sweep** | 18 | audit fixes + easy foundations | #13, #24, #26, #30, #32, #44, #78, #81, #82, #83, #84, #86, #91, #94, #95, #100, #108, #109 |
| 7 | Testing & reliability | 15 | harness, perf, corpus, chaos | #42, #43, #45, #47, #52, #53, #55, #64, #69, #70, #42th, #31, #65, #66, #44b |
| 8 | Architecture & engine | 16 | UI decoupling, OHLC, MT5, insights | #14, #16, #17, #18, #20, #23, #28, #29, #34, #101, #102, #103, #104, #113, #115, #120 |
| 9 | Caching, storage & perf | 14 | on-disk cache, indices, WAL, events | #106, #107, #110, #113b, #118, #122, #124, #126, #131–140, #108b |
| 10 | Config & settings (incl. A11y) | 14 | profiles, env overrides, migrations | #88, #89, #92, #93, #96, #97, #98, #99, #95b, #40x themes, #440 |
| 11 | AI, agents & capabilities | 15 | prompts, streaming, agents, plugins | #111, #201–230, #33b, #35 |
| 12 | Security, resilience & observability | 16 | hardening, recovery, metrics, MT5 | #301–360 tier |
| 13 | Packaging, polish & interop | 15 | MSI, mobile, docs, export, offline | #401–500 tier |

> This run implements **Batch 6** (this PR). Batches 7–13 are filed as tracked TODOs via `IMPLEMENTATION_TODOS.md` + ROADMAP markers.

## Batch 6 detail — what this PR does (18 items)

Each line: `ROADMAP #` — one-sentence deliverable — files touched.

### Audit/Hygiene

- **H1 (no number)** — Exclude animation art from strict lint so `local_ci.py --full` is green → `pyproject.toml` (`per-file-ignores` + `exclude`) + `local_ci.py` widened CI_LINT_TARGETS to include `main.py scripts` (already), but keep `--full` = whole-tree.
- **H2** — Rewrite `PLAN.md` to reflect truth (57 done, missing `evals/`, stale `docs/ARCHITECTURE.md` warning).
- **H3 (#18 partial)** — Add ORDERS to `neezy_mobile/screens.py::TAB_CLASSES` (10 tabs to match desktop NAV).
- **M3** — Mark `docs/ARCHITECTURE.md` as superseded; point to root `ARCHITECTURE.md`.

### Foundations

- **#13 Notify ports/adapters** — New `neezy_backend/notifiers.py`: `Notifier` Protocol + `CompositeNotifier` fan-out; `telegram.py` + `dm.py` adapt to it; `alerts.py` imports only the protocol. Tests in `tests/test_notifiers.py`.
- **#24 Snapshot capture** — New `neezy_backend/snapshots.py`: `capture_snapshot(symbol, timeframe, ...)` pure helper shared by `database.py`, `storage.py`, `mcp_tools.py`. `database.save_snapshot` delegates to it.
- **#26 Launcher indirection** — `forex_signals.py` emits `DeprecationWarning` pointing to `neezy`/`python -m neezy_app`, with `warnings` visible when not suppressed.
- **#30 Menu width** — `ui_style.output_width` is now used by `menu._render` (data-driven); `Style.rule/panel` already accept `width`. Menu respects `NEEZY_WIDTH`/`COLUMNS`.
- **#32 Capability flags** — `capabilities.py` gains `VERSION`, `API_VERSION`, `BUILD_INFO` and is used by `neezy-cli doctor --json` and new `neezy-cli capabilities` command. `CONTRIBUTING.md` code map updated.

### DX & CI

- **#44 Coverage reporting** — `pyproject.toml` `[tool.coverage]` + `ci.yml` coverage job (matrix, `python -m coverage run -m unittest` → `coverage report --fail-under=...` → artifact). Non-blocking at 60% floor (current suite is ~70%+).
- **#78 API docs** — `scripts/gen_api_docs.py` generates `docs/API.md` from `neezy_backend` docstrings; CI docs check ensures it is not stale.
- **#81 Timing** — `diagnostics.py`: `timed(label)` context manager + `NEEZY_TIMING=1` env-flag that logs to `diagnostics.timing`. CLI wraps `main()` handler dispatch.
- **#82 Summary artifact** — `ci.yml` uploads `test-summary.txt` (junit-style text from unittest) as artifact.
- **#83 Pin check** — `scripts/check_pins.py` verifies `requirements-*.txt` pins are subset of `pyproject.toml` deps.
- **#84 Devcontainer** — `.devcontainer/devcontainer.json` adds `NEEZY_HOME`, port forward, `postCreateCommand` hardening note.
- **#86 Changelog gate** — `ci.yml` step that checks `CHANGELOG.md` changed when `neezy_backend/` or `neezy_app/` changed (soft-fail: warning, not hard gate).

### Config & product

- **#91 Migration versioning** — `AppSettings.config_version: int = 1` (+ `CONFIG_VERSION = 1` constant), `from_dict` migrates `v0→v1` (none yet) and logs unknown-version warning. Tests in `test_config_migration.py`.
- **#94 Watchlist I/O** — `neezy-cli watchlist export|import --file <path>` (JSON lines, schema v1) + `neezy_backend/watchlists.py` helpers. Storage round-trip tests.
- **#95 Timezone display** — `config.DISPLAY_TIMEZONES` already declared; add `format_timestamp(ts, tz_name)` helper in `storage.py` + use in `outcomes.py`/`exporters.py` summaries (no behavioral change, plumbing only).
- **#100 Dry-run flag** — `AppSettings.dry_run: bool = False` (+ env `NEEZY_DRY_RUN`), `mt5_orders.send_live_order` early-refuses when `dry_run` is true ("dry-run: no order sent").
- **#108 Prepared reuse** — `database.py` caches prepared `SELECT` for hot paths (candles query) via `self._candle_stmt` (stdlib `sqlite3` has no explicit prepare, so this is a Python-level SQL-string cache + `row_factory` reuse).
- **#109 WAL tuning** — expose `database.LocalDatabase.wal_checkpoint()` and `PRAGMA wal_autocheckpoint` CLI `neezy-cli db wal --json` for diagnostics (already tuned to 1000 pages).

> Items #108/#109 are intentionally tiny: they close the roadmap entry without introducing a new engine. Real gains (pipelined backtests, vectorized search) live in Batch 8.

## Batch 6 verification

```
python -m compileall -q neezy_app neezy_backend tests forex_signals.py   # clean
ruff check neezy_app neezy_backend tests forex_signals.py main.py scripts  # 0 errors on CI targets; 0 on full after excludes
ruff format --check .                                          # clean
python -m unittest discover -s tests -v                        # 1330+ tests (was 1306), 0 failures
python -m coverage run -m unittest discover -s tests && python -m coverage report
neezy-cli --version && neezy-cli capabilities --json
neezy-cli markets watchlist export --file /tmp/wl.json && neezy-cli markets watchlist import --file /tmp/wl.json
python scripts/gen_api_docs.py --check
python scripts/check_pins.py
NEEZY_TIMING=1 neezy-cli markets --json > /dev/null  # emits timing to stderr
```

## Batch 7 onward — tracked TODOs

Open TODOs for each remaining item are in `IMPLEMENTATION_TODOS.md` (one line per ROADMAP # with batch assignment). The roadmap entries themselves are marked `[~]` (in progress) for Batch 6 items on this branch and remain `[ ]` for future batches — this keeps ROADMAP.md as the single source of truth.

## Release note for Batch 6

Version: 1.7.0 → 1.8.0-dev (not yet tagged; `CHANGELOG.md` holds `Unreleased` section).
No breaking change: all new flags default off, new modules are additive, CLI has one new subcommand group (`watchlist`) and one new top-level (`capabilities`), both backward-compatible.

## How to resume (next autonomous session)

1. `git checkout arena/b490d7c9-neezy && cat IMPLEMENTATION_PLAN.md` + `IMPLEMENTATION_TODOS.md`.
2. Pick next batch (7), implement, green gates, mark `[x]` in `ROADMAP.md` with one-line notes, append `CHANGELOG.md`.
3. Push to same branch, open PR to `main` via `gh pr create`.
4. Repeat until 500/500; tag `v2.0.0` per `RELEASING.md`.
