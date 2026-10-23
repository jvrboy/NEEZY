# Cloud training + lightweight PC executor

This deployment keeps the **Windows 10 PC always on but deliberately light**. It
connects to MT5, downloads validated JSON weights, performs compact inference,
enforces local risk limits, sends demo orders, and serves a read-only status API.
Training, backtesting, data collection, alerts, and the dashboard run elsewhere.

> **Safety default:** `execution_enabled` is `false`. The unattended service is
> **demo-only by implementation**, not merely by convention. Observe for weeks,
> paper-validate every exact model hash, and use broker-side stop losses. Existing
> manual MT5 CLI/desktop order paths are separate and retain their own confirmation
> gates. Historical and paper performance do not guarantee future results.

## 1. Responsibilities and realistic availability

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Windows 10 PC | MT5/broker connection, latest-model download, compact inference, persistent risk state, demo order placement/monitoring, loopback status API | Training, backtests, Transformers/Torch, public bind, remote order endpoints |
| Colab / Kaggle | Public-data pulls, training, held-out trade backtests, candidate upload | Broker login, 24/7 execution, automatic promotion |
| Hugging Face Hub | Versioned model candidates/manifests, promoted `latest/` pointers, public-candle datasets | Store tokens in files, execute code on the PC |
| GitHub | Code hosting and existing Python CI | Run the PC executor or broker actions |
| Cloudflare | Named Tunnel, Access, five-minute Worker health checks, alert dedupe, R2 status/data archives | Receive broker passwords or expose trade mutations |
| Vercel | Authenticated Next.js read-only dashboard for equity, open trades, models, and status | Hold Access secrets in browser code or place trades |

Free tiers are not 24/7 process hosts: Colab/Kaggle sessions end, Hugging Face
Spaces sleep, and Vercel functions are serverless. Cloud schedules can be delayed
or paused. The PC is therefore the only always-on component in this design. Kaggle
GPU quotas are account-dependent (often described as roughly 30 hours/week); the
current compact model is CPU-based and does not consume GPU quota.

## 2. Data and promotion flow

```text
Deriv public candles -> Kaggle / Colab
                      -> train + chronological held-out trade backtest
                      -> HF candidate model + hash-bound manifest + dataset
                      -> exact candidate paper-traded on demo (14d/20 trades min.)
                      -> manual promotion writes HF latest/<symbol>/<timeframe>.json

PC every 3 hours -> download latest manifest + JSON model
                -> verify SHA-256, schema, symbol/timeframe, held-out metrics,
                   profitable backtest evidence, exact-hash paper evidence
                -> atomic swap; any failure keeps the previous model

PC every 15s -> MT5 account/positions/deals -> persistent local risk gate
             -> one inference per newly closed candle -> optional demo order
             -> loopback /api/status -> Cloudflare Tunnel + Access
                                      -> Worker alerts/R2 + Vercel dashboard
```

Candidates never change `latest/` in the training notebook. Model files are JSON,
not pickle and not executable custom code. Old released files remain on the PC for
audit/recovery; only the atomic `active.json` pointer changes after every gate passes.

## 3. Windows PC setup

### 3.1 Reduce interruptions

1. Disable unnecessary startup applications in Task Manager. Keep security software.
2. In an elevated terminal, select High Performance and disable AC sleep:

   ```powershell
   powercfg /setactive SCHEME_MIN
   powercfg /change standby-timeout-ac 0
   powercfg /change hibernate-timeout-ac 0
   ```

3. Configure Windows Update **Active Hours** and restart notifications rather than
   disabling security updates. Review pending restarts regularly.
4. In BIOS/UEFI, enable **Restore on AC power loss** / **AC power recovery** if the
   hardware offers it. Verify Windows and the NEEZY service start correctly after a
   controlled power-cycle test.
5. Keep MT5 and the NEEZY service on the same Windows user/session. Enable broker-side
   SL/TP and test terminal auto-login on a **demo** account. A power cut, network
   outage, broker outage, or Session 0/terminal incompatibility can still stop trading.

### 3.2 Install runtime only

Use 64-bit Python 3.10–3.12. The native `MetaTrader5` package is Windows-only and is
included by the platform marker in `requirements-runtime.txt`.

```powershell
git clone https://github.com/jvrboy/NEEZY.git
cd NEEZY
powershell -ExecutionPolicy Bypass -File scripts\install_executor.ps1
notepad "$env:LOCALAPPDATA\NEEZY\executor.json"
```

The script creates `.venv-executor`, installs only `websocket-client` and Windows
MT5, copies `deploy/executor.example.json`, and validates it. It does not install
Torch, Transformers, pandas, a training stack, or a browser dashboard on the PC.

Edit `hf_repo_id`, symbols, and risk limits. Leave `execution_enabled=false` initially.
`pip_value_per_lot` and `lot_step` are explicit assumptions: verify them against the
broker's demo contract specification before enabling orders. For a private model
repository, set `HF_TOKEN` in the NSSM service's **Environment** tab, not in JSON,
notebooks, Git, or command examples. Public model repositories need no PC token.

Configure MT5 through the existing desktop **SETTINGS → MT5 BRIDGE** or the protected
`settings.json` in the same `NEEZY_HOME`. Do not put the broker password in a command
line. Then run the read-only preflight using that same home:

```powershell
$env:NEEZY_HOME = "$env:LOCALAPPDATA\NEEZY"
.\.venv-executor\Scripts\python.exe -m neezy_backend mt5 preflight
.\.venv-executor\Scripts\python.exe main.py --once
```

`--once` performs one monitoring/inference pass. It cannot send while
`execution_enabled=false`. A critical broker result returns a nonzero exit code.

### 3.3 Install the NSSM service

Install [NSSM](https://nssm.cc/) separately, then from Administrator PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_executor.ps1 -InstallService
nssm edit ForexBot
```

In the NSSM editor:

- **Log on:** use the same Windows account that can run the configured MT5 terminal.
  Enter credentials locally in NSSM; never commit them.
- **Environment:** confirm `NEEZY_HOME` and, only if needed, add `HF_TOKEN`.
- Confirm Application is `.venv-executor\Scripts\python.exe`, arguments point to
  `main.py --config ...\executor.json`, and Startup directory is the checkout.

The installer configures automatic start, restart on crash, a 5-second restart delay,
and rotated stdout/stderr. It intentionally does **not** start the service. Start only
after preflight and an observer-mode run succeed:

```powershell
nssm start ForexBot
nssm status ForexBot
```

Logs are under `%LOCALAPPDATA%\NEEZY\logs` for that Windows user. If MT5 works only in
an interactive session, fix that terminal/service-session issue before relying on NSSM;
do not bypass it by exposing an RPyC or broker port to the internet.

## 4. Train in Kaggle or Colab

1. Create a private HF **model** repository and **dataset** repository.
2. Import `kaggle/cloud/NEEZY_cloud_training.ipynb` into Kaggle or Colab.
3. Add platform secrets `HF_TOKEN`, `HF_MODEL_REPO`, and `HF_DATASET_REPO`. The token
   needs write access only to those repositories. Keep notebook versions private.
4. For the Kaggle CLI, replace `YOUR_USERNAME` in
   `kaggle/cloud/kernel-metadata.json`.
5. Run all cells. The notebook clones a configurable Git ref, installs
   `requirements-training.txt`, pulls public candles, trains, runs the held-out trade
   backtest, and calls `huggingface_hub.upload_file` for candidate/model/dataset files.

The backtest uses the final chronological 15% only, next-candle-open entries, one
position at a time, and stop-first ambiguous candles. Set a realistic spread assumption
in the notebook. A candidate that fails remains research material; it is not promoted.

### Exact-candidate paper validation and deliberate promotion

The PC can paper-validate the **exact candidate hash** without placing any broker
orders. Keep `execution_enabled=false`, use a real MT5 **demo** connection, and set
these fields in `executor.json`:

```json
{
  "execution_enabled": false,
  "paper_candidate": "manifests/MODEL_ID.json",
  "paper_spread": 0.0001
}
```

`paper_candidate` is the immutable HF manifest path, not `latest/`. Paper mode skips
production activation and cannot be combined with `execution_enabled=true`. It still
requires the candidate's schema, metrics, and held-out backtest to pass. The spread is
a mandatory nonzero **price-unit** assumption, not pips; verify it against the demo
broker and symbol. Start or restart the same lightweight service normally.

The validator uses closed MT5 candles, next-candle-open virtual entries, ATR stops and
targets, stop-first ambiguous candles, and model-horizon exits. Open simulations,
closed candles, and outcomes survive service restarts. A missing candle window or
corrupt state fails instead of inventing outcomes; restart that candidate's validation
from zero rather than editing evidence. No order/close/modify method is called.

Reports are written atomically outside Git to
`%LOCALAPPDATA%\NEEZY\paper-reports\MODEL_ID.json`; matching state is under `paper/`.
The default pass requires at least **14 full elapsed days**, **20 closed virtual
trades**, positive spread-adjusted expectancy, and profit factor above 1 when losses
exist. The dashboard shows
progress but cannot promote or trade. When the report passes, set `paper_candidate`
back to `""` before returning to normal observer/execution mode.

Install `requirements-training.txt` on the promotion machine, set `HF_TOKEN`, and
dry-run promotion using the generated report:

```bash
python scripts/promote_model.py \
  --hf-model-repo YOUR_USER/neezy-models \
  --candidate manifests/MODEL_ID.json \
  --paper-report /secure/path/paper-report.json
```

Add `--promote` only after every check passes. This writes only the small HF `latest/`
manifest; it does not retrain or replace the candidate bytes. The PC defaults to a
three-hour check (`model_poll_seconds=10800`). Hash mismatch, weak metrics, failed or
unbound backtest/paper evidence, path traversal, oversize files, and incompatible
schemas all reject the update without deleting the active model.

## 5. Cloudflare Tunnel + Access (no port forwarding)

The status server binds to `127.0.0.1:8787` and has only `GET /health` and
`GET /api/status`; there is no trade/close/settings route.

1. In Cloudflare Zero Trust, create a **remotely managed cloudflared tunnel**.
2. Add public hostname `status.example.com` -> `http://127.0.0.1:8787`.
3. Install `cloudflared` on Windows and run its Windows-service command from an
   elevated terminal with the tunnel token copied from Cloudflare:

   ```powershell
   cloudflared service install <TUNNEL_TOKEN>
   ```

   The token is a credential: use it only on the PC and never commit it. A locally
   managed tunnel can instead use `deploy/cloudflared-config.example.yml`; secure the
   UUID credentials JSON and ensure the Windows service account can read it.
4. Create a Cloudflare **Access** application for `status.example.com` and a **Service
   Auth** token. Require Access on every route; do not bypass it for the Worker/Vercel.
5. Test from a remote machine with the service-token headers, not from the PC's
   localhost. `https://status.example.com/api/status` should return sanitized JSON;
   unauthenticated requests should receive the Access challenge, not executor data.

## 6. Vercel dashboard

Import `dashboard/` as the Vercel project root. See `dashboard/README.md` for local
commands. Configure these server environment variables:

| Variable | Purpose |
| --- | --- |
| `NEEZY_STATUS_URL` | `https://status.example.com/api/status` |
| `CF_ACCESS_CLIENT_ID` | Access service-token client ID |
| `CF_ACCESS_CLIENT_SECRET` | Access service-token secret |
| `DASHBOARD_USERNAME` | Strong dashboard Basic Auth username |
| `DASHBOARD_PASSWORD` | Long, unique dashboard password |

The dynamic Next.js page server-renders the initial snapshot; its server route adds
Access headers for refreshes, and browser JavaScript never receives them. The Next 16
`proxy.js` requires Basic Auth and fails closed with 503 if credentials are missing.
Use HTTPS and rotate both dashboard and Access credentials. Vercel Deployment
Protection/SSO can be added as another layer. The dashboard polls its own relative
`/api/status` every 30 seconds; it never calls localhost and exposes no order controls.
Paper progress appears as a separate read-only candidate card when configured.

The PC atomically persists the latest 240 equity samples in `executor-status.json`, so
recent charts survive a service restart. This bounded local history is not a complete
ledger; use broker records and optional R2 snapshots for longer-term review. Corrupt
persistent executor state is not silently discarded.

## 7. Cloudflare Worker alerts and R2

See `cloudflare/README.md` for commands. The Worker cron runs every five minutes and
checks HTTP/JSON validity, heartbeat freshness, MT5 connectivity, daily loss, risk
blocks, and unprotected bot-owned stops. KV stores the incident fingerprint so identical
incidents do not alert every cron; a later healthy check sends recovery. Failed alert
deliveries are retried, and anonymous Worker HTTP requests cannot trigger checks.

R2 receives `status/latest.json` every run and one hourly snapshot. These are sanitized
status/equity logs, not credential-bearing text logs. Full NSSM/executor logs remain on
the PC. Telegram is supported directly; `ALERT_WEBHOOK_URL` can call an HTTPS automation
that delivers email. Treat that webhook URL as a secret and review the provider's data
policy. Cloudflare can observe Tunnel/Worker traffic and metadata.

## 8. Explicit data pulls and archives

No scheduled GitHub Actions cloud workflow is included. Public-candle collection
remains available as an explicit command:

```bash
python -m pip install -r requirements-actions.txt
python scripts/cloud_data_pull.py \
  --symbols frxEURUSD frxGBPUSD frxUSDJPY \
  --timeframe 15m --candles 5000
```

Run `python scripts/cloud_data_pull.py --help` for the output and publishing
options. Add `--upload` only after configuring the intended HF dataset repository
and credentials in the chosen runner's secret store. Optional R2 settings use the
same explicit script. Never commit tokens or place them in notebook source.

Launch the Kaggle/Colab training notebook manually as described above. Data pulls
do not train or promote a model, and neither path places broker orders. Do not make
a training job push straight to `latest/`; that would bypass paper validation.

## 9. Risk boundaries and operations

The unattended PC service enforces all of the following locally:

- disabled by default; **real/contest/simulated accounts cannot be auto-traded**;
- paper mode requires a demo connection, `execution_enabled=false`, and nonzero spread;
  it uses virtual outcomes only and never calls broker order methods;
- exact-model promotion gates above;
- maximum daily loss, daily order count, open-position count, and position-size cap;
- persisted UTC baseline/trade count/last candle so service restarts do not reset limits
  or duplicate a signal;
- fresh account/positions/deal reads immediately before an order;
- mandatory, direction-consistent broker-side SL and TP;
- new risk blocked if a bot-owned position lacks a stop;
- no order mutation in the status API, Worker, dashboard, MCP, or Agent tools.

At the first service start in a UTC day, opening balance is reconstructed from current
balance minus same-day deal P/L, commission, swap, and fee. Thereafter the persisted
baseline is authoritative. Verify the broker returns complete deal history; carried
positions and broker-specific balance operations can make a generic daily-loss model
imperfect. Use stricter broker/account protections as an independent backstop.

The executor manages exits primarily through broker-side SL/TP and monitors protection.
It does not automatically close an unknown/unprotected position; it raises a health
incident and blocks new bot risk. Power/internet failures still prevent new trades and
management, which is why server-held stops matter.

## 10. Verification and recovery

```bash
# Offline code checks
python local_ci.py
node --test cloudflare/worker.test.mjs
cd dashboard && npm ci && npm run build

# On the PC, safe config and one-pass checks
python main.py --check-config
python main.py --once
```

- **Bad update:** inspect `models` in `/api/status`; rejected candidates leave the active
  model untouched. Do not bypass the gate to force activation.
- **Paper gap/corruption:** do not edit the JSON evidence. If intentionally restarting,
  archive the candidate's `paper/` state and `paper-reports/` report outside the repo;
  the new run starts at zero days/trades and the old report must not be reused.
- **Rollback:** promote a previously validated manifest to the appropriate HF `latest/`
  path, or restore its matching released file/pointer on the PC after verifying its hash.
- **Stale dashboard:** check NSSM, MT5, `cloudflared`, Access service-token expiry, and
  the Worker result in that order. The dashboard shows the last good snapshot plus an
  outage banner rather than inventing values.
- **Risk breach/outage:** leave execution disabled, inspect broker positions directly,
  and retain broker-side stops. Do not reset `executor-risk.json` to circumvent a limit;
  corrupt/unreadable state deliberately prevents service startup.
