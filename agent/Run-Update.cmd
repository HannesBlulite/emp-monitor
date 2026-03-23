@echo off
:: Self-elevate to Administrator
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Requesting Administrator privileges...
    powershell.exe -Command "Start-Process cmd.exe -Verb RunAs -ArgumentList '/c \"%~f0\"'"
    exit /b
)

title DDC Tools - Agent Updater
echo.
echo  ============================================================
echo   DDC Tools - Agent Updater
echo  ============================================================
echo.

:: Find the script - try UNC first (admin sessions lose mapped drives)
set "SCRIPT_PATH=\\10.147.17.115\EDrive\DDC\tools\Update-DDCTools.ps1"
if not exist "%SCRIPT_PATH%" set "SCRIPT_PATH=%~dp0Update-DDCTools.ps1"

echo  Running: %SCRIPT_PATH%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_PATH%"

echo.
pause
