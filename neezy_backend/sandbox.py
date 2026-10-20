"""Path sandboxing helpers for any feature that touches local files.

Every agent tool, export, or import that accepts a user- or model-supplied path
should resolve it through :func:`resolve_within` first.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

PathLike = str | os.PathLike[str]


class PathNotAllowedError(ValueError):
    """Raised when a path resolves outside every allowed root."""


def resolve_within(root: PathLike, candidate: PathLike) -> Path:
    """Resolve ``candidate`` and require it to live inside ``root``.

    Relative candidates are interpreted relative to ``root``. Symlinks and
    ``..`` segments are resolved first, so they cannot be used to escape.
    """
    if "\0" in str(candidate):
        raise PathNotAllowedError("Path contains a null byte")
    base = Path(root).resolve()
    raw = Path(candidate)
    target = (raw if raw.is_absolute() else base / raw).resolve()
    if target != base and base not in target.parents:
        raise PathNotAllowedError(f"{candidate!s} is outside {base}")
    return target


def resolve_within_any(roots: Iterable[PathLike], candidate: PathLike) -> Path:
    """Like :func:`resolve_within` but accepts any one of several roots."""
    for root in roots:
        try:
            return resolve_within(root, candidate)
        except PathNotAllowedError:
            continue
    raise PathNotAllowedError(f"{candidate!s} is outside every allowed folder")
