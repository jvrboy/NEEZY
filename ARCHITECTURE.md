# NEEZY — Architecture

> Authoritative architecture reference, updated for the 2026-10 cloud/light-executor
> engineering run and verified against the current working tree.
> The older `docs/ARCHITECTURE.md` describes a pre-split monolith and is kept
> for history only.

## 1. What NEEZY is

NEEZY is a **local-first forex/market-signal workspace** with an optional
cloud-trained, lightweight-executor deployment: a native Python desktop
application (Tkinter) streams public market data over the Deriv WebSocket API,
computes deterministic closed-candle signals, and layers optional AI assistance,
ML research, alerting, and a MetaTrader 5 execution bridge on top. It ships four
faces over one backend:

| Face | Entry point | Technology |
|------|-------------|------------|
| Desktop app | `neezy` (`neezy_app.launcher:main`) | Tkinter + panel mixins |
| Terminal menu / CLI | `neezy-cli` (`neezy_backend.cli:main`) | argparse + styled menu (`menu.py`, `ui_style.py`) |
| Android app | `packaging/android/main.py` | Kivy (`neezy_mobile/`), built by Buildozer in CI |
| Lightweight executor | `main.py` (`neezy_backend.executor_service`) | Windows/MT5, JSON inference, loopback HTTP |

Design constraints (see `DECISIONS.md`): single user, no hosted account database,
and no telemetry by default. Network traffic is limited to public market data,
user-configured AI providers, the user's own MT5 terminal, optional notifications,
and explicitly configured Hugging Face/Cloudflare/Vercel integrations. Primary
persistent state lives under a per-user data directory; public datasets and
sanitized executor snapshots can optionally be archived to HF/R2. See
`docs/CLOUD_OPERATIONS.md` for the operational trust boundaries.

## 2. Data directory (`NEEZY_HOME`)

Resolved by `neezy_backend.storage.get_data_dir()`, overridable with the
`NEEZY_HOME` environment variable; otherwise `%APPDATA%\NEEZY` (Windows),
`~/Library/Application Support/NEEZY` (macOS), `$XDG_CONFIG_HOME/neezy`
(Linux). Contents:

- `settings.json` — validated `AppSettings` (config.py), written atomically
- `neezy.sqlite3` — candles, signals, snapshots, AI usage (WAL mode)
- `provider-keys.json` — market-data API keys (owner-only file)
- `telegram-secrets.json` — bot token (separate from settings)
- `signals-history.jsonl` — append-only signal history (atomic rewrites)
- `memory.jsonl` / `memory.sqlite3` — agent memory (FTS5 + TF-IDF vectors)
- `backups/` — zip snapshots created before destructive tool actions
- logs and research artifacts

## 3. Runtime architecture

```
                       ┌──────────────────────────────────────────┐
   Deriv public        │              neezy_backend               │
   WebSocket API ◄─────┤  stream.py  DerivStreamClient             │
   (wss, browser       │    │ reconnect/backoff, candidate URLs    │
    headers, ping)     │    ▼ events (EventBus, bounded queues)    │
                      │  indicators → patterns → strategies        │
                      │    │ confluence.py (weighted vote,         │
                      │    │   ATR SL/TP, analog replay win rate)  │
                      │    ▼ alerts.py (user rules)                │
                      │  database.py (SQLite WAL)  storage.py       │
                      │    (candles/signals/snapshots)  (settings, │
                      │                                 JSONL, zip │
                      │  providers.py (Alpha Vantage/Finnhub/       │
                      │    Binance/Twelve Data candle fetchers)     │
                      │  research.py + brain.py (local neural, stdlib only)
                      │  ai.py (BYOK providers, multi-key failover) │
                      │  local_llm.py (GGUF / transformers, offline)│
                      │  agent.py + tools.py (planner, registry,    │
                      │    permission tiers: READ_ONLY/WRITE/DESTRUCTIVE)
                      │  sandbox.py (path jail)  mt5_*.py (bridge,  │
                      │    orders, preflight, safety gates)         │
                      │  mcp.py (MCP server, loopback) mcp_tools/  │
                      │    mcp_catalog  telegram.py  dm.py  remote.py│
                      └───────────────┬──────────────────────────┘
                                      │
              ┌───────────────────────┼─────────────────────┐
              ▼                       ▼                     ▼
     neezy_app (Tkinter)       neezy_backend.cli       neezy_mobile (Kivy)
     App() = 17 mixins +        25 command groups,      screens.py services.py
     shell; worker threads      menu.py interactive     ui_kit.py
     hand back via App.after     REPL; JSON/plain text
```

### Optional cloud executor plane

`executor_service.py` is independent of Tk and the desktop event loop. It reuses
`MT5Bridge` and `brain.predict` but never invokes training or the backtester.
`model_hub.py` downloads bounded UTF-8 JSON from Hugging Face, verifies its SHA-256
and exact-hash held-out-backtest/paper evidence, then atomically changes a local
active-model pointer. A rejected candidate leaves the previous release active.
`model_validation.py` and `scripts/cloud_train.py` run on the cloud side only.
`paper_validation.py` is the separate no-order path for an explicitly configured
candidate: it verifies every non-paper gate, simulates exact-hash outcomes on MT5
demo candles with nonzero spread, persists restarts, and emits promotion-compatible
evidence. Paper mode forbids live execution and skips production model activation.

`execution_guard.py` persists UTC daily baseline, order count, and last evaluated
candle under `NEEZY_HOME`; it blocks real/simulated accounts, daily-limit breaches,
oversize/excess positions, duplicate candles, and missing broker-side SL/TP.
`status_api.py` exposes only loopback `GET /health` and `GET /api/status`; its bounded
recent-equity series is atomically restored from `executor-status.json`. A named
Cloudflare Tunnel plus Access is the only supported remote path. The Cloudflare
Worker and `dashboard/app/api/status/route.js` are read-only clients; neither has
an order mutation. `dashboard/proxy.js` separately authenticates dashboard users.

The cloud control/data plane is intentionally not highly available: notebook
sessions expire and Vercel is serverless. Only the Windows service is always-on.
Full deployment and rollback procedures are in `docs/CLOUD_OPERATIONS.md`.

### Threading rule

All network/model work runs in daemon worker threads. Results cross into the
Tk main loop exclusively through `App.after` callbacks; widgets are never
touched off the main thread (`tests/test_ui_smoke.py` enforces this for the AI
fallback path). `DerivStreamClient` owns its reconnect thread with exponential
backoff (capped at `max_reconnect_seconds`) and failover across candidate
endpoints. The MCP server runs a threaded `HTTPServer` bounded by a semaphore.

## 4. Signal pipeline (deterministic core)

1. `stream.py` delivers validated OHLC rows (`parse_candle` rejects
   non-positive/NaN/inconsistent candles).
2. `indicators.py` computes EMA/RSI/ATR/MACD/etc. on **closed** candles.
3. `strategies.py` maps 12 named strategies (SUPERTREND, EMA_PULLBACK,
   DIVERGENCE, DONCHIAN, SQUEEZE, MACD, KELTNER, ICHIMOKU, STOCH_RSI,
   MOMENTUM, RSI_REVERSAL, CCI_REVERSION) to BUY/SELL/NEUTRAL votes.
4. `confluence.py` aggregates weighted votes, derives ATR-based SL/TP, and
   estimates a win rate from historical analog replays; a strict pass
   (threshold `confluence_min_score`, default 55) and a search pass (floor
   `confluence_search_score`, default 30) produce the signals cards.
5. `alerts.py` evaluates user rules against each new analysis.
6. Outcomes are resolved conservatively (stop assumed to fill first inside a
   candle) in `outcomes.py` and persisted to history.

Everything in this chain is pure/deterministic where feasible: `quant.py`,
`regime.py`, `trend.py`, `divergence.py` are I/O-free modules with property
tests in `tests/`.

## 5. AI layer (optional, BYOK)

`ai.py` talks HTTPS directly to Gemini / Grok / OpenRouter / Ollama with
multi-key failover; keys are stored locally, never in the repo. `ai_cache.py`
and `ai_resilient.py` add response caching and retry semantics. Prompts are
composed by `context.py` from the same market snapshot the UI shows, so the
chat answers align with on-screen data. `use_knowledge` / `use_memory` /
`use_brain_model` gates keep advisory data out of prompts unless opted in.
`local_llm.py` runs GGUF/transformers models fully offline (weights-only
unpickler; no downloads).

## 6. Agent & tools (local automation)

`agent.py` (`AgentPlanner`) builds plans of `PlanStep`s and executes them
through `tools.py` (`ToolRegistry`). Every tool declares a permission tier:
`READ_ONLY` runs freely; `WRITE`/`DESTRUCTIVE` raise `PermissionError` unless
explicitly confirmed. File-touching tools resolve paths through
`sandbox.py` (`resolve_within`), which jails symlinks and `..` to allowed
roots. Destructive actions snapshot into `backups/` first (storage.py).
The MCP server (`mcp.py`) exposes the same registry over loopback HTTP with
bearer auth; public exposure is a separate opt-in read-only Cloudflare quick
tunnel with its own token.

## 7. MT5 bridge (execution, gated)

`mt5_bridge.py` wraps the `MetaTrader5` package (Windows terminal on the
user's own PC); falls back to a clearly-labelled simulated mode when the
package is absent. `mt5_orders.py` centralizes live-order rules shared by
CLI and desktop: market orders only, explicit confirmation (`--confirm`,
typed `SEND` in the menu, or a default-No dialog on the ORDERS page),
connection- and liveness-gated, never callable from agent/MCP tools.
`mt5_preflight.py` validates environment before first use. The separate NSSM
executor calls the same bridge only after `ExecutionGuard` verifies a real,
connected **demo** account and all persistent risk gates. This unattended path
cannot enable real-account trading; manual live-order behavior is unchanged.

## 8. Packaging & CI

- `pyproject.toml` — setuptools package `neezy-market-workspace`, console
  scripts `neezy` / `neezy-cli`, optional deps for dev/local models; ruff
  config (target py310, E/F/I/UP/B/BLE/RUF, line length 88).
- `.github/workflows/ci.yml` — matrix 3.10/3.11/3.12: ruff lint + format
  check + full unittest discovery + offline CLI smoke + wheel build.
- `.github/workflows/release.yml` — Windows EXE (PyInstaller onefile,
  smoke-started) and Android APK (Buildozer on ubuntu-24.04), published as
  GitHub Releases on every push to main.
- `local_ci.py` — the same three gates (compile, ruff, unittest) for
  pre-push use.
- `kaggle/` — ready-to-run research notebook plus `kaggle/cloud/` candidate
  training/publishing notebook (no broker access and no automatic promotion).
- `requirements-runtime.txt` — PC-only websocket + Windows MT5 dependencies;
  training/cloud-publishing dependencies are separate files.
- `cloudflare/` and `dashboard/` — read-only monitoring deployment components;
  their Node tests and production build are explicit local release checks.

## 9. Testing

The offline unittest suite covers backend modules, property/edge cases for math,
fake-tk smoke builds of the whole UI, CLI integration against stub fetches, MT5
safety, executor risk/model-update behavior, and platform config invariants.
Node tests cover the Worker; the production dashboard build is an explicit local release check.

## 10. Key invariants (do not break)

1. Signals are computed from closed candles only; no look-ahead.
2. Agent/MCP paths can never place live orders.
3. No secrets in the repo; keys live under `NEEZY_HOME` in owner-only files.
4. All local file access from tools goes through the sandbox path jail.
5. Settings are validated on construction (`AppSettings.__post_init__`).
6. UI thread rule: workers → `App.after` → widgets.
7. Offline testability: the entire Python suite passes without network.
8. Unattended execution is observer-first and demo-only; a config flag cannot
   enable it on real, contest, disconnected, or simulated accounts. Exact-candidate
   paper mode requires execution off and has no broker order path.
9. Cloud candidates activate only after exact-hash schema, held-out metric,
   trade-backtest, and paper-evidence checks; activation is atomic.
10. Remote monitoring is read-only and Access-protected; broker credentials and
    Cloudflare/HF/dashboard secrets never enter browser code or Git.
