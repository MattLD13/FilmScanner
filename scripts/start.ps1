param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path 'apps/web/dist/index.html')) {
    npm --prefix apps/web install
    npm --prefix apps/web run build
}
python -m uvicorn services.api.main:app --host 127.0.0.1 --port $Port
