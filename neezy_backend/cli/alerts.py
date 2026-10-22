"""Alert-rule CLI commands (local rule store, evaluated on new analyses)."""

from __future__ import annotations

from dataclasses import asdict

from ..alerts import AlertRule, AlertRuleStore
from .common import _emit, _symbol, _table


def cmd_alerts(args, fetch, out) -> int:
    store = AlertRuleStore()
    rules = store.load()
    if args.action == "add":
        rule = AlertRule(
            symbol="*" if args.symbol == "*" else _symbol(args.symbol),
            metric=args.metric,
            operator=args.operator,
            value=args.value,
            note=args.note or "",
        )
        store.save([*rules, rule])
        out.write(f"Added {rule.rule_id}: {rule.describe()}\n")
        return 0
    if args.action == "remove":
        remaining = [rule for rule in rules if rule.rule_id != args.rule_id]
        if len(remaining) == len(rules):
            out.write(f"No rule with id {args.rule_id}\n")
            return 1
        store.save(remaining)
        out.write(f"Removed {args.rule_id}\n")
        return 0
    if args.json:
        _emit(out, [asdict(rule) for rule in rules])
        return 0
    _table(
        out,
        ["ID", "RULE", "ENABLED", "NOTE"],
        [
            (r.rule_id, r.describe(), "yes" if r.enabled else "no", r.note)
            for r in rules
        ],
    )
    return 0
