#!/usr/bin/env python3
"""Compatibility launcher for the NEEZY desktop app (roadmap #26).

Prefer ``python -m neezy_app`` or the installed ``neezy`` command.
This shim stays for older docs/bookmarks and now emits a deprecation
warning so new code migrates. The warning is silent by default under
``-W ignore`` but visible with ``python -W default`` — standard library
behaviour for DeprecationWarning.
"""

import warnings

from neezy_app.launcher import main

if __name__ == "__main__":
    warnings.warn(
        "forex_signals.py is deprecated; use `neezy` or `python -m neezy_app`",
        DeprecationWarning,
        stacklevel=2,
    )
    main()
