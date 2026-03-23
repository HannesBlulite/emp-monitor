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
    # Convert mapped-drive path to UNC so the elevated session can find the script
    $elevatedPath = $PSCommandPath
    if ($elevatedPath -match '^([A-Z]):\\') {
        $driveLetter = $Matches[1]
        $netUse = net use "${driveLetter}:" 2>&1
        if ($netUse -match '\\\\[^\s]+') {
            $uncRoot = $Matches[0]
            $elevatedPath = $elevatedPath -replace "^${driveLetter}:\\", "$uncRoot\"
        }
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$elevatedPath`""
    exit
}

# ── Configuration ────────────────────────────────────────────────────────
$PackageName   = 'empmonitor-agent.zip'
$TaskName      = 'EmpMonitorAgent'
$UncBase       = '\\10.147.17.115\EDrive'

# Possible locations for the update package (tried in order)
$SearchPaths = @(
    $PSScriptRoot,                                    # Same folder as this script
    'E:\DDC\tools\updates',                           # Mapped drive
    "$UncBase\DDC\tools\updates"                      # UNC path
)

# Files that must NEVER be overwritten (employee-specific config)
$ProtectedFiles = @('config.json')

# ── Helpers ──────────────────────────────────────────────────────────────

function Write-Step($msg)    { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg)    { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)    { Write-Host "    $msg" -ForegroundColor Gray }

# ── Resolve install directory (E: drive may not be mapped in admin session) ──
$InstallDir = $null
if (Test-Path 'E:\DDC\tools\agent') {
    $InstallDir = 'E:\DDC\tools\agent'
} else {
    # Try to reconnect E: drive
    net use E: $UncBase /persistent:yes 2>&1 | Out-Null
    if (Test-Path 'E:\DDC\tools\agent') {
        $InstallDir = 'E:\DDC\tools\agent'
    } elseif (Test-Path "$UncBase\DDC\tools\agent") {
        $InstallDir = "$UncBase\DDC\tools\agent"
    }
}

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

try {

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

if (-not $InstallDir) {
    Write-Fail "Cannot reach agent folder (E: drive and UNC both failed)."
    Write-Host '    Make sure you are connected to the office network.' -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

Write-Info "Install directory: $InstallDir"

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

# Use a LOCAL temp folder for backup (avoids slow network I/O on mapped drives)
$backupDir = Join-Path $env:TEMP 'ddc-agent-backup'
if (Test-Path $backupDir) {
    Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# Back up only the .py, .txt, .json, .ps1 files (not venv, not __pycache__)
Get-ChildItem $InstallDir -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Extension -in @('.py', '.txt', '.json', '.ps1')
} | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $backupDir $_.Name) -Force
}

$backedUp = (Get-ChildItem $backupDir -File -ErrorAction SilentlyContinue).Count
Write-Ok "Backup: $backedUp files saved to local temp"

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

# ── Step 6: Ensure venv exists and update Python dependencies ────────────
Write-Step 'Checking Python environment'

$VenvDir  = "$InstallDir\venv"
$VenvPip  = "$VenvDir\Scripts\pip.exe"
$ReqFile  = "$InstallDir\requirements-agent.txt"
$PythonMinVer = [version]'3.10'

# Check if venv is complete (both python.exe AND pip.exe must exist)
$venvValid = (Test-Path "$VenvDir\Scripts\python.exe") -and (Test-Path "$VenvDir\Scripts\pip.exe")

if (-not $venvValid) {
    if (Test-Path $VenvDir) {
        Write-Info 'Existing venv is incomplete/broken - removing it...'
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Info 'Creating virtual environment...'

    # Find a system Python
    $candidates = @(
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Get-Command python3 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $PythonExe = $null
    foreach ($py in $candidates) {
        try {
            $ver = & $py --version 2>&1
            if ($ver -match 'Python (\d+\.\d+\.\d+)') {
                if ([version]$Matches[1] -ge $PythonMinVer) {
                    $PythonExe = $py
                    break
                }
            }
        } catch {}
    }

    if ($PythonExe) {
        Write-Info "Found Python: $PythonExe"

        # Create venv in LOCAL temp first (ensurepip fails on UNC/network paths)
        $localVenv = Join-Path $env:TEMP 'ddc-agent-venv'
        if (Test-Path $localVenv) { Remove-Item $localVenv -Recurse -Force }

        Write-Info 'Creating venv locally (avoids network path issues)...'
        & $PythonExe -m venv $localVenv 2>&1 | Out-Null

        if (Test-Path "$localVenv\Scripts\python.exe") {
            # Copy the whole venv to the network drive
            Write-Info 'Copying venv to install directory...'
            if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
            Copy-Item $localVenv $VenvDir -Recurse -Force
            Remove-Item $localVenv -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok 'Virtual environment created'
        } else {
            Write-Fail 'venv creation failed locally.'
            Remove-Item $localVenv -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Fail 'Python >= 3.10 not found. Cannot create venv.'
        Write-Host '    Install Python 3.12 first, then run this script again.' -ForegroundColor Yellow
    }
}

if ((Test-Path $VenvPip) -and (Test-Path $ReqFile)) {
    Write-Info 'Installing/updating dependencies...'
    $ErrorActionPreference = 'Continue'
    & $VenvPip install --upgrade pip --quiet 2>&1 | Out-Null
    & $VenvPip install -r $ReqFile --quiet 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
    Write-Ok 'Dependencies up to date'
} elseif (-not (Test-Path $VenvPip)) {
    Write-Fail 'pip not found - venv creation may have failed.'
}

# Clear __pycache__
$pycache = "$InstallDir\__pycache__"
if (Test-Path $pycache) {
    Remove-Item $pycache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info 'Cleared __pycache__'
}

# ── Step 7: Re-register and start the agent task ────────────────────────
Write-Step 'Registering scheduled task (with watchdog)'

# Task runs as normal user who has E: mapped — always use drive letter path
$TaskDir  = 'E:\DDC\tools\agent'
$VenvDir  = "$TaskDir\venv"

# But check pythonw against the path we CAN see (may be UNC or E:)
$checkVenv = "$InstallDir\venv"

if (-not (Test-Path "$checkVenv\Scripts\pythonw.exe")) {
    Write-Fail "Cannot find pythonw.exe in venv - venv may be broken."
    Write-Host '    Agent will not auto-start. A full reinstall may be needed.' -ForegroundColor Yellow
} else {
    # Remove old task
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction `
        -Execute "$VenvDir\Scripts\pythonw.exe" `
        -Argument "`"$TaskDir\main.py`"" `
        -WorkingDirectory $TaskDir

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

# ── Step 8: Create/update desktop shortcut (always refresh to ensure admin flag) ──
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Update DDC Tools.lnk'

Write-Step 'Setting up desktop shortcut'

    $scriptPath = '\\10.147.17.115\EDrive\DDC\tools\updates\Update-DDCTools.ps1'
    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$scriptPath`""
    $shortcut.WorkingDirectory = '\\10.147.17.115\EDrive\DDC\tools\updates'
    $shortcut.Description = 'Update DDC Tools (EMP Monitor Agent)'
    $shortcut.Save()

    # Set "Run as Administrator" flag on the shortcut
    $bytes = [System.IO.File]::ReadAllBytes($shortcutPath)
    $bytes[0x15] = $bytes[0x15] -bor 0x20
    [System.IO.File]::WriteAllBytes($shortcutPath, $bytes)

    Write-Ok "Shortcut created on Desktop: 'Update DDC Tools' (runs as admin)"
    Write-Info 'Next time, just double-click the shortcut.'

# ── Done ─────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  Update complete!' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green

} catch {
    Write-Host ''
    Write-Host "UNEXPECTED ERROR: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}

Write-Host ''
Pause-BeforeExit
