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

### Advanced analytics (v1.1)

- **Extended indicator engine**: Bollinger Bands (%B, bandwidth), Stochastic %K/%D, Wilder ADX with +DI/-DI, and SMA, plus a market-regime label (Trending / Ranging / Squeeze). The original 4-point score is unchanged, so existing alert thresholds keep working.
- **Price action**: candlestick patterns (doji, hammer, shooting star, marubozu, engulfing, inside bar), floor-trader pivots, and fractal swing support/resistance.
- **Chart overlays**: EMA 21, rolling Bollinger Bands, nearest support/resistance, a last-price marker, and price-axis labels with the correct precision for each market.
- **Trader toolkit (TOOLS tab)**: an ATR-based risk planner (position size, stop, target, risk and reward amounts), a walk-forward backtester (on the live buffer or on up to 5,000 freshly fetched candles in a background thread), and a market ranking with the strongest cross-market return correlations.
- **Alert rules (ALERTS tab)**: persistent rules on price, RSI, score, ADX, signal, or candle pattern with `>`, `>=`, `<`, `<=`, `==`, `crosses above`, and `crosses below`. Rules fire on the transition to true (edge-triggered), so they do not repeat on every tick.
- **Smarter copilot**: chat understands market names and questions about risk, levels, patterns, trend/regime, and the best current setups.
- **Headless CLI (`neezy-cli`)**: scan, analyze, backtest, risk, correlation, history, and alert management from a terminal, with `--json` output for scripting.
- **Reliability fixes**: late updates from a previous timeframe subscription are now discarded, typed spinbox values are saved, the history file compacts itself automatically, and read-only dropdowns follow the theme.

### Backtest methodology

Decisions use closed candles only and fill at the *next* candle's open. When the stop and target are both touched inside one candle, the stop is assumed to fill first. Results are reported in R multiples (1R = initial stop distance): trades, win rate, total R, expectancy, profit factor, max drawdown, and per-trade Sharpe. Simulated results do not predict future performance.

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

## Command-line tools

The `neezy-cli` command (also `python -m neezy_backend`) needs no display:

```bash
neezy-cli markets                              # list markets and timeframes
neezy-cli scan -t 15m                          # rank every market by signal strength
neezy-cli analyze EURUSD -t 1h                 # indicators, pivots, levels, patterns
neezy-cli backtest GBPUSD -t 5m -n 3000 --spread-pips 0.8 --trades
neezy-cli risk EURUSD --balance 10000 --risk 1 --entry 1.0850 --stop 1.0825
neezy-cli risk USDJPY --balance 5000 --entry 150.2 --direction SELL --atr 0.18 --pip-value 6.7
neezy-cli correlation EURUSD GBPUSD USDCHF --window 200
neezy-cli alerts add EURUSD rsi "crosses above" 70 --note "overbought"
neezy-cli alerts                               # list rules (shared with the desktop app)
neezy-cli history --summary
```

Every command accepts `--json`. Markets can be written as `EURUSD`, `EUR/USD`, or `frxEURUSD`.

## Local data

Settings, alert rules, and signal history are stored in the user's application configuration directory (Linux: `$XDG_CONFIG_HOME/neezy`, otherwise `~/.config/neezy`; macOS and Windows use their usual per-user application data locations). Set `NEEZY_HOME` to override the directory, useful for portable installs and tests. Settings are written atomically; signal history is an append-only JSON Lines file that is compacted to the newest 5,000 records once it passes about 2 MB. History export creates a standard CSV file at the location selected by the user.

## Project layout

```text
neezy_app/             Tkinter application and installed CLI entry point
neezy_backend/         validated settings, stream events/client, analysis, persistence
  indicators.py        EMA/RSI/ATR/MACD/Bollinger/Stochastic/ADX + signal engine
  patterns.py          candlestick patterns, pivots, swing support/resistance
  backtest.py          walk-forward backtester with R-multiple statistics
  risk.py              ATR stops and position sizing
  alerts.py            alert rules, edge-triggered engine, persistence
  analytics.py         correlation matrix and opportunity ranking
  markets.py           market catalog, timeframes, price precision
  cli.py               neezy-cli command-line tools
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
