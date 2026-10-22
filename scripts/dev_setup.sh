#!/usr/bin/env sh
# One-command developer environment (roadmap #71).
# Creates a venv, installs NEEZY editable with dev extras, and runs the CI gates.
set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
echo "==> Using $($PYTHON --version)"

if [ ! -d .venv ]; then
    echo "==> Creating .venv"
    "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate 2>/dev/null || . .venv/Scripts/activate

echo "==> Installing NEEZY (editable) with dev extras"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[dev]"

echo "==> Running local CI gates (compile, lint, format check, tests)"
python local_ci.py

echo
echo "Developer environment ready."
echo "  activate:  source .venv/bin/activate"
echo "  run tests: make test   (or: python -m unittest discover -s tests)"
echo "  lint:      make lint"
