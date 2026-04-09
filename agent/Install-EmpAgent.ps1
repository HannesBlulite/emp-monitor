<#
.SYNOPSIS
    EMP Monitor Agent - Silent Installer for Staff PCs

.DESCRIPTION
    Run this script with administrator privileges on each staff PC.
    It will:
      1. Check for / install Python 3.12
      2. Copy agent files to the agent directory
      3. Create a Python virtual environment & install dependencies
      4. Write the config with the provided agent token
      5. Register a Task Scheduler job so the agent starts at user logon
      6. Start the agent immediately

    All configuration is loaded from the .env file.

.PARAMETER AgentToken
    The agent token generated in the Django admin for this employee.

.EXAMPLE
    .\Install-EmpAgent.ps1 -AgentToken "abc123..."
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$AgentToken
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Load .env configuration ─────────────────────────────────────────────
. "$PSScriptRoot\Load-EnvConfig.ps1"

$InstallDir    = $AgentDir
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path

$PythonMinVer = if ($EnvConfig -and $EnvConfig.ContainsKey('PYTHON_MIN_VERSION')) {
    [version]$EnvConfig['PYTHON_MIN_VERSION']
} else {
    [version]'3.10'
}

# ── Helpers ──────────────────────────────────────────────────────────────

function Write-Step($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor Gray }

function Test-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
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
                $v = [version]$Matches[1]
                if ($v -ge $PythonMinVer) {
                    return $py
                }
            }
        } catch {}
    }
    return $null
}

# ── Pre-flight ───────────────────────────────────────────────────────────

if (-not (Test-Admin)) {
    Write-Fail 'This script must be run as Administrator.'
    Write-Host '    Right-click PowerShell > Run as administrator, then re-run this script.'
    exit 1
}

Write-Host '============================================================' -ForegroundColor Yellow
Write-Host '  EMP Monitor Agent - Installer' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Yellow

# ── Step 1: Python ───────────────────────────────────────────────────────
Write-Step 'Checking Python installation'

$PythonExe = Find-Python

if (-not $PythonExe) {
    Write-Host '    Python >= 3.10 not found. Installing Python 3.12...'
    $installerUrl  = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'
    $installerPath = "$env:TEMP\python-installer.exe"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Start-Process -FilePath $installerPath -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_pip=1' -Wait -NoNewWindow

    Remove-Item $installerPath -ErrorAction SilentlyContinue

    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('PATH', 'User')

    $PythonExe = Find-Python
    if (-not $PythonExe) {
        Write-Fail 'Python installation failed. Install Python 3.12+ manually and re-run.'
        exit 1
    }
}

Write-Ok "Python found: $PythonExe"

# ── Step 2: Copy agent files ────────────────────────────────────────────
Write-Step "Installing agent to $InstallDir"

if (Test-Path $InstallDir) {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask -and $existingTask.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$agentFiles = @('__init__.py', 'main.py', 'activity.py', 'browser_url.py', 'screenshot.py', 'server_comm.py', 'service.py', 'version.py', 'updater.py', 'notifier.py', 'requirements-agent.txt', 'Load-EnvConfig.ps1', '.env')
foreach ($f in $agentFiles) {
    $src = Join-Path $ScriptDir $f
    if (Test-Path $src) {
        Copy-Item $src "$InstallDir\$f" -Force
    } else {
        if ($f -notin @('Load-EnvConfig.ps1', '.env')) {
            Write-Fail "Missing agent file: $f"
            exit 1
        }
    }
}

Write-Ok "Agent files copied to $InstallDir"

# ── Step 3: Virtual environment & dependencies ──────────────────────────
Write-Step 'Setting up Python virtual environment'

if (-not (Test-Path (Split-Path $VenvDir))) {
    New-Item -ItemType Directory -Path (Split-Path $VenvDir) -Force | Out-Null
}

if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    & $PythonExe -m venv $VenvDir
}

$VenvPython = "$VenvDir\Scripts\python.exe"
$VenvPip    = "$VenvDir\Scripts\pip.exe"

Write-Ok 'Virtual environment ready'

Write-Step 'Installing Python dependencies'
$ErrorActionPreference = 'Continue'
& $VenvPython -m pip install --upgrade pip 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
& $VenvPython -m pip install -r "$InstallDir\requirements-agent.txt" 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
$ErrorActionPreference = 'Stop'

$checkOutput = & $VenvPython -c "import mss; import requests; import PIL; print('DEPS_OK')" 2>&1
$checkStr = ($checkOutput | Out-String).Trim()
if ($checkStr -match 'DEPS_OK') {
    Write-Ok 'Dependencies installed and verified'
} else {
    Write-Fail "Dependency check failed: $checkStr"
    exit 1
}

# ── Step 4: Write config (LOCAL per-PC, not on shared drive) ────────────
Write-Step 'Writing agent configuration'

$LocalConfigDir  = $LocalDataDir
$LocalConfigPath = $LocalConfig

if (-not (Test-Path $LocalConfigDir)) {
    New-Item -ItemType Directory -Path $LocalConfigDir -Force | Out-Null
}

$config = @{
    server_url                       = $ServerUrl
    agent_token                      = $AgentToken
    screenshot_interval_seconds      = $AgentSettings['screenshot_interval_seconds']
    activity_report_interval_seconds = $AgentSettings['activity_report_interval_seconds']
    screenshot_quality               = $AgentSettings['screenshot_quality']
    screenshot_format                = $AgentSettings['screenshot_format']
    idle_threshold_seconds           = $AgentSettings['idle_threshold_seconds']
    log_level                        = $AgentSettings['log_level']
} | ConvertTo-Json -Depth 2

[System.IO.File]::WriteAllText($LocalConfigPath, $config, (New-Object System.Text.UTF8Encoding $false))

if (Test-Path "$InstallDir\config.json") {
    Remove-Item "$InstallDir\config.json" -Force -ErrorAction SilentlyContinue
    Write-Info "Removed shared-drive config.json (now stored locally)"
}

Write-Ok "Config written to $LocalConfigPath (server: $ServerUrl)"

# ── Step 5: Create scheduled task (runs at user logon) ──────────────────
Write-Step 'Registering auto-start task'

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action  = New-ScheduledTaskAction `
    -Execute "$VenvDir\Scripts\pythonw.exe" `
    -Argument "`"$InstallDir\main.py`"" `
    -WorkingDirectory $InstallDir

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

$triggerRepeat = New-ScheduledTaskTrigger -Once -At '00:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

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

Write-Ok "Scheduled task '$TaskName' registered (runs at logon + watchdog every 5 min)"

# ── Step 6: Start the agent now ─────────────────────────────────────────
Write-Step 'Starting agent'

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $TaskName
if ($task.State -eq 'Running') {
    Write-Ok 'Agent is running'
} else {
    Write-Host "    [WARN] Task state: $($task.State) - check logs at $LocalDataDir\logs\agent.log" -ForegroundColor Yellow
}

# ── Done ─────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  Installation complete!' -ForegroundColor Green
Write-Host "  Install directory: $InstallDir" -ForegroundColor Green
Write-Host "  Config:            $LocalConfigPath" -ForegroundColor Green
Write-Host "  Logs:              $LocalDataDir\logs\agent.log" -ForegroundColor Green
Write-Host "  Task name:         $TaskName" -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''
Write-Host 'The agent will start automatically at each user logon.' -ForegroundColor Gray
