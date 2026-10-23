"""``neezy-cli bots`` and ``neezy-cli agents``: the automation dashboard."""

from __future__ import annotations

from typing import TextIO

from ..agents import AgentTeam, TeamContext
from ..bots import BotContext, BotManager
from ..ui_style import state_dot
from .common import _emit, _symbol


def cmd_bots(args, fetch, out: TextIO) -> int:
    action = getattr(args, "action", "list")
    manager = BotManager()
    if action == "list":
        return _bots_list(manager, out, args.json)
    if action == "status":
        return _bots_status(manager, out, args.json)
    if action == "run":
        return _bots_run(manager, args, fetch, out)
    raise ValueError(f"unknown bots action {action!r}")


def _bots_list(manager: BotManager, out: TextIO, as_json: bool) -> int:
    status = manager.status()
    if as_json:
        _emit(out, status)
        return 0
    out.write("NEEZY bot roster (read-only, tick-driven, educational):\n\n")
    for bot in status["bots"]:
        marker = state_dot(bot["state"])
        out.write(f"  {marker} {bot['id']:<11} {bot['role']:<12} {bot['name']}\n")
        out.write(f"      {bot['description']}\n")
    out.write(
        "\nRun:  neezy-cli bots run bot=scanner ticks=2\n"
        "      (same, dashless: see 'neezy-cli btoken stuck dash')\n"
    )
    return 0


def _bots_status(manager: BotManager, out: TextIO, as_json: bool) -> int:
    status = manager.status()
    if as_json:
        _emit(out, status)
        return 0
    out.write(
        f"Bots: {status['running']} running of {status['total']} registered, "
        f"{status['decisions_logged']} decisions logged (fresh instance)\n"
    )
    for bot in status["bots"]:
        marker = state_dot(bot["state"])
        last = bot["last_decision"]
        out.write(
            f"  {marker} {bot['id']:<11} state={bot['state']:<8} ticks={bot['ticks']}\n"
        )
        if last:
            out.write(f"      last: [{last['action']}] {last['detail']}\n")
    return 0


def _bots_run(manager: BotManager, args, fetch, out: TextIO) -> int:
    only = args.bot
    if only is not None and manager.get(only) is None:
        raise ValueError(f"unknown bot {only!r}; run 'neezy-cli bots list'")
    ticks = max(1, min(10, args.ticks))
    if only is None:
        manager.start_all()
    else:
        manager.start(only)
    context = BotContext(fetch=fetch, timeframe=args.timeframe)
    decisions = manager.run_ticks(ticks, context=context, only=only)
    if args.json:
        _emit(
            out,
            {
                "ticks": ticks,
                "bot": only or "all",
                "decisions": [
                    {
                        "bot": decision.bot_id,
                        "action": decision.action,
                        "detail": decision.detail,
                        "data": decision.data,
                    }
                    for decision in decisions
                ],
            },
        )
        return 0
    if not decisions:
        out.write("No bot produced a decision in this run.\n")
        return 1
    for decision in decisions:
        marker = state_dot("error" if decision.action == "error" else "running")
        out.write(
            f"  {marker} [{decision.bot_id}] {decision.action}: {decision.detail}\n"
        )
    out.write("\nBots are educational observers: nothing was sent anywhere.\n")
    return 0


def cmd_agents(args, fetch, out: TextIO) -> int:
    action = getattr(args, "action", "list")
    team = AgentTeam()
    if action == "list":
        if args.json:
            _emit(out, team.roster())
            return 0
        out.write("NEEZY agent team (deterministic, offline-capable):\n\n")
        for agent in team.roster():
            out.write(
                f"  [{agent['id']:<9}] {agent['role']:<9} {agent['description']}\n"
            )
        out.write("\nRun:  neezy-cli agents run goal=review EURUSD and GOLD\n")
        return 0
    if action == "run":
        goal = (args.goal or "").strip()
        if not goal:
            raise ValueError("agents run needs a goal: goal=review EURUSD momentum")
        context = TeamContext(
            goal=goal,
            fetch=fetch,
            timeframe=args.timeframe,
        )
        if args.symbol:
            context.symbols = tuple(_symbol(name) for name in args.symbol)
        result = team.run(context)
        if args.json:
            _emit(out, result)
            return 0
        out.write(result["report"] + "\n")
        return 0
    raise ValueError(f"unknown agents action {action!r}")
