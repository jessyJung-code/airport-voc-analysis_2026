$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot "dashboard_paths.json") -Raw | ConvertFrom-Json
python (Join-Path $PSScriptRoot "prepare_passenger_flow.py") --source $config.source_directory --output (Join-Path $PSScriptRoot "passenger_flow_data")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
