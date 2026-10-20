$ErrorActionPreference = 'Stop'
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
Push-Location $frontend
try {
    & npm.cmd run dev
    if ($LASTEXITCODE -ne 0) { throw 'Frontend process exited with an error.' }
} finally { Pop-Location }

