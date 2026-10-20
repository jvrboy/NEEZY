# NEEZY Architecture Documentation

## Overview

**NEEZY** is a native Python desktop workspace running 100% locally on the user's machine. It connects via WebSockets to Deriv's public market candle data feeds, executes real-time quantitative indicator analysis and strategy consensus, stores structured state in a local SQLite database, and provides AI market copilot capabilities with multi-key rotation and zero cloud lock-in.

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
- **`neezy_backend.database`**: SQLite WAL mode engine storing candles, signal history, snapshots, and FTS5 memory items.
- **`neezy_backend.tools`**: Typed tool registry with schema validation, permission tiers (READ_ONLY, WRITE, DESTRUCTIVE), and dry-run execution.
- **`neezy_backend.agent`**: Autonomous Planner/Executor agent loop managing multi-step task execution.
- **`neezy_backend.ai`**: Multi-key BYOK AI client with automated rotation and cooldown management for Gemini, Grok, OpenRouter, and Ollama Cloud.
- **`neezy_backend.storage`**: Atomic JSON persistence, path traversal sandboxing (`sanitize_path`), and zip backup/restore utilities.
