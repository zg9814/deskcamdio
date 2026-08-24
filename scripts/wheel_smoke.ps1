# Build the wheel, verify shipped assets, then install into a throwaway venv
# and boot the runtime headlessly. Exit code 0 = release package is viable.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$venv = Join-Path $env:TEMP ("deskcamdio-wheel-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

# Prefer the project venv (CPython 3.13 with build tooling); fall back to PATH.
$Py = "python"
$candidate = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $candidate) { $Py = $candidate }
Write-Host ("interpreter: $Py")

Write-Host "== 1/4 build wheel =="
& $Py -m build --wheel --outdir $dist $root
if ($LASTEXITCODE -ne 0) { throw "build failed" }
$wheel = Get-ChildItem $dist -Filter "deskcamdio-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { throw "no wheel produced" }
Write-Host ("wheel: " + $wheel.Name)

Write-Host "== 2/4 inspect contents =="
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($wheel.FullName)
try {
    $names = $zip.Entries | ForEach-Object { $_.FullName }
} finally {
    $zip.Dispose()
}
$appTomls = @($names | Where-Object { $_ -match "^deskcamdio/apps/[a-z_]+/app\.toml$" })
$fonts = @($names | Where-Object { $_ -match "^deskcamdio/assets/fonts/" })
$sounds = @($names | Where-Object { $_ -match "^deskcamdio/assets/sounds/.*\.wav$" })
Write-Host ("app.toml count: " + $appTomls.Count)
Write-Host ("font files: " + ($fonts -join ", "))
Write-Host ("sound files: " + $sounds.Count)
if ($appTomls.Count -lt 10) { throw "wheel missing app.toml manifests" }
if ($fonts.Count -lt 2) { throw "wheel missing bundled font/OFL" }
if ($sounds.Count -lt 4) { throw "wheel missing sound assets" }

Write-Host "== 3/4 install into throwaway venv =="
& $Py -m venv $venv
& (Join-Path $venv "Scripts\python.exe") -m pip install --quiet --disable-pip-version-check $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "wheel install failed" }

Write-Host "== 4/4 boot headless from installed wheel =="
$dataDir = Join-Path $env:TEMP ("dc-smoke-data-" + [guid]::NewGuid().ToString("N").Substring(0, 6))
& (Join-Path $venv "Scripts\deskcamdio-device.exe") --headless --frames 5 `
    --data-dir $dataDir --run-dir (Join-Path $dataDir "run")
$code = $LASTEXITCODE
Remove-Item -Recurse -Force $venv, $dataDir -ErrorAction SilentlyContinue
if ($code -ne 0) { throw "installed runtime did not boot cleanly (exit $code)" }
Write-Host "WHEEL SMOKE OK"
