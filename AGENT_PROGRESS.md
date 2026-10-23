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
| Latest verified baseline | 1102 tests OK (was 1081) + lint/format clean, AFTER Update #5 push |
| Updates completed | 53/500 (Updates #2 and #5 done) |
| Next Update in progress | **Update #6** backend service context object (next `[ ]` in ROADMAP.md) |

## Roadmap interpretation

The mission asked for a roadmap of 5000 improvements. `ROADMAP.md` groups
those ~5000 improvements into 500 numbered Updates (each large, bundling
10–20 related features/fixes), organized in five waves. This matches the
prior run's structure and is kept unchanged; new Updates are implemented
from item #.offset next (see ROADMAP.md for exact list and status).

## Update log

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
