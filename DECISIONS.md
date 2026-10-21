# DECISIONS.md

# NEEZY Architecture & Engineering Decisions Log

This document records architectural, design, and operational decisions made during the autonomous upgrade of NEEZY.

---

## Decision 1: Single-User Local Desktop Paradigm (Non-Negotiable)
- **Context**: The prompt constraints specify a local desktop app running on the user's machine without login, multi-tenancy, hosted databases, telemetry, or cloud dependencies.
- **Decision**: All new features (memory, tool execution, backtesting, AI rotation, database migrations, logs) are strictly file/SQLite based within the local `NEEZY_HOME` directory. Network interactions are isolated to Deriv WebSocket public data and user-configured AI provider endpoints.

## Decision 2: Tkinter / CustomTkinter Design System & Component Shell
- **Context**: Tkinter is the standard Python GUI library and already used across `neezy_app/ui.py`.
- **Decision**: Upgrade the existing Tkinter UI with a custom modern design token system (colors, typography, rounded frames, collapsible sidebar, Ctrl+K command palette modal, toast notifications) rather than introducing external heavy GUI frameworks that break platform portability or headless environments.

## Decision 3: Local Hybrid Vector/BM25 Memory Engine in SQLite
- **Context**: Long-term memory is required for the agent without adding external vector DB cloud services (e.g., Pinecone/Chroma server).
- **Decision**: Implement a pure Python / SQLite hybrid retriever using SQLite standard FTS5 (for BM25 text search) combined with lightweight TF-IDF / cosine similarity vector representations in Python. This guarantees 100% offline, zero-dependency long-term memory retrieval.

## Decision 4: Safe Local Subprocess Sandboxing & Path Guardrails
- **Context**: Agent backend tools need file and local code execution capabilities without posing local security risks (path traversal, arbitrary code execution risks).
- **Decision**: Implement strict path sandboxing relative to `NEEZY_HOME` or user workspace directories, enforce read-only/write permission tiers, mandate automatic pre-action snapshots/backups for destructive tool invocations, and run local Python code tools in isolated subprocesses with timeout and resource controls.

## Decision 5: Versioned Prompt Registry & /evals Evaluation Harness
- **Context**: Prompt strings were previously scattered or simple. System needs structured agent loops, tool schemas, and local benchmark evaluations.
- **Decision**: Create a dedicated prompt management package (`neezy_backend/prompts/`) storing versioned system prompts and dynamic templates. Build a local evaluation harness in `evals/` that runs benchmark tasks against local rules or LLM providers and outputs standardized JSON/Markdown report cards.

## Decision 6: Live MT5 Orders Only Behind Explicit Confirmation (2026-10 update)
- **Context**: The earlier README and this log said NEEZY never places trades. The MT5 bridge could already send orders, and a mock path returned `success: true` when no terminal was connected.
- **Decision**: Live orders stay available, but only through `neezy-cli mt5 order`, which refuses unless `--confirm` is given and MT5 is really connected. `--dry-run` validates without contacting MT5. The terminal menu requires typing `SEND`. Agent and MCP tools can read MT5 or preview an order and cannot send one. Tools marked WRITE or DESTRUCTIVE in the registry raise `PermissionError` unless `confirm=True`. Read commands (account, quote, candles) refuse simulated or disconnected data instead of returning made-up values.
- **Amendment (round 2)**: The desktop app's ORDERS page may also send a live market order. It has no typed-`SEND` step; instead every order goes through a confirmation dialog that defaults to No and lists the symbol, side, volume, stop, target and account. It also refuses unless the saved MT5 bridge toggle is on and the terminal is connected and live. The CLI does not check the toggle; that gap is accepted and left alone. The shared rules live in `neezy_backend/mt5_orders.py`, so the CLI and the desktop cannot drift apart. The ORDERS page supports market orders only. Agent and MCP tools are unchanged: they still cannot send an order.
- **Scope**: The bridge connects only to the MetaTrader 5 terminal on the user's own PC, which the user has already logged in to their broker. This stays inside Decision 1: no NEEZY-hosted service and no telemetry.
- **Not done**: No third-party MCP server is installed or run. `neezy_backend/mcp_catalog.py` only describes six community servers, with their risks and read-only profiles where they exist.
- **Known gap**: Saved MT5 passwords are plain text in `settings.json` under `NEEZY_HOME`, as in earlier versions. Moving them to the OS keychain is future work.
