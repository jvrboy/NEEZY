# NEEZY UI

The desktop UI is the base `neezy_app.ui.App` plus the enterprise layer in
`neezy_app/enterprise.py` (`EnterpriseApp`, started by `neezy` / the launcher).

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

## Fixes shipped with the layer
- Sidebar highlight now stays in sync with the active page; header title updates per page.
- Watchlist selection now selects the market everywhere (detail pane, signals table).
- Chart empty-state is centred; transient Tk draw errors no longer propagate.
- Combobox pop-downs, scrollbars and table headers follow the active theme.
- "Temperature x10" label corrected.
