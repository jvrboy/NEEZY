"""CLI subcommands for inspecting, editing, diffing, and profiling AppSettings."""

from __future__ import annotations

import dataclasses
from typing import Any, TextIO

from ..config import SETTINGS_PROFILES, AppSettings
from ..storage import SettingsStore, sanitize_path
from .common import _emit, _table

_DEFAULT_SETTINGS = AppSettings()
_FIELD_MAP = {f.name: f for f in dataclasses.fields(AppSettings)}


def _parse_field_value(name: str, raw: str) -> Any:
    if name not in _FIELD_MAP:
        raise ValueError(f"Unknown setting: {name!r}")
    default_val = getattr(_DEFAULT_SETTINGS, name)
    if isinstance(default_val, bool):
        low = raw.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{name} expects a boolean (true/false), got {raw!r}")
    if isinstance(default_val, int):
        return int(raw)
    if isinstance(default_val, float):
        return float(raw)
    return str(raw)


def cmd_config(args: Any, _fetch: Any, out: TextIO) -> int:
    store = SettingsStore()
    current = store.load()
    action = args.action

    if action == "list":
        needle = (args.filter or "").strip().lower()
        cur_dict = current.to_dict()
        def_dict = _DEFAULT_SETTINGS.to_dict()
        items = [
            {
                "name": k,
                "value": cur_dict[k],
                "default": def_dict[k],
                "modified": cur_dict[k] != def_dict[k],
            }
            for k in cur_dict
            if not needle or needle in k.lower()
        ]
        if args.json:
            _emit(out, {"count": len(items), "settings": items})
            return 0
        rows = [
            [
                "*" if item["modified"] else " ",
                item["name"],
                repr(item["value"]),
                repr(item["default"]),
            ]
            for item in items
        ]
        out.write(_table(["M", "SETTING", "VALUE", "DEFAULT"], rows) + "\n")
        return 0

    if action == "get":
        name = args.key
        if name not in _FIELD_MAP:
            raise ValueError(f"Unknown setting: {name!r}")
        payload = {
            "name": name,
            "value": getattr(current, name),
            "default": getattr(_DEFAULT_SETTINGS, name),
        }
        if args.json:
            _emit(out, payload)
            return 0
        out.write(f"{name} = {payload['value']!r} (default {payload['default']!r})\n")
        return 0

    if action == "set":
        name = args.key
        parsed = _parse_field_value(name, args.value)
        updated = current.updated(**{name: parsed})
        store.save(updated)
        payload = {"name": name, "value": getattr(updated, name), "saved": True}
        if args.json:
            _emit(out, payload)
            return 0
        out.write(f"Saved {name} = {payload['value']!r}\n")
        return 0

    if action == "diff":
        cur_dict = current.to_dict()
        def_dict = _DEFAULT_SETTINGS.to_dict()
        changes = [
            {"name": k, "value": cur_dict[k], "default": def_dict[k]}
            for k in cur_dict
            if cur_dict[k] != def_dict[k]
        ]
        if args.json:
            _emit(out, {"count": len(changes), "changes": changes})
            return 0
        if not changes:
            out.write("All settings match factory defaults.\n")
            return 0
        rows = [[c["name"], repr(c["value"]), repr(c["default"])] for c in changes]
        out.write(_table(["SETTING", "CURRENT", "DEFAULT"], rows) + "\n")
        return 0

    if action == "profiles":
        if args.json:
            _emit(out, {"profiles": SETTINGS_PROFILES})
            return 0
        rows = [
            [
                name,
                ", ".join(f"{k}={v!r}" for k, v in overrides.items())
                or "factory defaults",
            ]
            for name, overrides in SETTINGS_PROFILES.items()
        ]
        out.write(_table(["PROFILE", "OVERRIDES"], rows) + "\n")
        return 0

    if action == "profile":
        updated = current.apply_profile(args.name)
        store.save(updated)
        payload = {"profile": args.name, "saved": True}
        if args.json:
            _emit(out, payload)
            return 0
        out.write(f"Applied preset profile '{args.name}'.\n")
        return 0

    if action == "reset":
        store.save(AppSettings())
        if args.json:
            _emit(out, {"reset": True})
            return 0
        out.write("Settings reset to factory defaults.\n")
        return 0

    if action == "export":
        dest = sanitize_path(args.path)
        store.export_json(dest)
        if args.json:
            _emit(out, {"exported": str(dest)})
            return 0
        out.write(f"Exported settings to {dest}\n")
        return 0

    if action == "import":
        src = sanitize_path(args.path)
        loaded = store.import_json(src)
        if args.json:
            _emit(out, {"imported": str(src), "fields": len(loaded.to_dict())})
            return 0
        out.write(f"Imported settings from {src}\n")
        return 0

    raise ValueError(f"Unknown config action: {action!r}")
