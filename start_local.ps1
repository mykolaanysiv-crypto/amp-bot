$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python virtualenv' }
}
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install requirements' }
# Python supervisor starts/stops the separate run_web.py and run.py processes.
& $python -m scripts.local_supervisor
if ($LASTEXITCODE -ne 0) { throw "AMP local processes failed (exit code $LASTEXITCODE)" }
