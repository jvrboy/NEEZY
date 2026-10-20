# AUDIT.md

# NEEZY Repository Audit Report

**Date**: Autonomous Upgrade Baseline
**Scope**: Entire codebase (`neezy_backend`, `neezy_app`, `tests`, root scripts & packaging)

---

## 1. Executive Summary & App Overview

**NEEZY** is a native Python desktop workspace designed for financial market monitoring, technical analysis, automated rule alerting, backtesting, and AI-assisted market analysis.

Key properties:
- **Local Desktop App**: Runs 100% locally on the user's machine using Python and Tkinter.
- **Data Source**: Reconnecting background WebSocket connection to public market candles (Deriv API).
- **Storage**: Local SQLite database (`neezy.sqlite3` in WAL mode), local JSON/JSONL configuration files.
- **AI Integrations**: Bring-your-own-key multi-provider pool (Gemini, Grok, OpenRouter, Ollama Cloud) with automated failover and cooldowns.
- **Target User**: Quantitative traders, market researchers, and technical analysts who want zero-cloud, privacy-first local tooling.

---

## 2. Architecture & Data Flow Overview

```
               ┌──────────────────────────────────────────────┐
               │              Deriv WebSocket API             │
               └──────────────────────┬───────────────────────┘
                                      │ (candles / ticks)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │     neezy_backend.stream / DerivStream       │
               └──────────────────────┬───────────────────────┘
                                      │
                                      ▼
               ┌──────────────────────────────────────────────┐
               │    Engine Analysis (Indicators, Supertrend,   │
               │    Divergence, Strategies, Candlesticks)     │
               └──────────────┬────────────────┬──────────────┘
                              │                │
                              ▼                ▼
     ┌─────────────────────────────┐   ┌─────────────────────────────┐
     │ SQLite DB (neezy.sqlite3)   │   │  neezy_app.ui (Tkinter UI)  │
     │ - candles, signals, AI logs │   │  - App Shell, Charts, Tools │
     └─────────────────────────────┘   └──────────────┬──────────────┘
                                                      │
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │    neezy_backend.ai / Chat  │
                                       │    (Gemini/Grok/OR/Ollama)  │
                                       └─────────────────────────────┘
```

---

## 3. Findings Ranked by Priority

### Critical / High Priority

1. **Test Environment Dependency Discrepancy (FIXED IN BOOTSTRAP)**:
   - `pytest` invoked directly was missing `websocket-client` because tests ran in a separate virtual environment than the installed pip package.
   - *Status*: Resolved by ensuring `websocket-client` and editable package install in test environment.

2. **Lack of Structured Agent Tool Schema & Sandboxing**:
   - Agent interaction in `ai.py` was limited to plain text generation with context injection (`context.py`). No formal agent tool execution loop, tool registry, dry-run capabilities, or permission tiers existed.
   - Potential local risk if tools execute arbitrary shell or unvalidated path access.

3. **UI Monolith & Thread Safety**:
   - `neezy_app/ui.py` is a single 2,326-line file handling layout, rendering, event handling, network dispatching, and chart drawing.
   - Heavy operations like backtesting or multi-market scanning risk blocking the Tkinter event loop if not strictly queued in worker threads.

### Medium Priority

4. **Long-Term Memory & Evals Absence**:
   - Chat history was stored as simple conversation turns or database logs without vector/semantic retrieval, BM25 context search, or short-term summarization.
   - No benchmark evaluation suite (`/evals`) or local fine-tuning/few-shot data curation pipeline existed.

5. **UI Visual Cohesion & Design System**:
   - Standard Tkinter widgets and basic canvas drawing lack a modern enterprise feel (e.g. command palette, toast notification system, dark/light theme tokens, collapsible sidebar navigation).

### Low Priority / Quick Wins

6. **Documentation & CLI Polish**:
   - Missing explicit architectural breakdown docs (`docs/ARCHITECTURE.md`, `docs/AGENT.md`, `docs/LOCAL_SECURITY.md`, `docs/UI.md`).
   - Need unified local CI test script and Makefile / task runner for one-command developer verification.

---

## 4. Quick Wins Checklist

- [x] Create git backup tag `pre-upgrade-backup`.
- [x] Verify full test suite execution (117 tests passing).
- [ ] Implement `scripts/local_ci.sh` for instant local linting, formatting, and test validation.
- [ ] Create sandboxed path validation helper in `neezy_backend/storage.py`.
