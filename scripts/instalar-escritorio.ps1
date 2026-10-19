# Instala o actualiza BOT_PDF con Docker en este equipo Windows y lo deja abierto
# en el navegador. Monta los discos del equipo dentro del contenedor para que las
# rutas locales funcionen igual que sin Docker: pegar "C:\Users\...\ENTRADA" o
# elegirla en el explorador de la pantalla.
#
#   instalar-docker            (el .cmd de la raiz: doble clic, CMD o PowerShell)
#   .\scripts\instalar-escritorio.ps1   (desde PowerShell)
#   instalar-docker -Puerto 8100        (otro puerto; queda guardado en .env)
#
# Los datos (salidas, libro mayor, usuarios, registro) viven en el volumen
# "bot_pdf_botpdf_data" y sobreviven a reconstruir la imagen o volver a clonar.

param([int]$Puerto = 0)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Paso($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

# -- 1. Docker instalado y encendido ---------------------------------------------
Paso "Verificando Docker..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker no esta instalado o no esta en el PATH. Instale Docker Desktop y vuelva a ejecutar este script."
}

function Docker-Encendido {
    # En Windows PowerShell 5.1, redirigir el error de un programa con "Stop"
    # lanza una excepcion en vez de solo marcar el fallo.
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { docker info *> $null } finally { $ErrorActionPreference = $anterior }
    return ($LASTEXITCODE -eq 0)
}

if (-not (Docker-Encendido)) {
    # Instalado para todos los usuarios o solo para este.
    $desktop = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe")
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($desktop) {
        Paso "Docker Desktop esta apagado; se enciende..."
        Start-Process $desktop | Out-Null
    }
    $limite = (Get-Date).AddMinutes(3)
    while (-not (Docker-Encendido)) {
        if ((Get-Date) -gt $limite) {
            throw "Docker no responde. Abra Docker Desktop, espere a que diga 'Engine running' y vuelva a ejecutar este script."
        }
        Start-Sleep -Seconds 5
    }
}

# -- 2. El .env con las llaves de la IA ------------------------------------------
if (-not (Test-Path (Join-Path $raiz ".env"))) {
    Copy-Item (Join-Path $raiz ".env.example") (Join-Path $raiz ".env")
    Write-Host "   Se creo .env a partir de .env.example: ponga ahi sus llaves (MISTRAL_API_KEY, ...)" -ForegroundColor Yellow
    Write-Host "   y vuelva a ejecutar este script para que el servicio las tome." -ForegroundColor Yellow
}

# -- 2b. El puerto ------------------------------------------------------------------
# 8000 por omision. Con -Puerto se usa otro y se guarda en .env (BOTPDF_PUERTO), para
# que la proxima vez y actualizar-docker usen el mismo sin decirlo.
$rutaEnv = Join-Path $raiz ".env"
$lineasEnv = @(if (Test-Path $rutaEnv) { Get-Content $rutaEnv })
$guardado = $lineasEnv | Where-Object { $_ -match '^\s*BOTPDF_PUERTO\s*=\s*\d+' } | Select-Object -Last 1
if ($Puerto -le 0) {
    $Puerto = 8000
    if ($guardado -and ($guardado -match '(\d+)\s*$')) { $Puerto = [int]$Matches[1] }
} else {
    $nuevas = @($lineasEnv | Where-Object { $_ -notmatch '^\s*BOTPDF_PUERTO\s*=' }) + "BOTPDF_PUERTO=$Puerto"
    [System.IO.File]::WriteAllLines($rutaEnv, [string[]]$nuevas, (New-Object System.Text.UTF8Encoding($false)))
}
$env:BOTPDF_PUERTO = "$Puerto"
$url = "http://localhost:$Puerto"

# Si el puerto lo usa otro programa (no el propio Docker), se dice antes de construir.
$escucha = Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($escucha) {
    $quien = (Get-Process -Id $escucha.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($quien -notmatch 'docker|wslrelay|vpnkit') {
        throw "El puerto $Puerto lo esta usando '$quien'. Detengalo o use otro puerto: instalar-docker -Puerto 8100"
    }
}
Paso "Puerto: $Puerto"

# -- 3. Los discos del equipo, montados dentro del contenedor ----------------------
# DriveType: 2 extraible, 3 disco local, 4 unidad de red. Los de red y extraibles
# (WorkDrive, OneDrive, USB) a veces no se dejan montar: si fallan, se reintenta
# solo con los discos locales y se avisa.
$unidades = @(Get-CimInstance Win32_LogicalDisk |
    Where-Object { $_.DriveType -in 2, 3, 4 -and (Test-Path "$($_.DeviceID)\") } |
    Sort-Object DeviceID)

function Escribir-Override($discos) {
    $lineas = @(
        "# Generado por scripts/instalar-escritorio.ps1 para este equipo: no se versiona.",
        "# Monta cada disco en /equipo/<letra> y le dice al servicio como traducir las rutas.",
        "services:",
        "  botpdf:",
        "    environment:"
    )
    $mapa = ($discos | ForEach-Object { "$($_.DeviceID)=/equipo/$($_.DeviceID.Substring(0,1).ToLower())" }) -join ";"
    $lineas += "      BOTPDF_UNIDADES: `"$mapa`""
    $lineas += "    volumes:"
    foreach ($d in $discos) {
        $letra = $d.DeviceID.Substring(0, 1)
        $lineas += "      - `"${letra}:/:/equipo/$($letra.ToLower())`""
    }
    $texto = ($lineas -join "`n") + "`n"
    # Sin BOM: es YAML para docker compose.
    [System.IO.File]::WriteAllText((Join-Path $raiz "docker-compose.override.yml"), $texto, (New-Object System.Text.UTF8Encoding($false)))
}

Paso ("Discos del equipo: " + (($unidades | ForEach-Object { $_.DeviceID }) -join ", "))
Escribir-Override $unidades

# -- 4. Construir y arrancar -----------------------------------------------------
Paso "Construyendo la imagen y arrancando (la primera vez tarda unos minutos)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    $locales = @($unidades | Where-Object { $_.DriveType -eq 3 })
    $fuera = @($unidades | Where-Object { $_.DriveType -ne 3 } | ForEach-Object { $_.DeviceID })
    if ($fuera.Count -eq 0) { throw "docker compose no pudo arrancar el servicio. Revise el mensaje de arriba." }
    Write-Host "   No se pudieron montar todas las unidades; se reintenta solo con los discos locales." -ForegroundColor Yellow
    Write-Host ("   Quedan fuera: " + ($fuera -join ", ") + ". Sus rutas no se veran desde el contenedor.") -ForegroundColor Yellow
    Escribir-Override $locales
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose no pudo arrancar el servicio. Revise el mensaje de arriba." }
}

# -- 5. Esperar a que conteste y abrir la pantalla ---------------------------------
Paso "Esperando a que el servicio conteste..."
$listo = $false
$limite = (Get-Date).AddMinutes(3)
while (-not $listo -and (Get-Date) -lt $limite) {
    try {
        $respuesta = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 "$url/api/health"
        $listo = ($respuesta.StatusCode -eq 200)
    } catch {
        Start-Sleep -Seconds 3
    }
}
docker compose ps
if (-not $listo) {
    throw "El servicio no contesto en 3 minutos. Vea el registro con: docker compose logs -f"
}

Write-Host ""
Write-Host "BOT_PDF listo en $url" -ForegroundColor Green
Write-Host "Registro en vivo:  docker compose logs -f" -ForegroundColor Yellow
Write-Host "Detenerlo:         docker compose down   (los datos se conservan)" -ForegroundColor Yellow
Start-Process $url
