<#
.SYNOPSIS
    Loads the .env configuration file for EMP Monitor Agent scripts.

.DESCRIPTION
    Dot-source this file from any agent script to get:
      - $EnvConfig     : hashtable of all KEY=VALUE pairs from .env
      - $Tokens        : hashtable of employee name -> token
      - $ServerUrl     : server URL
      - $SharePaths    : array of network share UNC paths
      - $AgentDir      : agent install directory path
      - $TaskName      : scheduled task name
      - $AgentSettings : hashtable of default agent config values

    The .env file is searched in this order:
      1. Same folder as the calling script ($PSScriptRoot)
      2. E:\DDC\tools\agent\.env
      3. Each UNC share path: \\share\DDC\tools\agent\.env

.EXAMPLE
    . "$PSScriptRoot\Load-EnvConfig.ps1"
    Write-Host $ServerUrl
    Write-Host $Tokens['hannes']
#>

function Read-EnvFile {
    param([string]$Path)

    $result = @{}
    if (-not (Test-Path $Path)) { return $result }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#')) {
            $eqIdx = $line.IndexOf('=')
            if ($eqIdx -gt 0) {
                $key = $line.Substring(0, $eqIdx).Trim()
                $val = $line.Substring($eqIdx + 1).Trim()
                $result[$key] = $val
            }
        }
    }
    return $result
}

# ── Locate .env file ─────────────────────────────────────────────────────

$_envPath = $null
$_searchLocations = @(
    (Join-Path $PSScriptRoot '.env'),
    'E:\DDC\tools\agent\.env',
    '\\DDCSERVER-PC\EDrive\DDC\tools\agent\.env',
    '\\10.147.17.115\EDrive\DDC\tools\agent\.env'
)

foreach ($_loc in $_searchLocations) {
    if (Test-Path $_loc) {
        $_envPath = $_loc
        break
    }
}

if (-not $_envPath) {
    Write-Host '[ENV] WARNING: .env file not found. Using hardcoded defaults.' -ForegroundColor Yellow
    Write-Host "      Searched: $($_searchLocations -join ', ')" -ForegroundColor Yellow

    $EnvConfig     = @{}
    $Tokens        = @{}
    $ServerUrl     = 'https://ddcemp.co.za'
    $SharePaths    = @('\\DDCSERVER-PC\EDrive', '\\10.147.17.115\EDrive')
    $AgentDir      = 'E:\DDC\tools\agent'
    $TaskName      = 'EmpMonitorAgent'
    $AgentSettings = @{
        screenshot_interval_seconds      = 300
        activity_report_interval_seconds = 60
        screenshot_quality               = 60
        screenshot_format                = 'JPEG'
        idle_threshold_seconds           = 120
        log_level                        = 'INFO'
    }
} else {
    Write-Host "[ENV] Loaded: $_envPath" -ForegroundColor DarkGray

    $EnvConfig = Read-EnvFile $_envPath

    # ── Parse well-known keys ─────────────────────────────────────────────
    $ServerUrl  = if ($EnvConfig.ContainsKey('SERVER_URL'))  { $EnvConfig['SERVER_URL'] }  else { 'https://ddcemp.co.za' }
    $AgentDir   = if ($EnvConfig.ContainsKey('AGENT_DIR'))   { $EnvConfig['AGENT_DIR'] }   else { 'E:\DDC\tools\agent' }
    $TaskName   = if ($EnvConfig.ContainsKey('TASK_NAME'))   { $EnvConfig['TASK_NAME'] }   else { 'EmpMonitorAgent' }

    if ($EnvConfig.ContainsKey('SHARE_PATHS')) {
        $SharePaths = $EnvConfig['SHARE_PATHS'] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    } else {
        $SharePaths = @('\\DDCSERVER-PC\EDrive', '\\10.147.17.115\EDrive')
    }

    # ── Build token map from TOKEN_* keys ─────────────────────────────────
    $Tokens = @{}
    foreach ($key in $EnvConfig.Keys) {
        if ($key -match '^TOKEN_(.+)$') {
            $empName = $Matches[1].ToLower()
            $Tokens[$empName] = $EnvConfig[$key]
        }
    }

    # ── Agent default settings ────────────────────────────────────────────
    $AgentSettings = @{
        screenshot_interval_seconds      = [int](if ($EnvConfig.ContainsKey('SCREENSHOT_INTERVAL'))       { $EnvConfig['SCREENSHOT_INTERVAL'] }       else { 300 })
        activity_report_interval_seconds = [int](if ($EnvConfig.ContainsKey('ACTIVITY_REPORT_INTERVAL'))  { $EnvConfig['ACTIVITY_REPORT_INTERVAL'] }  else { 60 })
        screenshot_quality               = [int](if ($EnvConfig.ContainsKey('SCREENSHOT_QUALITY'))        { $EnvConfig['SCREENSHOT_QUALITY'] }        else { 60 })
        screenshot_format                = if ($EnvConfig.ContainsKey('SCREENSHOT_FORMAT'))                { $EnvConfig['SCREENSHOT_FORMAT'] }         else { 'JPEG' }
        idle_threshold_seconds           = [int](if ($EnvConfig.ContainsKey('IDLE_THRESHOLD'))            { $EnvConfig['IDLE_THRESHOLD'] }            else { 120 })
        log_level                        = if ($EnvConfig.ContainsKey('LOG_LEVEL'))                       { $EnvConfig['LOG_LEVEL'] }                 else { 'INFO' }
    }
}

# ── Convenience: local data paths (always per-PC) ────────────────────────
$LocalDataDir  = "$env:LOCALAPPDATA\DDC"
$LocalConfig   = "$LocalDataDir\config.json"
$VenvDir       = "$LocalDataDir\agent-venv"
