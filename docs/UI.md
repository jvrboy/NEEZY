# NEEZY UI

The desktop UI is the base `neezy_app.ui.App` plus the enterprise layer in
`neezy_app/enterprise.py` (`EnterpriseApp`, started by `neezy --desktop`).

## Design system
- Palette tokens and presets (Liquid dark, Midnight blue, High contrast) live in
  `App._apply_theme`; the enterprise layer re-themes ttk widgets on every change.
- Fonts resolve at start-up: Segoe UI / SF Pro / Inter / DejaVu Sans for UI and
  Cascadia Mono / Consolas / SF Mono / Menlo / DejaVu Sans Mono for data.
- Sidebar is the single navigation surface (the duplicate top tab strip is hidden).

## Interaction
| Shortcut | Action |
|---|---|
| Ctrl+K | Command palette (navigate, timeframe, markets, scan, themes) |
| Ctrl+1..8 | Jump to a page |
| F5 | Re-subscribe all market streams |
| Double-click a row | Open that market's chart |

## Feedback
- Toast notifications for triggered alert rules and signal changes.
- Status bar: connection/status text, selected market, analysed markets, last tick, UTC clock.

## Settings and optional integrations

The Settings notebook has **WORKSPACE**, **ENGINE**, **LOCAL DATA**, **AI PROVIDERS**, **LOCAL MODELS**, **MCP SERVER**, and **TELEGRAM** tabs. Settings save immediately and persist in the local data directory.

- **LOCAL MODELS** registers GGUF files or complete Transformers folders by reference, selects a local CHAT model, and exposes bounded context, output, threads, batch, CPU-memory, and offload settings. Optional inference libraries are detected without importing them at startup; model files stay at their original paths.
- **MCP SERVER** shows the local `http://127.0.0.1:<port>/mcp` URL, a masked local bearer token, copy/regenerate controls, and server state. Local write tools require a separate checkbox. An optional Cloudflare quick-tunnel toggle starts a separate ephemeral public URL and listener, with its own token and read-only market tool allow-list. Tunnel process/path and state are shown in Settings; stop/rotate controls are available.
- **TELEGRAM** stores the BotFather token separately, provides a token test, and accepts comma-separated numeric chat IDs. Notification delivery and authorized-chat write commands have separate controls.
- **ENGINE** can train the optional local neural experiment from saved candles. The setting for adding its advisory output to context is separate; it does not affect the core score.
- **AI PROVIDERS** includes an opt-in checkbox for adding matching local-memory notes to provider prompts; it defaults off.

MCP and Telegram network workers never directly manipulate Tk widgets. Remote app commands are marshalled through `AppCommandBridge` and run in the UI event loop. The local-storage helper text calls out that enabled AI and Telegram features send selected data externally. Pydroid/Android should use the headless CLI; Tkinter desktop widgets are not expected to work there. The backend targets Python 3.10+ (the existing CI matrix covers 3.10–3.12), while optional native inference/tunnel binaries remain OS- and architecture-dependent.

## Terminal tabbed workspace

Installed `neezy` with no arguments and `neezy-cli menu` open the headless
counterpart to the desktop workspace; `neezy --desktop` remains the explicit Tk
route. The terminal opens with a large ASCII NEEZY masthead, a responsive tab
bar, and CHAT active. The
seven tabs are **CHAT, SYMBOLS, CHART, SIGNALS, HISTORY, BOT, SETTINGS**. Tool
commands stay hidden until `/` opens the palette. The interface uses ordinary
line input and bordered ASCII panels: there is no curses, mouse handling,
cursor addressing, or screen clearing.

| Tab | Content and explicit refresh action |
|---|---|
| CHAT | Natural-language market requests and configured-provider AI chat |
| SYMBOLS | Search/select real catalog instruments; plain text searches this tab |
| CHART | `:refresh` fetches and renders real closed candles as an ASCII OHLC chart |
| SIGNALS | `:refresh` scans the selected symbol; `:scan all` scans the watchlist |
| HISTORY | `:refresh` loads the configured number of local signal-transition records |
| BOT | `:refresh` reads the lightweight executor's loopback status; no controls |
| SETTINGS | Six sub-tabs for general, appearance, data, AI, performance, and immutable safety information |

| Input | Action |
|---|---|
| `:chat` / `:symbols` / `:chart` / `:signals` / `:history` / `:bot` / `:settings` | Switch directly to a tab |
| `:next` / `:prev` | Cycle through tabs |
| `:tab symbols` | Alternative direct tab syntax |
| `:symbol EURUSD` and `:timeframe 15m` | Change shared chart/signal context |
| `:find volatility` | Search the symbol catalog |
| `:color on` / `:color off` | Re-evaluate safe colour support or force plain output |
| `:settings next` / `:settings prev` / `:settings ai` | Navigate SETTINGS sub-tabs |
| `:set width 44` / `:set hints off` | Apply responsive appearance preferences |
| `:set chart-count 240` / `:set chart-height 18` | Configure real chart refreshes |
| `:set scan-count 500` / `:set history-limit 20` | Configure scan/history refreshes |
| `:set provider gemini` / `:set temperature 0.7` / `:set max-tokens 900` | Set session AI defaults; explicit chat provider wins |
| `:set bot-timeout 1.5` | Set the bounded loopback status timeout (0.1–5 seconds) |
| `:reset` | Reset all session preferences |
| `:refresh` | Run the active tab's read-only refresh, if it has one |
| Plain language in CHAT | Route a recognized request to existing CLI argv; otherwise ask the configured AI provider |
| `/` and `/text` | Open or filter the hidden grouped command palette |
| Palette key + Enter | Run the selected existing CLI action |
| `/close` | Hide the palette and return to the active tab |
| `?` or `help` | Show natural-language and tab-navigation examples |
| `q` / `quit` / `exit` | Close the session |

Tab switches and settings changes do not perform network requests. Chart and
signal refreshes share the selected symbol/timeframe. History reads local data.
BOT status accepts no remote URL, reads only the validated loopback executor
address with a short timeout and bounded response, and offers no start, stop,
model-promotion, or order action. The tools also work outside the menu:

```bash
neezy-cli chart EURUSD -t 15m --width 72 --height 14
neezy-cli bot status
neezy-cli kernels status
neezy-cli kernels benchmark --iterations 250 --candles 512
```

SETTINGS changes last for the current terminal session. `width` accepts `auto`
or 28–84 columns; chart count is 20–2,000, chart height 6–30, history limit
1–100, scan count `default` or 60–5,000, AI temperature `default` or 0–2, and
AI tokens `default` or 32–4,000. Provider choices are `default`, `openrouter`,
`gemini`, `grok`, and `ollama`. AI keys remain in the existing protected key
store and are never rendered in SETTINGS. PERFORMANCE reports the fused
EMA/MACD/ATR backend and bounded symbol-cache statistics. Its refresh is the
read-only kernel status command. The benchmark checks exact numerical outputs
against the original algorithms before reporting local timings; it makes no
network calls and its ratios are not cross-device guarantees.

Colour follows the TTY/`NO_COLOR`/`FORCE_COLOR` rules, and `--plain` always
disables it. If Windows VT setup fails, colour is disabled automatically. On
wide terminals, status details sit beside the NEEZY artwork and palette rows
use aligned command/description columns. Smaller screens reflow the masthead,
tabs, palette, messages, activity labels, and piped prompts down to 28 columns.
No curses dependency or non-ASCII border glyph is required.

Natural-language buy/sell/open/close/order intent is deliberately not an order
path. The UI directs the user to the explicit palette's dry-run or live action.
The existing dry-run behavior, typed `SEND` live confirmation, and Agent/MCP
no-live-order rules are unchanged. Physical-device coverage is not implied by
the scripted Windows/Linux/Termux/Android/Codespaces compatibility tests.

## Fixes shipped with the layer
- Sidebar highlight now stays in sync with the active page; header title updates per page.
- Watchlist selection now selects the market everywhere (detail pane, signals table).
- Chart empty-state is centred; transient Tk draw errors no longer propagate.
- Combobox pop-downs, scrollbars and table headers follow the active theme.
- "Temperature x10" label corrected.
