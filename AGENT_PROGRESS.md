# AGENT_PROGRESS.md — autonomous run memory

This is the memory file of the autonomous full-repo engineering run on
`jvrboy/NEEZY`. Read this file and `ROADMAP.md` first on any restart, then
resume exactly where the state below says.

## Phase 0 — token and safety setup (done)

- Event buffer / context budget: the model runs with a large but finite
  context window; the working rule used from the start is:
  - never load whole large files when a search + line window will do;
  - after every completed Update: commit + push to `main` immediately
    (progress not pushed is treated as lost);
  - update this file and `ROADMAP.md` before every push so a restart can
    resume mid-Update without losing the plan.
- Assumed interruption model: the run can be cut off at any moment. No
  state lives only in chat; the repo itself carries the plan and progress.

## Environment notes for this run

- System python (`/opt/freestyle/python`, Python 3.12.3) has all runtime +
  test deps but NOT ruff, and its site-packages are read-only.
  A workspace-local venv with ruff was created at `.venv-ci/` (gitignored):
  - lint gate: `.venv-ci/bin/ruff check neezy_app neezy_backend tests forex_signals.py main.py scripts`
  - format gate: `.venv-ci/bin/ruff format --check ...`
  - `python local_ci.py` reruns these internally too; keep both.
- The push happens with `cloud_git push` (Freebuff-managed GitHub
  credential), one push per Update. No `scripts/push_repo.py` needed here
  (that was the previous run's local-mirror tooling).

## State (updated after every Update)

| Item | Value |
|------|-------|
| Phase | 3 — sequential implementation loop, active |
| Latest verified baseline | 1123 tests OK + lint/format clean, AFTER Update #9 push |
| Updates completed | 56/500 (Updates #2, #5, #6, #7, #9 done) |
| Next Update in progress | **Update #10** Extract MT5 bridge connection state machine (next `[ ]` in ROADMAP.md) |

## Roadmap interpretation

The mission asked for a roadmap of 5000 improvements. `ROADMAP.md` groups
those ~5000 improvements into 500 numbered Updates (each large, bundling
10–20 related features/fixes), organized in five waves. This matches the
prior run's structure and is kept unchanged; new Updates are implemented
from item #.offset next (see ROADMAP.md for exact list and status).

## Update log

- Update #9 (roadmap #9, provider abstraction) DONE: added `@runtime_checkable`
  `Provider` protocol (`fetch_candles` + `health` methods) to `neezy_backend/providers.py`;
  implemented on `ProviderSpec`; wired `data_providers.py` UI test worker to `spec.health()`;
  added `tests/test_providers_protocol.py` (5 tests). Suite 1118->1123 tests OK, ruff clean.

- Update #7 (roadmap #7, decouple UI mixins) DONE: refactored
  `neezy_app/ui_panels/orders.py` to use `self.settings_store.load()`
  on the `App` instance instead of instantiating `SettingsStore()` directly;
  updated golden test normalization regex to avoid replacing `/app` inside URLs;
  updated smoke tests in `tests/test_ui_smoke.py`. Suite 1118 tests OK, ruff clean.

- Update #6 (roadmap #6, service context) DONE and pushed: added
  neezy_backend/service_context.py (ServiceContext + scoped defaults),
  memory/signals tools share the context database, added
  tests/test_service_context.py (16 tests). Suite 1102->1118, ruff clean.

- Update #5 (roadmap #5, repository layer) DONE and pushed: added
  neezy_backend/repositories.py (four typed repos + shared helpers),
  LocalDatabase delegates to them with unchanged public surface, added
  tests/test_repositories.py (21 tests). Suite 1081->1102, ruff clean.

- Update #2 (roadmap #2, candle accessor layer) DONE and pushed: added
  `neezy_backend/candles.py` (validator, normalize, CandleStore protocol,
  InMemoryCandleStore, CandleAccessor), unified the Candle type, wired the
  CLI db save/candles and the 5 tools.py fetch sites, added
  tests/test_candles.py (44 tests). Suite 1037→1081, ruff clean. Note: ruff
  gate lives in `.venv-ci/` because system site-packages are read-only.

## Resume instructions

1. Read `AGENT_PROGRESS.md` (this file) and `ROADMAP.md`.
2. Read `HANDOFF.md` for batch-history detail and decisions.
3. Find the first `[ ]` entry in ROADMAP.md; that is the next Update.
4. Implement it completely (no stubs), run the gates:
   - `python local_ci.py` (tests + compile) — must pass;
   - `.venv-ci/bin/ruff check` + `ruff format --check` — must pass;
5. Update ROADMAP.md status → `[x]`, add CHANGELOG section, update this
   file, commit as `Update N: <summary>`, push to `main`.
6. Continue to the next `[ ]` item.
