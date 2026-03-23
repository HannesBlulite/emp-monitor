<#
.SYNOPSIS
    EMP Monitor Agent - Uninstaller

.DESCRIPTION
    Removes the EMP Monitor agent, scheduled task, and all local data.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$InstallDir = 'E:\DDC\tools\agent'
$TaskName   = 'EmpMonitorAgent'

function Test-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host '[FAIL] Run as Administrator.' -ForegroundColor Red
    exit 1
}

Write-Host 'Uninstalling EMP Monitor Agent...' -ForegroundColor Yellow

# Stop and remove scheduled task
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Scheduled task '$TaskName' removed" -ForegroundColor Green
} else {
    Write-Host "[SKIP] No scheduled task found" -ForegroundColor Gray
}

# Remove install directory
if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Recurse -Force
    Write-Host "[OK] Removed $InstallDir" -ForegroundColor Green
} else {
    Write-Host "[SKIP] $InstallDir not found" -ForegroundColor Gray
}

Write-Host ''
Write-Host 'EMP Monitor Agent has been uninstalled.' -ForegroundColor Green
