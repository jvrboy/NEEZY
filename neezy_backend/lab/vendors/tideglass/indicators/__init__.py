"""Indicator registry and backend dispatch.

``backend="auto"`` uses the compiled C++ core (``tideglass._core``) when it is
importable and falls back to the pure Python/NumPy reference otherwise. Both
backends return the same :class:`~tideglass.types.IndicatorResult` layout and
are verified against each other by ``tests/test_backend_parity.py``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import fields
from typing import Any, Callable, Dict, Mapping, Optional

import numpy as np

from ..config import SuiteConfig, load_config
from ..types import Candles, IndicatorResult
from . import cc as _cc
from .cc import CCParams, compute_cc
from .edi import EDIParams, compute_edi
from .fscr import FSCRParams, compute_fscr
from .mdr import MDRParams, RISK_LABELS, compute_mdr
from .srp import SESSION_LABELS, SRPParams, compute_srp
from .tdgz import TDGZParams, compute_tdgz
from .tis import REGIME_LABELS as TIS_LABELS, TISParams, compute_tis
from .vbo import PHASE_LABELS, VBOParams, compute_vbo

log = logging.getLogger(__name__)

BASE_ORDER = ("EDI", "VBO", "FSCR", "TDGZ", "TIS", "MDR", "SRP")

INDICATORS: Dict[str, tuple[type, Callable[..., IndicatorResult]]] = {
    "EDI": (EDIParams, compute_edi),
    "VBO": (VBOParams, compute_vbo),
    "FSCR": (FSCRParams, compute_fscr),
    "TDGZ": (TDGZParams, compute_tdgz),
    "TIS": (TISParams, compute_tis),
    "MDR": (MDRParams, compute_mdr),
    "SRP": (SRPParams, compute_srp),
}

_LABELS = {
    "VBO": {"phase": PHASE_LABELS},
    "TIS": {"regime": TIS_LABELS},
    "MDR": {"risk": RISK_LABELS},
    "SRP": {"session": SESSION_LABELS},
}

_WARMUP = {
    "EDI": lambda p: max(p.eq_len, p.ru_len - 1) + p.z_len - 1,
    "VBO": lambda p: p.long,
    "FSCR": lambda p: max(max(p.scales), p.ru_len) - 1,
    "TDGZ": lambda p: max(p.ru_len - 1, p.min_bars - 1),
    "TIS": lambda p: max(p.length, p.ru_len - 1),
    "MDR": lambda p: p.ru_len - 1 + 2 * p.roc_len + p.hl_len - 1,
    "SRP": lambda p: 0,
}

try:  # pragma: no cover - depends on the build environment
    from .. import _core  # type: ignore

    _HAVE_CORE = True
except ImportError:  # pragma: no cover
    _core = None
    _HAVE_CORE = False


def backend_name(requested: str = "auto") -> str:
    """Resolve ``auto``/``python``/``cpp`` to the backend that will actually run."""
    env = os.environ.get("TIDEGLASS_BACKEND")
    req = env or requested
    if req == "python":
        return "python"
    if req == "cpp":
        if not _HAVE_CORE:
            raise RuntimeError(
                "C++ backend requested but tideglass._core is not compiled. Run `pip install .`."
            )
        return "cpp"
    return "cpp" if _HAVE_CORE else "python"


def make_params(
    name: str,
    params: Optional[Mapping[str, Any]] = None,
    config: Optional[SuiteConfig] = None,
):
    """Build a validated params dataclass for ``name`` from config defaults + overrides."""
    cfg = config or load_config()
    merged = cfg.validate_params(name, params or {})
    cls = CCParams if name == "CC" else INDICATORS[name][0]
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in merged.items() if k in names})


def _cpp_compute(name: str, candles: Candles, p) -> IndicatorResult:
    pdict = {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.__dict__.items()}
    outs = _core.compute(
        name,
        candles.epoch,
        candles.open,
        candles.high,
        candles.low,
        candles.close,
        candles.ticks,
        pdict,
    )
    outs = {k: np.asarray(v, dtype=np.float64) for k, v in outs.items()}
    params = dict(pdict)
    return IndicatorResult(
        name,
        params,
        outs,
        warmup=_WARMUP[name](p),
        backend="cpp",
        labels=_LABELS.get(name, {}),
    )


def compute(
    name: str,
    candles: Candles,
    params: Optional[Mapping[str, Any]] = None,
    backend: str = "auto",
    config: Optional[SuiteConfig] = None,
) -> IndicatorResult:
    """Compute one base indicator (EDI, VBO, FSCR, TDGZ, TIS, MDR, SRP)."""
    if name not in INDICATORS:
        raise KeyError(
            f"Unknown indicator {name!r}; choose from {list(INDICATORS)} (CC via compute_all)"
        )
    p = make_params(name, params, config)
    if backend_name(backend) == "cpp":
        return _cpp_compute(name, candles, p)
    res = INDICATORS[name][1](candles, p)
    res.params = {
        k: (list(v) if isinstance(v, tuple) else v) for k, v in p.__dict__.items()
    }
    return res


def compute_cc_from(
    candles: Candles,
    base: Mapping[str, IndicatorResult],
    params: Optional[Mapping[str, Any]] = None,
    backend: str = "auto",
    config: Optional[SuiteConfig] = None,
    weights: Optional[Mapping[str, Any]] = None,
    with_reasons: bool = True,
) -> IndicatorResult:
    """Confluence Compass on top of already computed base results."""
    cfg = config or load_config()
    p = make_params("CC", params, cfg)
    wdoc = weights or cfg.weights
    if backend_name(backend) != "cpp":
        return compute_cc(candles, base, wdoc, p, with_reasons)
    w, boost = _cc.weight_matrix(wdoc)
    sig = _cc.extract_signals(base)
    regime = _cc.regime_codes(base["TIS"]["regime"], base["VBO"]["phase"])
    agg = _core.cc_aggregate(
        np.ascontiguousarray(sig),
        regime,
        base["VBO"]["expansion_prob"],
        base["SRP"]["anomaly_flag"],
        np.ascontiguousarray(w),
        boost,
        p.strength_ref,
        p.srp_penalty,
    )
    contrib = np.asarray(agg["contrib"], dtype=np.float64)
    outputs = {
        "score": np.asarray(agg["score"]),
        "confidence": np.asarray(agg["confidence"]),
        "regime": regime,
        "agreement": np.asarray(agg["agreement"]),
    }
    for i, n in enumerate(_cc.SIGNAL_ORDER):
        outputs[f"contrib_{n}"] = contrib[:, i]
    text = {}
    if with_reasons:
        text["reason"] = [
            _cc.reason_string(
                t,
                regime[t],
                outputs["score"][t],
                outputs["confidence"][t],
                contrib[t],
                p.min_contrib,
            )
            for t in range(len(candles))
        ]
    return IndicatorResult(
        "CC",
        p.__dict__.copy(),
        outputs,
        warmup=max(r.warmup for r in base.values()),
        backend="cpp",
        labels={"regime": _cc.REGIME_LABELS},
        text=text,
    )


def compute_all(
    candles: Candles,
    params: Optional[Mapping[str, Mapping[str, Any]]] = None,
    backend: str = "auto",
    config: Optional[SuiteConfig] = None,
    weights: Optional[Mapping[str, Any]] = None,
    with_reasons: bool = True,
) -> Dict[str, IndicatorResult]:
    """Compute all 7 base indicators plus the Confluence Compass."""
    cfg = config or load_config()
    params = params or {}
    base = {
        name: compute(name, candles, params.get(name), backend, cfg)
        for name in BASE_ORDER
    }
    base["CC"] = compute_cc_from(
        candles, base, params.get("CC"), backend, cfg, weights, with_reasons
    )
    return base


__all__ = [
    "INDICATORS",
    "BASE_ORDER",
    "compute",
    "compute_all",
    "compute_cc_from",
    "backend_name",
    "make_params",
]
