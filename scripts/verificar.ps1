# Lo mismo que corre CI, en la maquina, en el mismo orden.
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

$fallos = 0
function Paso($titulo, $bloque) {
    Write-Host ""
    Write-Host "-- $titulo --"
    & $bloque
    if ($LASTEXITCODE -eq 0) { Write-Host "   ok" }
    else { Write-Host "   FALLO"; $script:fallos++ }
}

$py = "python"
if (Test-Path "backend\.venv\Scripts\python.exe") { $py = ".\backend\.venv\Scripts\python.exe" }

Paso "Capas"               { & $py scripts\check_layers.py }
Paso "Lint del backend"    { Push-Location backend; & "..\$py" -m ruff check .; Pop-Location }
Paso "Pruebas del backend" { Push-Location backend; & "..\$py" -m pytest -q;    Pop-Location }
Paso "Tipos del front"     { Push-Location web; npm run check --silent; Pop-Location }
Paso "Pruebas del front"   { Push-Location web; npm run test --silent;  Pop-Location }
Paso "Build del front"     { Push-Location web; npm run build --silent; Pop-Location }

Write-Host ""
if ($fallos -eq 0) { Write-Host "Todo verde. El PR va a pasar." }
else { Write-Host "$fallos verificacion(es) en rojo. CI va a fallar igual." }
exit $fallos
