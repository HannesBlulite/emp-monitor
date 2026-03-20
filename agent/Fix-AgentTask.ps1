<#
.SYNOPSIS
    Fix the EmpMonitorAgent scheduled task to add watchdog auto-restart.

.DESCRIPTION
    Re-registers the scheduled task with:
      - AtLogOn trigger (existing)
      - Repeating trigger every 15 minutes (new — acts as watchdog)
      - RestartCount 999 (up from 3)
      - MultipleInstances = IgnoreNew (won't duplicate if already running)

    Run as Administrator on each employee PC.

.EXAMPLE
    .\Fix-AgentTask.ps1
    .\Fix-AgentTask.ps1 -InstallDir 'C:\DDC\tools\empmonitor-agent'
#>

param(
    [string]$InstallDir = 'C:\DDC\tools\agent',
    [string]$TaskName = 'EmpMonitorAgent'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Check admin
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[FAIL] Run as Administrator.' -ForegroundColor Red
    exit 1
}

$VenvDir = "$InstallDir\venv"
if (-not (Test-Path "$VenvDir\Scripts\pythonw.exe")) {
    Write-Host "[FAIL] Cannot find $VenvDir\Scripts\pythonw.exe" -ForegroundColor Red
    exit 1
}

Write-Host "Updating scheduled task '$TaskName'..." -ForegroundColor Cyan

# Stop existing task if running
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
}

# Remove old task
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "$VenvDir\Scripts\pythonw.exe" `
    -Argument "`"$InstallDir\main.py`"" `
    -WorkingDirectory $InstallDir

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

$triggerRepeat = New-ScheduledTaskTrigger -Once -At '00:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerLogon, $triggerRepeat) `
    -Settings $settings `
    -Description 'EMP Monitor Agent - captures screenshots and tracks activity' `
    -RunLevel Limited `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "[OK] Task '$TaskName' registered. State: $($task.State)" -ForegroundColor Green
Write-Host '     Triggers: AtLogOn + Repeat every 15 min (watchdog)' -ForegroundColor Gray
