"""Reproducible, advisory-only ML and FX-pair research on public candles.

Neural stages are fresh fits, not warm starts: the first fit sees only the
oldest 70%; the final fit retains a chronological untouched test set using
brain.train_model's purged train/validation/test boundaries. No seed/horizon
search is performed on that test set. Pair research fixes its hedge ratio on
the training segment, uses lagged rolling z-scores, and charges turnover costs.
Correlation is not cointegration, and simulated performance is not a forecast.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from .brain import train_model
from .config import AppSettings
from .markets import PUBLIC_WS_URL, TIMEFRAMES
from .storage import _atomic_json_write
from .stream import fetch_history

Candle = tuple[int, float, float, float, float]
Fetch = Callable[..., list[Candle]]
DEFAULT_RESEARCH_SYMBOLS = (
    "DSI10",
    "DSI20",
    "DSI30",
    "R_10",
    "R_50",
    "R_100",
    "1HZ100V",
    "frxEURUSD",
    "frxGBPUSD",
    "frxAUDUSD",
    "frxUSDJPY",
)


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2:
        return 0.0
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    covariance = sum((a - lm) * (b - rm) for a, b in zip(left, right, strict=True))
    scale = math.sqrt(
        sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right)
    )
    return covariance / scale if scale else 0.0


def _closes(rows: Sequence[Sequence[float]]) -> dict[int, float]:
    result = {}
    previous = -math.inf
    for row in rows:
        if len(row) != 5 or not all(math.isfinite(float(value)) for value in row):
            raise ValueError("candles must have five finite values")
        epoch, open_, high, low, close = row
        if isinstance(epoch, bool) or epoch < 0 or int(epoch) != epoch:
            raise ValueError("candle epochs must be non-negative integers")
        if epoch <= previous or min(open_, high, low, close) <= 0:
            raise ValueError("candles must be positive and strictly ordered")
        if high < max(open_, close) or low > min(open_, close) or high < low:
            raise ValueError("inconsistent OHLC values")
        previous = epoch
        result[int(epoch)] = float(close)
    return result


def pair_research(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Chronological two-leg return-residual simulation, never order execution.

    Last rows are discarded as potentially active; timestamps are inner-joined.
    All z-scores use observations strictly before the position's return interval.
    PnL is an unlevered, gross-exposure-normalised log-return approximation.
    """
    cfg = settings or AppSettings()
    a, b = _closes(left[:-1]), _closes(right[:-1])
    epochs = sorted(a.keys() & b.keys())
    if len(epochs) < max(cfg.pair_min_overlap, cfg.pair_lookback * 3):
        raise ValueError("not enough aligned closed candles for pair research")
    x = [math.log(a[t]) for t in epochs]
    y = [math.log(b[t]) for t in epochs]
    rx = [x[i] - x[i - 1] for i in range(1, len(x))]
    ry = [y[i] - y[i - 1] for i in range(1, len(y))]
    boundary = int(len(rx) * 0.7)
    mx, my = statistics.fmean(rx[:boundary]), statistics.fmean(ry[:boundary])
    variance = sum((r - my) ** 2 for r in ry[:boundary])
    if variance <= 1e-20:
        raise ValueError("hedge leg has no training variance")
    beta = (
        sum(
            (p - mx) * (q - my)
            for p, q in zip(rx[:boundary], ry[:boundary], strict=True)
        )
        / variance
    )
    residual = [0.0]
    for p, q in zip(rx, ry, strict=True):
        residual.append(residual[-1] + p - beta * q)
    train_corr = _correlation(rx[:boundary], ry[:boundary])
    enabled = abs(train_corr) >= cfg.pair_min_correlation
    position, age, previous_position = 0, 0, 0
    equity, peak, drawdown, costs, entries = 0.0, 0.0, 0.0, 0.0, 0
    pnl, path = [], []
    last_z = 0.0
    for i in range(boundary + 1, len(residual) - 1):
        window = residual[i - cfg.pair_lookback : i]
        sigma = statistics.pstdev(window)
        z = (residual[i] - statistics.fmean(window)) / sigma if sigma > 1e-12 else 0.0
        last_z = z
        previous_position = position
        if position and (
            abs(z) <= cfg.pair_exit_z
            or abs(z) >= cfg.pair_stop_z
            or age >= cfg.pair_max_holding
        ):
            position, age = 0, 0
        elif not position and enabled and cfg.pair_entry_z <= abs(z) < cfg.pair_stop_z:
            position = -1 if z > 0 else 1
            age = 0
            entries += 1
        cost = abs(position - previous_position) * cfg.pair_cost_bps / 10000
        result = position * (residual[i + 1] - residual[i]) / (1 + abs(beta)) - cost
        equity += result
        costs += cost
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        pnl.append(result)
        path.append({"epoch": epochs[i + 1], "pnl": result, "position": position})
        age += bool(position)
    # Charge flattening at the final observation as well as all entries/exits.
    if position and pnl:
        cost = abs(position) * cfg.pair_cost_bps / 10000
        costs += cost
        equity -= cost
        pnl[-1] -= cost
        path[-1]["pnl"] -= cost
        drawdown = max(drawdown, peak - equity)
    deviation = statistics.pstdev(pnl) if pnl else 0.0
    return {
        "aligned_candles": len(epochs),
        "train_returns": boundary,
        "test_bars": len(pnl),
        "hedge_beta": beta,
        "train_correlation": train_corr,
        "test_correlation": _correlation(rx[boundary:], ry[boundary:]),
        "eligible": enabled,
        "last_z": last_z,
        "entries": entries,
        "net_log_return": equity,
        "max_log_drawdown": drawdown,
        "cost_log_return": costs,
        "test_sharpe_unannualized": statistics.fmean(pnl) / deviation
        if deviation
        else 0.0,
        "path": path,
        "caveat": (
            "Research only; correlation is not cointegration. "
            "Costs are assumptions, not broker quotes."
        ),
    }


def training_run(
    symbols: Sequence[str] = DEFAULT_RESEARCH_SYMBOLS,
    *,
    timeframe: str = "5m",
    settings: AppSettings | None = None,
    fetch: Fetch = fetch_history,
    progress: Callable[[str], None] | None = None,
    checkpoint: str | None = None,
) -> dict[str, Any]:
    """Fetch fresh public candles, train staged neural fits, checkpoint per symbol.

    Injection of ``fetch`` is for deterministic tests only. Provenance records
    the actual endpoint, full OHLC SHA256 and capture/window timestamps. Each
    market's failure is explicit and does not discard successful checkpoints.
    """
    cfg = settings or AppSettings()
    if timeframe not in TIMEFRAMES:
        raise ValueError("unsupported timeframe")
    report: dict[str, Any] = {
        "schema": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": cfg.deriv_endpoint or PUBLIC_WS_URL,
        "timeframe": timeframe,
        "settings": {
            key: value
            for key, value in cfg.to_dict().items()
            if key.startswith(("ml_", "pair_"))
        },
        "method": (
            "Staged fresh MLP fits; no test-driven selection or warm-start claim."
        ),
        "symbols": {},
        "forex_pairs": {},
    }
    forex = {}
    for symbol in dict.fromkeys(symbols):
        if progress:
            progress(f"Fetching and training {symbol}")
        try:
            rows = fetch(
                symbol,
                TIMEFRAMES[timeframe],
                cfg.ml_history_candles,
                url=report["endpoint"],
                timeout=cfg.ml_fetch_timeout,
            )
            # Validate the entire fetch before hashing, training or persisting it.
            _closes(rows)
            if len(rows) < 400:
                raise ValueError("at least 400 fresh candles are required")
            kwargs = {
                "symbol": symbol,
                "timeframe": timeframe,
                "horizon": cfg.ml_horizon,
                "deadband_atr": cfg.ml_deadband_atr,
                "min_samples": cfg.ml_min_samples,
                "seed": cfg.ml_seed,
            }
            initial = train_model(
                rows[: int(len(rows) * 0.7)],
                epochs=max(1, cfg.ml_epochs // 2),
                **kwargs,
            )
            final = train_model(rows, epochs=cfg.ml_epochs, **kwargs)
            record = {
                "status": "trained",
                "candles": len(rows),
                "first_epoch": rows[0][0],
                "last_epoch": rows[-1][0],
                "ohlc_sha256": hashlib.sha256(
                    json.dumps(rows, separators=(",", ":")).encode()
                ).hexdigest(),
                "initial_report": initial["report"],
                "report": final["report"],
                "model": final["model"],
            }
            report["symbols"][symbol] = record
            if symbol.startswith("frx"):
                forex[symbol] = rows
        except (OSError, RuntimeError, ValueError) as error:
            report["symbols"][symbol] = {"status": "error", "error": str(error)}
        if checkpoint:
            _atomic_json_write(Path(checkpoint), report)
    for left, right in combinations(forex, 2):
        key = f"{left}:{right}"
        try:
            result = pair_research(forex[left], forex[right], settings=cfg)
            # Store aggregate findings; per-bar path is reproducible via pair_research.
            result.pop("path")
            report["forex_pairs"][key] = result
        except ValueError as error:
            report["forex_pairs"][key] = {"status": "error", "error": str(error)}
    if checkpoint:
        _atomic_json_write(Path(checkpoint), report)
    return report
