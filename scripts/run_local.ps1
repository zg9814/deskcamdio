[CmdletBinding()]
param(
    [switch]$Headless,
    [ValidateRange(1, 240)]
    [int]$Fps = 30,
    [ValidateRange(0, 10000000)]
    [int]$Frames = 0
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$dataDir = Join-Path $repoRoot 'work\local-data'
$runDir = Join-Path $repoRoot 'work\local-run'

if ([string]::IsNullOrWhiteSpace($env:UV_CACHE_DIR)) {
    $env:UV_CACHE_DIR = Join-Path $workspaceRoot '.uv-cache'
}

foreach ($path in ($env:UV_CACHE_DIR, $dataDir, $runDir)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uvCommand) {
    throw 'uv was not found. Install it first with: winget install astral-sh.uv'
}

$nativeArgs = @(
    'run'
    'deskcamdio-device'
    '--data-dir'
    $dataDir
    '--run-dir'
    $runDir
    '--fps'
    $Fps.ToString()
)
if ($Headless) {
    $nativeArgs += '--headless'
}
if ($Frames -gt 0) {
    $nativeArgs += @('--frames', $Frames.ToString())
}

Write-Host "Starting DeskCamdio from $repoRoot" -ForegroundColor Cyan
Write-Host "Data: $dataDir" -ForegroundColor DarkGray
Write-Host 'Close the window or press Ctrl+C to stop.' -ForegroundColor DarkGray

Push-Location $repoRoot
try {
    & $uvCommand.Source @nativeArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "DeskCamdio exited with code $exitCode"
    }
}
finally {
    Pop-Location
}
