# Run robo-outlook with this repo's venv Python.
# Use this when plain `python` opens the Microsoft Store stub or is not on PATH.
#
#   .\scripts\run-outlook.ps1 -m robo_lukas.outlook search "read:no" --limit 5 --show-index 0 --format json
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Passthrough
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "No venv Python at:" $Py -ForegroundColor Red
    Write-Host "From repo root run:" -ForegroundColor Yellow
    Write-Host '  py -3.13 -m venv .venv' -ForegroundColor Gray
    Write-Host '  .\.venv\Scripts\Activate.ps1' -ForegroundColor Gray
    Write-Host '  pip install -e .' -ForegroundColor Gray
    exit 2
}
Set-Location -LiteralPath $RepoRoot
& $Py @Passthrough
exit $LASTEXITCODE
