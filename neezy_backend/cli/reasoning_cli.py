"""Reasoning & thinking CLI (Batch 8)."""

from __future__ import annotations

import json
from typing import Any

from ..config import AppSettings
from ..reasoning import ReasoningEngine


def cmd_reasoning(args: Any) -> int:
    q = getattr(args, "query", "") or getattr(args, "text", "") or ""
    if not q:
        print("Provide a query -- e.g. reasoning think 'explain EURUSD momentum'")
        return 2
    # Build settings override if provided
    s = AppSettings()
    if getattr(args, "strategy_opt", None):
        try:
            s = s.updated(reasoning_strategy=args.strategy_opt)
        except Exception:
            pass
    if getattr(args, "mode", None):
        try:
            s = s.updated(thinking_mode=args.mode)  # type: ignore[arg-type]
        except Exception:
            pass
    if getattr(args, "depth", None):
        try:
            s = s.updated(reasoning_depth=int(args.depth))
        except Exception:
            pass
    engine = ReasoningEngine(s)

    action = getattr(args, "action", "think")
    if action == "think":
        trace = engine.think(q, context=getattr(args, "context", "") or "")
    elif action == "cot":
        trace = engine.chain_of_thought(q, depth=int(getattr(args, "depth", 3) or 3))
    elif action == "tot":
        trace = engine.tree_of_thought(q)
    elif action == "react":
        trace = engine.react(q)
    elif action == "reflect":
        trace = engine.reflective(q)
    elif action == "debate":
        trace = engine.debate(q)
    else:
        trace = engine.think(q)

    if getattr(args, "json", False):
        print(json.dumps(trace.to_dict(), indent=2))
    else:
        print(trace.summary())
        for step in trace.steps:
            print(f"  {step.index}: [{step.kind}] {step.content} (c={step.confidence})")
        print(f"Answer: {trace.final_answer}")
    return 0
