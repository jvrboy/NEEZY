"""``neezy-cli btoken``: inspect and test the keyboard-accessibility layer."""

from __future__ import annotations

from typing import TextIO

from ..btoken import (
    BTOKENS,
    btoken_enabled,
    describe_mode,
    normalize_argv,
    stuck_key_help,
    tokens_by_category,
    translate,
)
from ..ui_style import fit_table
from .common import _emit


def cmd_btoken(args, fetch, out: TextIO) -> int:
    del fetch
    action = getattr(args, "action", "list")
    if action == "list":
        return _list(out, args.json)
    if action == "translate":
        return _translate(out, args.text, args.json)
    if action == "stuck":
        return _stuck(out, args.key)
    if action == "rewrite":
        return _rewrite(out, args.tokens, args.json)
    raise ValueError(f"unknown btoken action {action!r}")


def _list(out: TextIO, as_json: bool) -> int:
    if as_json:
        _emit(
            out,
            {
                "mode": describe_mode(),
                "enabled": btoken_enabled(),
                "tokens": [
                    {
                        "token": event.token,
                        "key": event.key,
                        "category": event.category,
                        "action": event.action,
                    }
                    for event in BTOKENS.values()
                ],
            },
        )
        return 0
    out.write("BTOKEN KEYS - typeable stand-ins for broken keys\n")
    out.write(f"Mode: {describe_mode()}\n\n")
    grouped = tokens_by_category()
    for category in sorted(grouped):
        out.write(f"{category}:\n")
        rows = [(event.token, event.key, event.action) for event in grouped[category]]
        for line in fit_table(("token", "key", "what it does"), rows, width=72):
            out.write("  " + line + "\n")
        out.write("\n")
    out.write(
        "Menus accept these tokens directly. One-shot commands accept\n"
        "name=value flags without dashes, e.g.  neezy-cli scan timeframe=15m\n"
    )
    return 0


def _translate(out: TextIO, text: str, as_json: bool) -> int:
    events = translate(text)
    if not events:
        out.write("No btokens found. Prefix tokens with bt: e.g. bt:enter\n")
        return 1
    if as_json:
        _emit(
            out,
            [
                {
                    "token": event.token,
                    "key": event.key,
                    "category": event.category,
                    "action": event.action,
                }
                for event in events
            ],
        )
        return 0
    for event in events:
        out.write(f"{event.token} -> {event.key} ({event.category}): {event.action}\n")
    return 0


def _stuck(out: TextIO, key: str) -> int:
    lines = stuck_key_help(key)
    for line in lines:
        out.write(line + "\n")
    return 0


def _rewrite(out: TextIO, tokens: list[str], as_json: bool) -> int:
    rewritten, full = normalize_argv(tokens)
    if as_json:
        _emit(
            out,
            {"input": tokens, "rewritten": rewritten, "full_mode": full},
        )
        return 0
    out.write("input:    " + " ".join(tokens) + "\n")
    out.write("rewritten:" + " ".join(rewritten) + "\n")
    out.write(f"mode:     {'full btoken' if full else 'standard'}\n")
    return 0
