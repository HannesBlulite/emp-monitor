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

    All configuration is loaded from the .env file on the shared drive.

.EXAMPLE
    Double-click or right-click > Run with PowerShell
#>

# ── Self-elevate to Administrator if needed ──────────────────────────────
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
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

# ── Load .env configuration ─────────────────────────────────────────────
# Load-EnvConfig.ps1 may be in the same folder, or in the agent dir
$_loaderCandidates = @(
    (Join-Path $PSScriptRoot 'Load-EnvConfig.ps1'),
    (Join-Path (Split-Path $PSScriptRoot) 'agent\Load-EnvConfig.ps1'),
    'E:\DDC\tools\agent\Load-EnvConfig.ps1',
    '\\10.147.17.115\EDrive\DDC\tools\agent\Load-EnvConfig.ps1',
    '\\DDCSERVER-PC\EDrive\DDC\tools\agent\Load-EnvConfig.ps1'
)
$_loaderFound = $false
foreach ($_loader in $_loaderCandidates) {
    if (Test-Path $_loader) {
        . $_loader
        $_loaderFound = $true
        break
    }
}

if (-not $_loaderFound) {
    Write-Host '[WARN] Load-EnvConfig.ps1 not found. Using hardcoded defaults.' -ForegroundColor Yellow
    $ServerUrl  = 'https://ddcemp.co.za'
    $SharePaths = @('\\DDCSERVER-PC\EDrive', '\\10.147.17.115\EDrive')
    $AgentDir   = 'E:\DDC\tools\agent'
    $TaskName   = 'EmpMonitorAgent'
    $LocalDataDir = "$env:LOCALAPPDATA\DDC"
    $LocalConfig  = "$LocalDataDir\config.json"
    $VenvDir      = "$LocalDataDir\agent-venv"
}

# ── Configuration ────────────────────────────────────────────────────────
$PackageName   = 'empmonitor-agent.zip'
$UncBase       = if ($SharePaths.Count -gt 0) { $SharePaths[0] } else { '\\10.147.17.115\EDrive' }

$SearchPaths = @($PSScriptRoot)
foreach ($share in $SharePaths) {
    $SearchPaths += "$share\DDC\tools\updates"
}
$SearchPaths += 'E:\DDC\tools\updates'

$ProtectedFiles = @('config.json', '.env')

# ── Helpers ──────────────────────────────────────────────────────────────

function Write-Step($msg)    { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)    { Write-Host "    $msg" -ForegroundColor Gray }

# ── Resolve install directory ────────────────────────────────────────────
$InstallDir = $null
foreach ($share in $SharePaths) {
    if (Test-Path "$share\DDC\tools\agent") {
        $InstallDir = "$share\DDC\tools\agent"
        break
    }
}
if (-not $InstallDir -and (Test-Path 'E:\DDC\tools\agent')) {
    $InstallDir = 'E:\DDC\tools\agent'
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
    Write-Info 'Attempting network reconnection...'
    foreach ($share in $SharePaths) {
        net use $share 2>&1 | Out-Null
        $candidate = "$share\DDC\tools\updates\$PackageName"
        if (Test-Path $candidate) {
            $PackagePath = $candidate
            break
        }
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
    Write-Host '    Run Setup-Agent.ps1 for first-time installation.' -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

$LocalConfigPath = $LocalConfig
$SharedConfigPath = "$InstallDir\config.json"

if ((Test-Path $LocalConfigPath)) {
    Write-Info "Local config found: $LocalConfigPath"
} elseif ((Test-Path $SharedConfigPath)) {
    Write-Info "Migrating config from shared drive to local..."
    if (-not (Test-Path $LocalDataDir)) {
        New-Item -ItemType Directory -Path $LocalDataDir -Force | Out-Null
    }
    Copy-Item $SharedConfigPath $LocalConfigPath -Force
    Remove-Item $SharedConfigPath -Force -ErrorAction SilentlyContinue
    Write-Ok "Config migrated to $LocalConfigPath"
} else {
    Write-Fail "No config.json found (checked local and shared drive)."
    Write-Host "    Run Setup-Agent.ps1 or Fix-Agent.ps1 to create a config for this PC." -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

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

$agentProcesses = Get-WmiObject Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir*" -or $_.CommandLine -like '*main.py*' }
foreach ($proc in $agentProcesses) {
    try { $proc.Terminate() | Out-Null } catch {}
}

# ── Step 4: Back up current agent ───────────────────────────────────────
Write-Step 'Backing up current agent'

$backupDir = Join-Path $env:TEMP 'ddc-agent-backup'
if (Test-Path $backupDir) {
    Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

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
    $localZip = Join-Path $tempDir $PackageName
    Copy-Item $PackagePath $localZip
    Write-Info 'Package copied locally'

    $extractDir = Join-Path $tempDir 'extracted'
    Expand-Archive -Path $localZip -DestinationPath $extractDir -Force
    Write-Info 'Package extracted'

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

    Get-ChildItem $backupDir -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Force
    }
    Write-Ok 'Backup restored'

    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue

    Pause-BeforeExit
    exit 1
} finally {
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ── Step 6: Ensure venv exists and update Python dependencies ────────────
Write-Step 'Checking Python environment'

$LocalAgentDir = $VenvDir
if (-not (Test-Path $LocalAgentDir)) {
    New-Item -ItemType Directory -Path (Split-Path $LocalAgentDir) -Force | Out-Null
}
$VenvPython  = "$VenvDir\Scripts\python.exe"
$VenvPip     = "$VenvDir\Scripts\pip.exe"
$ReqFile     = "$InstallDir\requirements-agent.txt"

$OldNetVenv = "$InstallDir\venv"
if (Test-Path $OldNetVenv) {
    Write-Info 'Removing old network-share venv (now using local venv)...'
    Remove-Item $OldNetVenv -Recurse -Force -ErrorAction SilentlyContinue
}

$PythonMinVer = if ($EnvConfig -and $EnvConfig.ContainsKey('PYTHON_MIN_VERSION')) {
    [version]$EnvConfig['PYTHON_MIN_VERSION']
} else {
    [version]'3.10'
}

$venvValid = (Test-Path "$VenvDir\Scripts\python.exe") -and (Test-Path "$VenvDir\Scripts\pip.exe")

if (-not $venvValid) {
    if (Test-Path $VenvDir) {
        Write-Info 'Existing venv is incomplete/broken - removing it...'
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Info 'Creating virtual environment...'

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

        $localVenv = Join-Path $env:TEMP 'ddc-agent-venv'
        if (Test-Path $localVenv) { Remove-Item $localVenv -Recurse -Force }

        Write-Info 'Creating venv locally (avoids network path issues)...'
        & $PythonExe -m venv $localVenv 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

        if (Test-Path "$localVenv\Scripts\python.exe") {
            Write-Info 'Moving venv to local directory...'
            if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
            Copy-Item $localVenv $VenvDir -Recurse -Force
            Remove-Item $localVenv -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok 'Virtual environment created (local)'
        } else {
            Write-Fail 'venv creation failed locally.'
            Remove-Item $localVenv -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Fail 'Python >= 3.10 not found. Cannot create venv.'
        Write-Host '    Install Python 3.12 first, then run this script again.' -ForegroundColor Yellow
    }
}

if ((Test-Path $VenvPython) -and (Test-Path $ReqFile)) {
    Write-Info 'Installing dependencies (this may take a moment)...'

    $ErrorActionPreference = 'Continue'
    & $VenvPython -m pip install --upgrade pip 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    & $VenvPython -m pip install -r $ReqFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    $pipExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'

    if ($pipExit -ne 0) {
        Write-Fail "pip install failed (exit code $pipExit)"
    }

    $checkOutput = & $VenvPython -c "import mss; import requests; import PIL; print('DEPS_OK')" 2>&1
    $checkStr = ($checkOutput | Out-String).Trim()
    if ($checkStr -match 'DEPS_OK') {
        Write-Ok 'Dependencies verified'
    } else {
        Write-Fail "Dependencies NOT installed. Import check output:"
        Write-Host "    $checkStr" -ForegroundColor Red
        Write-Info 'Attempting reinstall...'
        & $VenvPython -m pip install --force-reinstall -r $ReqFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        $recheck = & $VenvPython -c "import mss; import requests; import PIL; print('DEPS_OK')" 2>&1
        $recheckStr = ($recheck | Out-String).Trim()
        if ($recheckStr -match 'DEPS_OK') {
            Write-Ok 'Dependencies verified after reinstall'
        } else {
            Write-Fail "CRITICAL: Dependencies still missing after reinstall. Agent will NOT work."
            Write-Host "    Output: $recheckStr" -ForegroundColor Red
        }
    }
} elseif (-not (Test-Path $VenvPython)) {
    Write-Fail 'Python not found in venv - venv creation may have failed.'
}

$pycache = "$InstallDir\__pycache__"
if (Test-Path $pycache) {
    Remove-Item $pycache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info 'Cleared __pycache__'
}

# ── Step 7: Re-register and start the agent task ────────────────────────
Write-Step 'Registering scheduled task (with watchdog)'

$TaskDir     = $AgentDir
$LocalVenvDir = $VenvDir

if (-not (Test-Path "$LocalVenvDir\Scripts\pythonw.exe")) {
    Write-Fail "Cannot find pythonw.exe in venv - venv may be broken."
    Write-Host '    Agent will not auto-start. Run Setup-Agent.ps1 for a full reinstall.' -ForegroundColor Yellow
} else {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction `
        -Execute "$LocalVenvDir\Scripts\pythonw.exe" `
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
    Start-Sleep -Seconds 5

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq 'Running') {
        $proc = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*agent-venv*" }
        if ($proc) {
            Write-Ok "Agent started and running (PID: $($proc.Id))"
        } else {
            Write-Warn "Task says Running but no pythonw process found - agent may have crashed"
            Write-Info "Try running manually to see errors:"
            Write-Host "    & `"$LocalVenvDir\Scripts\python.exe`" `"$TaskDir\main.py`"" -ForegroundColor Yellow
        }
    } else {
        Write-Warn "Task state: $($task.State) - agent may have crashed on start"
        Write-Info "Diagnosing..."
        $testOutput = & "$LocalVenvDir\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'$TaskDir'); import main" 2>&1
        $testStr = ($testOutput | Out-String).Trim()
        if ($testStr) {
            Write-Fail "Agent import error:"
            Write-Host "    $testStr" -ForegroundColor Red
        } else {
            Write-Ok "Task registered (will start at next logon)"
        }
    }
    Write-Info 'Triggers: AtLogOn + Repeat every 15 min (watchdog)'
}

# ── Step 8: Create/update desktop shortcut ───────────────────────────────
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Update DDC Tools.lnk'

Write-Step 'Setting up desktop shortcut'

$updateScript = $null
foreach ($share in $SharePaths) {
    $candidate = "$share\DDC\tools\updates\Update-DDCTools.ps1"
    if (Test-Path $candidate) {
        $updateScript = $candidate
        break
    }
}
if (-not $updateScript) {
    $updateScript = 'E:\DDC\tools\updates\Update-DDCTools.ps1'
}

$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'powershell.exe'
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$updateScript`""
$shortcut.WorkingDirectory = Split-Path $updateScript
$shortcut.Description = 'Update DDC Tools (EMP Monitor Agent)'
$shortcut.Save()

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
