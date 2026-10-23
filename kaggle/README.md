# NEEZY on Kaggle

> For the cloud-trained/light-PC deployment, use [`cloud/NEEZY_cloud_training.ipynb`](cloud/NEEZY_cloud_training.ipynb) and the [cloud operations guide](../docs/CLOUD_OPERATIONS.md). That notebook trains/backtests and uploads HF candidates/datasets without broker access or automatic promotion. The original research notebook below is unchanged.

`NEEZY_on_Kaggle.ipynb` installs and runs NEEZY inside a Kaggle notebook: the headless
engine and `neezy-cli`, live confluence cards, the local SQLite store, backtests, and an
optional screenshot of the Tk desktop workspace.

NEEZY analyses public market data for learning and research. It places no trades, never
logs into a broker, and is not financial advice.

| File | Purpose |
| --- | --- |
| `NEEZY_on_Kaggle.ipynb` | the notebook (committed without saved outputs) |
| `kernel-metadata.json` | Kaggle CLI metadata for `kaggle kernels push` |

## Quick start — Internet on (recommended)

1. Kaggle → **Create → Notebook**.
2. **File → Import Notebook** and upload `NEEZY_on_Kaggle.ipynb`.
3. In the editor open **Settings → Internet** and switch it **ON**
   (new accounts must verify a phone number first).
4. **Run all**.

The install cell runs `pip install git+https://github.com/jvrboy/NEEZY.git@main`.
Set `GIT_REF` to a tag or commit to pin a build, or `GITHUB_REPO` to use a fork.
No GPU is needed.

## Mode 2 — no Internet, attach the repo as a Dataset

NEEZY is pure Python, so an attached copy of this repository is used directly from
`/kaggle/input` (added to `sys.path`); nothing is downloaded or built.

**With the Kaggle CLI**

```bash
git clone --depth 1 https://github.com/jvrboy/NEEZY.git /tmp/neezy-dataset
cd /tmp/neezy-dataset
rm -rf .git .github
kaggle datasets init -p .
# edit dataset-metadata.json: set a title and a unique slug, e.g. <username>/neezy-source
kaggle datasets create -p .
```

**With the Kaggle website**

Create a **Dataset** and upload the repository files (or a zip), then attach it to the
notebook with **Add Input**.

Then in the notebook:

1. Attach the dataset (**Add Input → Your Datasets**).
2. Set `INSTALL_SOURCE = "dataset"` in the settings cell.
3. Run all.

The install cell finds any folder under `/kaggle/input` that contains `pyproject.toml`,
`neezy_backend/` and `neezy_app/`. In this mode the `neezy-cli` console script is not
created — call `python -m neezy_backend ...` or use the `neezy()` helper defined in the
notebook.

## What runs on Kaggle

| NEEZY component | On Kaggle | Why |
| --- | --- | --- |
| Headless engine + `neezy-cli` (analysis, confluence cards, scanner, backtests) | ✅ | pure Python |
| Local SQLite store (`NEEZY_HOME`) | ✅ | point it at `/kaggle/working` to survive the session |
| Deriv public market data | ✅ with Internet on | outbound WebSocket on 443 |
| BYO-key AI providers (Gemini / Grok / OpenRouter / Ollama Cloud) | ✅ | keys from Kaggle Secrets |
| Optional local GGUF / Transformers models | ⚠️ | CPU only, extra native wheels, slow |
| Desktop Tk workspace | ⚠️ screenshot only | no display; the notebook renders a PNG through Xvfb |
| MT5 bridge, Telegram bot, local MCP server, Cloudflare tunnel | ❌ | needs Windows MetaTrader, a persistent bot host, or a loopback client |

## Where things are stored

The notebook sets `NEEZY_HOME=/kaggle/working/neezy-home`, so the SQLite database,
`settings.json` and provider-key files live in the notebook output directory.
`/kaggle/working` persists when you run **Save Version → Save & Run All** (up to 20 GB) and
can be re-attached as an input next time.

```bash
neezy-cli db stats                        # size and row counts
neezy-cli db export /kaggle/working/neezy-export.json
neezy-cli db prune --days 30              # apply the retention window
```

## Pushing the notebook with the Kaggle CLI

```bash
cd kaggle
# 1. edit kernel-metadata.json and replace YOUR_USERNAME (and adjust the slug/title)
# 2. push and run
kaggle kernels push -p .
kaggle kernels status <username>/neezy-on-kaggle
```

`kernel-metadata.json` sets `enable_internet: true`, but Kaggle has been reported to ignore
that flag for API-uploaded notebooks. If the run comes back with Internet off, open the
notebook in the editor and toggle Internet on, or use the Dataset mode above.

## Notes and limits

* **Packages do not persist.** Each session starts from a clean image, so the install cell
  must run again after every restart. Run All does that for you.
* **Session limits** are 12 h for CPU/GPU notebooks and 9 h for TPU. Keep long scans and
  training runs checkpointed in `/kaggle/working`.
* **The desktop GUI is not interactive** on Kaggle. The screenshot cell installs `xvfb`,
  `x11-utils` and ImageMagick with `apt`, launches `python -m neezy_app` on a virtual
  display and captures the window. If the image has no `tkinter`, no root access or no
  apt, the cell says so and the rest of the notebook continues.
* **Secrets.** Add `NEEZY_AI_KEY` (and optionally `ALPHA_VANTAGE_KEY`, `FINNHUB_KEY`,
  `TWELVE_DATA_KEY`) under **Add-ons → Secrets**; the notebook exports them as environment
  variables. Avoid committing keys into cells.
* **Key files are plain text.** `neezy-cli ai keys add` writes `ai-keys.json` inside
  `NEEZY_HOME`; if you save a notebook version, that file becomes part of the saved
  output. Keep such versions private.
* **Data source.** Deriv's public feed needs no key and no login. If every endpoint in
  `neezy-cli doctor` is unreachable, the network path is blocked — try another network or
  pin a working endpoint with `NEEZY_WS_URL`.
* **Educational only.** Win rates are in-sample replays of past candles. Simulated and
  historical results do not predict future performance.

## What was verified

Locally (Python 3.11, no display, Deriv unreachable):

* the notebook executes end-to-end in both install modes (GitHub `pip install` and an
  attached checkout used through `sys.path`);
* `neezy-cli markets` / `--version` / `risk` work offline; connectivity, candle and backup
  failures produce readable messages instead of tracebacks;
* the confluence card table renders from synthetic candles through the same code path;
* the repository test suite passes (367 tests, 2 environment skips).

The Kaggle-only pieces — `apt-get install xvfb`, `import tkinter` in the Kaggle image and
the screenshot capture — are best-effort with graceful fallbacks, since they cannot be
exercised outside a Kaggle session.
