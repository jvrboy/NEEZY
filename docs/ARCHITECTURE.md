# NEEZY Architecture Documentation — LEGACY SNAPSHOT

> ⚠️ **This file is superseded by root `ARCHITECTURE.md`**, which is the authoritative reference verified for the cloud/light-executor run.
> This legacy snapshot (pre-split monolith diagram) is kept for history only.
> For current architecture, read `ARCHITECTURE.md` at the repo root.

## Overview

**NEEZY** is a local-first Python workspace. Its application state and SQLite database live on the user's machine; it connects to Deriv's public candle feed and can optionally send AI prompts to a configured provider or alerts and messages through Telegram. The desktop GUI is optional for the headless backend/CLI. MCP defaults to a loopback-only endpoint; an explicitly enabled Cloudflare quick tunnel starts a second, separately tokened, read-only market-tool endpoint. Market analysis and strategy consensus run locally.

---

## High-Level System Architecture

```
                                 ┌─────────────────────────────┐
                                 │     Deriv WebSocket API     │
                                 └──────────────┬──────────────┘
                                                │ (public candles / ticks)
                                                ▼
                                 ┌─────────────────────────────┐
                                 │     neezy_backend.stream    │
                                 │    (DerivStreamClient)      │
                                 └──────────────┬──────────────┘
                                                │
                                                ▼
                                 ┌─────────────────────────────┐
                                 │    neezy_backend.events     │
                                 │         (EventBus)          │
                                 └───────┬──────────────┬──────┘
                                         │              │
                                         ▼              ▼
 ┌───────────────────────────┐   ┌───────────────┐   ┌───────────────────────────┐
 │ neezy_backend.indicators  │   │  AlertEngine  │   │     neezy_app.ui (GUI)    │
 │ (Supertrend, Divergence,  │   └───────────────┘   │ (Workspace, Charts, Tools)│
 │  Strategies, Patterns)    │                       └─────────────┬─────────────┘
 └─────────────┬─────────────┘                                     │
               │                                                   ▼
               ▼                                     ┌───────────────────────────┐
 ┌───────────────────────────┐                       │    neezy_backend.agent    │
 │ Local SQLite Database     │                       │    (Planner / Executor)   │
 │ (neezy.sqlite3 WAL mode)  │                       └─────────────┬─────────────┘
 └─────────────┬─────────────┘                                     │
                                                                   ▼
                                                     ┌───────────────────────────┐
                                                     │    neezy_backend.tools    │
                                                     │      (ToolRegistry)       │
                                                     └───────────────────────────┘
```

---

## Backend Modules Overview

- **`neezy_backend.stream`**: Reconnecting background WebSocket client with multi-endpoint failover and backoff.
- **`neezy_backend.database`**: SQLite WAL mode engine storing candles, signal history, snapshots, and memory items; FTS5 is used when the SQLite build includes it, with a portable `LIKE` fallback otherwise.
- **`neezy_backend.tools`**: Typed tool registry with schema validation, permission tiers (READ_ONLY, WRITE, DESTRUCTIVE), and dry-run execution.
- **`neezy_backend.agent`**: Minimal planner/executor; its current plan is a fixed `read_market` step, not a general autonomous planner.
- **`neezy_backend.remote`**: Bounded bridge that dispatches MCP/Telegram application commands on the Tk-owning thread.
- **`neezy_backend.mcp` / `mcp_tools`**: Bearer-protected Streamable HTTP server, explicit local tool allow-list, and narrower public read-only allow-list.
- **`neezy_backend.tunnel`**: Optional `cloudflared` quick-tunnel process manager; no shell, downloads, firewall changes, or implicit tunnel startup.
- **`neezy_backend.local_llm`**: Path-only GGUF/Transformers model registry plus optional CPU-only inference; third-party runtimes load lazily.
- **`neezy_backend.backtest`**: Parameter-grid decision cache keeps only signal/score/ATR and fingerprints the source candles, avoiding repeated full-window analysis output and rejecting mismatched data.
- **`neezy_backend.telegram`**: Token store and Bot API service with numeric chat allow-listing, command polling, and queued notifications.
- **`neezy_backend.brain`**: Optional local MLP experiment with chronological holdout validation and advisory predictions.
- **`neezy_backend.ai`**: Multi-key BYOK AI client with automated rotation and cooldown management for Gemini, Grok, OpenRouter, and Ollama Cloud.
- **`neezy_backend.storage`**: Atomic JSON persistence, path traversal sandboxing (`sanitize_path`), and zip backup/restore utilities.

The base project targets Python 3.10+; the existing CI matrix covers Python 3.10–3.12. The CLI/backend do not require Tkinter, so they can run on mobile Python environments when their standard library and `websocket-client` are available. Tk GUI, local inference runtimes, and the external tunnel binary remain platform-dependent.
