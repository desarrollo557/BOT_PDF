$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "==> Verificando Docker..." -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker no está instalado ni disponible en PATH. Instálalo antes de ejecutar esta app."
}

Write-Host "==> Construyendo la imagen de BOT_PDF..." -ForegroundColor Cyan
docker compose build

Write-Host "==> Arrancando la aplicación..." -ForegroundColor Cyan
docker compose up -d

Write-Host "==> Estado del contenedor:" -ForegroundColor Cyan
docker compose ps

Write-Host "" 
Write-Host "La aplicación queda disponible en http://localhost:8000" -ForegroundColor Green
Write-Host "Para ver los logs: docker compose logs -f" -ForegroundColor Yellow
