# Levanta el servicio entero con un solo comando: el backend y el front.
#
# En puertos que esten libres, y esa es la razon de que exista. Esta maquina
# corre otros servicios de Node -- habia uno escuchando en el 5173, que es justo
# el puerto por omision de Vite -- y arrancar encima de ellos o falla, o peor:
# Vite salta solo al siguiente y la direccion que uno tenia anotada deja de ser
# la buena sin que nadie lo diga.
#
#   .\scripts\levantar.ps1                  puertos automaticos
#   .\scripts\levantar.ps1 -WebPort 5200    uno concreto
#   .\scripts\levantar.ps1 -Fijo            falla si el pedido esta ocupado
#
# Ctrl+C para los dos. El front corre en primer plano y el backend se para en
# el bloque de limpieza, porque un backend que sobrevive al front es el que
# ocupa el 8000 la proxima vez y nadie se acuerda de por que.
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [switch]$Fijo
)

$ErrorActionPreference = "Stop"

function Test-PuertoLibre([int]$puerto) {
    # Por .NET y no por Get-NetTCPConnection: la misma comprobacion vale en
    # cualquier Windows y en PowerShell 5.1, que es el que hay en la maquina.
    $activos = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    foreach ($punto in $activos) {
        if ($punto.Port -eq $puerto) { return $false }
    }
    return $true
}

function Get-Puerto([int]$pedido, [string]$para) {
    if (Test-PuertoLibre $pedido) { return $pedido }
    if ($Fijo) {
        throw "El puerto $pedido esta ocupado y se pidio -Fijo. Libere el puerto o elija otro."
    }
    foreach ($candidato in ($pedido + 1)..($pedido + 40)) {
        if (Test-PuertoLibre $candidato) {
            Write-Host "   $pedido ocupado: $para se va al $candidato"
            return $candidato
        }
    }
    throw "No hay ningun puerto libre para $para entre el $pedido y el $($pedido + 40)."
}

$raiz = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$py = Join-Path $raiz "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if (-not (Test-Path (Join-Path $raiz "web\node_modules"))) {
    Write-Host "Falta web\node_modules. Corra primero:  cd web; npm install"
    exit 1
}

Write-Host ""
Write-Host "-- puertos --"
$ApiPort = Get-Puerto $ApiPort "el backend"
$WebPort = Get-Puerto $WebPort "el front"

Write-Host ""
Write-Host "-- backend --"
$argumentos = @("-m", "uvicorn", "resolutions.api.main:app", "--port", "$ApiPort")
$backend = Start-Process -FilePath $py -ArgumentList $argumentos -WorkingDirectory (Join-Path $raiz "backend") -PassThru -NoNewWindow

try {
    # Se espera a que conteste antes de arrancar el front. Sin esto, las
    # primeras peticiones del navegador atraviesan un proxy que apunta a un
    # puerto todavia mudo, y la pantalla abre con errores de red que no son
    # ciertos treinta segundos despues.
    $listo = $false
    foreach ($intento in 1..60) {
        if ($backend.HasExited) {
            throw "El backend se cayo al arrancar (codigo $($backend.ExitCode))."
        }
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $listo = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $listo) { throw "El backend no contesto en el $ApiPort al cabo de 30 segundos." }
    Write-Host "   escuchando en http://127.0.0.1:$ApiPort"

    # El proxy del servidor de desarrollo lee esta variable. Sin ella apunta al
    # 8000 fijo, que es lo correcto de costumbre y lo equivocado en cuanto el
    # backend tuvo que irse a otro puerto.
    $env:API_URL = "http://127.0.0.1:$ApiPort"

    Write-Host ""
    Write-Host "-- front --"
    Write-Host "   abra http://localhost:$WebPort"
    Write-Host "   Ctrl+C para parar los dos"
    Write-Host ""

    Push-Location (Join-Path $raiz "web")
    try {
        # Se llama a Vite directo y no por "npm run dev -- ...". PowerShell se
        # come el "--" -- lo trata como su propio fin de parametros -- asi que
        # npm recibia "--port 5174" como configuracion suya, la descartaba, y
        # Vite arrancaba con "5174" de directorio raiz: sin vite.config.ts, sin
        # el proxy de /api y en el puerto que le diera la gana.
        #
        # --strictPort a proposito: si el puerto se ocupo entre la comprobacion
        # y este momento, es mejor un fallo que Vite mudandose en silencio.
        $vite = Join-Path $raiz "web/node_modules/.bin/vite.cmd"
        & $vite dev --port $WebPort --strictPort
    } finally {
        Pop-Location
    }
} finally {
    Write-Host ""
    if (-not $backend.HasExited) {
        # El arbol entero: el backend arranca un proceso por documento, y matar
        # solo al padre deja los hijos ocupando memoria y el puerto a medias.
        taskkill /PID $backend.Id /T /F 2>&1 | Out-Null
        Write-Host "backend detenido."
    }
}
