param([string]$RepoRoot)
$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('RepoRoot')) {
    $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
}
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    [Console]::Error.WriteLine('Run uv sync --project tools/eduvia-mcp --python 3.12 first.')
    exit 2
}
& $python -m eduvia_mcp.server --repo-root $RepoRoot
exit $LASTEXITCODE
