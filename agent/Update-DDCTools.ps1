<#
.SYNOPSIS
    Updates the DDC Tools (EMP Monitor Agent) from the shared folder.

.DESCRIPTION
    Staff can copy this script to their desktop and run it.
    It will:
      1. Reach back to the shared network folder for the latest agent package
      2. Stop the running agent task
      3. Back up the current agent files
      4. Extract the new files (preserving config.json)
      5. Reinstall Python dependencies if requirements changed
      6. Restart the agent task

    No admin privileges required for normal updates.

.EXAMPLE
    Double-click or right-click > Run with PowerShell
#>

# ── Self-elevate to Administrator if needed ──────────────────────────────
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

# ── Configuration ────────────────────────────────────────────────────────
$PackageName   = 'empmonitor-agent.zip'
$InstallDir    = 'E:\DDC\tools\agent'
$TaskName      = 'EmpMonitorAgent'

# Possible locations for the update package (tried in order)
$SearchPaths = @(
    $PSScriptRoot,                                    # Same folder as this script
    'E:\DDC\tools\updates',                           # Mapped drive
    '\\10.147.17.115\EDrive\DDC\tools\updates'        # UNC path
)

# Files that must NEVER be overwritten (employee-specific config)
$ProtectedFiles = @('config.json')

# ── Helpers ──────────────────────────────────────────────────────────────

function Write-Step($msg)    { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg)    { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)    { Write-Host "    $msg" -ForegroundColor Gray }

function Pause-BeforeExit {
    Write-Host ''
    Write-Host 'Press any key to close...' -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}

# ── Banner ───────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Yellow
Write-Host '  DDC Tools - Agent Updater' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Yellow

# ── Step 1: Find the update package ─────────────────────────────────────
Write-Step 'Looking for update package'

$PackagePath = $null
foreach ($folder in $SearchPaths) {
    if (-not $folder) { continue }
    $candidate = Join-Path $folder $PackageName
    Write-Info "Trying: $candidate"
    if (Test-Path $candidate) {
        $PackagePath = $candidate
        break
    }
}

if (-not $PackagePath) {
    # Last resort: try to reconnect the network share
    Write-Info 'Attempting network reconnection...'
    net use '\\10.147.17.115\EDrive' 2>&1 | Out-Null
    $candidate = '\\10.147.17.115\EDrive\DDC\tools\updates\' + $PackageName
    if (Test-Path $candidate) {
        $PackagePath = $candidate
    }
}

if (-not $PackagePath) {
    Write-Fail "Cannot find $PackageName in any known location."
    Write-Host '    Make sure you are connected to the office network.' -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

$packageDate = (Get-Item $PackagePath).LastWriteTime.ToString('yyyy-MM-dd HH:mm')
Write-Ok "Found update package (modified: $packageDate)"

# ── Step 2: Verify current installation exists ──────────────────────────
Write-Step 'Checking current installation'

if (-not (Test-Path $InstallDir)) {
    Write-Fail "Agent not installed at $InstallDir"
    Write-Host '    Run the full installer first (Install-EmpAgent.ps1).' -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

if (-not (Test-Path "$InstallDir\config.json")) {
    Write-Fail "No config.json found - agent may not be properly installed."
    Pause-BeforeExit
    exit 1
}

# Read current version if available
$currentVersion = 'unknown'
if (Test-Path "$InstallDir\version.py") {
    $verContent = Get-Content "$InstallDir\version.py" -Raw
    if ($verContent -match 'AGENT_VERSION\s*=\s*"([^"]+)"') {
        $currentVersion = $Matches[1]
    }
}
Write-Ok "Current installation found (version: $currentVersion)"

# ── Step 3: Stop the agent task ─────────────────────────────────────────
Write-Step 'Stopping agent'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-Ok 'Agent stopped'
} else {
    Write-Info 'Agent was not running'
}

# Also kill any lingering pythonw processes running the agent
$agentProcesses = Get-WmiObject Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir*" }
foreach ($proc in $agentProcesses) {
    try { $proc.Terminate() | Out-Null } catch {}
}

# ── Step 4: Back up current agent ───────────────────────────────────────
Write-Step 'Backing up current agent'

$backupDir = "$InstallDir\_backup"
if (Test-Path $backupDir) {
    Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# Back up only the .py and .txt files (not venv, not __pycache__)
Get-ChildItem $InstallDir -File | Where-Object {
    $_.Extension -in @('.py', '.txt', '.json', '.ps1') -and $_.DirectoryName -eq $InstallDir
} | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $backupDir $_.Name)
}

Write-Ok "Backup saved to $backupDir"

# ── Step 5: Extract and apply update ────────────────────────────────────
Write-Step 'Applying update'

$tempDir = Join-Path $env:TEMP "ddc-agent-update-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # Copy ZIP locally first (faster than extracting over network)
    $localZip = Join-Path $tempDir $PackageName
    Copy-Item $PackagePath $localZip
    Write-Info 'Package copied locally'

    # Extract
    $extractDir = Join-Path $tempDir 'extracted'
    Expand-Archive -Path $localZip -DestinationPath $extractDir -Force
    Write-Info 'Package extracted'

    # Copy files to install directory, skipping protected files
    $updatedFiles = @()
    $skippedFiles = @()

    Get-ChildItem $extractDir -File | ForEach-Object {
        if ($_.Name -in $ProtectedFiles) {
            $skippedFiles += $_.Name
        } else {
            Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Force
            $updatedFiles += $_.Name
        }
    }

    Write-Ok "Updated $($updatedFiles.Count) files"
    if ($skippedFiles.Count -gt 0) {
        Write-Info "Protected (not overwritten): $($skippedFiles -join ', ')"
    }

    # Read new version
    $newVersion = 'unknown'
    if (Test-Path "$InstallDir\version.py") {
        $verContent = Get-Content "$InstallDir\version.py" -Raw
        if ($verContent -match 'AGENT_VERSION\s*=\s*"([^"]+)"') {
            $newVersion = $Matches[1]
        }
    }
    Write-Info "Version: $currentVersion -> $newVersion"

} catch {
    Write-Fail "Update failed: $_"
    Write-Host '    Restoring from backup...' -ForegroundColor Yellow

    # Restore backup
    Get-ChildItem $backupDir -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Force
    }
    Write-Ok 'Backup restored'

    # Cleanup temp
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue

    Pause-BeforeExit
    exit 1
} finally {
    # Cleanup temp dir
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ── Step 6: Update Python dependencies if needed ────────────────────────
Write-Step 'Checking Python dependencies'

$VenvPip = "$InstallDir\venv\Scripts\pip.exe"
$ReqFile = "$InstallDir\requirements-agent.txt"

if ((Test-Path $VenvPip) -and (Test-Path $ReqFile)) {
    $ErrorActionPreference = 'Continue'
    & $VenvPip install -r $ReqFile --quiet 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
    Write-Ok 'Dependencies up to date'
} else {
    Write-Info 'Skipped (venv not found - may need full reinstall)'
}

# Clear __pycache__
$pycache = "$InstallDir\__pycache__"
if (Test-Path $pycache) {
    Remove-Item $pycache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info 'Cleared __pycache__'
}

# ── Step 7: Re-register and start the agent task ────────────────────────
Write-Step 'Registering scheduled task (with watchdog)'

$VenvDir = "$InstallDir\venv"

if (-not (Test-Path "$VenvDir\Scripts\pythonw.exe")) {
    Write-Fail "Cannot find $VenvDir\Scripts\pythonw.exe - venv may be broken."
    Write-Host '    Agent will not auto-start. A full reinstall may be needed.' -ForegroundColor Yellow
} else {
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

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq 'Running') {
        Write-Ok "Agent started (task state: Running)"
    } else {
        Write-Ok "Task registered (state: $($task.State) - will start at next logon)"
    }
    Write-Info 'Triggers: AtLogOn + Repeat every 15 min (watchdog)'
}

# ── Step 8: Create desktop shortcut (so staff always runs latest) ────────
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Update DDC Tools.lnk'

if (-not (Test-Path $shortcutPath)) {
    Write-Step 'Creating desktop shortcut'

    $scriptPath = '\\10.147.17.115\EDrive\DDC\tools\updates\Update-DDCTools.ps1'
    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$scriptPath`""
    $shortcut.WorkingDirectory = '\\10.147.17.115\EDrive\DDC\tools\updates'
    $shortcut.Description = 'Update DDC Tools (EMP Monitor Agent)'
    $shortcut.Save()

    Write-Ok "Shortcut created on Desktop: 'Update DDC Tools'"
    Write-Info 'Next time, just double-click the shortcut.'
} else {
    Write-Info 'Desktop shortcut already exists.'
}

# ── Done ─────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  Update complete!' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

Pause-BeforeExit
