# NEEZY Agent Tools, Memory, MCP & Local Learning

## Tool architecture

`neezy_backend.tools.ToolRegistry` stores typed tool definitions, validates arguments, and assigns `READ_ONLY`, `WRITE`, or `DESTRUCTIVE` permissions. The desktop app builds a separate, allow-listed registry for its local MCP and Telegram integrations. Remote calls that need application state are marshalled through `AppCommandBridge` and executed by Tk's owning thread; the bridge is bounded and rejects work during shutdown. Database-only operations use the thread-safe local SQLite wrapper.

The generic `AgentPlanner` is not currently an autonomous, general-purpose planner: `create_plan()` returns one fixed `read_market` step for `frxEURUSD` on `15m`. Do not describe it as decomposing arbitrary goals or selecting tools dynamically.

## MCP tools

The default Streamable HTTP MCP server is exposed at `http://127.0.0.1:<port>/mcp`. It requires a locally stored bearer token, checks local Host/Origin values, and binds only to loopback. Its write tools are hidden/rejected unless the user enables **Allow write tools on the local MCP server** in Settings. It exposes no shell, arbitrary-file, broker, or trade-execution tools.

Local read capabilities include status, market listing/analysis/scans, recent signal transitions, alert listing, safe settings reads, local memory search, outcome reports, and neural-model status/prediction. Local gated writes include safe workspace setting updates, market/timeframe selection, alert creation/deletion, note saving, and local research-model training. Tool metadata and argument schemas are defined in `neezy_backend/mcp_tools.py`.

**Optional public tunnel:** The user may explicitly start a Cloudflare quick tunnel from Settings. It exposes a separate local listener with its own bearer token and a smaller, explicit read-only registry: status, market listing/analysis/scans, outcome reports, and advisory-model status/prediction. It does not expose settings, memory, recent signal history, alerts, chat, training, or write tools, regardless of the local write toggle. The URL is ephemeral; a client must support MCP Streamable HTTP with a custom bearer token. Any agent that obtains the token can read this public tool set, and Cloudflare proxies the request. Do not imply all hosted agents can connect.

## Local memory

Notes are stored in `neezy.sqlite3` (`memory_items`) and indexed with SQLite FTS5 (`memory_fts`) when the SQLite build includes FTS5; Android/other builds without it use a parameterized text-search fallback. The app and local integrations can search and add notes. The **Include relevant local memory in provider prompts** option defaults to off; only when enabled are matching note excerpts added to AI-provider requests. The public MCP registry does not expose memory. The database file itself is not uploaded.

## Local generative models

`neezy_backend.local_llm` indexes user-selected GGUF files and Hugging Face-style Transformers folders without copying weights or contacting a model hub. GGUF runtime uses llama.cpp with mmap, CPU-only layers, bounded context, batch, and thread settings. Transformers supports SafeTensors and standard PyTorch `.bin` checkpoints with `local_files_only` and `trust_remote_code=False`; restricted `weights_only` deserialization is requested for `.bin`. Optional disk offload uses Accelerate and temporary files that are cleaned up after inference. Neither mmap nor disk offload guarantees one model layer at a time in RAM; KV cache/runtime overhead remains. `neezy-cli local-model` supports headless import/list/remove/chat and is suitable for mobile Python workflows where optional native wheels exist.

## Neural research model

`neezy_backend.brain` trains a small local MLP using stored candle history and chronological train/validation/test partitions. Reports include untouched holdout metrics and a validation status. The model is optional, shown as advisory context, and does not alter the deterministic signal score or execute trades. Low or inconclusive held-out performance remains research-only; historical accuracy does not guarantee future results.

Use **SETTINGS → ENGINE → Train local brain on saved candles** in the UI, or the headless commands:

```bash
neezy-cli brain train EURUSD -t 15m
neezy-cli brain status EURUSD -t 15m
neezy-cli brain predict EURUSD -t 15m
```

The CLI trains from candles already saved to the local database. `neezy-cli db save EURUSD -t 15m -n 5000` can fetch and store history first. The UI requires at least 300 saved candles before starting a training attempt.

## Telegram commands

The Telegram bot uses the same allow-listed tool registry and UI-thread bridge. Polling and message delivery run in background workers; only configured numeric chat IDs can invoke commands. Read commands work when the bot is enabled. Mutating commands require the separate **Allow authorized chats to change settings, alerts, and memory** setting. The BotFather token is stored separately in `telegram-bot.json`; messages and alerts are delivered through Telegram's external Bot API.

## Verification

This checkout has no `evals/` directory or `evals/run_evals.py`/`tasks.json` harness. Run the repository's standard-library tests instead:

```bash
python -m unittest discover -s tests -v
ruff check neezy_app neezy_backend tests
```
