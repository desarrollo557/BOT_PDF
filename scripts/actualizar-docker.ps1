# Actualiza BOT_PDF en Docker a la ultima version del repositorio:
# detiene el contenedor, trae los cambios y vuelve a construir y arrancar.
# Los datos (volumen bot_pdf_botpdf_data) y el .env se conservan.
#
#   actualizar-docker            (el .cmd de la raiz: doble clic, CMD o PowerShell)
#   .\scripts\actualizar-docker.ps1   (desde PowerShell)
#
# Equivale a: docker compose down; git pull; .\scripts\instalar-escritorio.ps1

param([int]$Puerto = 0)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

Write-Host "==> Deteniendo BOT_PDF..." -ForegroundColor Cyan
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Host "   (no estaba corriendo)" -ForegroundColor Yellow }

if (Test-Path (Join-Path $raiz ".git")) {
    # Cambios hechos a mano en este equipo (el Dockerfile, el compose...) impiden
    # el pull. Se apartan con git stash -- no se borran: "git stash list" los
    # muestra y "git stash pop" los recupera -- y se sigue con la version nueva.
    $cambios = git status --porcelain --untracked-files=no
    if ($cambios) {
        Write-Host "==> Hay cambios locales; se guardan aparte con git stash:" -ForegroundColor Yellow
        $cambios | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow }
        git stash push -m "actualizar-docker: cambios locales antes de actualizar"
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron apartar los cambios locales. Revise con: git status" }
    }
    Write-Host "==> Trayendo la ultima version del repositorio..." -ForegroundColor Cyan
    git fetch --quiet
    if ($LASTEXITCODE -ne 0) { throw "No se pudo traer la version nueva (git fetch). Revise la conexion a internet." }
    # Un archivo suelto (sin seguimiento) que la version nueva trae con el mismo
    # nombre frena el pull: "untracked working tree files would be overwritten"
    # (2026-10-29, una copia a mano de scripts\renombrar_reclamaciones.py). Se
    # aparta a .actualizar-respaldo\<fecha>\ -- no se borra -- y se sigue.
    $sueltos = @(git ls-files --others --exclude-standard)
    $respaldo = Join-Path $raiz (".actualizar-respaldo\" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
    foreach ($suelto in $sueltos) {
        git cat-file -e "@{u}:$suelto" 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $destino = Join-Path $respaldo $suelto
        New-Item -ItemType Directory -Force (Split-Path $destino) | Out-Null
        Move-Item -LiteralPath (Join-Path $raiz $suelto) -Destination $destino
        Write-Host "   La version nueva trae $suelto; la copia suelta se aparto en $destino" -ForegroundColor Yellow
    }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "git pull no pudo avanzar (hay cambios locales o la rama diverge). Revise con: git status"
    }
}

& (Join-Path $PSScriptRoot "instalar-escritorio.ps1") -Puerto $Puerto
