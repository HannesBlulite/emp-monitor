param(
    [string]$Domain = "",
    [string]$DropletIp = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = 'Stop'

function New-RandomSecret {
    param([int]$ByteCount = 48)

    $bytes = New-Object byte[] $ByteCount
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=')
}

if ([string]::IsNullOrWhiteSpace($Domain)) {
    $Domain = Read-Host 'Enter production domain name (leave blank if using IP only)'
}

if ([string]::IsNullOrWhiteSpace($DropletIp)) {
    $DropletIp = Read-Host 'Enter droplet public IP address'
}

$allowedHosts = @()
$csrfOrigins = @()

if (-not [string]::IsNullOrWhiteSpace($Domain)) {
    $allowedHosts += $Domain
    $csrfOrigins += "https://$Domain"
}

if (-not [string]::IsNullOrWhiteSpace($DropletIp)) {
    $allowedHosts += $DropletIp
}

$djangoSecret = New-RandomSecret -ByteCount 64
$dbPassword = New-RandomSecret -ByteCount 32

$envContent = @"
DJANGO_SECRET_KEY=$djangoSecret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=$($allowedHosts -join ',')
DJANGO_CSRF_TRUSTED_ORIGINS=$($csrfOrigins -join ',')
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True

DB_ENGINE=django.db.backends.postgresql
DB_NAME=empmonitor
DB_USER=empmonitor
DB_PASSWORD=$dbPassword
DB_HOST=127.0.0.1
DB_PORT=5432

SCREENSHOT_RETENTION_DAYS=30
ACTIVITY_LOG_RETENTION_DAYS=90
"@

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $env:TEMP ("empmonitor-production-{0}.env" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
}

Set-Content -Path $OutputPath -Value $envContent -Encoding UTF8

Write-Host "Production env file generated:" -ForegroundColor Green
Write-Host $OutputPath -ForegroundColor Green
Write-Host ""
Write-Host "Use this file as /opt/emp-monitor/.env on the droplet." -ForegroundColor Cyan
Write-Host "Keep it private. It contains real secrets." -ForegroundColor Yellow