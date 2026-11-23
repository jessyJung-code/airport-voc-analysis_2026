$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python (Join-Path $PSScriptRoot "build_dg_sg_months.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python (Join-Path $PSScriptRoot "prepare_dg_rates.py")
