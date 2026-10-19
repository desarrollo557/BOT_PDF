# Actualiza BOT_PDF en Docker a la ultima version del repositorio:
# detiene el contenedor, trae los cambios y vuelve a construir y arrancar.
# Los datos (volumen bot_pdf_botpdf_data) y el .env se conservan.
#
#   actualizar-docker            (el .cmd de la raiz: doble clic, CMD o PowerShell)
#   .\scripts\actualizar-docker.ps1   (desde PowerShell)
#
# Equivale a: docker compose down; git pull; .\scripts\instalar-escritorio.ps1

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

Write-Host "==> Deteniendo BOT_PDF..." -ForegroundColor Cyan
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Host "   (no estaba corriendo)" -ForegroundColor Yellow }

if (Test-Path (Join-Path $raiz ".git")) {
    Write-Host "==> Trayendo la ultima version del repositorio..." -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "git pull no pudo avanzar (hay cambios locales o la rama diverge). Revise con: git status"
    }
}

& (Join-Path $PSScriptRoot "instalar-escritorio.ps1")
