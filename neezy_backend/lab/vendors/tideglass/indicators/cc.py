"""Confluence Compass (CC) - regime-aware meta-indicator.

CC turns the seven base indicators into one directional reading.

1. Each base indicator contributes a directional signal ``s_i`` in [-1, 1]:

   ===== =============================== ==========================
   Code  Signal                          Interpretation
   ===== =============================== ==========================
   EDI   ``snap_back``                   mean-reversion pull
   FSCR  ``consensus``                   multi-scale trend vote
   TDGZ  ``net_pull``                    nearest/stronger magnet
   TIS   ``direction x score / 100``     trend quality, signed
   MDR   ``signal`` (``-sign(m) decay``) reversal pressure
   SRP   ``hour_bias``                   learned hourly drift
   ===== =============================== ==========================

   VBO is non-directional; it modulates confidence instead.

2. Regime (codes): 3 ``trend`` if TIS regime >= dirty_trend, else 2
   ``breakout`` if the VBO phase is exhale, else 1 ``range`` if TIS says range,
   else 0 ``chop``.

3. ``score = sum(w_i s_i) / sum(w_i)`` using the regime's weights from
   ``config/confluence_weights.json`` (missing signals are skipped).

4. ``agreement = sum(w_i |s_i| [sign s_i = sign score]) / sum(w_i |s_i|)``;
   ``confidence = clamp(agreement sqrt(min(1, |score| / strength_ref))
   (1 + vbo_boost (p_exp - 0.5)) (1 - srp_penalty [anomaly]), 0, 1)``.

5. ``reason`` is a plain-language list of the contributors, strongest first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

import numpy as np

from ..types import Candles, IndicatorResult
from ._common import clamp

SIGNAL_ORDER = ("EDI", "FSCR", "TDGZ", "TIS", "MDR", "SRP")
REGIME_NAMES = ("chop", "range", "breakout", "trend")
REGIME_LABELS = {i: n for i, n in enumerate(REGIME_NAMES)}


@dataclass(frozen=True)
class CCParams:
    strength_ref: float = 0.5
    srp_penalty: float = 0.15
    min_contrib: float = 0.005


def weight_matrix(weights_doc: Mapping) -> tuple[np.ndarray, np.ndarray]:
    """Convert the weights JSON document into ``(W[4, 6], boost[4])`` arrays."""
    w = np.zeros((len(REGIME_NAMES), len(SIGNAL_ORDER)))
    boost = np.zeros(len(REGIME_NAMES))
    for r, name in enumerate(REGIME_NAMES):
        reg = weights_doc["regimes"][name]
        for i, ind in enumerate(SIGNAL_ORDER):
            w[r, i] = float(reg["weights"].get(ind, 0.0))
        boost[r] = float(reg.get("vbo_boost", 0.0))
    return w, boost


def extract_signals(base: Mapping[str, IndicatorResult]) -> np.ndarray:
    """Stack the six directional base signals into an ``(n, 6)`` matrix."""
    tis = base["TIS"]
    cols = [
        base["EDI"]["snap_back"],
        base["FSCR"]["consensus"],
        base["TDGZ"]["net_pull"],
        tis["direction"] * tis["score"] / 100.0,
        base["MDR"]["signal"],
        base["SRP"]["hour_bias"],
    ]
    return np.column_stack(cols)


def regime_codes(tis_regime: np.ndarray, vbo_phase: np.ndarray) -> np.ndarray:
    """Map TIS regime + VBO phase to the CC regime code (NaN when TIS is NaN)."""
    out = np.full(tis_regime.shape[0], np.nan)
    for t, (r, ph) in enumerate(zip(tis_regime, vbo_phase)):
        if not math.isfinite(r):
            continue
        if r >= 2:
            out[t] = 3
        elif math.isfinite(ph) and ph == 1:
            out[t] = 2
        elif r == 1:
            out[t] = 1
        else:
            out[t] = 0
    return out


def aggregate(
    signals: np.ndarray,
    regime: np.ndarray,
    exp_prob: np.ndarray,
    anomaly: np.ndarray,
    w: np.ndarray,
    boost: np.ndarray,
    p: CCParams,
) -> Dict[str, np.ndarray]:
    """Core aggregation shared with the C++ ``cc_aggregate`` kernel."""
    n, k = signals.shape
    score = np.full(n, np.nan)
    conf = np.full(n, np.nan)
    agree = np.full(n, np.nan)
    contrib = np.full((n, k), np.nan)
    for t in range(n):
        r = regime[t]
        if not math.isfinite(r):
            continue
        wr = w[int(r)]
        num = den = 0.0
        for i in range(k):
            s = signals[t, i]
            if math.isfinite(s) and wr[i] > 0:
                num += wr[i] * s
                den += wr[i]
        if den <= 0:
            continue
        sc = num / den
        ssc = 1.0 if sc > 0 else (-1.0 if sc < 0 else 0.0)
        tot = same = 0.0
        for i in range(k):
            s = signals[t, i]
            if math.isfinite(s) and wr[i] > 0:
                contrib[t, i] = wr[i] * s / den
                tot += wr[i] * abs(s)
                ssi = 1.0 if s > 0 else (-1.0 if s < 0 else 0.0)
                if ssc != 0.0 and ssi == ssc:
                    same += wr[i] * abs(s)
            else:
                contrib[t, i] = 0.0
        ag = same / tot if tot > 0 else 0.0
        pe = exp_prob[t] if math.isfinite(exp_prob[t]) else 0.5
        vmult = 1.0 + boost[int(r)] * (pe - 0.5)
        smult = (
            1.0 - p.srp_penalty
            if (math.isfinite(anomaly[t]) and anomaly[t] != 0)
            else 1.0
        )
        cf = clamp(
            ag * math.sqrt(min(1.0, abs(sc) / p.strength_ref)) * vmult * smult, 0.0, 1.0
        )
        score[t], conf[t], agree[t] = sc, cf, ag
    return {"score": score, "confidence": conf, "agreement": agree, "contrib": contrib}


def reason_string(
    t: int,
    regime: float,
    score: float,
    conf: float,
    contrib: np.ndarray,
    min_contrib: float,
) -> str:
    """Plain-language explanation of bar ``t``."""
    if not math.isfinite(score):
        return "warming up: not enough history for a reading"
    order = sorted(range(len(SIGNAL_ORDER)), key=lambda i: (-abs(contrib[i]), i))
    ssc = 1.0 if score > 0 else (-1.0 if score < 0 else 0.0)
    pro, con = [], []
    for i in order:
        cv = contrib[i]
        if not math.isfinite(cv) or abs(cv) < min_contrib:
            continue
        item = f"{SIGNAL_ORDER[i]} {cv:+.2f}"
        (pro if (cv > 0) == (ssc > 0) and ssc != 0 else con).append(item)
    bias = "bullish" if score > 0.05 else ("bearish" if score < -0.05 else "neutral")
    parts = [
        f"{bias} {score:+.2f} (confidence {conf:.2f}) in {REGIME_NAMES[int(regime)]} regime"
    ]
    parts.append("supported by " + (", ".join(pro) if pro else "nothing"))
    if con:
        parts.append("opposed by " + ", ".join(con))
    return "; ".join(parts)


def compute_cc(
    candles: Candles,
    base: Mapping[str, IndicatorResult],
    weights_doc: Mapping,
    p: CCParams = CCParams(),
    with_reasons: bool = True,
) -> IndicatorResult:
    """Combine the seven base results (keys EDI, VBO, FSCR, TDGZ, TIS, MDR, SRP)."""
    w, boost = weight_matrix(weights_doc)
    sig = extract_signals(base)
    regime = regime_codes(base["TIS"]["regime"], base["VBO"]["phase"])
    agg = aggregate(
        sig,
        regime,
        base["VBO"]["expansion_prob"],
        base["SRP"]["anomaly_flag"],
        w,
        boost,
        p,
    )
    outputs = {
        "score": agg["score"],
        "confidence": agg["confidence"],
        "regime": regime,
        "agreement": agg["agreement"],
    }
    for i, name in enumerate(SIGNAL_ORDER):
        outputs[f"contrib_{name}"] = agg["contrib"][:, i]
    text = {}
    if with_reasons:
        text["reason"] = [
            reason_string(
                t,
                regime[t],
                agg["score"][t],
                agg["confidence"][t],
                agg["contrib"][t],
                p.min_contrib,
            )
            for t in range(len(candles))
        ]
    warm = max(r.warmup for r in base.values())
    return IndicatorResult(
        "CC",
        p.__dict__.copy(),
        outputs,
        warmup=warm,
        labels={"regime": REGIME_LABELS},
        text=text,
    )
