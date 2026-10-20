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
