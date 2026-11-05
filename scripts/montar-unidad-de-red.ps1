# Deja que el bot, en Docker, ESCRIBA en una unidad de red de Windows (W:, ...):
# la monta dentro del contenedor como un disco mas, con la cuenta que la abre.
#
#   .\scripts\montar-unidad-de-red.ps1 W             montarla (pide usuario y clave)
#   .\scripts\montar-unidad-de-red.ps1 W -Quitar     volver a leerla sin montarla
#
# Sin esto el contenedor lee las unidades de red con su cliente SMB, que solo
# lee: el destino tenia que estar en este equipo. El operador pidio el
# 2026-11-04 entregar en W:\FOLIA-BOT\MAGANGUE PROCESADO, el escritorio de otro
# equipo, y acepto que la clave quede guardada en la configuracion del volumen
# de Docker (botpdf-red-<letra>). No va a ningun archivo del repositorio ni al
# .env. Si cambia la clave, se vuelve a correr este script.
#
# Mientras este montada, si el otro equipo esta apagado el bot no arranca:
# Docker no puede montar la unidad. Se quita con -Quitar.

param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Letra,
    [string]$Usuario = "",
    [switch]$Quitar
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$Letra = $Letra.Trim().TrimEnd('\', ':').ToUpper()
if ($Letra -notmatch '^[A-Z]$') { throw "Indique la letra de la unidad, por ejemplo: W" }
$volumen = "botpdf-red-$($Letra.ToLower())"

function Paso($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

# Docker escribe su progreso por stderr; con "Stop", Windows PowerShell 5.1 lo
# toma por un error. Lo que decide es el codigo de salida.
function Hay-Volumen {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker volume inspect $volumen 2>$null | Out-Null
    $hay = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $anterior
    return $hay
}

function Quitar-Volumen {
    if (-not (Hay-Volumen)) { return }
    Paso "Deteniendo BOT_PDF para soltar la unidad (los datos se conservan)..."
    $ErrorActionPreference = "Continue"
    docker compose down
    docker volume rm $volumen | Out-Null
    $ErrorActionPreference = "Stop"
    if (Hay-Volumen) { throw "No se pudo quitar el volumen $volumen. Revise con: docker volume ls" }
}

if ($Quitar) {
    Quitar-Volumen
    Paso "La unidad ${Letra}: vuelve a leerse por la red, sin escribir en ella."
    & (Join-Path $PSScriptRoot "instalar-escritorio.ps1") -SinNavegador
    exit 0
}

# -- 1. La unidad y su servidor -------------------------------------------------
$unidad = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${Letra}:'"
if (-not $unidad -or $unidad.DriveType -ne 4 -or -not $unidad.ProviderName) {
    throw "La unidad ${Letra}: no es una unidad de red conectada en este equipo. Conectela en el Explorador y vuelva a correr el script."
}
$unc = $unidad.ProviderName.TrimEnd('\')
$servidor = $unc.TrimStart('\').Split('\')[0]
$dispositivo = "//" + ($unc.TrimStart('\') -replace '\\', '/')
# El kernel monta por direccion IP, no por nombre.
$direccion = $servidor
if ($servidor -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    $direccion = [System.Net.Dns]::GetHostAddresses($servidor) |
        Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1 -ExpandProperty IPAddressToString
    if (-not $direccion) { throw "No se pudo averiguar la direccion de $servidor." }
}
Paso "La unidad ${Letra}: es $unc"

# -- 2. Usuario y clave --------------------------------------------------------
# Se propone la cuenta con la que Windows ya abre ese servidor.
$propuesto = ""
$lineas = @(cmdkey /list)
for ($i = 0; $i -lt $lineas.Count; $i++) {
    if ($lineas[$i] -match "target=$([regex]::Escape($servidor))\s*$") {
        for ($j = $i + 1; $j -lt [Math]::Min($i + 4, $lineas.Count); $j++) {
            if ($lineas[$j] -match '^\s*(Usuario|User)\s*:\s*(.+?)\s*$') { $propuesto = $Matches[2]; break }
        }
        if ($propuesto) { break }
    }
}
if (-not $Usuario) {
    $pregunta = if ($propuesto) { "Usuario de $servidor [$propuesto]" } else { "Usuario de $servidor (DOMINIO\usuario)" }
    $Usuario = Read-Host $pregunta
    if (-not $Usuario) { $Usuario = $propuesto }
}
if (-not $Usuario) { throw "Hace falta el usuario con el que se abre $servidor." }
$dominio = ""
$nombre = $Usuario
if ($Usuario -match '^([^\\]+)\\(.+)$') { $dominio = $Matches[1]; $nombre = $Matches[2] }

$segura = Read-Host "Clave de $Usuario (no se muestra)" -AsSecureString
$puntero = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($segura)
try { $clave = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($puntero) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($puntero) }
if (-not $clave) { throw "Hace falta la clave." }

# En las opciones del montaje la coma separa: una coma de la clave va doble.
$opciones = @(
    "addr=$direccion",
    "username=$nombre",
    $(if ($dominio) { "domain=$dominio" }),
    "password=$($clave -replace ',', ',,')",
    "vers=3.0",
    "uid=0", "gid=0", "file_mode=0777", "dir_mode=0777",
    "iocharset=utf8",
    "noserverino"
) | Where-Object { $_ }
$o = $opciones -join ","
$clave = $null

# -- 3. El volumen, y la prueba de leer y escribir -----------------------------
Quitar-Volumen
Paso "Creando el volumen $volumen ($dispositivo)..."
$ErrorActionPreference = "Continue"
docker volume create --driver local --opt type=cifs --opt "device=$dispositivo" --opt "o=$o" $volumen | Out-Null
$creado = ($LASTEXITCODE -eq 0)
$o = $null
$ErrorActionPreference = "Stop"
if (-not $creado) { throw "Docker no pudo crear el volumen $volumen." }

Paso "Probando que el contenedor lee y escribe en ${Letra}:..."
$prueba = ".botpdf-prueba-de-escritura-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$ErrorActionPreference = "Continue"
docker run --rm -v "${volumen}:/m" botpdf:latest sh -c "ls /m > /dev/null && touch /m/$prueba && rm /m/$prueba"
$bien = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $bien) {
    $ErrorActionPreference = "Continue"
    docker volume rm $volumen | Out-Null
    $ErrorActionPreference = "Stop"
    throw "No se pudo montar ${Letra}: dentro de Docker (lo mas comun: usuario o clave). No quedo nada montado; vuelva a correr el script."
}
Paso "Montada: el bot lee y escribe en ${Letra}:"

# -- 4. El bot, con la unidad montada ------------------------------------------
& (Join-Path $PSScriptRoot "instalar-escritorio.ps1") -SinNavegador
