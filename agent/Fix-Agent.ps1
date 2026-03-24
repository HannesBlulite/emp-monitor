<#
.SYNOPSIS
    Quick-fix script for EMP Monitor agent on staff PCs.
    Fixes BOM in config.json, ensures correct token, copies latest main.py, restarts agent.

.DESCRIPTION
    Run this as Administrator on each staff PC.
    It will auto-detect the employee from the existing config, or you can specify one.

.PARAMETER Employee
    Employee name: danita, janelda, jeandri, lizelle, monique, nicole, hannes

.EXAMPLE
    .\Fix-Agent.ps1 -Employee danita
    .\Fix-Agent.ps1                   # auto-detects from existing config
#>

param(
    [string]$Employee = ''
)

$ErrorActionPreference = 'Stop'

# ═══ Configuration ═══════════════════════════════════════════════════════
$AgentDir       = 'E:\DDC\tools\agent'
$LocalConfigDir = "$env:LOCALAPPDATA\DDC"
$ConfigPath     = "$LocalConfigDir\config.json"
$LegacyConfig   = "$AgentDir\config.json"
$TaskName       = 'EmpMonitorAgent'
$ServerUrl      = 'https://ddcemp.co.za'

# Employee token map (from production database)
$Tokens = @{
    'hannes'  = '57ec45bcb6c3bab3f789e2167997662b8aca0853775d7f44371e7bbf7bfec6a2'
    'danita'  = '8429a776498257c1b0913080b4847ce6226f3061866cc5f298a75420bfb914a6'
    'janelda' = 'd227b36070d2bdf2d85cc41e869a5bbdf6f2a519d2a38c9754f88977ee463abc'
    'jeandri' = '4f97e3f9f2c04b36d466c88aa29e4de9ad4775accefb3e6b325ba53f006d2c9d'
    'lizelle' = 'e55c692b08c1a58e5eb98962a648824d7a19cee39651d1425dd9f0b76fb87de4'
    'monique' = '4cc5908c6c7863b3c7d0b2174e29e6ce2f250717db617c1e6c93e60c2b3c43a4'
    'nicole'  = 'f5456d42c61c23bf9fe79513116ef356eefccde5c0e659f8312505e39a0283c7'
}

# Network share paths to try for latest main.py
$SharePaths = @(
    '\\10.147.17.115\EDrive\DDC\tools\agent\main.py'
)

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
    Write-Host "    The agent is not installed on this PC. Run Install-EmpAgent.ps1 instead." -ForegroundColor Yellow
    pause
    exit 1
}
Write-Ok "Agent directory: $AgentDir"

# ── Step 3: Determine employee ──────────────────────────────────────────
Write-Step "Identifying employee"

if ($Employee -eq '') {
    # Try to auto-detect from local config first, then legacy shared-drive config
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
    Write-Host ""
    Write-Host "    Could not auto-detect employee. Please choose:" -ForegroundColor Yellow
    Write-Host ""
    $names = @('danita', 'janelda', 'jeandri', 'lizelle', 'monique', 'nicole', 'hannes')
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
    Write-Host "    Valid names: $($Tokens.Keys -join ', ')" -ForegroundColor Yellow
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

# Also kill any stray pythonw processes running main.py
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
foreach ($src in $SharePaths) {
    if (Test-Path $src) {
        try {
            Copy-Item $src "$AgentDir\main.py" -Force
            Write-Ok "Copied main.py from $src"
            $copied = $true
        } catch {
            Write-Warn "Could not overwrite main.py (file in use). Skipping file copy..."
            Write-Info "The agent will use the existing main.py (but we will still fix config.json)."
            $copied = $true # Mark as 'handled' so we don't show the reachability error
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

if (-not (Test-Path $LocalConfigDir)) {
    New-Item -ItemType Directory -Path $LocalConfigDir -Force | Out-Null
}

$config = @{
    server_url                       = $ServerUrl
    agent_token                      = $Token
    screenshot_interval_seconds      = 300
    activity_report_interval_seconds = 60
    screenshot_quality               = 60
    screenshot_format                = 'JPEG'
    idle_threshold_seconds           = 120
    log_level                        = 'INFO'
} | ConvertTo-Json -Depth 2

# Write WITHOUT BOM
[System.IO.File]::WriteAllText($ConfigPath, $config, (New-Object System.Text.UTF8Encoding $false))
Write-Ok "Config written to $ConfigPath"

# Remove any shared-drive config to prevent confusion
if (Test-Path $LegacyConfig) {
    Remove-Item $LegacyConfig -Force -ErrorAction SilentlyContinue
    Write-Info "Removed shared-drive config.json (now stored locally)"
}

# Verify no BOM
$verifyBytes = [System.IO.File]::ReadAllBytes($ConfigPath)
if ($verifyBytes[0] -eq 0xEF -and $verifyBytes[1] -eq 0xBB) {
    Write-Fail "BOM still present! Something went wrong."
    pause
    exit 1
}
Write-Ok "Verified: no BOM in config.json"

# ── Step 7: Check venv exists ────────────────────────────────────────────
Write-Step "Checking Python venv"
$VenvDir = "$env:LOCALAPPDATA\DDC\agent-venv"
$VenvPythonw = "$VenvDir\Scripts\pythonw.exe"

if (Test-Path $VenvPythonw) {
    Write-Ok "Venv found: $VenvDir"
} else {
    Write-Warn "Venv not found at $VenvDir"
    Write-Info "The agent task may fail. Consider running Update-DDCTools.ps1 to rebuild the venv."
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
    Write-Warn "No scheduled task found. You may need to run Install-EmpAgent.ps1 first."
}

# ── Step 9: Quick verification ──────────────────────────────────────────
Write-Step "Verification"
$logDir = "$LocalConfigDir\logs"
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
