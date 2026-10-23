"""BTOKEN KEYS: the NEEZY keyboard-accessibility layer.

Some users cannot press modifier or special keys: a broken CTRL, DEL, SPACE,
SHIFT, ESC, dash, or arrow key must never lock someone out of the CLI. This
module gives every such key a *typeable* stand-in and rewrites argv so the
whole CLI stays usable without dashes, spaces, or modifiers.

Three layers of support:

1. **Key tokens** - a registry (:data:`BTOKENS`) mapping ``bt:``-prefixed
   words to logical key events, e.g. ``bt:ctrl-c``, ``bt:enter``,
   ``bt:space``. The interactive menu accepts them as commands.
2. **Dashless argv** - :func:`normalize_argv` rewrites friendly forms into
   standard flags before argparse sees them:

   - ``timeframe=15m``      -> ``--timeframe 15m``
   - ``t=15m`` / ``n=300``  -> short aliases resolve to long flags
   - ``json=1``             -> ``--json`` (boolean flag)
   - with ``NEEZY_BTOKEN=1``: ``json`` alone -> ``--json`` and ``,`` works
     as an argument separator when SPACE is broken.

3. **Broken-key guidance** - :func:`stuck_key_help` explains, per broken
   key, exactly what to type instead.

Rewriting is conservative by default: ``name=value`` tokens only become
flags when ``name`` matches a real option of the active subcommand and the
token would not be swallowed by a free-text positional (a webhook title or
chat prompt must keep literal ``=``). Explicit btoken mode (env var or
``--btoken``) is more aggressive because the user asked for it.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass

SEP = "="
TOKEN_PREFIX = "bt:"
_SEPARATOR = ","  # stands in for SPACE in explicit btoken mode

_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """One logical key event produced by a btoken."""

    token: str
    key: str
    category: str
    action: str


# token -> (logical key, category, what it does)
_BTOKEN_TABLE: tuple[tuple[str, str, str, str], ...] = (
    ("bt:enter", "ENTER", "confirm", "submit the current prompt"),
    ("bt:return", "ENTER", "confirm", "submit the current prompt"),
    ("bt:space", "SPACE", "confirm", "accept the default / next prompt"),
    ("bt:tab", "TAB", "navigation", "move to the next field"),
    ("bt:shift-tab", "SHIFT+TAB", "navigation", "move to the previous field"),
    ("bt:esc", "ESC", "cancel", "dismiss or cancel the current panel"),
    ("bt:escape", "ESC", "cancel", "dismiss or cancel the current panel"),
    ("bt:del", "DEL", "editing", "clear the current input line"),
    ("bt:delete", "DEL", "editing", "clear the current input line"),
    ("bt:backspace", "BACKSPACE", "editing", "erase one character"),
    ("bt:ctrl-c", "CTRL+C", "cancel", "quit the app safely"),
    ("bt:ctrl-d", "CTRL+D", "cancel", "quit the app safely"),
    ("bt:ctrl-z", "CTRL+Z", "cancel", "suspend (type bt:quit instead)"),
    ("bt:quit", "CTRL+C", "cancel", "quit the app safely"),
    ("bt:up", "UP", "navigation", "previous history entry"),
    ("bt:down", "DOWN", "navigation", "next history entry"),
    ("bt:left", "LEFT", "navigation", "move the cursor left"),
    ("bt:right", "RIGHT", "navigation", "move the cursor right"),
    ("bt:home", "HOME", "editing", "jump to the start of the line"),
    ("bt:end", "END", "editing", "jump to the end of the line"),
    ("bt:pgup", "PAGEUP", "navigation", "scroll one page up"),
    ("bt:pgdn", "PAGEDOWN", "navigation", "scroll one page down"),
    ("bt:shift", "SHIFT", "modifier", "no-op; lowercase input is accepted"),
    ("bt:ctrl", "CTRL", "modifier", "no-op; use bt: prefixed commands"),
    ("bt:alt", "ALT", "modifier", "no-op; use bt: prefixed commands"),
)

BTOKENS: dict[str, KeyEvent] = {
    token: KeyEvent(token, key, category, action)
    for token, key, category, action in _BTOKEN_TABLE
}

# Keys a user might report as broken -> friendly guidance.
_STUCK_GUIDANCE: dict[str, tuple[str, ...]] = {
    "space": (
        "Set NEEZY_BTOKEN=1 once, then separate arguments with a comma:",
        "neezy-cli analyze,frxEURUSD,timeframe=15m",
        "The comma is only a separator in btoken mode; normal commands",
        "never need it.",
    ),
    "ctrl": (
        "Never needed: quit words work everywhere.",
        "In the menu type  quit  or  bt:quit  instead of CTRL+C.",
        "In one-shot commands the process ends on its own.",
    ),
    "shift": (
        "Everything is case-insensitive where it matters.",
        "Type symbols lowercase:  eurusd  resolves to frxEURUSD.",
        "Commands and flags accept lowercase only.",
    ),
    "dash": (
        "Use the equals form instead of dashes:",
        "neezy-cli analyze frxEURUSD timeframe=15m json",
        "Short names work too:  t=15m  n=300  ->  -t 15m  -n 300.",
    ),
    "del": (
        "In the menu, submit an empty line to restart the prompt.",
        "The token  bt:del  clears the current input.",
    ),
    "delete": (
        "In the menu, submit an empty line to restart the prompt.",
        "The token  bt:del  clears the current input.",
    ),
    "esc": (
        "The menu closes panels with  /close  or  bt:esc.",
        "One-shot commands never wait for ESC.",
    ),
    "enter": (
        "Menus need some submit key; if ENTER works for you it is the",
        "easiest. Otherwise everything is also available one-shot:",
        "neezy-cli scan   replaces the menu entirely.",
    ),
    "tab": (
        "No tab completion is required: every command has a full-word",
        "name and the menu lists all keys with  /",
    ),
    "arrows": (
        "Menus are linear: type the item key (for example  s  for scan)",
        "instead of arrowing through a list.",
    ),
    "arrow": (
        "Menus are linear: type the item key (for example  s  for scan)",
        "instead of arrowing through a list.",
    ),
}


def tokens_by_category() -> dict[str, list[KeyEvent]]:
    """All btokens grouped by category (for the ``btoken list`` command)."""
    grouped: dict[str, list[KeyEvent]] = {}
    for event in BTOKENS.values():
        grouped.setdefault(event.category, []).append(event)
    return grouped


def translate(text: str) -> list[KeyEvent]:
    """Translate a typed line of ``bt:`` tokens into key events.

    Unknown tokens are skipped; ``translate("bt:space bt:enter")`` returns
    the SPACE and ENTER events. Plain words are ignored so a whole sentence
    can be fed in safely.
    """
    events = []
    for word in text.split():
        token = word.lower()
        if not token.startswith(TOKEN_PREFIX):
            continue
        event = BTOKENS.get(token)
        if event is not None:
            events.append(event)
    return events


def stuck_key_help(key: str) -> list[str]:
    """Guidance lines for a broken key name (any case, with or without bt:)."""
    cleaned = key.strip().lower().removeprefix(TOKEN_PREFIX)
    if not cleaned:
        return ["Name a key: space, ctrl, shift, dash, del, esc, enter, arrows."]
    direct = _STUCK_GUIDANCE.get(cleaned)
    if direct is not None:
        return list(direct)
    for name, lines in _STUCK_GUIDANCE.items():
        if cleaned.startswith(name) or name.startswith(cleaned):
            return list(lines)
    return [
        f"No dedicated workaround for {cleaned!r}; these keys have one:",
        "space, ctrl, shift, dash, del, esc, enter, tab, arrows.",
    ]


# --------------------------------------------------------------------------
# Dashless argv rewriting
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OptionSpec:
    """One argparse option, dashless-accessible."""

    long: str  # "--timeframe"
    short: str | None  # "-t" if present
    takes_value: bool


@dataclass(frozen=True, slots=True)
class _PositionalSpec:
    """One argparse positional argument of a subcommand."""

    name: str  # "symbols"
    nargs: str | int | None
    # True when any text is accepted (a prompt, title, or message body).
    free_text: bool


@dataclass(frozen=True, slots=True)
class _CommandSpec:
    options: dict[str, _OptionSpec]  # key: option name without dashes
    positionals: list[_PositionalSpec]


def _option_key(name: str) -> str:
    """Canonical lookup key: strip dashes, unify underscores to hyphens."""
    return name.lstrip("-").replace("_", "-")


def _takes_value(action: argparse.Action) -> bool:
    if action.nargs == 0:  # store_true / store_false / count / const
        return False
    return True


def _is_free_text(action: argparse.Action) -> bool:
    if action.option_strings:
        return False
    if action.choices is not None or action.type is not None:
        return False
    # nargs='*' or '+' with a plain str annotation still accepts anything,
    # but lists of market names validate later, so treat only single slots
    # (nargs None) as protected free text.
    return action.nargs is None


def _collect(parser: argparse.ArgumentParser) -> dict[str, _CommandSpec]:
    """Walk a parser (and its subparsers) into plain specs.

    Returns a mapping keyed by subcommand path, e.g. "" (global),
    "scan", ("mt5", "order") joined as "mt5 order".
    """
    specs: dict[str, _CommandSpec] = {}

    def visit(p: argparse.ArgumentParser, path: str) -> None:
        options: dict[str, _OptionSpec] = {}
        positionals: list[_PositionalSpec] = []
        subparsers: dict[str, argparse.ArgumentParser] = {}
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                subparsers = dict(action.choices)
                continue
            if action.option_strings:
                if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
                    continue
                long = next(
                    (name for name in action.option_strings if name.startswith("--")),
                    action.option_strings[0],
                )
                short = next(
                    (
                        name
                        for name in action.option_strings
                        if not name.startswith("--")
                    ),
                    None,
                )
                spec = _OptionSpec(
                    long=long, short=short, takes_value=_takes_value(action)
                )
                for name in action.option_strings:
                    options[_option_key(name)] = spec
            else:
                positionals.append(
                    _PositionalSpec(
                        name=action.dest,
                        nargs=action.nargs,
                        free_text=_is_free_text(action),
                    )
                )
        specs[path] = _CommandSpec(options=options, positionals=positionals)
        for name, sub in subparsers.items():
            visit(sub, f"{path} {name}".strip())

    visit(parser, "")
    return specs


_PARSER_SPECS: dict[str, _CommandSpec] | None = None


def command_specs() -> dict[str, _CommandSpec]:
    """Lazily built parser map (cached; build_parser is not cheap)."""
    global _PARSER_SPECS
    if _PARSER_SPECS is None:
        from .cli.parser import build_parser

        _PARSER_SPECS = _collect(build_parser())
    return _PARSER_SPECS


def reset_parser_cache() -> None:
    """Test hook: forget the cached parser map."""
    global _PARSER_SPECS
    _PARSER_SPECS = None


def _split_pair(token: str) -> tuple[str, str] | None:
    if SEP not in token:
        return None
    name, _, value = token.partition(SEP)
    if not name or not value:
        return None
    return name.lower(), value


def _rewrite_pair_from(name: str, value: str, spec: _OptionSpec) -> list[str] | None:
    """``name=value`` -> flag tokens given the resolved option spec."""
    del name
    if spec.takes_value:
        return [spec.long, value]
    lowered = value.lower()
    if lowered in _TRUE_WORDS:
        return [spec.long]
    if lowered in _FALSE_WORDS:
        return []  # explicitly disabled: drop the flag
    return [spec.long, value]  # argparse will reject the stray value


class _PositionalCursor:
    """Tracks which positional slot the next plain token would fill."""

    def __init__(self, specs: list[_PositionalSpec]) -> None:
        self._specs = specs
        self._index = 0
        self._repeat = 0  # remaining repeats inside a multi-value positional

    def current(self) -> _PositionalSpec | None:
        if self._index >= len(self._specs):
            return None
        return self._specs[self._index]

    def consumes_free_text(self) -> bool:
        """True while the active positional accepts any literal text."""
        spec = self.current()
        return spec is not None and spec.free_text and self._repeat == 0

    def advance(self) -> None:
        spec = self.current()
        if spec is None:
            return
        nargs = spec.nargs
        if nargs is None:
            self._index += 1
            return
        if isinstance(nargs, int):
            self._repeat += 1
            if self._repeat >= nargs:
                self._index += 1
                self._repeat = 0
            return
        # '*' consumes everything; '+' behaves like '*' after the first.
        self._repeat = 1


def _resolve_path(argv: Sequence[str], specs: dict[str, _CommandSpec]) -> str:
    """Find the deepest matching subcommand path for this argv.

    Option tokens (and their values) are skipped so global flags before
    the command name, e.g. ``--btoken scan json``, still resolve to the
    ``scan`` spec.
    """
    path = ""
    for token in argv:
        if token.startswith("-") and token != "-":
            # Skip the option and, when it takes a value at this level,
            # the value that follows it.
            spec = specs.get(path)
            if spec is not None:
                option = spec.options.get(_option_key(token))
                if option is not None and option.takes_value:
                    continue  # value handled by the loop below
            continue
        candidate = f"{path} {token}".strip()
        if candidate in specs:
            path = candidate
            continue
        break
    return path


def normalize_argv(
    argv: Sequence[str],
    *,
    mode: str = "auto",
    env: dict[str, str] | None = None,
) -> tuple[list[str], bool]:
    """Rewrite argv into a dashless-friendly, argparse-ready list.

    ``mode``:
    - ``"auto"`` (default): enable full btoken rewriting when the env var
      ``NEEZY_BTOKEN`` is set or ``--btoken`` appears in argv; otherwise
      apply only the conservative ``name=value`` subset.
    - ``"full"``: full btoken mode (comma separators, bare flag words).
    - ``"safe"``: conservative subset only.

    Returns ``(rewritten_argv, full_mode_used)``. Tokens are never removed
    except explicit ``flag=false`` forms, so error messages stay honest.
    """
    raw = list(argv)
    values = os.environ if env is None else env
    if mode == "auto":
        full = bool(values.get("NEEZY_BTOKEN", "")) or "--btoken" in raw
    else:
        full = mode == "full"

    if full:
        # Comma stands in for SPACE: split every token on commas, but keep
        # the pieces only when they are non-empty (",,," is one empty word).
        expanded: list[str] = []
        for token in raw:
            expanded.extend(piece for piece in token.split(_SEPARATOR) if piece)
        raw = expanded

    specs = command_specs()
    path = _resolve_path(raw, specs)
    spec = specs.get(path)
    global_options = specs.get("").options if specs.get("") else {}
    local_options = spec.options if spec else {}

    def options_for(name: str) -> _OptionSpec | None:
        # Subcommand options win; global flags (--debug, --btoken) follow.
        return local_options.get(name) or global_options.get(name)

    cursor = _PositionalCursor(spec.positionals if spec else [])

    out: list[str] = []
    option_expects_value = False
    positional_active = False

    for token in raw:
        if option_expects_value:
            out.append(token)
            option_expects_value = False
            continue
        if token.startswith("-") and token != "-":
            key = _option_key(token)
            opt = options_for(key)
            if opt is not None and opt.takes_value:
                option_expects_value = True
            out.append(token)
            continue

        positional_active = cursor.consumes_free_text()
        pair = _split_pair(token) if not positional_active else None
        if pair is not None:
            name, value = pair
            spec_lookup = options_for(_option_key(name))
            rewritten = (
                _rewrite_pair_from(name, value, spec_lookup) if spec_lookup else None
            )
            if rewritten is not None:
                out.extend(rewritten)
                continue

        if full and not positional_active:
            bare_lookup = options_for(_option_key(token))
            if bare_lookup is not None and not bare_lookup.takes_value:
                out.append(bare_lookup.long)
                continue

        out.append(token)
        cursor.advance()

    return out, full


def btoken_enabled(env: dict[str, str] | None = None) -> bool:
    """Is accessibility-first btoken mode switched on?"""
    values = os.environ if env is None else env
    return bool(values.get("NEEZY_BTOKEN", ""))


def describe_mode(env: dict[str, str] | None = None) -> str:
    return (
        "full (NEEZY_BTOKEN=1): comma separators and bare flag words enabled"
        if btoken_enabled(env)
        else "standard: name=value flags accepted; set NEEZY_BTOKEN=1 for more"
    )
