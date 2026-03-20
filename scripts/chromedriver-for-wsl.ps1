#Requires -Version 5.1
<#
.SYNOPSIS
  Starts Windows ChromeDriver so Python/Selenium running in WSL can drive Windows Chrome.

.DESCRIPTION
  WSL and Windows have different loopback interfaces: chromedriver.exe listening on 127.0.0.1
  on Windows is NOT reachable as 127.0.0.1 from WSL. This script:
    1) Reads your WSL guest IP (source of connections from WSL to Windows)
    2) Starts chromedriver with --allowed-ips=<that IP>
    3) Prints the export line for WSL: CHROMEDRIVER_REMOTE_URL=http://<Windows host>:<port>

  Keep this PowerShell window open while using robo-outlook from WSL.

  ChromeDriver: keep chromedriver.exe under %LOCALAPPDATA%\robo-lukas\chromedriver-win64\
  (recommended). This script also checks Downloads\chromedriver-win64 for a quick unzip.

.NOTES
  If the connection still fails, Windows Firewall may be blocking inbound TCP on $Port.
#>

param(
    [Parameter(Mandatory = $false)]
    [string] $ChromeDriverExe = "",

    [int] $Port = 9515
)

$searchPaths = @(
    "$env:LOCALAPPDATA\robo-lukas\chromedriver-win64\chromedriver.exe",
    "$env:USERPROFILE\Downloads\chromedriver-win64\chromedriver.exe"
)

if ([string]::IsNullOrWhiteSpace($ChromeDriverExe)) {
    foreach ($p in $searchPaths) {
        if (Test-Path -LiteralPath $p) {
            $ChromeDriverExe = $p
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($ChromeDriverExe) -or -not (Test-Path -LiteralPath $ChromeDriverExe)) {
    Write-Error @"
ChromeDriver not found.
  Tried:
$(($searchPaths | ForEach-Object { "    $_" }) -join "`n")
  Pass an explicit path:
    .\scripts\chromedriver-for-wsl.ps1 -ChromeDriverExe 'C:\path\to\chromedriver.exe'
"@
    exit 1
}

$resolv = wsl.exe -e cat /etc/resolv.conf 2>$null
if (-not $resolv) {
    Write-Error "Could not run: wsl.exe -e cat /etc/resolv.conf"
    exit 1
}
$winHost = ($resolv | Select-String -Pattern 'nameserver\s+(\S+)' | ForEach-Object { $_.Matches.Groups[1].Value } | Select-Object -First 1)
if (-not $winHost) {
    Write-Error "Could not parse nameserver from WSL resolv.conf"
    exit 1
}

$wslIp = (wsl.exe -e hostname -I 2>$null).Trim() -split '\s+' | Select-Object -First 1
if (-not $wslIp) {
    Write-Error "Could not get WSL IP from: wsl.exe -e hostname -I"
    exit 1
}

Write-Host "=== robo-lukas: ChromeDriver for WSL bridge ===" -ForegroundColor Cyan
Write-Host "Using:       $ChromeDriverExe"
Write-Host "Port:         $Port"
Write-Host "Allow WSL IP: $wslIp"
Write-Host ""
Write-Host "In WSL, run (or put in .env as CHROMEDRIVER_REMOTE_URL):" -ForegroundColor Yellow
Write-Host "  export CHROMEDRIVER_REMOTE_URL=http://${winHost}:$Port"
Write-Host ""
Write-Host "Press Ctrl+C here to stop ChromeDriver." -ForegroundColor DarkGray
Write-Host ""

& $ChromeDriverExe --port=$Port --allowed-ips=$wslIp
