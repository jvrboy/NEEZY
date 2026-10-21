# NEEZY Repository Audit — 2026-10-22 autonomous run

Fresh, verified audit for the 500-update engineering run. Every "verified"
claim below was reproduced in this run (test suite, ruff 0.17.1, compileall,
CI logs via the GitHub API). Older findings were re-checked against
`9a17b52` (v1.6.0) and closed or carried forward.

## Verified snapshot

| Check | Result |
|-------|--------|
| `python -m unittest discover -s tests` | **533 tests, 1 failure** (43.9 s) |
| `ruff check .` | **43 errors** (19 kaggle notebook, 14 `neezy_app/glass.py`, 8 `neezy_backend/quant.py`, 2 `neezy_backend/exporters.py`) |
| `ruff format --check .` | 4 files would be reformatted |
| `python -m compileall` | clean |
| GitHub Actions "Python CI" on `main` | **failing** at the Lint step (last 10 runs red) |
| "Release builds" workflow | green (EXE + APK) |
| Unused imports/vars (F401/F811/F841) | none |

## CRITICAL

1. **CI is red on main** (verified from workflow logs). The lint gate sees 24
   errors in `glass.py`, `quant.py`, `exporters.py`; the format gate fails on
   the same files. Every push has been failing quality assurance. Fix first.

## HIGH

2. **Test failure: `tests/test_enterprise_ui.py::test_every_nav_entry_has_glyph_and_title`.**
   `NAV` (constants.py) contains `ORDERS` but `PAGE_TITLES`
   (enterprise.py) has no `ORDERS` entry, so the ORDERS page renders with a
   fallback title. Regression from the ORDERS-page commit.

3. **Interactive menu reads real stdin when mocked** — `neezy_backend/menu.py`
   `run_menu(..., input_fn=input)` binds the builtin at import time, so
   `mock.patch("builtins.input")` in `tests/test_ui_style.py` never applies.
   In CI the test passes only because stdin hits EOF immediately; in an
   interactive-stdin environment the suite hangs in a prompt loop. Correct
   fix: resolve the default inside the function body (`input_fn=None`).

4. **Plain-text MT5 password in `settings.json`** (carried forward, Decision 6
   known gap). Additionally `SettingsStore.save` does **not** `chmod 0o600`
   the file, unlike every other secret store in the codebase
   (`ai.py`, `telegram.py`, `providers.py`, `mcp.py` all do). Minimum fix now:
   owner-only permissions; full fix (OS keychain) is a roadmap item.

## MEDIUM

5. **Documentation drift.** `PLAN.md` marks Batch 5 (`evals/` harness) and
   Batch 8 docs as "Completed", but no `evals/` directory exists in the tree
   and `docs/AGENT.md` itself says so; `DECISIONS.md` Decision 5 promises a
   `neezy_backend/prompts/` package that does not exist. Progress documents
   overstate reality — dangerous for future autonomous runs.

6. **Mobile port tab drift.** `neezy_mobile/screens.py` TAB_CLASSES has 9
   tabs; desktop `NAV` has 10 (mobile lacks ORDERS and a tools/settings gap
   varies). Docstring claims parity with desktop NAV.

7. **Duplicated path-jail implementations.** `storage.py::sanitize_path` and
   `sandbox.py::resolve_within` implement overlapping traversal protection
   with different semantics (`allow_absolute` escape hatch vs strict). Two
   security-critical code paths can drift apart.

8. **Thread-safety of heavy UI work not re-verified since the ui.py split**
   (carried forward). The `App.after` rule is tested only for the AI fallback
   path, not for backtests/training/scanner threads.

9. **Kaggle notebook lint debt** — 19 findings (E501, BLE001 blind except,
   B007 unused loop var, RUF005) in `kaggle/NEEZY_on_Kaggle.ipynb`; outside
   the CI lint path but degrades `ruff check .` for contributors.

## LOW

10. **Test resource warnings.** Several `ResourceWarning: unclosed database`
    warnings from tests that don't close `Store()` handles (cosmetic, but
    noisy and can mask real leaks).

11. **`SignalHistoryStore` default filename** is `signal-history.jsonl`; the
    storage module docstring says `signals-history.jsonl` (naming drift).

12. **Windows-only paths unverified from Linux** (carried forward): the
    PyInstaller entry, PowerShell/cmd menu behavior, MT5 on Windows.

13. **`local_ci.py` and CI lint paths diverge** — `local_ci.py` lints the
    whole tree (incl. kaggle), CI lints only `neezy_app neezy_backend tests
    forex_signals.py`; `tests/test_kaggle_notebook.py` exists so notebooks
    are partially covered.

## Positive findings (no action)

- No `TODO`/`FIXME`/`XXX` markers anywhere; no `eval`/`exec`/`shell=True`;
  no `pickle` of untrusted data (local_llm uses a weights-only unpickler).
- Atomic writes (`_atomic_json_write` with fsync + `os.replace`) for
  settings/history; SQLite in WAL mode; bounded queues in the event bus.
- Strict OHLC validation at the websocket boundary; closed-candle-only
  strategies; conservative outcome resolution (stop fills first).
- Permission tiers on all agent tools; MT5 live orders gated behind typed
  confirmations; CLI refuses simulated data on read commands.
- No secrets committed; secret stores are owner-only files with 0o600
  (except settings.json, item 4).
- Tests cover the full stack offline, including fake-tk UI smoke builds.

## Fix order (Phase 2)

1. Items 1–4 (CI red → green, failing test, menu default binding, settings
   permissions).
2. Items 5–6 (documentation truth, mobile parity).
3. Items 7, 9–13 (dedupe path jails, notebook lint, warnings, naming,
   CI/local lint parity, thread re-audit groundwork) — folded into the
   roadmap where they become larger works.

The remaining engineering work is structured as exactly 500 numbered updates
in `ROADMAP.md` (Phase 3), ordered foundations-first.
