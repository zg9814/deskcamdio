# Deploy DeskCamdio v1.0 source to the Pi (Windows dev machine).
# Requires: OpenSSH client (ssh/scp) with key auth configured for the Pi,
# or interactive password entry. Packaging uses the bundled bsdtar.
param(
    [string]$HostName = "192.168.1.17",
    [string]$UserName = "fish",
    [string]$RemoteSourceDir = "/tmp/deskcamdio-1.0.0-src",
    [string]$RemoteInstallScript = "/tmp/install_release.sh"
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$tarball = Join-Path $env:TEMP "deskcamdio-v1.0.tar.gz"
if (Test-Path $tarball) { Remove-Item $tarball -Force }

Write-Host "== 1/4 packaging source =="
$excludeArgs = @(
    "--exclude=.git", "--exclude=__pycache__", "--exclude=.venv",
    "--exclude=.pytest_cache", "--exclude=.ruff_cache", "--exclude=.mypy_cache",
    "--exclude=data", "--exclude=backups", "--exclude=work", "--exclude=dist",
    "--exclude=build", "--exclude=.runtime"
)
& tar.exe -czf $tarball @excludeArgs -C $root .
if ($LASTEXITCODE -ne 0) { throw "tar packaging failed" }
Write-Host ("packed: " + (Get-Item $tarball).Length + " bytes")

Write-Host "== 2/4 upload =="
& scp.exe $tarball ("{0}@{1}:/tmp/deskcamdio-v1.0.tar.gz" -f $UserName, $HostName)
if ($LASTEXITCODE -ne 0) { throw "scp upload failed" }

& scp.exe (Join-Path $PSScriptRoot "install_release.sh") ("{0}@{1}:{2}" -f $UserName, $HostName, $RemoteInstallScript)
if ($LASTEXITCODE -ne 0) { throw "scp script upload failed" }

Write-Host "== 3/4 extract on Pi =="
& ssh.exe ("{0}@{1}" -f $UserName, $HostName) "rm -rf $RemoteSourceDir && mkdir -p $RemoteSourceDir && tar xzf /tmp/deskcamdio-v1.0.tar.gz -C $RemoteSourceDir && echo extracted"
if ($LASTEXITCODE -ne 0) { throw "remote extraction failed" }

Write-Host "== 4/4 atomic install (needs sudo; enter password when prompted) =="
& ssh.exe -t ("{0}@{1}" -f $UserName, $HostName) "sudo bash $RemoteInstallScript $RemoteSourceDir"
if ($LASTEXITCODE -ne 0) { throw "remote install failed" }

Write-Host "Done. Start with: sudo systemctl enable --now deskcamdio.service"
