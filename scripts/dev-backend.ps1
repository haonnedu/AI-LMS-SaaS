$ErrorActionPreference = 'Stop'
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup.ps1 first.' }
Push-Location $backend
try {
    & $python scripts/run_api.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend process exited with an error.' }
} finally { Pop-Location }

