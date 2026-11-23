$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python -m streamlit run (Join-Path $PSScriptRoot "voc_dashboard_app.py")
