<#
.SYNOPSIS
    EMP Monitor Agent - One-Command Setup for any staff PC.

.DESCRIPTION
    Drop this on any PC (new or existing) and it handles everything:
      1. Maps the E: drive to the shared network folder if needed
      2. Writes the correct per-employee config locally
      3. Creates/repairs the Python venv
      4. Installs dependencies
      5. Registers the scheduled task
      6. Starts the agent

    All configuration (tokens, server URL, share paths) is loaded from
    the .env file on the shared drive. Edit .env to add new employees.

.PARAMETER Employee
    Employee name (must match a TOKEN_<name> entry in .env).
    If omitted, auto-detects from existing config or prompts for selection.

.EXAMPLE
    .\Setup-Agent.ps1 -Employee lizelle
    .\Setup-Agent.ps1                     # prompts for employee selection
#>

param(
    [string]$Employee = ''
)

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
    $argList = "-ExecutionPolicy Bypass -File `"$elevatedPath`""
    if ($Employee) { $argList += " -Employee $Employee" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Load .env configuration ─────────────────────────────────────────────
. "$PSScriptRoot\Load-EnvConfig.ps1"

$PythonMinVer = if ($EnvConfig.ContainsKey('PYTHON_MIN_VERSION')) {
    [version]$EnvConfig['PYTHON_MIN_VERSION']
} else {
    [version]'3.10'
}

# ═════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════

function Write-Step($msg)  { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "    $msg" -ForegroundColor Gray }

function Pause-BeforeExit {
    Write-Host ''
    Write-Host 'Press any key to close...' -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}

function Find-Python {
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

    foreach ($py in $candidates) {
        try {
            $ver = & $py --version 2>&1
            if ($ver -match 'Python (\d+\.\d+\.\d+)') {
                if ([version]$Matches[1] -ge $PythonMinVer) {
                    return $py
                }
            }
        } catch {}
    }
    return $null
}

# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════

Write-Host ''
Write-Host '============================================================' -ForegroundColor Yellow
Write-Host '  EMP Monitor Agent - Full Setup' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Yellow

try {

# ── Step 1: Ensure E: drive is mapped to the correct share ───────────
Write-Step 'Checking network drive (E:)'

$driveOk = $false

if (Test-Path "$AgentDir\main.py") {
    Write-Ok 'E: drive is mapped and agent folder is accessible'
    $driveOk = $true
} else {
    Write-Info 'E: drive not accessible or not mapped correctly'

    $currentE = net use E: 2>&1
    if ($currentE -notmatch 'error') {
        Write-Info 'Disconnecting current E: mapping...'
        net use E: /delete /yes 2>&1 | Out-Null
    }

    foreach ($share in $SharePaths) {
        Write-Info "Trying: net use E: $share /persistent:yes"
        $result = net use E: $share /persistent:yes 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path "$AgentDir\main.py")) {
            Write-Ok "E: mapped to $share"
            $driveOk = $true
            break
        } else {
            net use E: /delete /yes 2>&1 | Out-Null
        }
    }

    if (-not $driveOk) {
        Write-Fail 'Could not map E: drive to the shared folder.'
        Write-Host '    Make sure this PC is connected to the office network.' -ForegroundColor Yellow
        Write-Host "    Tried: $($SharePaths -join ', ')" -ForegroundColor Yellow
        Pause-BeforeExit
        exit 1
    }
}

if (-not (Test-Path "$AgentDir\main.py")) {
    Write-Fail "Agent files not found at $AgentDir"
    Pause-BeforeExit
    exit 1
}

$currentVersion = 'unknown'
if (Test-Path "$AgentDir\version.py") {
    $verContent = Get-Content "$AgentDir\version.py" -Raw
    if ($verContent -match 'AGENT_VERSION\s*=\s*"([^"]+)"') {
        $currentVersion = $Matches[1]
    }
}
Write-Info "Agent version on share: $currentVersion"

# ── Step 2: Select employee ──────────────────────────────────────────
Write-Step 'Identifying employee'

if ($Employee -eq '' -and (Test-Path $LocalConfig)) {
    try {
        $rawBytes = [System.IO.File]::ReadAllBytes($LocalConfig)
        $rawText = if ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF) {
            [System.Text.Encoding]::UTF8.GetString($rawBytes, 3, $rawBytes.Length - 3)
        } else {
            [System.Text.Encoding]::UTF8.GetString($rawBytes)
        }
        $existingConfig = $rawText | ConvertFrom-Json
        $existingToken = $existingConfig.agent_token

        if ($existingToken -and $existingToken -ne 'REPLACE_WITH_AGENT_TOKEN') {
            foreach ($name in $Tokens.Keys) {
                if ($Tokens[$name] -eq $existingToken) {
                    $Employee = $name
                    Write-Ok "Auto-detected: $Employee (from local config)"
                    break
                }
            }
        }
    } catch {
        Write-Warn "Could not parse existing config: $_"
    }
}

if ($Employee -eq '') {
    if ($Tokens.Count -eq 0) {
        Write-Fail 'No employee tokens found in .env file.'
        Pause-BeforeExit
        exit 1
    }

    Write-Host ''
    Write-Host '    Select employee for this PC:' -ForegroundColor Yellow
    Write-Host ''
    $names = @($Tokens.Keys | Sort-Object)
    for ($i = 0; $i -lt $names.Count; $i++) {
        Write-Host "      [$($i+1)] $($names[$i])" -ForegroundColor White
    }
    Write-Host ''
    $choice = Read-Host "    Enter number (1-$($names.Count))"
    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $names.Count) {
        Write-Fail 'Invalid choice'
        Pause-BeforeExit
        exit 1
    }
    $Employee = $names[$idx]
}

$Employee = $Employee.ToLower()
if (-not $Tokens.ContainsKey($Employee)) {
    Write-Fail "Unknown employee: $Employee"
    Write-Host "    Available: $($Tokens.Keys -join ', ')" -ForegroundColor Yellow
    Write-Host "    Add TOKEN_$Employee=<token> to .env to register this employee." -ForegroundColor Yellow
    Pause-BeforeExit
    exit 1
}

$Token = $Tokens[$Employee]
Write-Ok "Employee: $Employee"
Write-Info "Token: $($Token.Substring(0,8))...$($Token.Substring($Token.Length - 4))"

# ── Step 3: Stop any running agent ───────────────────────────────────
Write-Step 'Stopping existing agent'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Ok 'Agent stopped'
} elseif ($task) {
    Write-Info "Task exists but not running (state: $($task.State))"
} else {
    Write-Info 'No existing scheduled task found'
}

Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($cmdLine -match 'main\.py') {
            $_ | Stop-Process -Force
            Write-Info "Killed stray pythonw process (PID $($_.Id))"
        }
    } catch {}
}

# ── Step 4: Write local config ───────────────────────────────────────
Write-Step 'Writing local config'

if (-not (Test-Path $LocalDataDir)) {
    New-Item -ItemType Directory -Path $LocalDataDir -Force | Out-Null
}

$config = @{
    server_url                       = $ServerUrl
    agent_token                      = $Token
    screenshot_interval_seconds      = $AgentSettings['screenshot_interval_seconds']
    activity_report_interval_seconds = $AgentSettings['activity_report_interval_seconds']
    screenshot_quality               = $AgentSettings['screenshot_quality']
    screenshot_format                = $AgentSettings['screenshot_format']
    idle_threshold_seconds           = $AgentSettings['idle_threshold_seconds']
    log_level                        = $AgentSettings['log_level']
} | ConvertTo-Json -Depth 2

[System.IO.File]::WriteAllText($LocalConfig, $config, (New-Object System.Text.UTF8Encoding $false))
Write-Ok "Config: $LocalConfig"
Write-Info "Server: $ServerUrl"

$sharedConfig = "$AgentDir\config.json"
if (Test-Path $sharedConfig) {
    Remove-Item $sharedConfig -Force -ErrorAction SilentlyContinue
    Write-Info 'Removed shared-drive config.json'
}

# ── Step 5: Python venv ──────────────────────────────────────────────
Write-Step 'Setting up Python environment'

$VenvPython  = "$VenvDir\Scripts\python.exe"
$VenvPythonw = "$VenvDir\Scripts\pythonw.exe"
$ReqFile     = "$AgentDir\requirements-agent.txt"

$venvValid = (Test-Path $VenvPython) -and (Test-Path "$VenvDir\Scripts\pip.exe")

if (-not $venvValid) {
    if (Test-Path $VenvDir) {
        Write-Info 'Existing venv is incomplete - removing...'
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $PythonExe = Find-Python
    if (-not $PythonExe) {
        Write-Fail 'Python >= 3.10 not found.'
        Write-Host '    Install Python 3.12 from https://python.org and re-run.' -ForegroundColor Yellow
        Pause-BeforeExit
        exit 1
    }
    Write-Info "System Python: $PythonExe"

    Write-Info 'Creating virtual environment...'
    & $PythonExe -m venv $VenvDir 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

    if (-not (Test-Path $VenvPython)) {
        Write-Fail 'Venv creation failed.'
        Pause-BeforeExit
        exit 1
    }
    Write-Ok 'Virtual environment created'
} else {
    Write-Ok "Venv found: $VenvDir"
}

if (Test-Path $ReqFile) {
    Write-Info 'Installing dependencies...'
    $ErrorActionPreference = 'Continue'
    & $VenvPython -m pip install --upgrade pip 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    & $VenvPython -m pip install -r $ReqFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    $ErrorActionPreference = 'Stop'

    $checkOutput = & $VenvPython -c "import mss; import requests; import PIL; print('DEPS_OK')" 2>&1
    $checkStr = ($checkOutput | Out-String).Trim()
    if ($checkStr -match 'DEPS_OK') {
        Write-Ok 'Dependencies verified'
    } else {
        Write-Fail "Dependency check failed: $checkStr"
        Write-Info 'Attempting force reinstall...'
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m pip install --force-reinstall -r $ReqFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        $ErrorActionPreference = 'Stop'
    }
}

$pycache = "$AgentDir\__pycache__"
if (Test-Path $pycache) {
    Remove-Item $pycache -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info 'Cleared __pycache__'
}

# ── Step 6: Register scheduled task ─────────────────────────────────
Write-Step 'Registering scheduled task'

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "$VenvDir\Scripts\pythonw.exe" `
    -Argument "`"$AgentDir\main.py`"" `
    -WorkingDirectory $AgentDir

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

Write-Ok "Task '$TaskName' registered (logon + watchdog every 15 min)"

# ── Step 7: Start the agent ──────────────────────────────────────────
Write-Step 'Starting agent'

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {
    $proc = Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*agent-venv*" }
    if ($proc) {
        Write-Ok "Agent running (PID: $($proc.Id))"
    } else {
        Write-Ok 'Agent started'
    }
} else {
    Write-Warn "Task state: $($task.State)"
    Write-Info 'Try running manually to see errors:'
    Write-Host "    & `"$VenvPython`" `"$AgentDir\main.py`"" -ForegroundColor Yellow
}

# ── Step 8: Desktop shortcut ─────────────────────────────────────────
Write-Step 'Creating desktop shortcut'

$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Update DDC Tools.lnk'

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

Write-Ok "Desktop shortcut created: 'Update DDC Tools'"

# ── Step 9: Verify ───────────────────────────────────────────────────
Write-Step 'Verification'

$logFile = "$LocalDataDir\logs\agent.log"
if (Test-Path $logFile) {
    Write-Info 'Latest log entries:'
    Get-Content $logFile -Tail 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
} else {
    Write-Info 'Log file not created yet (agent may need a moment)'
}

# ── Done ─────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host "  SETUP COMPLETE for $($Employee.ToUpper())" -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''
Write-Host "  Employee:  $Employee" -ForegroundColor Gray
Write-Host "  Config:    $LocalConfig" -ForegroundColor Gray
Write-Host "  Venv:      $VenvDir" -ForegroundColor Gray
Write-Host "  Agent dir: $AgentDir" -ForegroundColor Gray
Write-Host "  Log:       $logFile" -ForegroundColor Gray
Write-Host "  Task:      $TaskName" -ForegroundColor Gray
Write-Host ''

} catch {
    Write-Host ''
    Write-Host "UNEXPECTED ERROR: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}

Pause-BeforeExit
