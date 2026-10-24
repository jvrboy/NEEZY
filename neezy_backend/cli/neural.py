"""Advanced neural CLI: train advanced architectures, list prompts, eval holdout."""

from __future__ import annotations

import json
from typing import Any

from ..brain_advanced import (
    ALL_ARCHITECTURES,
    ARCHITECTURE_INFO,
    train_advanced,
)
from ..prompts import PROMPT_REGISTRY, get_prompt


def cmd_neural(args: Any) -> int:
    action = getattr(args, "action", None)
    if action == "architectures":
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {k: ARCHITECTURE_INFO.get(k, {}) for k in ALL_ARCHITECTURES},
                    indent=2,
                )
            )
        else:
            for arch in ALL_ARCHITECTURES:
                info = ARCHITECTURE_INFO.get(arch, {})
                print(f"{arch}: {info.get('note', '')}")
        return 0
    if action == "prompts":
        if getattr(args, "prompt_id", None):
            p = get_prompt(args.prompt_id)
            if p is None:
                print(f"unknown prompt {args.prompt_id!r}")
                return 1
            print(
                json.dumps(
                    {
                        "id": p.id,
                        "version": p.version,
                        "role": p.role,
                        "template": p.template,
                        "variables": list(p.variables),
                    },
                    indent=2,
                )
            )
        else:
            if getattr(args, "json", False):
                print(json.dumps(PROMPT_REGISTRY, indent=2))
            else:
                for pid in sorted(PROMPT_REGISTRY):
                    print(pid)
        return 0
    if action == "train-advanced":
        # Demo: trains on synthetic candles if no file provided
        candles = [[i, 100.0, 101.0, 99.0, 100.5] for i in range(500)]
        run = train_advanced(
            candles,
            architecture=getattr(args, "architecture", "neezy_mlp_deep_v2"),
            symbol=getattr(args, "symbol", "R_100"),
            timeframe=getattr(args, "timeframe", "5m"),
        )
        if getattr(args, "json", False):
            from ..brain_advanced import training_manifest

            print(json.dumps(training_manifest(run), indent=2))
        else:
            msg = (
                f"trained {run.architecture} epochs {run.epochs_ran} "
                f"early_stopped={run.early_stopped} hash={run.artifact_hash}"
            )
            print(msg)
        return 0
    print("usage: neural <architectures|prompts|train-advanced>")
    return 1
