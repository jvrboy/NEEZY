# NEEZY

NEEZY is a native Python/Tkinter market-monitoring workspace. It reads public market candles from Deriv's WebSocket API and computes educational technical-analysis summaries. It does not place trades, authenticate to broker accounts, or provide financial advice.

## Confluence engine, data providers and card workspace (v1.6.0)

**Confluence.** `neezy_backend/confluence.py` combines every backend tool into one weighted vote per market: the EMA stack, MACD, RSI, ADX/DI, Bollinger extremes, all named strategies (including Divergence and the shipped learned edge weights). The weighted net becomes one card: **INSTRUMENT, BUY/SELL, ENTRY, SL, TP, WIN RATE**. The stop is the ATR multiple set in SETTINGS > DATA PROVIDERS and the target is its larger ATR multiple.

**Win rate.** The card's win rate is a replay of the market's own history: bars whose cheap per-bar confluence proxies match the current reading are walked forward and counted as hit-TP-first or hit-SL-first (the stop fills first when both levels sit inside one candle). Cards report the analog sample count and call this an in-sample replay, never a forecast; not enough history falls back to a clearly-labelled confluence-strength estimate.

**Always-signal ANALYSIS button.** The SIGNALS tab now renders signal cards and an **ANALYSIS** button. It scans the whole watchlist with the full backend, then relaxes strict-mode misses into search mode so the scan always produces cards (markets with too little candle history are listed as unavailable instead of guessing). Every produced card is stored locally and becomes a HISTORY card.

**History with exactly two outcomes.** HISTORY shows the same card fields plus OUTCOME, which is exactly `TP` or `SL` - nothing else. Pending cards resolve automatically from locally stored candles and the local store rejects any other outcome value.

**Data providers.** SETTINGS > DATA PROVIDERS selects the market-data provider used when buffers need history: Deriv (default, public WebSocket, no key), Alpha Vantage, Finnhub, Binance (crypto only) and Twelve Data. API keys are saved to a local owner-only `provider-keys.json` (or read from `ALPHA_VANTAGE_KEY`, `FINNHUB_KEY`, `TWELVE_DATA_KEY`) and can be tested from the tab. Symbols an external provider cannot cover are refused with a clear message rather than silently substituted. The same tab exposes six persisted confluence controls: strict score, search score, ATR stop/target multiples, outcome horizon and minimum win-rate analog samples.

**More strategies.** ICHIMOKU, STOCH_RSI, MOMENTUM (ROC + ADX), RSI_REVERSAL and CCI_REVERSION now join SUPERTREND, EMA_PULLBACK, DIVERGENCE, DONCHIAN, SQUEEZE, MACD and KELTNER in the registry; every one of them votes inside the confluence.

**Backend scanner agent.** `neezy_backend/scanner.py` provides `ConfluenceAnalyzer` for headless use - `scan()` for the strict pass and `full_analysis()` for the strict + search pipeline that the ANALYSIS button drives.

## Features

- Multi-market watchlist and live signal table with selectable timeframes.
- Candlestick canvas and per-market indicator detail for EMA 9/21/50, RSI 14, ATR 14, and MACD histogram.
- Closed-candle analysis, explicit trend/volatility context, and finite/OHLC validation before data reaches the signal engine.
- Reconnecting background WebSocket service with bounded backoff, observable status events, and clean shutdown.
- Local persistent settings (theme, polling rate, data density, candle buffer, refresh, alert threshold, startup timeframe, history size, and market-data connection: custom WebSocket URL and reconnect delays).
- Signal-transition history stored locally with CSV export and configurable desktop beeps.
- Three theme presets, chat input shortcut (Enter), and a compatibility launcher for older instructions.

### Advanced backend (v1.2)

- **Supertrend** (`neezy_backend/trend.py`) with ATR bands, flip detection, bars-since-flip, and distance from the active line. Also adds Donchian and Keltner channels, Williams %R, CCI, rate of change, linear-regression slope, Stochastic RSI, and Bollinger bandwidth percentiles.
- **Divergence engine** (`neezy_backend/divergence.py`): fractal pivot detection, bullish/bearish RSI and MACD-histogram divergence with a 0-1 strength score, and **correlation divergence** — short rolling correlation versus a long baseline, labelled `stable`, `converging`, `decoupling`, or `inverted`, ranked across a basket of markets.
- **Named strategies** (`neezy_backend/strategies.py`): `SUPERTREND`, `EMA_PULLBACK`, `DIVERGENCE`, `DONCHIAN`, `SQUEEZE`, `MACD`, `KELTNER`, plus the pair strategy `CORRELATION_DIVERGENCE`. Each returns a direction, a 0-100 confidence, reasons, and its metrics; `run_all()` scores them together and `consensus()` turns them into a vote-weighted verdict.
- **Local SQLite database** (`neezy_backend/database.py`): candles, signal transitions, analysis snapshots, AI usage, memory, and key/value state in one WAL-mode file. Retention pruning, `VACUUM`, JSON export, and per-table counts are built in. The database is local; there is no hosted database service.
- **Bring-your-own-key AI** (`neezy_backend/ai.py`): Gemini, Grok (xAI), OpenRouter, and Ollama Cloud, each with multiple API keys. Keys rotate automatically on quota (402/429), auth (401/403), or transient errors, with per-key cooldowns and usage logging.
- **Local context builder** (`neezy_backend/context.py`): one compact indicator summary feeds both `neezy-cli read` and the chat, so the AI always sees the same numbers the UI shows.

### AI providers (free models only)

Open **SETTINGS → AI PROVIDERS**, pick a provider, paste a key, and press **Add key**. Repeat for as many keys as you like; the pool is tried in least-recently-used order and a key that reports a quota or rate limit is parked for a cooldown (15 minutes by default, 24 hours for a rejected key) before it is retried. The model dropdown lists free models only. If a catalogue has gone stale, `neezy-cli ai chat --model <id>` accepts any model id, and the base URL can be overridden in Settings to point at a proxy or a self-hosted Ollama endpoint.

| Provider | Default base URL | Free model examples |
| --- | --- | --- |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash` |
| Grok (xAI) | `https://api.x.ai/v1` | `grok-3-mini`, `grok-4-fast` |
| OpenRouter | `https://openrouter.ai/api/v1` | `deepseek/deepseek-r1:free`, `meta-llama/llama-3.3-70b-instruct:free` |
| Ollama Cloud | `https://ollama.com/v1` | `gpt-oss:20b`, `gpt-oss:120b`, `deepseek-v3.1:671b` |

Keys are written to `ai-keys.json` in the NEEZY data directory with owner-only permissions (`0600`) on POSIX; on Windows the `%APPDATA%` ACL applies. They are stored in plain text because the app must send them to the provider, so treat that file like any other credential store. Keys are never logged, printed in full, or sent anywhere except the provider you selected.

### Local generative models (offline inference)

In **SETTINGS → LOCAL MODELS**, register a `.gguf` file or a complete local Transformers model folder (SafeTensors or standard PyTorch `.bin` weights, with `config.json` and tokenizer files). Registration stores the path and metadata only; NEEZY does not copy or download multi-gigabyte weights. Keep the source path intact. GGUF inference uses the optional `llama-cpp-python` runtime with mmap enabled, CPU-only execution, and bounded context/batch/thread settings. mmap can reduce eager allocation, but it does **not** guarantee that only one model layer is resident in RAM; the OS page cache and KV cache also consume memory. SafeTensors files are weights, not a runtime: use Transformers + PyTorch, and optionally Accelerate for best-effort CPU/SSD module offload. Offload can require extra temporary disk space, which NEEZY removes after generation. The runtime never downloads model files and sets `trust_remote_code=False`; PyTorch `.bin` loading also requests restricted `weights_only` deserialization. Only import trusted models, and expect CPU inference to be slow on mobile.

Optional installation extras (some packages need platform-specific wheels or native build tools):

```bash
python -m pip install '.[local-gguf]'
python -m pip install '.[local-transformers,local-disk-offload]'
```

The local model can be selected for CHAT without an API key; if inference cannot start, NEEZY falls back to its deterministic on-device rule-based read. Available model formats/runtimes depend on the operating system and Python build.

### MCP agent bridge, Telegram and local learning

**MCP for local clients.** In **SETTINGS → MCP SERVER**, enable the server and copy the displayed URL and bearer token into an MCP client that runs on the same computer and supports Streamable HTTP. The default endpoint is `http://127.0.0.1:8765/mcp`. It is loopback-only and token-protected; rotate the token from Settings to revoke old clients. Read tools cover market analysis, strategy scans, recent signals, alerts, settings, local memory, outcomes and the optional research model. Write tools (alert changes, safe workspace settings, selection, memory saves and model training) are hidden and denied until **Allow write tools on the local MCP server** is enabled. This switch never enables writes through the public tunnel. There is no shell, arbitrary-file or broker/trade tool.

**Public tunnel (opt-in).** If you explicitly enable **Enable public Cloudflare quick tunnel (read-only)**, install `cloudflared` separately and point the Settings field to its executable. NEEZY launches it only while the local MCP server is enabled and displays a temporary HTTPS URL after Cloudflare provisions one. No inbound firewall port is opened; traffic is proxied through Cloudflare. The public listener has a distinct bearer token, a 60-request/minute limit, and a strict market-only read allow-list (`app_status`, market list/analysis/scan, outcome report, and advisory model status/prediction). It does not expose settings, local memory, signal history, chat, alerts, model training, or any writes—even when local MCP writes are enabled. Only connect an agent that supports MCP Streamable HTTP and a custom bearer token; not every hosted agent supports those options. Any agent with the public token can read the exposed market tools, so only share it with a trusted client. Disable the tunnel or rotate its token to revoke access; quick-tunnel URLs are temporary. Cloudflare is an external service and can observe proxied traffic/metadata. Browser clients that send a non-loopback `Origin` are rejected; this is intended for server-to-server MCP clients. The loopback MCP token is never reused for the tunnel. A local MCP client may forward tool results to its model provider, so review that provider's data policy.

**Telegram alerts and commands.** Create a bot with `@BotFather`; in **SETTINGS → TELEGRAM**, paste and save the bot token, optionally test it, enter your numeric Telegram chat ID(s), then enable the bot. Message the bot with `/start` after adding the chat ID. Alert-rule triggers and qualifying signal changes can be sent to authorized chats. Read commands (`/status`, `/markets`, `/signals`, `/analyze`, `/scan`, `/ask`, `/alerts`, `/help`) are available to allow-listed chats. The separate write-permission checkbox enables `/alert`, `/remember`, `/set` and `/delete-alert`. The bot token is stored separately in `telegram-bot.json` with owner-only permissions (`0600` when supported); chat IDs and feature flags are in `settings.json`. Telegram is an external service: messages and enabled alert content are sent through Telegram's Bot API.

**Local memory and neural experiment.** Stored notes stay in the local SQLite database. **Include relevant local memory in provider prompts** is off by default; enable it only if you want relevant notes included in AI-provider requests. In **SETTINGS → ENGINE**, train the optional local model from saved candles; the separate context checkbox controls whether its advisory output is included in app context. The model is research-only, uses chronological holdout validation, and never changes the core signal score or places trades. The UI needs at least 300 saved candles for a training attempt; performance must be assessed on untouched data and is not a guarantee of future results. Headless commands are also available:

```bash
neezy-cli brain train EURUSD -t 15m
neezy-cli brain status EURUSD -t 15m
neezy-cli brain predict EURUSD -t 15m
```

### Advanced analytics (v1.1)

- **Extended indicator engine**: Bollinger Bands (%B, bandwidth), Stochastic %K/%D, Wilder ADX with +DI/-DI, and SMA, plus a market-regime label (Trending / Ranging / Squeeze). The original 4-point score is unchanged, so existing alert thresholds keep working.
- **Price action**: candlestick patterns (doji, hammer, shooting star, marubozu, engulfing, inside bar), floor-trader pivots, and fractal swing support/resistance.
- **Chart overlays**: EMA 21, rolling Bollinger Bands, nearest support/resistance, a last-price marker, and price-axis labels with the correct precision for each market.
- **Trader toolkit (TOOLS tab)**: an ATR-based risk planner (position size, stop, target, risk and reward amounts), a walk-forward backtester (on the live buffer or on up to 5,000 freshly fetched candles in a background thread), and a market ranking with the strongest cross-market return correlations.
- **Alert rules (ALERTS tab)**: persistent rules on price, RSI, score, ADX, signal, or candle pattern with `>`, `>=`, `<`, `<=`, `==`, `crosses above`, and `crosses below`. Rules fire on the transition to true (edge-triggered), so they do not repeat on every tick.
- **Smarter copilot**: chat understands market names and questions about risk, levels, patterns, trend/regime, and the best current setups.
- **Headless CLI (`neezy-cli`)**: scan, analyze, backtest, risk, correlation, history, and alert management from a terminal, with `--json` output for scripting.
- **Reliability fixes**: late updates from a previous timeframe subscription are now discarded, typed spinbox values are saved, the history file compacts itself automatically, and read-only dropdowns follow the theme.

### Backtest methodology

Decisions use closed candles only and fill at the *next* candle's open. When the stop and target are both touched inside one candle, the stop is assumed to fill first. Results are reported in R multiples (1R = initial stop distance): trades, win rate, total R, expectancy, profit factor, max drawdown, and per-trade Sharpe. Simulated results do not predict future performance.

## Install and run

Python 3.10 or newer is required. The existing CI matrix covers Python 3.10–3.12; other versions are not claimed until tested. Tkinter must be installed separately by the operating system (on Debian/Ubuntu, the `python3-tk` package may be needed). Install the desktop app and its WebSocket dependency from the repository root:

```bash
python -m pip install .
neezy
```

Alternatively, run from a checkout without installing:

```bash
python -m pip install -r requirements.txt
python -m neezy_app
```

The original `python forex_signals.py` entry point remains available. The GUI requires a desktop session.

**Kaggle notebooks.** `kaggle/NEEZY_on_Kaggle.ipynb` installs the headless engine and CLI
in a Kaggle session, points `NEEZY_HOME` at `/kaggle/working/neezy-home` so candles,
settings and history survive the session, prints live confluence cards, and can capture a
screenshot of the Tk workspace on a virtual display. Kaggle has no desktop session, so the
GUI is not interactive there, and the MT5 bridge, Telegram bot, local MCP server and
Cloudflare tunnel are not usable on Kaggle. With Internet switched off, attach a copy of
this repository as a Kaggle Dataset and set `INSTALL_SOURCE = "dataset"`; see
[`kaggle/README.md`](kaggle/README.md) for both install paths, storage and limits.

**Android / Pydroid 3:** NEEZY's Python backend and `neezy-cli` are headless and do not import Tkinter. In Pydroid, install/clone the project in a writable directory, install the base dependency (`websocket-client`) with Pydroid's pip/quick-install support, and run `python -m neezy_backend --help` or `python -m neezy_backend markets`. Grant the app storage permission if you choose a shared location; set `NEEZY_HOME` to a writable app-owned directory if the default config path is unsuitable. Market data still needs an internet connection. Tkinter/desktop widgets are not expected to work in Pydroid. Native `llama-cpp-python`, PyTorch, Transformers, and `cloudflared` availability depends on compatible Android wheels/binaries; NEEZY does not bundle them, and the optional model/tunnel features may therefore be unavailable on a particular phone. This repository has not been validated on a physical Android/Pydroid device.

## Command-line tools

The `neezy-cli` command (also `python -m neezy_backend`) needs no display:

```bash
neezy-cli markets                              # list markets and timeframes
neezy-cli scan -t 15m                          # rank every market by signal strength
neezy-cli analyze EURUSD -t 1h                 # indicators, pivots, levels, patterns
neezy-cli backtest GBPUSD -t 5m -n 3000 --spread-pips 0.8 --trades
neezy-cli risk EURUSD --balance 10000 --risk 1 --entry 1.0850 --stop 1.0825
neezy-cli risk USDJPY --balance 5000 --entry 150.2 --direction SELL --atr 0.18 --pip-value 6.7
neezy-cli correlation EURUSD GBPUSD USDCHF --window 200
neezy-cli alerts add EURUSD rsi "crosses above" 70 --note "overbought"
neezy-cli alerts                               # list rules (shared with the desktop app)
neezy-cli history --summary
```

Every command accepts `--json`. Markets can be written as `EURUSD`, `EUR/USD`, or `frxEURUSD`.

### Advanced analysis and local data

```bash
neezy-cli read EURUSD -t 15m                  # engine + Supertrend + divergence + strategies
neezy-cli supertrend EURUSD -t 1h --period 10 --multiplier 3
neezy-cli divergence GBPUSD -t 5m --lookback 5
neezy-cli corrdiv EURUSD GBPUSD USDCHF --window 50 --baseline 200
neezy-cli strategies                          # list the registry
neezy-cli strategies EURUSD -t 15m            # score every strategy + consensus
```

```bash
neezy-cli db stats                            # path, size, row counts
neezy-cli db save EURUSD -t 15m -n 500        # fetch and store candles on this PC
neezy-cli db candles EURUSD -t 15m --limit 20
neezy-cli db signals --limit 20
neezy-cli db export ~/neezy-export.json
neezy-cli db prune --days 30
neezy-cli db vacuum
```

```bash
neezy-cli ai providers                        # provider, free models, key counts
neezy-cli ai models openrouter
neezy-cli ai keys add openrouter --label "work key"   # prompts with hidden input
neezy-cli ai keys                             # ids, masked keys, usability
neezy-cli ai keys reset gemini               # clear that provider's cooldowns
neezy-cli ai reset                           # ...or every provider
neezy-cli ai chat "is EURUSD trending?" --provider gemini --symbol EURUSD
neezy-cli ai usage
```

`NEEZY_AI_KEY` supplies a key without putting it in shell history, and `ai chat` records every attempt in the local `ai_calls` table.

Local models can also be managed without a display (including from a mobile terminal):

```bash
neezy-cli local-model runtime --json
neezy-cli local-model add ~/models/my-model.gguf --name "Small local model"
neezy-cli local-model list
neezy-cli local-model chat <MODEL_ID> "Summarize the current market context"
neezy-cli local-model remove <MODEL_ID>    # removes the index entry, not weight files
```

Use `neezy-cli local-model --help` for context, output, thread, batch, and offload options. Headless CLI commands do not require Tkinter.


## Connection troubleshooting

NEEZY tries Deriv's current public market-data endpoint
(`wss://api.derivws.com/trading/v1/options/ws/public`, no app id or login needed)
first, then the legacy v3 hosts (`ws.derivws.com`, `ws.binaryws.com`,
`frontend.binaryws.com`). The legacy hosts sit behind Cloudflare and can answer
`Handshake status 520` ("origin error") for long stretches; that means Deriv's
host is down or refusing the request, and the app cannot fix it server-side. The
app rotates to the next endpoint and reports failures as one readable line
instead of a raw header dump.

Diagnose connectivity without opening the GUI:

```bash
neezy-cli doctor            # probe every endpoint, print status and detail
neezy-cli doctor --json     # machine-readable
```

If every endpoint fails, the network path is the problem, not the app. Check,
in order: VPN or proxy in use, antivirus/firewall TLS inspection, corporate DNS,
then try a different network (for example a mobile hotspot) and run `doctor`
again. If one endpoint works and another does not, pin the working one:

```bash
# Windows CMD
set NEEZY_WS_URL=wss://api.derivws.com/trading/v1/options/ws/public
neezy
```

```bash
# PowerShell
$env:NEEZY_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
neezy
```

```bash
# macOS / Linux
export NEEZY_WS_URL="wss://api.derivws.com/trading/v1/options/ws/public"
neezy
```

Related environment variables:

| Variable | Purpose |
| --- | --- |
| `NEEZY_WS_URL` | Pin a single market-data endpoint (proxy, or a host not listed above). Disables rotation. |
| `NEEZY_APP_ID` | Use your own registered Deriv app id instead of the shared `1089` test id. |

Both are read when the app starts, so restart `neezy` after changing them.

## Local data

Settings, alert rules, signal history, and the SQLite database live in the user's application data directory (Linux: `$XDG_CONFIG_HOME/neezy`, otherwise `~/.config/neezy`; macOS and Windows use their usual per-user application data locations). Set `NEEZY_HOME` to override the directory, useful for portable installs and tests.

| File | Contents |
| --- | --- |
| `neezy.sqlite3` | Candles, signal transitions, analysis snapshots, AI call log, key/value state |
| `settings.json` | Workspace, engine, storage, AI, MCP and Telegram settings; contains Telegram chat IDs but no bot token |
| `ai-keys.json` | Provider API keys and their cooldown/usage state (`0600` when supported) |
| `mcp-token.json` | Local MCP bearer token (`0600` when supported) |
| `telegram-bot.json` | Telegram Bot API token (`0600` when supported) |
| `signal-history.jsonl` | Append-only signal log kept for CSV export |
| `alerts.json` | Alert rules |

Settings are written atomically. The database runs in WAL mode, prunes rows older than the configured retention (default 90 days) via `db prune` or **SETTINGS → LOCAL DATA → Apply retention now**, and can be exported as JSON from the same tab. The JSONL history compacts itself to the newest 5,000 records once it passes about 2 MB, and history export creates a standard CSV at the location you choose.

NEEZY does not upload the database or send telemetry. Network traffic includes Deriv's public market feed, requests to a configured AI provider when AI answers are enabled, and Telegram messages/alerts when the Telegram bot is enabled. Local notes enter AI-provider prompts only when the memory-context option is enabled. The MCP endpoint is bound to loopback and serves a local MCP client; a hosted service cannot reach it without a separately secured tunnel.

## Project layout

```text
neezy_app/             Tkinter application and installed CLI entry point
neezy_backend/         validated settings, stream events/client, analysis, persistence
  trend.py             Supertrend, Donchian, Keltner, Williams %R, CCI, Stoch RSI
  divergence.py        pivot detection, RSI/MACD divergence, correlation divergence
  confluence.py        multi-factor confluence engine, win-rate replay, TP/SL resolver
  providers.py         Deriv/Alpha Vantage/Finnhub/Binance/Twelve Data candle fetchers
  scanner.py           watchlist confluence scanner agent (strict + search passes)
  strategies.py        named strategy registry, consensus voting
  context.py           one market snapshot shared by CLI and AI prompts
  database.py          local SQLite store (candles, signals, snapshots, AI usage, memory)
  ai.py                provider catalogue, multi-key pools, rotation, chat client
  brain.py             local MLP experiment with chronological holdout validation
  mcp.py               bearer-protected loopback Streamable HTTP server
  mcp_tools.py         allow-listed desktop tools for MCP and Telegram
  remote.py            bounded bridge to the Tk-owning thread
  telegram.py          Bot API adapter, authorized chats, and queued notifications
  indicators.py        EMA/RSI/ATR/MACD/Bollinger/Stochastic/ADX + signal engine
  patterns.py          candlestick patterns, pivots, swing support/resistance
  backtest.py          walk-forward backtester with R-multiple statistics
  risk.py              ATR stops and position sizing
  alerts.py            alert rules, edge-triggered engine, persistence
  analytics.py         correlation matrix and opportunity ranking
  markets.py           market catalog, timeframes, price precision
  cli.py               neezy-cli command-line tools
tests/                 standard-library unittest suite
forex_signals.py       backward-compatible launcher
pyproject.toml         package/build metadata and developer tool configuration
```

## Shipped knowledge datasets (v1.4)

The package `neezy_backend/data` folder ships versioned JSON knowledge datasets that the UI, CLI, and offline assistant consult:

| File | Contents |
| --- | --- |
| `knowledge.json` | Train-then-validate study records per symbol (written by `study.py`). |
| `deriv_symbols.json` | Deriv symbol catalogue used by the market list. |
| `market_knowledge.json` | Curated reference: indicator definitions, candle patterns, risk rules, Deriv public API notes. |
| `strategy_playbook.json` | Per-strategy reference: signal, best/weak regime, key metrics, consensus rule. |
| `model_weights.json` | Per-symbol edge weights and confidence derived from the out-of-sample study records. |

`neezy_backend/datasets.py` loads them (cached, path-traversal safe); `neezy_backend/insights.py` blends them into one-line learned context. New surfaces:

- **INSIGHTS page** in the desktop UI: read-only digest of datasets, indicators, patterns, strategies, and per-symbol edge weights.
- **`neezy-cli datasets`**: list the shipped datasets and look up learned weights per symbol (`neezy-cli datasets frxEURUSD`).
- **Offline chat**: the no-provider fallback answer now appends the symbol's learned edge-weight line, caveated as not a forecast.

The weights are derived from backtests over historical candles with a charged spread; they are out-of-sample for that window only and are not forecasts.

## Fresh public-data ML and pair research (v1.5.0)

This release actually ran the package's neural model on **33,000 newly fetched
5-minute candles across 11 instruments**. The source is Deriv's no-login public
endpoint, `wss://api.derivws.com/trading/v1/options/ws/public`. Legacy v3 hosts
returned HTTP 520 in this environment; the current public endpoint worked.

- `neezy_backend/research.py` orchestrates an initial fit on the oldest 70%, then
  a final fresh fit with the existing purged chronological train/validation/test
  split. These are **22 fresh MLP fits, not warm-start fine-tuning**. Training-only
  feature normalization and validation-only early stopping remain in `brain.py`.
  No seed, horizon or strategy search used the final test segment.
- `data/ml_research.json` stores learned neural weights, initial/final evaluation
  reports, capture timestamps, settings, raw OHLC SHA256 hashes and caveats.
- `data/research_candles/*.json` retains the exact 11 raw public candle snapshots
  used for training; these are also included in the wheel.
- Six Forex pair experiments align candles by timestamp, estimate hedge beta on
  the training slice, use lagged rolling z-scores for subsequent return intervals,
  apply entry/exit/stop/time-stop rules and charge turnover plus final-flattening
  costs. This is an exposure-normalized log-return approximation, not broker fills,
  a cointegration test, an executable trading system or a claim of profitability.

### Captured holdout results

Captured at `2026-10-21T00:20:37+00:00`. The potentially active final bar is excluded.

| Market | Test examples | Balanced accuracy | Directional screening |
| --- | ---: | ---: | --- |
| `1HZ100V` | 419 | 52.38% | research-only |
| `DSI10` | 428 | 58.27% | passed screening |
| `DSI20` | 435 | 67.08% | passed screening |
| `DSI30` | 431 | 60.61% | passed screening |
| `R_10` | 409 | 39.80% | research-only |
| `R_100` | 419 | 50.53% | research-only |
| `R_50` | 427 | 49.90% | research-only |
| `frxAUDUSD` | 418 | 49.52% | research-only |
| `frxEURUSD` | 412 | 50.05% | research-only |
| `frxGBPUSD` | 410 | 47.59% | research-only |
| `frxUSDJPY` | 409 | 49.30% | research-only |

The three Drift Switching models passed the existing directional screening rule,
not a significance or profitability test. Five-bar labels overlap, reducing the
effective independent sample count. **DSI history requests returned current data,
but these symbols were absent from `active_symbols` and rejected by `ticks`**;
the UI labels them as history-only research, not live-stream availability.
Volatility and Forex models stayed unqualified and return neutral directions.
All six Forex pair simulations were negative after the default assumed costs;
the losing findings are retained rather than tuned away on the test segment.

### Desktop, CLI and backend tools

**INSIGHTS** now displays neural holdout metrics and FX-pair findings alongside the
reference datasets. It includes a dedicated research-market selector (including
DSI history), a fresh-data training action, and a saved-candle FX-pair action.
Same-market, same-timeframe bundled models can back the existing opt-in neural
advisory setting; local trained models take precedence. No trades are placed.

**SETTINGS → ML RESEARCH / PAIR RESEARCH** adds 17 validated, persisted controls:
history length, epochs, horizon, ATR deadband, minimum labels, seed, probability
threshold, API timeout, insight row limit, pair z-score lookback, minimum aligned
overlap, entry/exit/stop z thresholds, costs in bps, maximum holding bars, and
minimum training correlation. The pair reference market is a session selector.

```bash
# Offline: report actual bundled live-data evaluations (no model matrices)
neezy-cli research status

# Fetch NEW public candles, refit and checkpoint after each market
neezy-cli research train DSI10 DSI20 DSI30 R_100 frxEURUSD frxGBPUSD \
  --timeframe 5m --candles 3000 --epochs 60 --horizon 5 --seed 17 \
  --out ./research-run.json
```

Private loopback MCP adds `get_research_report`, `get_dataset_inventory`, and
`research_forex_pair` as read-only tools; the public tunnel allow-list is unchanged.
The legacy `model_weights.json` is a descriptive heuristic, **not ML weights**;
its old `confidence` field denotes sample coverage, not probability of profit.

Dataset loading now rejects traversal/symlinks and returns defensive cache copies.
Knowledge remains opt-in in ordinary chat. UI smoke tests no longer open real
network connections. `python local_ci.py` treats lint/format failures as failures
and uses the standard-library unittest runner, matching the workflow gates.

Local verification: 313 tests passed with no skips, Ruff lint/format checks passed,
real Tk enterprise construction/navigation/settings persistence passed under Xvfb,
CLI smoke checks passed, and the 1.5.0 wheel built. GitHub-hosted runs still report
failure and the bridge's job-log request returns 404; the remote failure cause is
unverified, so this is not a claim of green GitHub CI.

## Imported knowledge base and second training capture (2026-10-21)

**Imported knowledge base.** A 12-file knowledge base supplied as `DATA.zip`
(trading fundamentals, risk management, Deriv volatility / drift-switching /
other synthetic indices, correlation strategies, a 16-strategy hypothesis
library, backtesting and validation method, psychology and journaling,
machine-readable decision rules, and 55 Q&A training pairs) now ships as ten
versioned datasets in `neezy_backend/data/`, preserved under their original
keys with per-file provenance (origin, SHA256 of each zip source) and
sourced enrichment sections. Every new entry carries a `sources` field; no
facts were written from memory.

| New dataset | Contents | Entries |
| --- | --- | ---: |
| `trading_fundamentals.json` | Glossary, instruments, orders, mechanics (9 topics) | 9 topics |
| `risk_management.json` | Sizing, loss control, drawdown protocol (12 topics) | 12 topics |
| `deriv_synthetic_indices.json` | Volatility + drift-switching + other synthetics merged, with regime tables, strategies, mistakes, progression | 23 strategies, 3 regimes |
| `correlation_strategies.json` | Positive/negative correlation, divergence, entry checklist, Python snippets | 5-row strategy table |
| `general_strategies.json` | 16 hypothesis archetypes, filters, trade management, regime selector | 16 strategies |
| `backtesting_validation.json` | 12-step pipeline, 17 metrics, 14 methods, 11 overfitting traps, go-live checklist | 12-step pipeline |
| `psychology_journaling.json` | 10 behavioural biases, journal/review routines, warning signs | 10 biases |
| `decision_rules.json` | 8 machine-readable candidate rules, circuit breakers, sizing function, regime classifier | 8 rules |
| `qa_training_pairs.json` | Question/answer pairs for retrieval or fine-tuning | 55 pairs |
| `knowledge_index.json` | Load order, safety rules, honesty notes, evidence levels from the zip index | 11-entry load order |

Enrichment is sourced, not invented: pair-research context cites cointegration
failure and walk-forward evidence ([PEP-KO case study](https://arxiv.org/abs/2609.35359),
[seven-pair walk-forward gate](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7204658),
[pair pre-selection effects](https://link.springer.com/article/10.1007/s10260-023-00702-4));
validation context cites walk-forward and overfitting-correction literature
([walk-forward framework](https://arxiv.org/html/2512.12924v1),
[robustness grading / PBO](https://arxiv.org/abs/2608.23808),
[trials-adjusted gating](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7361818));
sizing context cites fixed-fractional and Kelly sources
([position sizing](https://www.activtrades.com/en/news/what-is-position-sizing-in-trading),
[Kelly practice](https://blog.traderspost.io/article/kelly-criterion-position-sizing-automated-trading));
psychology context cites journaling-before-pattern and loss-aversion research
([trading psychology](https://www.tradesviz.com/trading-psychology/),
[journal behaviour metrics](https://acy.com/en/market-news/education/trading-journal-behavior-metrics-j-o-20251210-110438/));
indicator context cites condition-dependent RSI/MACD effectiveness studies
([RSI vs MACD effectiveness](https://www.researchgate.net/publication/392317792_Analysis_of_the_Effectiveness_of_RSI_and_MACD_Indicators_in_Addressing_Stock_Price_Volatility),
[key indicators study](https://www.sciencedirect.com/science/article/pii/S2666827025000143));
Deriv synthetic context cites Deriv's generator description plus this
environment's endpoint verification
([synthetic indices](https://deriv.com/markets/derived-indices/synthetic-indices)).

**Second training capture.** The existing pipeline re-fetched **33,000 fresh
5-minute candles** (11 markets x 3,000) and refit all 22 staged MLPs. Captured
at `2026-10-21T06:17:31+00:00`:

| Market | Test examples | Balanced accuracy | Screening |
| --- | ---: | ---: | --- |
| DSI10 | 427 | 60.78% | passed screening |
| DSI20 | 439 | 66.85% | passed screening |
| DSI30 | 429 | 64.95% | passed screening |
| 1HZ100V | 420 | 51.66% | research-only |
| R_10 | 407 | 49.35% | research-only |
| R_50 | 423 | 50.10% | research-only |
| R_100 | 421 | 49.06% | research-only |
| frxAUDUSD | 421 | 52.35% | research-only |
| frxEURUSD | 411 | 51.88% | research-only |
| frxGBPUSD | 409 | 50.17% | research-only |
| frxUSDJPY | 409 | 50.00% | research-only |

All six Forex pair experiments were again net negative after assumed costs
(net log returns -0.0072 to -0.0105); the losing findings are retained. The
three Drift Switching models again passed the directional screening rule —
still not a profitability or significance test. DSI access remains
history-only: current candles were served by `ticks_history`, but the symbols
were absent from `active_symbols` and rejected by `ticks` requests. Raw
candle snapshots, hashes and provenance were re-verified against the new
capture before shipping.

## Development checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q neezy_app neezy_backend forex_signals.py
ruff check neezy_app neezy_backend tests forex_signals.py
ruff format --check neezy_app neezy_backend tests forex_signals.py
```

The app depends on Deriv's public WebSocket endpoint and an internet connection for live candles. The service may be unavailable or rate-limited; the UI surfaces connection and API errors and retries transient disconnects. The market monitor is informational only; do not use its signals as a substitute for independent analysis or professional advice.
