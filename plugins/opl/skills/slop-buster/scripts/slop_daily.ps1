$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'slop_daily.py'
& py -3 -B -X utf8 $scriptPath @args
Write-Host "Slop Buster finished with exit code $LASTEXITCODE. Close this window when ready."
