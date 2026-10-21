"""Direct Messaging & Decision Metrics engine for alerts and decision matrix."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from neezy_backend.indicators import analyze
from neezy_backend.risk import position_size
from neezy_backend.strategies import consensus, run_all

logger = logging.getLogger(__name__)


def send_dm_notification(
    webhook_url: str,
    title: str,
    message: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Send a direct message notification to a Webhook URL (Discord/Slack/HTTP)."""
    cleaned_url = webhook_url.strip()
    if not cleaned_url:
        return {"success": False, "error": "Webhook URL is empty"}
    if not cleaned_url.startswith(("http://", "https://")):
        return {
            "success": False,
            "error": "Webhook URL must start with http:// or https://",
        }

    # Format payload for standard webhook, Discord, or Slack compatibility
    payload: dict[str, Any] = {
        "text": f"*{title}*\n{message}",
        "title": title,
        "message": message,
        "level": level,
        "content": f"**{title}**\n{message}",
    }
    if fields:
        payload["fields"] = fields
        field_strs = [f"• **{k}**: {v}" for k, v in fields.items()]
        payload["text"] += "\n" + "\n".join(field_strs)
        payload["content"] += "\n" + "\n".join(field_strs)

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        cleaned_url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "NEEZY-DM-Client/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            if 200 <= status_code < 300:
                return {
                    "success": True,
                    "status_code": status_code,
                    "message": "Direct message sent successfully",
                }
            return {
                "success": False,
                "status_code": status_code,
                "error": f"Webhook server returned status {status_code}",
            }
    except Exception as ex:  # noqa: BLE001
        logger.warning(f"Failed to send DM notification: {ex}")
        return {"success": False, "error": str(ex)}


def format_signal_dm(
    symbol: str,
    timeframe: str,
    signal: str,
    score: float,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Format a signal event into a Direct Message payload."""
    emoji = (
        "🟢"
        if "BUY" in signal.upper()
        else ("🔴" if "SELL" in signal.upper() else "⚪")
    )
    title = f"{emoji} NEEZY Signal Alert: {symbol} ({timeframe})"
    message = f"Signal: {signal}\nScore: {score:.1f}/4.0"
    fields = {
        "Symbol": symbol,
        "Timeframe": timeframe,
        "Signal": signal,
        "Score": f"{score:.1f}",
    }
    if metrics:
        for k, v in metrics.items():
            fields[k] = str(v)
    return {
        "title": title,
        "message": message,
        "fields": fields,
        "level": "warning" if score >= 3.0 else "info",
    }


def compute_decision_metrics(
    symbol: str,
    timeframe: str,
    candles: list[dict[str, Any]],
    balance: float = 10000.0,
    risk_percent: float = 1.0,
    max_drawdown_pct: float = 10.0,
) -> dict[str, Any]:
    """Compute comprehensive decision metrics for trade setup evaluation."""
    if not candles or len(candles) < 30:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "verdict": "INSUFFICIENT_DATA",
            "score": 0.0,
            "confidence": 0.0,
            "reasons": ["Not enough candles provided (minimum 30 required)"],
        }

    indicators = analyze(candles) or {}
    last_candle = candles[-1]
    last_price = float(
        last_candle["close"] if isinstance(last_candle, dict) else last_candle[4]
    )
    atr = float(indicators.get("atr", 0.0010) or 0.0010)

    # Multi-strategy consensus
    strat_signals = run_all(candles)
    verdict = consensus(strat_signals)

    direction = verdict["label"]
    confidence = verdict["confidence"]
    votes = verdict["votes"]

    # Entry, stop, and target calculations
    if "BUY" in direction:
        entry = last_price
        stop = entry - (1.5 * atr)
    elif "SELL" in direction:
        entry = last_price
        stop = entry + (1.5 * atr)
    else:
        entry = last_price
        stop = entry - (1.5 * atr)

    plan = position_size(
        symbol=symbol,
        balance=balance,
        risk_percent=risk_percent,
        entry=entry,
        stop=stop,
        reward_to_risk=2.0,
    )
    risk_dict = plan.to_dict()
    rsi = float(indicators.get("rsi", 50.0) or 50.0)
    adx_dict = indicators.get("adx")
    adx = float(adx_dict.get("adx", 20.0) if isinstance(adx_dict, dict) else 20.0)

    reasons = list(verdict.get("reasons", []))
    if adx > 25.0:
        reasons.append(f"Strong trend strength (ADX = {adx:.1f})")
    else:
        reasons.append(f"Ranging/weak trend market (ADX = {adx:.1f})")

    drawdown_risk_ok = (risk_dict["risk_amount"] / balance * 100) <= max_drawdown_pct

    decision_label = direction
    if confidence >= 70 and adx >= 20 and drawdown_risk_ok:
        decision_label = (
            f"STRONG_{direction}" if direction in ("BUY", "SELL") else direction
        )
    elif confidence < 40:
        decision_label = "NEUTRAL"

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "decision": decision_label,
        "consensus_direction": direction,
        "confidence": round(confidence, 1),
        "strategy_votes": votes,
        "last_price": round(last_price, 5),
        "atr": round(atr, 5),
        "rsi": round(rsi, 1),
        "adx": round(adx, 1),
        "risk_plan": risk_dict,
        "drawdown_risk_ok": drawdown_risk_ok,
        "reasons": reasons,
    }
