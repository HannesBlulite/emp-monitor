@echo off
title DDC Tools - Agent Updater
powershell.exe -ExecutionPolicy Bypass -File "%~dp0Update-DDCTools.ps1"
if %ERRORLEVEL% NEQ 0 pause
