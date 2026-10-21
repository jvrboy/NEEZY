# NEEZY Repository Audit

Refreshed on branch `neezy-update-2026-10` against the working tree. Earlier
versions of this file described the 2,326-line `ui.py` and 372 tests; both are
out of date.

## Snapshot

| Item | Value |
|------|-------|
| Tests | `python -m unittest discover -s tests`: 438 run, 2 skipped, all OK |
| Lint | `ruff check` on `neezy_app neezy_backend tests forex_signals.py local_ci.py`: 24 errors, all in files this branch did not touch (`neezy_app/glass.py` 12, `neezy_backend/quant.py` 10, `neezy_backend/exporters.py` 2) |
| Format | `ruff format --check`: 3 files would change (`glass.py`, `exporters.py`, `quant.py`), all pre-existing |
| Desktop window | `neezy_app/ui.py` is 784 lines: `App(tk.Tk)` shell, theme, widget helpers, settings apply, close. Screens live in 16 mixins under `neezy_app/ui_panels/` |
| Backend | `neezy_backend/`: 52 Python files, about 16,000 lines |

The split moved 144 methods without changing their bodies. A check of the
parsed AST of each method against `HEAD` found no changes and no missing
methods. `NAV` and `RESEARCH_CONTROLS` moved to `neezy_app/ui_panels/constants.py`
and are still importable from `neezy_app.ui`.

## Architecture

```
Deriv public WebSocket ──► neezy_backend.stream / DerivStreamClient
                                   │
                    indicators, patterns, strategies, confluence, alerts
                                   │
        ┌──────────────────────────┴───────────────────────────┐
  SQLite (neezy.sqlite3, WAL)                       neezy_app.ui (Tkinter)
  candles, signals, history                  shell + ui_panels/* mixins
                                                       │
                                  AI providers (BYOK) · local GGUF models
                                  MCP server · Telegram · MT5 bridge (gated)
```

Panel modules: `market` (watchlist, chart, polling), `signals`, `insights`
(research, brain, strategies), `chat`, `tools_page`, `alerts`, `history`,
`database`, `settings`, `ai_settings`, `local_models`, `data_providers`, `mcp`,
`telegram`, `remote`, `integrations` (MT5 and webhook settings).

Thread rule that still holds: network and model work runs in worker threads and
hands results back through `App.after`. Widgets are only touched on the main
thread. The chat test in `tests/test_ui_smoke.py` checks this for the AI
fallback path.

## Status of earlier findings

1. **Test environment mismatch.** Resolved. Tests run from a venv with the
   package installed. On Debian/PEP 668 systems use a venv; `pip install -e`
   into the system Python is blocked.

2. **No agent tool permission model.** Resolved. `neezy_backend/tools.py` has
   `ToolPermission` tiers. `WRITE` and `DESTRUCTIVE` tools raise
   `PermissionError` unless `confirm=True`. `dry_run` is always allowed.

3. **UI monolith.** Resolved for structure. `ui.py` went from 4,929 lines to
   784, and screens are in separate mixin modules. The methods are unchanged, so
   the split does not by itself fix any UI-thread issues. Heavy work (analysis,
   backtests, model training) still runs in threads; that path was not re-audited
   in this pass.

4. **Live order path could report success while disconnected.** Resolved.
   `place_order` refuses when MT5 is not connected. `preview_order` never
   contacts the terminal. `neezy-cli mt5 order` requires `--confirm` unless
   `--dry-run`. The terminal menu requires typing `SEND`. No agent or MCP tool
   calls `place_order`.

5. **Simulated market data mixed with live data.** Resolved. With the bridge
   disconnected, `get_account_info`, `get_quote`, `fetch_candles`, and
   `get_positions` return an error, not sample numbers. CLI `mt5 account`,
   `quote`, and `candles` refuse to print simulated output. Mock output in
   agent tools is labelled `[SIMULATED]`.

6. **MCP server sprawl.** Partly addressed. Six third-party MT5 and Windows
   desktop MCP servers are listed in `neezy_backend/mcp_catalog.py` for reference
   only. Nothing is installed or started. Two have a read-only mode
   (`desktop-win32`, `desktop-winremote`); the other four do not.

## Open items

- **Plain-text MT5 password.** `settings.json` stores the MT5 password in plain
  text. Moving it to the OS keychain is future work (see `DECISIONS.md`,
  Decision 6). Ariadng's MCP config passes the password on the command line,
  which is visible to other local processes.
- **Thread safety of heavy work.** Analysis, backtest, and training threads have
  not been re-checked for shared state since the split.
- **Pre-existing lint debt.** The 24 ruff errors and 3 unformatted files are in
  `glass.py`, `quant.py`, and `exporters.py`. They were not touched.
- **Test resource warnings.** Six `unclosed database` ResourceWarnings appear in
  the baseline too. They are test-only and do not fail the run.
- **Windows verification.** `packaging/windows/neezy_entry.py` and the
  PowerShell and cmd CLI paths have not been run on Windows from this environment.
- **Phase 4 ("ide") undefined.** Needs a decision from the owner.

## Checklist

- [x] Git backup tag `pre-upgrade-backup`.
- [x] Full test suite passing (438 tests).
- [x] Unified local CI script (`local_ci.py`) runs syntax, ruff lint/format, and unittest gates.
- [x] Split `neezy_app/ui.py` into panel mixins.
- [x] Sandboxed path validation helper in `neezy_backend/storage.py`.
- [ ] Move the MT5 password out of `settings.json`.
- [ ] Re-audit background threads in the UI.
