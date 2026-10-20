#!/usr/bin/env python3
"""Compatibility launcher for the NEEZY desktop app.

Prefer ``python -m neezy_app`` or the installed ``neezy`` command.
"""

from neezy_app.launcher import main

if __name__ == "__main__":
    main()
