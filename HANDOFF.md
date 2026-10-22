# NEEZY Autonomous Engineering Run — HANDOFF

This file is the memory of the autonomous senior-engineer run on `jvrboy/NEEZY`
(forex signals desktop workspace: Python/Tkinter + Deriv WebSocket, MT5 bridge,
Kivy mobile port, Kaggle research). It is updated after every batch and pushed
to `main` so progress survives if the run is interrupted.

## Current state

| Item | Value |
|------|-------|
| Phase | 4 (batched implementation) — active |
| Current batch | Batch 5 COMPLETE (3 updates: #15,38,41) |
| Updates completed | 51/500 |
| Updates remaining | 449 |
| Run started | 2026-10-22 (SAST); resumed in a fresh session same day |
| Baseline at run start | commit `9a17b52`, v1.6.0 |
| CI on main | GREEN on `804d717` (Python CI 3.10/3.11/3.12 all pass; golden JSON float-tolerance fix applied) |
| Suite size | 869 tests (682 → +187 across batches 4+5) |

## Batch 5 summary (verified before push)

- `python local_ci.py --full`: compile, ruff check, ruff format, **869 tests
  OK**, fully offline.
- Stream parser hardened (#38): `parse_candle` converts
  KeyError/TypeError/OverflowError into ValueError; non-mapping history
  payloads rejected up front. Fuzz tests found the `epoch: inf` →
  OverflowError escape for real.
- Event payload contracts (#15): `PAYLOAD_CONTRACTS` + `debug_bus()`;
  validation off by default in production.
- Stream lifecycle race stress tests (#41): 6 tests, fake WebSocketApp,
  no deadlocks, exactly-once `stopped`.
- CI follow-up: batch 4/5 golden JSON fixtures failed on 3.10/3.11
  (statistics-correlation ULP drift). Fixed by float-tolerant JSON
  comparison (`math.isclose` rel 1e-9; strings/structure stay exact).
  Python CI green on `804d717`.

## Batch 4 summary (verified before push)

- `python local_ci.py --full`: compile, ruff check, ruff format, **842 tests
  OK**, fully offline.
- cli.py (2,081 lines) → `neezy_backend/cli/` package (12 modules); entry
  point, public names, and mock.patch targets unchanged.
- ai.py (834 lines) → `neezy_backend/ai/` package (errors/prompts/providers/
  keystore/transport/client); public surface re-exported.
- `storage.sanitize_path` now delegates to `sandbox.resolve_within`
  (single traversal guard); wrapper CWD-anchoring bug found + fixed.
- `ConfluenceSignal.from_dict` / `from_history_record` + typed store
  accessors (`append_signal` / `read_signals`); UI write path wired.
- Datasets: `schema_version: 1` stamped in all 27 JSON datasets; migrating
  loader; future versions fail loud.
- New test modules: indicator properties (80), CLI golden files (27 + 48
  fixtures), e2e offline pipeline (9), signal protocol (21), sanitize
  wrapper (11), dataset schema (12).

## Exact next step for the next run/session

1. Read this file and ROADMAP.md; resume at **Batch 6**.
2. Recommended Batch 6 (architecture wave, size to taste): #2 candle
   accessor layer, #5 repository layer over SQLite, #6 backend service
   context, #7 decouple UI mixins from stores. These are the four remaining
   Hard foundations items; alternatively mix in #9 typing pass, #13
   menu/ui_style split, #42-#47 test-infrastructure items for a lighter
   batch.
3. Workflow per batch: implement → full local gates (`python local_ci.py
   --full`) → mark ROADMAP entries `[x]` → CHANGELOG section → update this
   file → `python /home/z/my-project/scripts/push_repo.py "<message>"`.
4. Watch CI via ClaudeBridge `list_workflow_runs` after each push.
5. Local mirror has no `.git`; the manifest-based pusher
   (`scripts/push_repo.py`) diffs against `.repo_manifest.json` — never
   hand-edit that file; re-run `--init` only after a fresh full mirror.

## Notes carried forward

- `neezy_backend/__init__.py` still says `__version__ = "1.5.0"` while
  pyproject is 1.6.0 — align at the next release commit (deliberately not
  bundled into batch 4 to keep it refactor-only).
- Known indicator quirks pinned in tests (see #37 notes in
  tests/test_indicator_properties.py docstrings): `atr()` does not validate
  candle consistency (inverted first bar → negative ATR); one-ulp wobble on
  flat-series EMA/SMA; `analyze()` rejects a garbage forming bar even though
  it is dropped afterwards. Candidates for roadmap "engine hardening".
- Golden fixtures: regenerate with `NEEZY_UPDATE_GOLDEN=1 python -m unittest
  tests.test_cli_golden` after any intentional CLI output change.
- ClaudeBridge session TTL: if MCP calls start failing with 404, delete
  `/home/z/my-project/scripts/.mcp_session` (the client re-initializes).

## Batch 1-3 summaries (prior sessions)

- Batch 3: 682 tests OK. Provider TTL response cache; DB maintenance() +
  WAL tuning; backup retention pruning; history compaction; perf ceilings.
- Batch 2: 660 tests OK. Theme module, capabilities flags, API contract
  tests, dev tooling (Makefile, pre-commit, templates), settings-load
  warnings, `--debug`.
- Batch 1: 630 tests OK. 95 new tests; real bugs fixed (exporters CSV
  crash, knowledge shallow-copy leak); config STRATEGIES derived; risk
  `resolve_stop`; ResourceWarning gate.

## Decisions and assumptions

- A1: Work happens in a local mirror; commits are pushed to `main` directly
  via the ClaudeBridge GitHub MCP (`push_files_to_branch`). No PRs; owner
  asked for direct pushes.
- A2: "Phase 4 (ide)" from the old audit is out of scope unless the roadmap
  makes it concrete.
- A3: Existing behaviors (BYOK AI, MT5 confirm gates, local-first security
  model in DECISIONS 1-6) are preserved; nothing gets relaxed.
- A4: `docs/ARCHITECTURE.md` is kept but superseded by root
  `ARCHITECTURE.md` (docs/ copy left untouched to avoid breaking links).
- A5 (batch 4): the CLI and AI splits keep module-level re-exports so every
  historical import and patch target survives; subagents were used for
  well-scoped test-only updates (#19/#37/#39/#40) but never push.

## BLOCKED items

- (none)
