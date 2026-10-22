# Contributing to NEEZY

Thanks for helping. NEEZY is a local-first market-signal workspace: Python
3.10+, Tkinter desktop, standard-library backend, no hosted services. Read
`ARCHITECTURE.md` first — it maps every module and the invariants that are
non-negotiable.

## Setup (one command)

```sh
sh scripts/dev_setup.sh          # POSIX
pwsh scripts/dev_setup.ps1       # Windows
```

or manually:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Everyday commands

```sh
make test      # full suite (offline; no network needed)
make lint      # ruff check + format check
make format    # auto-fix lint and format
make ci        # everything local_ci.py gates (what CI runs)
make run       # launch the desktop app
```

## Ground rules

1. **Tests are offline.** The suite never touches the network. Use the fake
   fetch/websocket patterns already in `tests/`.
2. **Never break the invariants** (see ARCHITECTURE.md §10): closed candles
   only, no agent-driven live orders, no secrets in the repo, sandboxed
   paths for tools, validated settings, widgets only on the Tk main thread.
3. **Match the style.** Ruff (E, F, I, UP, B, BLE, RUF; line length 88) is
   the arbiter — run `make format` before you commit.
4. **Add tests for every change.** New module without tests does not ship.
5. **Update `CHANGELOG.md`** for user-visible changes, under "Unreleased".

## Where things live

| You are changing… | Start in… |
|---|---|
| Signals / strategies | `neezy_backend/strategies.py`, `confluence.py` |
| Chart / panels | `neezy_app/ui_panels/*.py` |
| CLI | `neezy_backend/cli.py` (see ROADMAP #1 for the split plan) |
| Tests | `tests/` — one module per backend module |
| Docs | `docs/`, `ARCHITECTURE.md`, this file |

## Pull requests

Use the PR template. CI must be green on all three Python versions before
review. If you touched `neezy_backend/data/*.json`, mention it — shipped
datasets are user-visible.

## Reporting bugs

Open an issue with the bug template; include `neezy-cli doctor` output
(redact anything sensitive). For security matters, see `SECURITY.md`.
