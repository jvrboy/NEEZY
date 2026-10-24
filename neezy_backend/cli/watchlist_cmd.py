"""Watchlist import/export CLI (roadmap #94)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from ..config import AppSettings
from ..markets import display_name, watchlist
from ..storage import SettingsStore
from ..watchlists import export_watchlist
from ..watchlists import import_watchlist as _import_wl
from .common import _emit, _table


def _current_symbols(settings: AppSettings | None = None) -> list[str]:
    s = settings or SettingsStore().load()
    wl = watchlist(s.watchlist_extra)
    return sorted(wl.keys())


def cmd_watchlist(args: Any, _fetch: Any, out: TextIO) -> int:
    action = getattr(args, "action", None)
    if action == "show":
        symbols = _current_symbols()
        if getattr(args, "json", False):
            _emit(out, {"symbols": symbols, "count": len(symbols)})
        else:
            rows = [(sym, display_name(sym)) for sym in symbols]
            _table(out, ["symbol", "display"], rows)
        return 0
    if action == "export":
        dest = Path(args.file)
        symbols = _current_symbols()
        doc_path = export_watchlist(dest, symbols=symbols, meta={"source": "cli"})
        if getattr(args, "json", False):
            _emit(
                out,
                {"exported": str(doc_path), "count": len(symbols), "symbols": symbols},
            )
        else:
            out.write(f"Exported {len(symbols)} symbols to {doc_path}\n")
        return 0
    if action == "import":
        src = Path(args.file)
        doc = _import_wl(src)
        store = SettingsStore()
        settings = store.load()
        new_extra = ",".join(doc["symbols"])
        updated = settings.updated(watchlist_extra=new_extra)
        store.save(updated)
        if getattr(args, "json", False):
            _emit(
                out,
                {"imported": doc["symbols"], "count": doc["count"], "source": str(src)},
            )
        else:
            out.write(f"Imported {doc['count']} symbols from {src}\n")
        return 0
    raise ValueError(f"Unknown watchlist action {action!r}")
