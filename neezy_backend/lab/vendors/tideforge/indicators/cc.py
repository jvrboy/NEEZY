"""Confluence Compass (CC) — the meta-indicator.

Concept
-------
CC combines EDI, VBO, FSCR, TDGZ, TIS, MDR and SRP into one signed
directional score with a confidence value, a regime label and a plain-language
reason string. Weights come from config/confluence_weights.json and are
regime-aware: trend regimes lean on FSCR/TIS, range regimes lean on EDI/TDGZ,
chop leans on VBO/MDR.

Directional contributions per indicator (each mapped to [-1, +1]):
  EDI  : stretch (positive stretch = bullish stretch, but exhaustion flips it)
  VBO  : (phase==exhale ? +1 : phase==inhale ? -1 : 0) * expansion_prob
  FSCR : consensus
  TDGZ : (pull_below - pull_above) — closer strong gravity below pulls up
  TIS  : (score/100) * sign(net move of window)
  MDR  : -decay * divergence (strong decay + divergence = bearish for longs)
  SRP  : -rhythm_anomaly * sign(expected_bias)  (anomaly vs learned rhythm)

Confidence = 0.5*mean(|contributions|) + 0.5*(share of ready indicators),
scaled by agreement (1 - disagreement share).

Reason string: lists top contributors, e.g.
  "bullish: FSCR +0.62, TIS +0.41; bearish: MDR -0.30; regime=clean_trend".
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

import numpy as np

from neezy_backend.lab.vendors.tideforge.core import nputil as nu
from neezy_backend.lab.vendors.tideforge.core.candles import CandleSeries
from neezy_backend.lab.vendors.tideforge.core.registry import Indicator, IndicatorOutput
from neezy_backend.lab.vendors.tideforge.indicators.edi import EDI
from neezy_backend.lab.vendors.tideforge.indicators.fscr import FSCR
from neezy_backend.lab.vendors.tideforge.indicators.mdr import MDR
from neezy_backend.lab.vendors.tideforge.indicators.srp import SRP
from neezy_backend.lab.vendors.tideforge.indicators.tdgz import TDGZ
from neezy_backend.lab.vendors.tideforge.indicators.tis import TIS
from neezy_backend.lab.vendors.tideforge.indicators.vbo import VBO

DEFAULT_WEIGHTS = {
    "clean_trend": {
        "FSCR": 1.5,
        "TIS": 1.3,
        "EDI": 0.7,
        "TDGZ": 0.6,
        "VBO": 0.5,
        "MDR": 0.9,
        "SRP": 0.5,
    },
    "dirty_trend": {
        "FSCR": 1.2,
        "TIS": 1.0,
        "EDI": 0.9,
        "TDGZ": 0.8,
        "VBO": 0.7,
        "MDR": 1.1,
        "SRP": 0.5,
    },
    "range": {
        "FSCR": 0.5,
        "TIS": 0.6,
        "EDI": 1.5,
        "TDGZ": 1.4,
        "VBO": 1.0,
        "MDR": 0.9,
        "SRP": 0.7,
    },
    "chop": {
        "FSCR": 0.6,
        "TIS": 0.7,
        "EDI": 1.2,
        "TDGZ": 1.0,
        "VBO": 1.4,
        "MDR": 1.3,
        "SRP": 0.6,
    },
}

REGIME_SOURCE = "TIS"  # TIS supplies the regime label


class CC(Indicator):
    NAME = "CC"
    PARAMS = {
        "weights_path": (
            0,
            0,
            0,
            "path to confluence_weights.json; 0 = built-in defaults",
        ),
        "confidence_floor": (0.35, 0.0, 1.0, "min confidence for a valid signal"),
    }

    def __init__(self, **overrides) -> None:
        super().__init__(**overrides)
        path = str(self.params.get("weights_path") or "")
        self.weights = DEFAULT_WEIGHTS
        if path and os.path.exists(path):
            with open(path) as fh:
                self.weights = json.load(fh).get("weights", DEFAULT_WEIGHTS)
        self.sub = {
            "EDI": EDI(),
            "VBO": VBO(),
            "FSCR": FSCR(),
            "TDGZ": TDGZ(),
            "TIS": TIS(),
            "MDR": MDR(),
            "SRP": SRP(),
        }
        self.warmup = max(s.warmup for s in self.sub.values())

    def _warmup(self) -> int:  # pragma: no cover - __init__ sets it
        return 0

    # ------------------------------------------------------------------ core
    @staticmethod
    def contributions(
        all_rows: Dict[str, Dict[int, IndicatorOutput]], epoch: int
    ) -> Dict[str, float]:
        contrib: Dict[str, float] = {}
        edi = all_rows["EDI"].get(epoch)
        if edi and edi.ready:
            stretch = edi.values.get("stretch") or 0.0
            exhaust = edi.values.get("exhaustion") or 0.0
            contrib["EDI"] = float(stretch * (1.0 - 0.6 * exhaust))
        vbo = all_rows["VBO"].get(epoch)
        if vbo and vbo.ready:
            ph = vbo.values.get("breath_phase") or 1.0
            ep = vbo.values.get("expansion_prob") or 0.0
            d = 1.0 if ph == 2 else (-1.0 if ph == 0 else 0.0)
            contrib["VBO"] = float(d * ep)
        fscr = all_rows["FSCR"].get(epoch)
        if fscr and fscr.ready:
            contrib["FSCR"] = float(fscr.values.get("consensus") or 0.0)
        tdgz = all_rows["TDGZ"].get(epoch)
        if tdgz and tdgz.ready:
            contrib["TDGZ"] = float(
                (tdgz.values.get("pull_below") or 0.0)
                - (tdgz.values.get("pull_above") or 0.0)
            )
        tis = all_rows["TIS"].get(epoch)
        if tis and tis.ready:
            score = (tis.values.get("score") or 0.0) / 100.0
            # TIS itself carries no direction; it gates conviction. Its
            # contribution is signed by FSCR's consensus when available.
            fscr = all_rows["FSCR"].get(epoch)
            direction = 0.0
            if fscr and fscr.ready:
                direction = float(np.sign(fscr.values.get("consensus") or 0.0))
            contrib["TIS"] = float(score * direction * 0.5)
        mdr = all_rows["MDR"].get(epoch)
        if mdr and mdr.ready:
            decay = mdr.values.get("decay") or 0.0
            div = mdr.values.get("divergence") or 0.0
            contrib["MDR"] = float(-max(decay, 0.0) * div)
        srp = all_rows["SRP"].get(epoch)
        if srp and srp.ready:
            anom = srp.values.get("rhythm_anomaly") or 0.0
            eb = srp.values.get("expected_bias") or 0.0
            contrib["SRP"] = float(-anom * np.sign(eb))
        return contrib

    def compute(self, series: CandleSeries) -> list[IndicatorOutput]:
        all_rows: Dict[str, Dict[int, IndicatorOutput]] = {}
        for name, ind in self.sub.items():
            all_rows[name] = {int(o.epoch): o for o in ind.compute(series)}

        out: list[IndicatorOutput] = []
        epoch_list = [int(e) for e in series.epochs]
        for idx, epoch in enumerate(epoch_list):
            contrib = self.contributions(all_rows, epoch)
            tis_row = all_rows["TIS"].get(epoch)
            regime = (tis_row.values.get("regime_str") if tis_row else None) or "chop"
            w = self.weights.get(regime, DEFAULT_WEIGHTS["chop"])
            ready_names = list(contrib.keys())
            if not ready_names or idx < self.warmup:
                out.append(
                    IndicatorOutput(
                        epoch=epoch,
                        indicator=self.NAME,
                        ready=False,
                        values={"regime_str": regime} if ready_names else {},
                    )
                )
                continue
            wsum = sum(w.get(k, 1.0) for k in ready_names) + nu.EPS
            signed = sum(w.get(k, 1.0) * contrib[k] for k in ready_names) / wsum
            score = float(np.tanh(signed))
            mean_abs = float(np.mean([abs(contrib[k]) for k in ready_names]))
            readiness = len(ready_names) / 7.0
            signs = [
                1 if contrib[k] > 0 else -1
                for k in ready_names
                if abs(contrib[k]) > 1e-9
            ]
            agree = abs(sum(signs)) / max(len(signs), 1) if signs else 0.0
            confidence = float(
                np.clip(0.5 * mean_abs + 0.5 * readiness, 0, 1) * (0.5 + 0.5 * agree)
            )
            valid = confidence >= self.params["confidence_floor"]
            bulls = sorted(
                ((k, v) for k, v in contrib.items() if v > 0.05), key=lambda x: -x[1]
            )
            bears = sorted(
                ((k, v) for k, v in contrib.items() if v < -0.05), key=lambda x: x[1]
            )
            reason = (
                f"bullish: " + ", ".join(f"{k} {v:+.2f}" for k, v in bulls[:3])
                if bulls
                else "no bullish push"
            )
            reason += "; " + (
                "bearish: " + ", ".join(f"{k} {v:+.2f}" for k, v in bears[:3])
                if bears
                else "no bearish push"
            )
            reason += f"; regime={regime}; confidence={confidence:.2f}"
            out.append(
                IndicatorOutput(
                    epoch=epoch,
                    indicator=self.NAME,
                    ready=bool(valid),
                    values={
                        "directional_score": score,
                        "confidence": confidence,
                        "regime_str": regime,
                    },
                    meta={
                        "reason": reason,
                        "contributions": {k: round(v, 4) for k, v in contrib.items()},
                    },
                )
            )
        return out
