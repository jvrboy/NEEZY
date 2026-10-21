#!/usr/bin/env python3
"""Local CI runner for NEEZY.

Runs syntax compilation, mandatory Ruff lint/format gates, and unittest.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def run_cmd(cmd, cwd=ROOT):
    print(f"\n==> Executing: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    return res.returncode


def main():
    print("=== NEEZY LOCAL CI CHECK ===")
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

    # 2. Match the GitHub workflow: lint and formatting are mandatory gates.
    print("\n2. Running Linter and Formatting Checks...")
    targets = ["neezy_app", "neezy_backend", "tests", "forex_signals.py", "local_ci.py"]
    for options in (["check"], ["format", "--check"]):
        ret = run_cmd([sys.executable, "-m", "ruff", *options, *targets])
        if ret != 0:
            print("ERROR: Ruff gate failed; install dev dependencies if missing.")
            errors += 1

    # 3. Use the standard-library test runner; no undeclared pytest dependency.
    print("\n3. Running Unittest Suite...")
    ret = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    if ret != 0:
        print("ERROR: Test suite failed.")
        errors += 1
    else:
        print("PASS: All tests passed successfully.")

    if errors > 0:
        print(f"\n❌ Local CI FAILED with {errors} error(s).")
        sys.exit(1)
    else:
        print("\n✅ Local CI PASSED successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
