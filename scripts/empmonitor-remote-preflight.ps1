param(
    [string]$ServerUrl = "",
    [switch]$SkipPackageCheck
)

$ErrorActionPreference = 'Stop'

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "==== $Title ====" -ForegroundColor Cyan
}

function Add-Result {
    param(
        [string]$Name,
        [object]$Value
    )

    $script:Report[$Name] = $Value
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PythonCommand {
    foreach ($commandName in @('py', 'python')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Get-PythonVersion {
    param([string]$PythonCommand)

    if (-not $PythonCommand) {
        return $null
    }

    try {
        if ((Split-Path $PythonCommand -Leaf).ToLower() -eq 'py.exe') {
            return (& $PythonCommand -3 --version 2>&1 | Out-String).Trim()
        }

        return (& $PythonCommand --version 2>&1 | Out-String).Trim()
    }
    catch {
        return "ERROR: $($_.Exception.Message)"
    }
}

function Test-PythonModules {
    param([string]$PythonCommand)

    if (-not $PythonCommand) {
        return @{ available = $false; details = 'Python not found' }
    }

    $modules = @('mss', 'requests', 'PIL', 'win32serviceutil')
    $result = [ordered]@{}

    foreach ($module in $modules) {
        try {
            if ((Split-Path $PythonCommand -Leaf).ToLower() -eq 'py.exe') {
                & $PythonCommand -3 -c "import $module" 2>$null
            }
            else {
                & $PythonCommand -c "import $module" 2>$null
            }

            $result[$module] = $LASTEXITCODE -eq 0
        }
        catch {
            $result[$module] = $false
        }
    }

    return @{ available = $true; details = $result }
}

function Get-UrlParts {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $null
    }

    try {
        $uri = [Uri]$Url
        $port = if ($uri.IsDefaultPort) {
            if ($uri.Scheme -eq 'https') { 443 } else { 80 }
        }
        else {
            $uri.Port
        }

        return [ordered]@{
            original = $Url
            host = $uri.Host
            scheme = $uri.Scheme
            port = $port
            base = "$($uri.Scheme)://$($uri.Authority)"
        }
    }
    catch {
        return @{ error = "Invalid URL: $Url" }
    }
}

function Test-ServerReachability {
    param([hashtable]$UrlParts)

    if (-not $UrlParts -or $UrlParts.error) {
        return @{ ok = $false; details = 'No valid server URL provided' }
    }

    $tcpTest = $null
    $httpStatus = $null
    $httpError = $null

    try {
        $tcpTest = Test-NetConnection -ComputerName $UrlParts.host -Port $UrlParts.port -InformationLevel Detailed -WarningAction SilentlyContinue
    }
    catch {
        $tcpTest = @{ TcpTestSucceeded = $false; Message = $_.Exception.Message }
    }

    try {
        $response = Invoke-WebRequest -Uri ($UrlParts.base + '/login/') -UseBasicParsing -TimeoutSec 10
        $httpStatus = $response.StatusCode
    }
    catch {
        if ($_.Exception.Response) {
            $httpStatus = [int]$_.Exception.Response.StatusCode
        }
        else {
            $httpError = $_.Exception.Message
        }
    }

    $remoteAddress = $tcpTest.RemoteAddress
    if ($remoteAddress -and $remoteAddress.IPAddressToString) {
        $remoteAddress = $remoteAddress.IPAddressToString
    }

    $sourceAddress = $tcpTest.SourceAddress
    if ($sourceAddress -and $sourceAddress.IPAddress) {
        $sourceAddress = $sourceAddress.IPAddress
    }

    return [ordered]@{
        ok = ($tcpTest.TcpTestSucceeded -eq $true)
        tcp = [ordered]@{
            computer = $UrlParts.host
            port = $UrlParts.port
            succeeded = $tcpTest.TcpTestSucceeded
            remoteAddress = $remoteAddress
            interfaceAlias = $tcpTest.InterfaceAlias
            sourceAddress = $sourceAddress
        }
        http = [ordered]@{
            loginUrl = $UrlParts.base + '/login/'
            statusCode = $httpStatus
            error = $httpError
        }
    }
}

function Get-NetworkSummary {
    $addresses = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notlike '127.*' -and
            $_.PrefixOrigin -ne 'WellKnown' -and
            $_.IPAddress -notlike '169.254*'
        } |
        Sort-Object InterfaceAlias, IPAddress |
        Select-Object InterfaceAlias, IPAddress, PrefixLength

    $zeroTier = $addresses | Where-Object { $_.InterfaceAlias -like '*ZeroTier*' }

    return [ordered]@{
        addresses = $addresses
        zeroTierAddresses = $zeroTier
    }
}

function Get-BasicSystemInfo {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem

    return [ordered]@{
        computerName = $env:COMPUTERNAME
        currentUser = "$env:USERDOMAIN\$env:USERNAME"
        isAdmin = Test-IsAdmin
        osCaption = $os.Caption
        osVersion = $os.Version
        lastBoot = $os.LastBootUpTime
        manufacturer = $cs.Manufacturer
        model = $cs.Model
    }
}

function Get-DisplaySummary {
    try {
        $monitors = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams -ErrorAction Stop
        return [ordered]@{
            count = @($monitors).Count
            detected = $true
        }
    }
    catch {
        return [ordered]@{
            count = $null
            detected = $false
            error = $_.Exception.Message
        }
    }
}

$script:Report = [ordered]@{}

Write-Host "EMP Monitor Remote Preflight" -ForegroundColor Green
Write-Host "This script does not install anything. It only collects the facts needed for deployment." -ForegroundColor DarkGray

if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
    $ServerUrl = Read-Host 'Enter the EMP Monitor server URL (example: http://10.147.17.89:8000)'
}

$serverParts = Get-UrlParts -Url $ServerUrl

Write-Section 'System'
$systemInfo = Get-BasicSystemInfo
$systemInfo.GetEnumerator() | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Key, $_.Value) }
Add-Result -Name 'system' -Value $systemInfo

Write-Section 'Network'
$network = Get-NetworkSummary
$network.addresses | Format-Table -AutoSize | Out-String | Write-Host
if (@($network.zeroTierAddresses).Count -gt 0) {
    Write-Host 'ZeroTier addresses detected:' -ForegroundColor Yellow
    $network.zeroTierAddresses | Format-Table -AutoSize | Out-String | Write-Host
}
else {
    Write-Host 'ZeroTier addresses detected: none'
}
Add-Result -Name 'network' -Value $network

Write-Section 'Display'
$display = Get-DisplaySummary
$display.GetEnumerator() | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Key, $_.Value) }
Add-Result -Name 'display' -Value $display

Write-Section 'Python'
$pythonCommand = Get-PythonCommand
$pythonVersion = Get-PythonVersion -PythonCommand $pythonCommand
Write-Host ("command: {0}" -f $(if ($pythonCommand) { $pythonCommand } else { 'not found' }))
Write-Host ("version: {0}" -f $(if ($pythonVersion) { $pythonVersion } else { 'not found' }))

$pythonData = [ordered]@{
    command = $pythonCommand
    version = $pythonVersion
}

if (-not $SkipPackageCheck) {
    $moduleCheck = Test-PythonModules -PythonCommand $pythonCommand
    if ($moduleCheck.available) {
        Write-Host 'modules:'
        $moduleCheck.details.GetEnumerator() | ForEach-Object {
            Write-Host ("  {0}: {1}" -f $_.Key, $(if ($_.Value) { 'installed' } else { 'missing' }))
        }
    }
    else {
        Write-Host ("modules: {0}" -f $moduleCheck.details)
    }

    $pythonData.modules = $moduleCheck
}

Add-Result -Name 'python' -Value $pythonData

Write-Section 'Server Reachability'
if ($serverParts.error) {
    Write-Host $serverParts.error -ForegroundColor Red
    Add-Result -Name 'server' -Value $serverParts
}
else {
    Write-Host ("server_url: {0}" -f $serverParts.original)
    $reachability = Test-ServerReachability -UrlParts $serverParts
    Write-Host ("tcp_succeeded: {0}" -f $reachability.tcp.succeeded)
    Write-Host ("source_address: {0}" -f $reachability.tcp.sourceAddress)
    Write-Host ("remote_address: {0}" -f $reachability.tcp.remoteAddress)
    Write-Host ("http_login_status: {0}" -f $(if ($reachability.http.statusCode) { $reachability.http.statusCode } else { 'no response' }))
    if ($reachability.http.error) {
        Write-Host ("http_error: {0}" -f $reachability.http.error) -ForegroundColor Yellow
    }

    Add-Result -Name 'server' -Value ([ordered]@{
        url = $serverParts
        reachability = $reachability
    })
}

Write-Section 'Recommended Next Step'
$serverReachable = $false
if ($script:Report.server -and $script:Report.server.reachability) {
    $serverReachable = $script:Report.server.reachability.ok -eq $true
}

$readyForInstall = $pythonCommand -and $pythonVersion -and $serverReachable

if ($readyForInstall) {
    Write-Host 'This PC can likely proceed to agent installation once you provide the agent token.' -ForegroundColor Green
}
else {
    Write-Host 'Do not install yet. Fix the failed prerequisite(s) first and rerun this script.' -ForegroundColor Yellow
}

$reportPath = Join-Path $env:TEMP ("empmonitor_preflight_{0}.json" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
$script:Report | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8

Write-Section 'Saved Report'
Write-Host $reportPath -ForegroundColor Green
Write-Host 'Send me the console output or the JSON file contents from that path.' -ForegroundColor DarkGray