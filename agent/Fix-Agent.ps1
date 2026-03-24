<#
.SYNOPSIS
    Quick-fix script for EMP Monitor agent on staff PCs.
    Fixes BOM in config.json, ensures correct token, copies latest main.py, restarts agent.

.DESCRIPTION
    Run this as Administrator on each staff PC.
    It will auto-detect the employee from the existing config, or you can specify one.
    All configuration is loaded from the .env file on the shared drive.

.PARAMETER Employee
    Employee name (must match a TOKEN_<name> entry in .env).

.EXAMPLE
    .\Fix-Agent.ps1 -Employee danita
    .\Fix-Agent.ps1                   # auto-detects from existing config
#>

param(
    [string]$Employee = ''
)

$ErrorActionPreference = 'Stop'

# ── Load .env configuration ─────────────────────────────────────────────
. "$PSScriptRoot\Load-EnvConfig.ps1"

$LegacyConfig = "$AgentDir\config.json"
$ConfigPath   = $LocalConfig

# Network share paths to try for latest main.py
$MainPySources = @()
foreach ($share in $SharePaths) {
    $MainPySources += "$share\DDC\tools\agent\main.py"
}

# ═══ Helpers ═════════════════════════════════════════════════════════════
function Write-Step($msg)  { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "    $msg" -ForegroundColor Gray }

# ═══ Start ═══════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor White
Write-Host "   EMP Monitor Agent - Quick Fix" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor White
Write-Host ""

# ── Step 1: Check admin ─────────────────────────────────────────────────
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "This script must be run as Administrator!"
    Write-Host "    Right-click PowerShell -> Run as Administrator" -ForegroundColor Yellow
    pause
    exit 1
}

# ── Step 2: Check agent dir exists ──────────────────────────────────────
Write-Step "Checking agent installation"
if (-not (Test-Path $AgentDir)) {
    Write-Fail "Agent directory not found: $AgentDir"
    Write-Host "    The agent is not installed on this PC. Run Setup-Agent.ps1 instead." -ForegroundColor Yellow
    pause
    exit 1
}
Write-Ok "Agent directory: $AgentDir"

# ── Step 3: Determine employee ──────────────────────────────────────────
Write-Step "Identifying employee"

if ($Employee -eq '') {
    $configsToTry = @($ConfigPath, $LegacyConfig)
    foreach ($cfgPath in $configsToTry) {
        if ($Employee -ne '') { break }
        if (Test-Path $cfgPath) {
            try {
                $rawBytes = [System.IO.File]::ReadAllBytes($cfgPath)
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
                            Write-Ok "Auto-detected: $Employee (from $cfgPath)"
                            break
                        }
                    }
                }
            } catch {
                Write-Warn "Could not parse config at ${cfgPath}: $_"
            }
        }
    }
}

if ($Employee -eq '') {
    if ($Tokens.Count -eq 0) {
        Write-Fail "No employee tokens found in .env file."
        pause
        exit 1
    }

    Write-Host ""
    Write-Host "    Could not auto-detect employee. Please choose:" -ForegroundColor Yellow
    Write-Host ""
    $names = @($Tokens.Keys | Sort-Object)
    for ($i = 0; $i -lt $names.Count; $i++) {
        Write-Host "      [$($i+1)] $($names[$i])" -ForegroundColor White
    }
    Write-Host ""
    $choice = Read-Host "    Enter number (1-$($names.Count))"
    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $names.Count) {
        Write-Fail "Invalid choice"
        pause
        exit 1
    }
    $Employee = $names[$idx]
}

$Employee = $Employee.ToLower()
if (-not $Tokens.ContainsKey($Employee)) {
    Write-Fail "Unknown employee: $Employee"
    Write-Host "    Available: $($Tokens.Keys -join ', ')" -ForegroundColor Yellow
    Write-Host "    Add TOKEN_$Employee=<token> to .env to register this employee." -ForegroundColor Yellow
    pause
    exit 1
}

$Token = $Tokens[$Employee]
Write-Ok "Employee: $Employee"
Write-Info "Token: $($Token.Substring(0,8))...$($Token.Substring($Token.Length - 4))"

# ── Step 4: Stop the agent ──────────────────────────────────────────────
Write-Step "Stopping agent"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Ok "Agent stopped"
} elseif ($task) {
    Write-Info "Agent was not running (state: $($task.State))"
} else {
    Write-Warn "Scheduled task '$TaskName' not found"
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

# ── Step 5: Copy latest main.py from share ──────────────────────────────
Write-Step "Updating main.py"
$copied = $false
foreach ($src in $MainPySources) {
    if (Test-Path $src) {
        try {
            Copy-Item $src "$AgentDir\main.py" -Force
            Write-Ok "Copied main.py from $src"
            $copied = $true
        } catch {
            Write-Warn "Could not overwrite main.py (file in use). Skipping file copy..."
            Write-Info "The agent will use the existing main.py (but we will still fix config.json)."
            $copied = $true
        }
        break
    }
}
if (-not $copied) {
    Write-Warn "Could not reach network share. main.py NOT updated."
    Write-Info "You may need to manually copy main.py to $AgentDir"
}

# ── Step 6: Fix config.json (LOCAL per-PC, BOM-free, correct token) ─────
Write-Step "Writing config.json to local PC"

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

[System.IO.File]::WriteAllText($ConfigPath, $config, (New-Object System.Text.UTF8Encoding $false))
Write-Ok "Config written to $ConfigPath"

if (Test-Path $LegacyConfig) {
    Remove-Item $LegacyConfig -Force -ErrorAction SilentlyContinue
    Write-Info "Removed shared-drive config.json (now stored locally)"
}

$verifyBytes = [System.IO.File]::ReadAllBytes($ConfigPath)
if ($verifyBytes[0] -eq 0xEF -and $verifyBytes[1] -eq 0xBB) {
    Write-Fail "BOM still present! Something went wrong."
    pause
    exit 1
}
Write-Ok "Verified: no BOM in config.json"

# ── Step 7: Check venv exists ────────────────────────────────────────────
Write-Step "Checking Python venv"
$VenvPythonw = "$VenvDir\Scripts\pythonw.exe"

if (Test-Path $VenvPythonw) {
    Write-Ok "Venv found: $VenvDir"
} else {
    Write-Warn "Venv not found at $VenvDir"
    Write-Info "The agent task may fail. Consider running Setup-Agent.ps1 or Update-DDCTools.ps1 to rebuild the venv."
}

# ── Step 8: Start the agent ─────────────────────────────────────────────
Write-Step "Starting agent"
if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $taskAfter = Get-ScheduledTask -TaskName $TaskName
    if ($taskAfter.State -eq 'Running') {
        Write-Ok "Agent is running!"
    } else {
        Write-Warn "Task state: $($taskAfter.State) (may still be starting)"
    }
} else {
    Write-Warn "No scheduled task found. Run Setup-Agent.ps1 to create one."
}

# ── Step 9: Quick verification ──────────────────────────────────────────
Write-Step "Verification"
$logDir = "$LocalDataDir\logs"
$logFile = Join-Path $logDir "agent.log"
if (Test-Path $logFile) {
    Write-Info "Latest log entries:"
    Get-Content $logFile -Tail 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
} else {
    Write-Info "Log file not found yet at $logFile (agent may need a moment)"
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "   FIX COMPLETE for $($Employee.ToUpper())" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Config: $ConfigPath" -ForegroundColor Gray
Write-Host "  Token:  $($Token.Substring(0,8))...$($Token.Substring($Token.Length - 4))" -ForegroundColor Gray
Write-Host "  Log:    $logFile" -ForegroundColor Gray
Write-Host ""
pause
