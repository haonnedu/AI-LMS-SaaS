param(
    [switch]$SkipInstall,
    [string]$Python312,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

function Assert-Python312([string]$Executable) {
    $version = & $Executable -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>$null
    if ($LASTEXITCODE -ne 0 -or "$version".Trim() -ne '3.12') {
        throw 'Python 3.12 is required. Supply -Python312 <absolute-path-to-python.exe>. Existing environments are never deleted automatically.'
    }
}

if (-not $SkipInstall -or $CheckOnly) {
    Get-Command npm.cmd -ErrorAction Stop | Out-Null
    $python = Join-Path $repo 'backend\.venv\Scripts\python.exe'
    if ($Python312) {
        if (-not [IO.Path]::IsPathRooted($Python312) -or -not (Test-Path -LiteralPath $Python312 -PathType Leaf)) {
            throw '-Python312 must name an existing absolute executable path.'
        }
        Assert-Python312 $Python312
    }
    if (Test-Path -LiteralPath $python) {
        Assert-Python312 $python
    } elseif (-not $Python312) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            $candidate = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $Python312 = "$candidate".Trim() }
        }
        if (-not $Python312) {
            foreach ($name in @('python3.12', 'python')) {
                $candidate = Get-Command $name -ErrorAction SilentlyContinue
                if ($candidate) {
                    $version = & $candidate.Source -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>$null
                    if ($LASTEXITCODE -eq 0 -and "$version".Trim() -eq '3.12') {
                        $Python312 = $candidate.Source
                        break
                    }
                }
            }
        }
        if (-not $Python312) { throw 'Install Python 3.12 or supply -Python312 <absolute-path-to-python.exe>.' }
        Assert-Python312 $Python312
    }
    if ($CheckOnly) {
        Write-Host 'Python 3.12 validation passed. No files changed or packages installed.'
        return
    }
}

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

if (-not (Test-Path -LiteralPath $python)) {
    & $Python312 -m venv (Join-Path $repo 'backend\.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the backend virtual environment.' }
    Assert-Python312 $python
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

