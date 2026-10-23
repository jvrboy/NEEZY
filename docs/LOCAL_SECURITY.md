# NEEZY Local Security & Privacy

NEEZY keeps its configuration and primary database on the user's computer. It has no account service, hosted database, or telemetry. Some explicitly enabled features do communicate with external services; see **Network and data flow** below.

## Network and data flow

- The market feed uses Deriv's public WebSocket API.
- The optional lightweight executor downloads bounded JSON manifests/models from the configured Hugging Face repository. It does not download pickle or custom model code. An optional HF token comes from the service environment and is never included in status output.
- When explicitly deployed, the executor status API is loopback-only and read-only. Cloudflare Tunnel + Access exposes sanitized status to the Cloudflare Worker and Vercel server route; the Worker can archive those status/equity snapshots in R2. Browser code never receives Access service-token secrets, and none of these paths can place or close trades. See `CLOUD_OPERATIONS.md`.
- AI requests go to the provider selected in **SETTINGS → AI PROVIDERS** when AI answers are enabled. The database file is not uploaded. Market context is sent with an AI request, and relevant stored notes are added only when **Include relevant local memory in provider prompts** is explicitly enabled.
- When enabled, the Telegram integration polls and sends messages through Telegram's Bot API. Authorized-chat commands and alert notifications are therefore processed by Telegram as messages. The bot token is stored separately from normal settings.
- The default MCP server is authenticated and bound only to `127.0.0.1`; it is intended for an MCP client on the same computer.
- If the user explicitly enables the Cloudflare quick tunnel, NEEZY starts a separate loopback-only MCP listener and runs the separately installed `cloudflared` executable. Requests pass through Cloudflare and reach a distinct public token and a market-only, read-only registry. Public tools expose current app status, market catalogue/analysis/scan, outcome reports, and the optional advisory-model status/prediction. Private settings, signal history, local notes, chat, alerts, model training, and writes are not in the public registry. The tunnel is not started by default and is stopped when disabled or when the local MCP server stops.
- Optional generative model inference is local-only. Model files are registered by path, not copied/downloaded. Transformers uses `local_files_only=True` and `trust_remote_code=False`; PyTorch `.bin` loading requests `weights_only=True`.

The optional integrations are not required for the core market feed or deterministic signal engine. Disable them in Settings to stop their network activity. Exporting a database or copying credential files is a user action.

## Unattended executor safety

The NSSM executor starts with `execution_enabled=false` and accepts orders only on a real connected MT5 **demo** account. It persists daily risk state and last evaluated candle so restarts cannot reset limits or duplicate a signal. Candidate activation requires SHA-256 integrity plus exact-hash held-out backtest and paper evidence; rejected downloads preserve the active model. The optional paper-candidate mode forbids execution, skips production activation, and records only virtual demo outcomes with no broker order methods. Bounded recent equity is restored from an atomic local status file. The status service has no mutation routes. Cloud training candidates never update `latest/` automatically, and HF/Kaggle/GitHub/Cloudflare/Vercel credentials are held only in their respective secret stores. The complete threat and operations boundary is in `CLOUD_OPERATIONS.md`.

## MCP server

- Binds to loopback only; non-loopback bind addresses are rejected. Host and browser Origin checks also reject non-local requests.
- Every local MCP request requires a bearer token generated locally and stored in `mcp-token.json` with owner-only POSIX permissions (`0600` when supported). Regenerate it in **SETTINGS → MCP SERVER** to revoke local clients. Treat it like a password.
- When the public tunnel is enabled, it uses a distinct token in `mcp-public-token.json`, also owner-only where supported. Rotating that token stops the existing public endpoint and starts a new one if the tunnel remains enabled. The local MCP token is never reused.
- Request bodies are bounded and the HTTP server caps concurrent request workers. The public listener also rate-limits authenticated requests to 60 per minute (shared by the public endpoint). The local MCP registry is allow-listed; it has no shell, arbitrary-file, arbitrary-code, broker or trade-execution tools.
- Local write tools are hidden and denied by default. Enabling them permits only documented local workspace, alert, memory, selection and research-model actions. Destructive tools are not exposed. The public registry is independently allow-listed and read-only regardless of the local write switch.
- A public quick-tunnel URL is temporary and not an identity boundary. Anyone who obtains the public token can call the exposed market tools. Share it only with a trusted agent that supports MCP Streamable HTTP plus a custom bearer token. Disable the toggle or rotate the token to revoke access. Do not expose the local MCP port or bind either service to a public interface.
- Cloudflare terminates/proxies the tunnel traffic, so Cloudflare can observe request content and metadata. Browser clients that send a non-loopback `Origin` are rejected; the tunnel is for server-to-server MCP use. A local MCP client can also forward tool inputs/results to its own model provider. Review both external services' data policies.

## Telegram bot

- The BotFather token is stored in `telegram-bot.json` with owner-only POSIX permissions (`0600` when supported), separate from `settings.json`. Removing the token stops the bot and deletes the local token file.
- Incoming commands are ignored unless the numeric chat ID appears in the configured allow-list (up to 20 IDs). Read commands are non-mutating; settings, alert, and memory writes require a separate Settings checkbox and are off by default.
- Outbound notifications and command replies are sent to Telegram. Only add chats you control and avoid sending sensitive notes through the bot. API errors are sanitized so request URLs containing the token are not logged or returned.

## Local storage and credentials

Settings, SQLite state, AI provider keys, and integration tokens are held under the per-user NEEZY data directory (overridden by `NEEZY_HOME`). AI keys are stored in plain text because the selected provider must receive them; protect `ai-keys.json` as a credential file. POSIX credential files use mode `0600` when supported; Windows relies on the user's application-data ACL.

Stored notes are local by default. They are included in AI-provider prompts only with the explicit memory-context option enabled. Local brain models are advisory research artifacts; they do not modify the deterministic signal score or place trades. Generative model weights are not copied or downloaded by NEEZY; the local registry stores their filesystem paths. GGUF/Transformers inference is optional and CPU-oriented. Import only trusted model files: `trust_remote_code` is disabled, and PyTorch `.bin` files require restricted `weights_only` loading. `llama.cpp` mmap and Transformers disk offload do not guarantee that only one model layer occupies RAM.

## Other security controls

### Path traversal protection

The `sanitize_path` helper in `neezy_backend/storage.py` resolves and validates user-supplied file paths against the application data directory. Relative traversal such as `../` is rejected.

### Tool permissions

Tools in `neezy_backend/tools.py` carry explicit `READ_ONLY`, `WRITE`, or `DESTRUCTIVE` permissions. MCP does not expose destructive tools, and its write permissions are independently gated by Settings.
