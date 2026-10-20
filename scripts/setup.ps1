param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

foreach ($relative in @('.env', 'frontend\.env.local', 'backend\.env')) {
    $target = Join-Path $repo $relative
    $example = if ($relative -eq 'frontend\.env.local') {
        Join-Path $repo 'frontend\.env.example'
    } else {
        "$target.example"
    }
    if (-not (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $example -Destination $target
        Write-Host "Created $relative"
    }
}
if ($SkipInstall) { return }

Get-Command python -ErrorAction Stop | Out-Null
Get-Command npm.cmd -ErrorAction Stop | Out-Null
$python = Join-Path $repo 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $repo 'backend\.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the backend virtual environment.' }
}
Push-Location (Join-Path $repo 'backend')
try {
    & $python -m pip install -r requirements-dev.lock
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    & $python -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Backend package installation failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $repo 'frontend')
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. See DEVELOPMENT.md for native and Docker startup commands.'

