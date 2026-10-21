# NEEZY Upgrades — Work Log

Branch: `freebuff/a68ed870d878701bd171af3b`, pushed to `main` as `eb008da` (v1.6.0).

## Verification summary
- `python -m unittest discover -s tests` → 367 tests OK (2 environment skips).
- `ruff check` + `ruff format --check` → clean (ruff 0.17.1).
- `python -m compileall neezy_app neezy_backend forex_signals.py` → clean.
- `python local_ci.py` → ✅ all three gates passed.
- Fake-tk smoke build of `neezy_app.ui.App()` with all new tabs → OK.
- Headless import check of new backend modules → OK.

## Audited and fixed during the work
- `neezy_backend/storage.py`: damaged `SignalHistoryStore.export_csv` / `clear`
  methods restored after an improper class insertion; `Mapping` import added.
- `neezy_backend/config.py`: missing `SYMBOLS` import restored (crash in
  `watchlist_extra` validation); strategy frozenset synced with the engine
  registry (test_platform gate).
- `neezy_backend/strategies.py`: broken one-line import repaired.
- Lint: 38 ruff findings fixed (unsorted imports, E501 long lines, unused
  variables, RUF012 mutable class attributes in tests, B007, RUF059).

## New backend modules
- `neezy_backend/providers.py` — Alpha Vantage / Finnhub / Binance / Twelve
  Data candle fetchers + local `provider-keys.json` key store.
- `neezy_backend/confluence.py` — weighted multi-factor vote, ATR-driven
  SL/TP, analog-replay win rate, strict/search passes, TP/SL resolver.
- `neezy_backend/scanner.py` — `ConfluenceAnalyzer` watchlist agent.

## UI changes (`neezy_app/ui.py`)
- SIGNALS: card strip (INSTRUMENT, BUY/SELL, ENTRY, SL, TP, WIN RATE) +
  always-on ANALYSIS button (strict pass → search pass; persists cards).
- HISTORY: same cards + outcome badge limited to exactly TP or SL.
- SETTINGS > DATA PROVIDERS: provider selector, key save/test, candle count,
  six persisted confluence controls.

Trade-offs worth knowing:
- Provider requests use only the standard library (urllib); no new deps.
- Search mode floors signals at the `confluence_search_score` (default 30) and
  falls back to the last-bar EMA/momentum side when no directional factor
  exists — that is the "always provides signals" requirement.
- History outcome resolution is conservative: stop fills first inside a candle.
