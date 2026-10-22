# NEEZY Autonomous Engineering Run — HANDOFF

This file is the memory of the autonomous senior-engineer run on `jvrboy/NEEZY`
(forex signals desktop workspace: Python/Tkinter + Deriv WebSocket, MT5 bridge,
Kivy mobile port, Kaggle research). It is updated after every batch and pushed
to `main` so progress survives if the run is interrupted.

## Current state

| Item | Value |
|------|-------|
| Phase | 4 (batched implementation) — run context ending; see Next steps |
| Current batch | Batch 3 COMPLETE (8 updates: #105,130,133,136,143,144,145,164) |
| Updates completed | 40/500 (34 implemented + 6 verified-already-done/N-A across batches) |
| Updates remaining | 460 |
| Run started | 2026-10-22 (SAST) |
| Baseline at run start | commit `9a17b52`, v1.6.0 |
| CI on main | green through batch 2 (72ee05e in progress at last check) |

## Batch 3 summary (verified before push)

- Suite: **682 tests OK** (673 → +9).
- Provider TTL response cache; DB maintenance() + WAL tuning; backup
  retention pruning; history compaction at startup; perf smoke ceilings.

## Exact next step for the next run/session

1. Read this file and ROADMAP.md; resume at **Batch 4**.
2. Recommended Batch 4 (wave-1 leftovers): #1 split CLI monolith,
   #3 Signal dataclass, #4 unify path jails, #12 AI package split,
   #19 dataset schema versioning, #37 property-based indicator tests,
   #39 CLI golden files, #40 e2e offline pipeline.
3. Workflow per batch: implement → full local gates (`python local_ci.py
   --full`) → mark ROADMAP entries `[x]` → CHANGELOG section → update this
   file → `python /home/z/my-project/scripts/push_repo.py "<message>"`.
4. Watch CI via ClaudeBridge `list_workflow_runs` after each push.

## Batch 1 summary (verified before push)

- Suite: **630 tests OK** (535 at batch start → +95 new tests).
- `ruff check .` and `ruff format --check .` clean; compileall clean.
- Real bugs found by the new tests and fixed:
  - `exporters.signals_to_csv` crashed (`StringIO(newlines=)` invalid kwarg)
    — shipped broken, now fixed + schema-pinned.
  - `knowledge.record_for` shallow copy leaked nested mutations — now deep.
- Key changes: config STRATEGIES derived from engine registry; risk
  `resolve_stop` helper; settings-load warnings; `--debug`; ResourceWarning
  gate in tests; dev tooling (Makefile, dev_setup, pre-commit, templates).

## Verified state after Phase 2

- Full suite: **535 tests OK** (2 new regression tests added).
- `ruff check .` → clean (whole tree incl. kaggle notebook).
- `ruff format --check .` → clean.
- Fixes pushed: PAGE_TITLES ORDERS entry, menu `input` late binding,
  settings.json chmod 0o600, quant.py/exporters.py/glass.py lint, notebook
  lint, 4 files reformatted.

## Files touched this run

- (Phase 0) `HANDOFF.md` (this file) — created.
- (Phase 1) `ARCHITECTURE.md` — written at repo root (docs/ARCHITECTURE.md
  predates it and covers an older layout; the new root file supersedes it).
- (Phase 1) `AUDIT.md` — replaced with a fresh, verified audit.

## Known bugs found this run (to fix in Phase 2)

- N1 (medium, test infra): `neezy_backend/menu.py` — `input_fn=input` is bound
  at import time, so `mock.patch("builtins.input")` in
  `tests/test_ui_style.py::test_cli_menu_plain_flag_runs_without_colour` has no
  effect; the real stdin is read. Under a stdin that returns blank lines forever
  the menu loops printing the prompt and the suite hangs. Fix: resolve the
  default inside `run_menu` (`input_fn=None` → `input`).
- N2 (high, correctness): `neezy_app/ui_panels/constants.py` — `PAGE_TITLES`
  missing the `ORDERS` entry added with the ORDERS page; test failure above.
- N3 (high, CI): 24 ruff errors in CI's lint path (glass/quant/exporters).
- N4 (low): kaggle notebook lint debt (19 findings) — outside CI lint path.

## Decisions and assumptions

- A1: Work happens in a local clone; commits are pushed to `main` directly via
  the ClaudeBridge GitHub MCP (`push_files_to_branch`). No PRs; owner asked for
  direct pushes.
- A2: "Phase 4 (ide)" from the old audit is out of scope unless the roadmap
  makes it concrete.
- A3: Existing behaviors (BYOK AI, MT5 confirm gates, local-first security
  model in DECISIONS.md 1–6) are preserved; nothing gets relaxed.
- A4: `docs/ARCHITECTURE.md` is kept but superseded by root `ARCHITECTURE.md`
  for this run (docs/ copy left untouched to avoid breaking links).

## BLOCKED items

- (none yet)

## Exact next step

1. Finish Phase 1: write root `ARCHITECTURE.md` + fresh `AUDIT.md`; push.
2. Phase 2: fix N1–N4 + every other audit finding; make CI green; push.
3. Phase 3: author `ROADMAP.md` with exactly 500 numbered updates; push.
4. Phase 4: implement batches; update `CHANGELOG.md`, `ROADMAP.md`, and this
   file after each batch; push each batch.
