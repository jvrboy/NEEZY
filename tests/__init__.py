"""NEEZY test suite.

Roadmap #63: ResourceWarnings are promoted to errors during the test run so
unclosed stores, databases, and files fail CI instead of leaking silently.
(The suite currently opens and closes every handle explicitly; this gate
keeps it that way.) If a test legitimately needs to leak a resource, wrap
it with ``warnings.catch_warnings()`` and restore ``simplefilter``.
"""

import warnings

# Uninitialized/skipped modules do not need the filter; applying it at import
# time covers every discovery mode (unittest discover, IDE, CI matrix).
warnings.simplefilter("error", ResourceWarning)
