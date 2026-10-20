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

## Fixes shipped with the layer
- Sidebar highlight now stays in sync with the active page; header title updates per page.
- Watchlist selection now selects the market everywhere (detail pane, signals table).
- Chart empty-state is centred; transient Tk draw errors no longer propagate.
- Combobox pop-downs, scrollbars and table headers follow the active theme.
- "Temperature x10" label corrected.
