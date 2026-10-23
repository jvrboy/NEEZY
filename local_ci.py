#!/usr/bin/env python3
"""Local CI runner for NEEZY.

Runs syntax compilation, mandatory Ruff lint/format gates, and unittest.

`--full` also lints the kaggle notebook and packaging helpers, matching the
widest local check (`ruff check .`) so a green local run is never narrower
than the remote gate plus the repo-wide expectations (roadmap #85: parity
with GitHub CI, and then some).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# The GitHub "Python CI" targets plus the new cloud/packaging helpers.
CI_LINT_TARGETS = [
    "neezy_app",
    "neezy_backend",
    "tests",
    "forex_signals.py",
    "main.py",
    "scripts",
]
# The whole-tree check used by the release gate of this script.
FULL_LINT_TARGETS = ["."]


def run_cmd(cmd, cwd=ROOT):
    print(f"\n==> Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL)
    return res.returncode


def main() -> None:
    full = "--full" in sys.argv
    print("=== NEEZY LOCAL CI CHECK ===" + (" (full)" if full else ""))
    errors = 0

    # 1. Compile all Python files
    print("\n1. Checking Python Syntax Compilation...")
    ret = run_cmd(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "neezy_app",
            "neezy_backend",
            "tests",
            "forex_signals.py",
        ]
    )
    if ret != 0:
        print("ERROR: Syntax compilation failed.")
        errors += 1
    else:
        print("PASS: Syntax compilation OK.")

    # 2. Lint and formatting are mandatory gates. --full widens to the entire
    #    tree (kaggle notebook, packaging).
    print("\n2. Running Linter and Formatting Checks...")
    targets = FULL_LINT_TARGETS if full else CI_LINT_TARGETS
    for options in (["check"], ["format", "--check"]):
        ret = run_cmd([sys.executable, "-m", "ruff", *options, *targets])
        if ret != 0:
            print("ERROR: Ruff gate failed; install dev dependencies if missing.")
            errors += 1

    # 3. Use the standard-library test runner; no undeclared pytest dependency.
    #    Every child runs with stdin=/dev/null (see run_cmd) so interactive
    #    menu tests read EOF and quit cleanly even under a headless terminal.
    print("\n3. Running Unittest Suite...")
    ret = run_cmd(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-v",
        ]
    )
    if ret != 0:
        print("ERROR: Test suite failed.")
        errors += 1
    else:
        print("PASS: All tests passed successfully.")

    if errors > 0:
        print(f"\nFAIL: Local CI failed with {errors} error(s).")
        sys.exit(1)

    print("\nPASS: Local CI completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
