# Actualiza BOT_PDF en Docker a la ultima version del repositorio:
# trae los cambios y, solo si llegaron, detiene el contenedor y vuelve a
# construir y arrancar. Los datos (volumen bot_pdf_botpdf_data) y el .env se
# conservan.
#
#   actualizar-docker            (el .cmd de la raiz: doble clic, CMD o PowerShell)
#   .\scripts\actualizar-docker.ps1   (desde PowerShell)
#
# Equivale a: git pull; docker compose down; .\scripts\instalar-escritorio.ps1

param([int]$Puerto = 0)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# Primero la version nueva y despues detener: si git no puede avanzar, el bot
# sigue funcionando con la version de antes. Al reves, un pull que fallaba lo
# dejaba apagado (2026-10-29, dos veces seguidas).
if (Test-Path (Join-Path $raiz ".git")) {
    # Aqui decide el codigo de salida de cada comando, no lo que escriban en su
    # salida de errores: con "Stop", Windows PowerShell 5.1 corta en cuanto un
    # programa escribe ahi si se redirige, aunque haya terminado bien.
    $ErrorActionPreference = "Continue"

    # Cambios hechos a mano en este equipo (el Dockerfile, el compose...) impiden
    # el pull. Se apartan con git stash -- no se borran: "git stash list" los
    # muestra y "git stash pop" los recupera -- y se sigue con la version nueva.
    $cambios = git status --porcelain --untracked-files=no
    if ($cambios) {
        Write-Host "==> Hay cambios locales; se guardan aparte con git stash:" -ForegroundColor Yellow
        $cambios | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow }
        git stash push -m "actualizar-docker: cambios locales antes de actualizar"
        if ($LASTEXITCODE -ne 0) { throw "No se pudieron apartar los cambios locales; el bot sigue con la version de antes. Revise con: git status" }
    }
    Write-Host "==> Trayendo la ultima version del repositorio..." -ForegroundColor Cyan
    git fetch --quiet
    if ($LASTEXITCODE -ne 0) { throw "No se pudo traer la version nueva (git fetch); el bot sigue con la version de antes. Revise la conexion a internet." }

    # Un archivo suelto (sin seguimiento) que la version nueva trae con el mismo
    # nombre frena el pull: "untracked working tree files would be overwritten"
    # (2026-10-29, una copia a mano de scripts\renombrar_reclamaciones.py). Se
    # aparta a .actualizar-respaldo\<fecha>\ -- no se borra -- y se sigue. Se
    # compara con la lista de la version nueva: preguntar archivo por archivo
    # escribia un error por cada suelto que no esta en ella (.opencode\...).
    $nuevos = @(git -c core.quotepath=off ls-tree -r --name-only "@{u}")
    if ($LASTEXITCODE -ne 0) { throw "No se pudo leer la version nueva (git ls-tree); el bot sigue con la version de antes. Revise con: git status" }
    $deLaNueva = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($nuevo in $nuevos) { [void]$deLaNueva.Add($nuevo) }
    $respaldo = Join-Path $raiz (".actualizar-respaldo\" + (Get-Date -Format "yyyy-MM-dd_HHmmss"))
    foreach ($suelto in @(git -c core.quotepath=off ls-files --others --exclude-standard)) {
        if ($suelto.EndsWith("/")) {
            # Una carpeta entera (un repositorio dentro de otro): choca si la
            # version nueva trae algo dentro.
            $choca = @($nuevos | Where-Object { $_.StartsWith($suelto, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
        } else {
            $choca = $deLaNueva.Contains($suelto)
        }
        if (-not $choca) { continue }
        $limpio = $suelto.TrimEnd("/")
        $destino = Join-Path $respaldo $limpio
        New-Item -ItemType Directory -Force (Split-Path $destino) | Out-Null
        Move-Item -LiteralPath (Join-Path $raiz $limpio) -Destination $destino
        Write-Host "   La version nueva trae $limpio; la copia suelta se aparto en $destino" -ForegroundColor Yellow
    }

    git merge --ff-only "@{u}"
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo avanzar a la version nueva (hay cambios locales o la rama diverge); el bot sigue con la version de antes. Revise con: git status"
    }
    $ErrorActionPreference = "Stop"
}

Write-Host "==> Deteniendo BOT_PDF..." -ForegroundColor Cyan
docker compose down
if ($LASTEXITCODE -ne 0) { Write-Host "   (no estaba corriendo)" -ForegroundColor Yellow }

& (Join-Path $PSScriptRoot "instalar-escritorio.ps1") -Puerto $Puerto
