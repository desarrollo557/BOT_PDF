# Reune en un archivo todo lo necesario para saber por que BOT_PDF en Docker
# falla: estado y reinicios del contenedor, memoria, salud, una prueba de
# reconocimiento (no crea trabajos) y el registro. Deja "diagnostico-docker.txt"
# en la raiz del repositorio, para mirarlo o pegarlo.
#
#   diagnosticar-docker                        (CMD)  /  .\diagnosticar-docker.cmd (PowerShell)
#   .\diagnosticar-docker.cmd -Archivo "C:\ruta\al\archivo.pdf"   prueba tambien con ese PDF

param([string]$Archivo = "")

$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$salida = Join-Path $raiz "diagnostico-docker.txt"
$puerto = 8000
$rutaEnv = Join-Path $raiz ".env"
if (Test-Path $rutaEnv) {
    $linea = Get-Content $rutaEnv | Where-Object { $_ -match '^\s*BOTPDF_PUERTO\s*=\s*(\d+)' } | Select-Object -Last 1
    if ($linea -and ($linea -match '(\d+)\s*$')) { $puerto = [int]$Matches[1] }
}
$url = "http://localhost:$puerto"

function Seccion($titulo) { "`n===== $titulo =====" }
function Correr($bloque) { try { & $bloque 2>&1 | Out-String } catch { "ERROR: $_" } }

$informe = @()
$informe += "Diagnostico de BOT_PDF en Docker - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$informe += "Equipo: $env:COMPUTERNAME"

$informe += Seccion "Version del repositorio"
$informe += Correr { git log -1 --format="%h %s (%ad)" --date=short }
$informe += Correr { git status --short }

$informe += Seccion "Docker"
$informe += Correr { docker version --format "cliente {{.Client.Version}} / motor {{.Server.Version}}" }
$informe += Correr { docker info --format "memoria del motor: {{.MemTotal}} bytes, CPUs: {{.NCPU}}" }

$informe += Seccion "Contenedor"
$informe += Correr { docker compose ps }
$informe += Correr { docker inspect botpdf --format "estado={{.State.Status}} reinicios={{.RestartCount}} sin_memoria(OOMKilled)={{.State.OOMKilled}} ultimo_codigo_de_salida={{.State.ExitCode}} inicio={{.State.StartedAt}} salud={{if .State.Health}}{{.State.Health.Status}}{{end}}" }
$informe += Correr { docker stats --no-stream --format "CPU {{.CPUPerc}}  memoria {{.MemUsage}} ({{.MemPerc}})" botpdf }
$informe += Correr { docker exec botpdf df -h /data /tmp }
$informe += Correr { docker exec botpdf tesseract --version }
$informe += Correr { docker exec botpdf tesseract --list-langs }
$informe += Correr { docker exec botpdf python -c "import pymupdf; print('pymupdf', pymupdf.VersionBind)" }
$informe += Correr { docker exec botpdf python -c "import resolutions, pathlib; a = pathlib.Path(resolutions.__file__).parent / 'assets'; print('plantillas:', sorted(p.name for p in a.rglob('*') if p.is_file()))" }
$informe += Correr { docker exec botpdf sh -c "env | grep -E '^(BOTPDF|RESOLUTIONS)_' | sort; echo; env | grep -E '_API_KEY=' | sed -E 's/=(.{4}).*/=\1... (presente)/'" }
$informe += Correr { docker exec botpdf sh -c "ls /equipo 2>/dev/null && echo '(discos montados)' || echo 'sin /equipo: los discos del equipo no estan montados'" }

$informe += Seccion "Salud del servicio"
$informe += Correr { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "$url/api/health").Content }

# Un PDF minimo valido, para probar la subida sin depender de ningun archivo.
$minimo = Join-Path $env:TEMP "botpdf-prueba.pdf"
$pdf = "%PDF-1.4`n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj`n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj`n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj`ntrailer<</Root 1 0 R>>`n%%EOF`n"
[System.IO.File]::WriteAllText($minimo, $pdf, (New-Object System.Text.ASCIIEncoding))

$informe += Seccion "Prueba de reconocimiento con un PDF minimo (no crea trabajos)"
$informe += Correr { curl.exe -sS -m 120 -w "`nHTTP %{http_code} en %{time_total}s" -F "file=@$minimo;type=application/pdf" "$url/api/reconocer" }

if ($Archivo) {
    $informe += Seccion "Prueba de reconocimiento con $Archivo (no crea trabajos)"
    if (Test-Path $Archivo) {
        $informe += "tamano: {0:N1} MB" -f ((Get-Item $Archivo).Length / 1MB)
        $informe += Correr { curl.exe -sS -m 900 -w "`nHTTP %{http_code} en %{time_total}s" -F "file=@$Archivo;type=application/pdf" "$url/api/reconocer" }
    } else {
        $informe += "No existe: $Archivo"
    }
}

$informe += Seccion "Estado del contenedor despues de las pruebas"
$informe += Correr { docker inspect botpdf --format "estado={{.State.Status}} reinicios={{.RestartCount}} sin_memoria(OOMKilled)={{.State.OOMKilled}} ultimo_codigo_de_salida={{.State.ExitCode}}" }

$informe += Seccion "Registro del contenedor (ultimas 200 lineas)"
$informe += Correr { docker compose logs --no-color --tail 200 botpdf }

$informe += Seccion "Registro diario del servicio (ultimas 80 lineas)"
$informe += Correr { docker exec botpdf sh -c "ls -t /data/logs/bot-*.log 2>/dev/null | head -1 | xargs -r tail -n 80" }

$informe -join "`n" | Out-File -FilePath $salida -Encoding utf8
Remove-Item $minimo -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Diagnostico guardado en: $salida" -ForegroundColor Green
Write-Host "Abralo o peguelo completo para revisarlo." -ForegroundColor Yellow
