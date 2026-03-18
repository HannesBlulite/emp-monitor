<#
.SYNOPSIS
    Builds the EMP Monitor Agent deployment ZIP.

.DESCRIPTION
    Creates a distributable empmonitor-agent.zip that contains all agent files
    plus the install/uninstall scripts. Copy this ZIP to a staff PC, extract,
    and run the installer.
#>

$AgentDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputDir = Join-Path (Split-Path -Parent $AgentDir) 'dist'
$ZipName   = 'empmonitor-agent.zip'
$ZipPath   = Join-Path $OutputDir $ZipName

# Files to include in the package
$files = @(
    '__init__.py',
    'main.py',
    'activity.py',
    'browser_url.py',
    'screenshot.py',
    'server_comm.py',
    'service.py',
    'version.py',
    'updater.py',
    'config.json',
    'requirements-agent.txt',
    'Install-EmpAgent.ps1',
    'Uninstall-EmpAgent.ps1'
)

# Create output directory
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Create a temp staging folder
$staging = Join-Path $env:TEMP "empmonitor-agent-staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

# Copy files to staging
foreach ($f in $files) {
    $src = Join-Path $AgentDir $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $staging $f)
        Write-Host "  + $f" -ForegroundColor Gray
    } else {
        Write-Host "  [SKIP] $f not found" -ForegroundColor Yellow
    }
}

# Create ZIP
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path "$staging\*" -DestinationPath $ZipPath -CompressionLevel Optimal

# Cleanup
Remove-Item $staging -Recurse -Force

$size = [math]::Round((Get-Item $ZipPath).Length / 1KB, 1)
Write-Host ''
Write-Host "Package built: $ZipPath ($size KB)" -ForegroundColor Green
Write-Host ''
Write-Host 'Deployment instructions:' -ForegroundColor Cyan
Write-Host '  1. Copy the ZIP to the staff PC'
Write-Host '  2. Extract to any folder'
Write-Host '  3. Open PowerShell as Administrator in that folder'
Write-Host '  4. Run:  .\Install-EmpAgent.ps1 -AgentToken "TOKEN_FROM_ADMIN_PANEL"'
