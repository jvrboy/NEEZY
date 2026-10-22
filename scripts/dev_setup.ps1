# One-command developer environment for Windows (roadmap #71).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path .venv)) {
    Write-Host "==> Creating .venv"
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

Write-Host "==> Installing NEEZY (editable) with dev extras"
python -m pip install --upgrade pip | Out-Null
python -m pip install -e ".[dev]"

Write-Host "==> Running local CI gates"
python local_ci.py

Write-Host ""
Write-Host "Developer environment ready. Run tests: make test"
