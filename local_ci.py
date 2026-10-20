#!/usr/bin/env python3
"""Local CI runner for NEEZY.

Runs syntax compilation, ruff checks (if available), and the test suite.
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

    # 2. Run Ruff check if installed
    print("\n2. Running Linter Checks...")
    try:
        ret = run_cmd(["ruff", "check", "neezy_app", "neezy_backend", "tests"])
        if ret != 0:
            print("WARNING: Ruff check reported issues.")
    except FileNotFoundError:
        print("INFO: Ruff linter not found in environment, skipping.")

    # 3. Run Pytest test suite
    print("\n3. Running Pytest Test Suite...")
    pytest_bin = Path(sys.executable).parent / "pytest"
    if not pytest_bin.exists():
        pytest_bin = "pytest"
    ret = run_cmd([str(pytest_bin)])
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
