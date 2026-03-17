@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%empmonitor-remote-preflight.ps1"

if not exist "%PS_SCRIPT%" (
    echo EMP Monitor preflight script not found.
    echo Expected file: %PS_SCRIPT%
    echo.
    pause
    exit /b 1
)

echo EMP Monitor Remote Preflight
echo.
echo A PowerShell window may ask for the server URL.
echo Use your EMP Monitor server address, for example:
echo http://10.147.17.89:8000
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"

echo.
echo When it finishes, copy the output or the saved JSON report path and send it back.
pause