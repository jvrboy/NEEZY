[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$NssmPath = "nssm",
    [string]$ServiceName = "ForexBot",
    [switch]$InstallService
)

$ErrorActionPreference = "Stop"
if ([Environment]::OSVersion.Platform -ne "Win32NT") {
    throw "The lightweight MT5 executor setup must run on Windows."
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Root ".venv-executor"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$HomeDir = Join-Path $env:LOCALAPPDATA "NEEZY"
$Config = Join-Path $HomeDir "executor.json"
$LogDir = Join-Path $HomeDir "logs"
$Main = Join-Path $Root "main.py"

if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating runtime-only virtual environment"
    & $Python -m venv $Venv
}

Write-Host "==> Installing runtime dependencies (no training libraries)"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements-runtime.txt")

New-Item -ItemType Directory -Force -Path $HomeDir, $LogDir | Out-Null
if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $Root "deploy\executor.example.json") $Config
    Write-Host "==> Created $Config (execution remains disabled)"
}

& $VenvPython $Main --config $Config --check-config
if ($LASTEXITCODE -ne 0) {
    throw "Executor config validation failed."
}

if ($InstallService) {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run PowerShell as Administrator to install the NSSM service."
    }
    $Nssm = Get-Command $NssmPath -ErrorAction SilentlyContinue
    if (-not $Nssm) {
        throw "NSSM was not found. Install it or pass -NssmPath C:\path\to\nssm.exe."
    }
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        throw "Service $ServiceName already exists; use 'nssm edit $ServiceName' to inspect it."
    }

    & $NssmPath install $ServiceName $VenvPython $Main --config $Config
    & $NssmPath set $ServiceName AppDirectory $Root
    & $NssmPath set $ServiceName AppEnvironmentExtra "NEEZY_HOME=$HomeDir" "PYTHONUNBUFFERED=1"
    & $NssmPath set $ServiceName AppStdout (Join-Path $LogDir "nssm-stdout.log")
    & $NssmPath set $ServiceName AppStderr (Join-Path $LogDir "nssm-stderr.log")
    & $NssmPath set $ServiceName AppRotateFiles 1
    & $NssmPath set $ServiceName AppRotateBytes 1048576
    & $NssmPath set $ServiceName AppExit Default Restart
    & $NssmPath set $ServiceName AppRestartDelay 5000
    & $NssmPath set $ServiceName Start SERVICE_AUTO_START

    Write-Host ""
    Write-Host "Service configured but NOT started. Before starting it:"
    Write-Host "  1. Edit $Config and keep execution_enabled=false for initial observation."
    Write-Host "  2. Run 'nssm edit $ServiceName' and use the same Windows account as MT5."
    Write-Host "  3. Configure MT5 in NEEZY, run 'neezy-cli mt5 preflight', and test demo only."
    Write-Host "  4. Start with 'nssm start $ServiceName' only after those checks pass."
} else {
    Write-Host ""
    Write-Host "Runtime ready. Config: $Config"
    Write-Host "Re-run with -InstallService from Administrator PowerShell to configure NSSM."
}
