# NEEZY

NEEZY is a native Python/Tkinter market-monitoring workspace. It reads public market candles from Deriv's WebSocket API and computes educational technical-analysis summaries. It does not place trades, authenticate to broker accounts, or provide financial advice.

## Features

- Multi-market watchlist and live signal table with selectable timeframes.
- Candlestick canvas and per-market indicator detail for EMA 9/21/50, RSI 14, ATR 14, and MACD histogram.
- Closed-candle analysis, explicit trend/volatility context, and finite/OHLC validation before data reaches the signal engine.
- Reconnecting background WebSocket service with bounded backoff, observable status events, and clean shutdown.
- Local persistent settings (theme, polling rate, data density, candle buffer, refresh, and alert threshold).
- Signal-transition history stored locally with CSV export and configurable desktop beeps.
- Three theme presets, chat input shortcut (Enter), and a compatibility launcher for older instructions.

## Install and run

Python 3.10 or newer is required. Tkinter must be installed with Python by the operating system (on Debian/Ubuntu, the `python3-tk` package may be needed). Install the app and its WebSocket dependency from the repository root:

```bash
python -m pip install .
neezy
```

Alternatively, run from a checkout without installing:

```bash
python -m pip install -r requirements.txt
python -m neezy_app
```

The original `python forex_signals.py` entry point remains available. A graphical desktop session is required.

## Local data

Settings and signal history are stored in the user's application configuration directory (Linux: `$XDG_CONFIG_HOME/neezy`, otherwise `~/.config/neezy`; macOS and Windows use their usual per-user application data locations). Set `NEEZY_HOME` to override the directory, useful for portable installs and tests. Settings are written atomically; signal history is an append-only JSON Lines file. History export creates a standard CSV file at the location selected by the user.

## Project layout

```text
neezy_app/             Tkinter application and installed CLI entry point
neezy_backend/         validated settings, stream events/client, analysis, persistence
tests/                 standard-library unittest suite
forex_signals.py       backward-compatible launcher
pyproject.toml         package/build metadata and developer tool configuration
```

## Development checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q neezy_app neezy_backend forex_signals.py
ruff check neezy_app neezy_backend tests forex_signals.py
ruff format --check neezy_app neezy_backend tests forex_signals.py
```

The app depends on Deriv's public WebSocket endpoint and an internet connection for live candles. The service may be unavailable or rate-limited; the UI surfaces connection and API errors and retries transient disconnects. The market monitor is informational only; do not use its signals as a substitute for independent analysis or professional advice.
