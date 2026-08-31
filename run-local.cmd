@echo off
setlocal

where pwsh.exe >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 ^(pwsh.exe^) was not found.
    echo Install it with: winget install Microsoft.PowerShell
    pause
    exit /b 1
)

pwsh.exe -NoLogo -NoProfile -File "%~dp0scripts\run_local.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo DeskCamdio failed to start. Exit code: %EXIT_CODE%
    pause
)
exit /b %EXIT_CODE%
