# NEEZY Upgrades — Work Log

## 2026-10-23 — Cloud/light-executor deployment
- Added an observer-first, demo-only Windows executor with runtime-only deps,
  restart-persistent risk limits, broker-side SL/TP, and atomic HF model updates.
- Added cloud candidate training + held-out trade backtests, exact-hash paper
  promotion, scheduled data/retrain jobs, Cloudflare watchdog/R2, and an
  authenticated read-only Vercel dashboard.
- Added an explicit no-order paper-candidate mode with persistent virtual outcomes,
  mandatory spread, gap/corruption protection, and promotion-compatible reports.
- Added atomic recent-equity restoration and read-only paper progress on the dashboard.
- Added offline Python and Node tests plus a production Next.js build gate.
- Full setup and limitations are documented in `docs/CLOUD_OPERATIONS.md`.

Branch for this update: `arena/55d4b77d-neezy` (not merged to `main`).

## Verification summary
- `python local_ci.py` → 971 tests OK (2 environment skips); compile, Ruff lint,
  and formatting gates passed.
- `node --test cloudflare/worker.test.mjs` → 8 tests OK.
- `cd dashboard && npm run build` → production build passed, including the dynamic
  server-rendered status page and Node status route.
- `main.py --once` with an isolated empty data directory stayed observer-only and
  returned a critical offline-broker result without sending orders.
- No real MT5 terminal, Hugging Face repository, Cloudflare account, or Vercel
  deployment was used; those require the credentials and setup in the operations guide.

## Audited and fixed during the work
- `tests/test_mt5_compat.py`: the lazy RPyC client test now follows the same optional-
  dependency skip contract as the other RPyC integration tests on clean dev installs.
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
