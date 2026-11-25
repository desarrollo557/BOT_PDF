<# :
@echo off
rem Instala BOT_PDF (Folia) en un PC nuevo, o lo pone al dia, con un doble clic.
rem Copie este archivo al PC (USB o carpeta compartida) y abralo.
rem Solo revisar, sin cambiar nada:  set BOTPDF_SOLO_REVISAR=1 & instalar-equipo-nuevo.cmd
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((Get-Content -LiteralPath '%~f0' -Raw)))"
set CODIGO=%ERRORLEVEL%
echo.
pause
exit /b %CODIGO%
#>

# -- Lo que se puede ajustar ----------------------------------------------------
$Repositorio = "https://github.com/desarrollo557/BOT_PDF.git"
$Rama        = "produccion"
$Carpeta     = Join-Path $env:USERPROFILE "Desktop\BOT_PDF"
# El puerto de la pantalla: el primero libre de esta lista. Otro programa puede
# tener el 8100 (LibreOffice lo usa por omision): entonces se usa el siguiente.
$PuertosPosibles = @(8100, 8200, 8300, 8400, 8500, 8600, 8700, 8800, 8900, 9100, 9200)
# El destino compartido de las corridas: el escritorio del PC de SIAR1.
$Servidor    = "200.100.20.101"
$Recurso     = "\\200.100.20.101\Users\SIAR1\Desktop"
# La letra para conectarlo: la que ya lo tenga, o la primera libre de esta
# lista. En cada PC puede ser otra: en la pantalla el destino se pega siempre
# como ruta de red, igual en todos.
$LetrasPosibles = "WVUTSRQPONMLKJIHGFE"
$Cuenta      = "SIAR\SIAR1"
$Origen      = "\\200.100.20.97\afinia\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MAGANGUE"
$Destino     = "MAGANGUE PRUEBA PILOTO"
# -------------------------------------------------------------------------------

$ErrorActionPreference = "Continue"
$SoloRevisar = [bool]$env:BOTPDF_SOLO_REVISAR

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Bien($texto) { Write-Host "    OK  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    !!  $texto" -ForegroundColor Yellow }
function Falla($texto) { Write-Host ""; Write-Host "    XX  $texto" -ForegroundColor Red; exit 1 }
function Pregunta($texto) { (Read-Host "    $texto (S/N)").Trim().ToUpper().StartsWith("S") }
function Hay($comando) { [bool](Get-Command $comando -ErrorAction SilentlyContinue) }
function Refrescar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Docker-Responde { docker info --format "{{.NCPU}}" 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
function Abrir-Docker {
    $candidatos = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
    )
    $exe = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) { Falla "No se encontro Docker Desktop. Abralo a mano y vuelva a correr este archivo." }
    Start-Process $exe
    Write-Host "    Esperando a que Docker arranque (hasta 4 minutos). Si Docker Desktop muestra sus"
    Write-Host "    condiciones, aceptelas en su ventana."
    for ($i = 0; $i -lt 48; $i++) {
        Start-Sleep -Seconds 5
        if (Docker-Responde) { return }
    }
    # Lo mas comun en un PC nuevo: WSL (lo que usa Docker) sin instalar o viejo.
    Aviso "Docker no arranco. Se instala o actualiza WSL, que es lo que usa Docker (pide permiso de administrador)."
    Start-Process wsl -ArgumentList "--install", "--no-distribution" -Verb RunAs -Wait -ErrorAction SilentlyContinue
    Start-Process wsl -ArgumentList "--update" -Verb RunAs -Wait -ErrorAction SilentlyContinue
    Falla "REINICIE EL PC y vuelva a abrir este archivo. Si sigue igual, active la virtualizacion (VT-x / SVM) en la BIOS."
}
function Ejecutar-Script($ruta, [string[]]$argumentos) {
    # En esta misma ventana y sin capturar lo que escribe: asi se ven sus
    # mensajes y puede pedir usuario y clave. Solo se lee su codigo de salida
    # (capturarlo todo mezclaba sus mensajes con el codigo, y una instalacion
    # que habia salido bien se daba por fallida).
    $lista = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ruta`"") + $argumentos
    $proceso = Start-Process powershell -ArgumentList $lista -NoNewWindow -PassThru
    $null = $proceso.Handle
    $proceso.WaitForExit()
    return [int]$proceso.ExitCode
}

Write-Host "Instalacion de BOT_PDF (Folia) en $env:COMPUTERNAME" -ForegroundColor White
if ($SoloRevisar) { Aviso "Modo solo revisar: no se cambia nada." }

# -- 1. Git y Docker Desktop -----------------------------------------------------
Paso "1. Programas: Git y Docker Desktop"
if (-not (Hay "winget") -and (-not (Hay "git") -or -not (Hay "docker"))) {
    Falla "Falta winget. Instale 'App Installer' desde la Microsoft Store, o Git y Docker Desktop a mano."
}
if (Hay "git") { Bien "Git instalado" } elseif ($SoloRevisar) { Aviso "Falta Git" } else {
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    Refrescar-Path
    if (-not (Hay "git")) { Falla "Git se instalo pero esta ventana no lo ve. Cierrela y abra otra vez este archivo." }
    Bien "Git instalado"
}
if (Hay "docker") { Bien "Docker Desktop instalado" } elseif ($SoloRevisar) { Aviso "Falta Docker Desktop" } else {
    winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements
    Write-Host ""
    Aviso "Docker Desktop recien instalado: REINICIE EL PC, abra Docker Desktop, acepte sus condiciones"
    Aviso "y vuelva a abrir este archivo para seguir."
    exit 0
}

# -- 2. Docker encendido y con todos los procesadores ------------------------------
Paso "2. Docker encendido y con todos los procesadores"
# Docker Desktop necesita WSL. En un PC nuevo no viene: se instala antes de
# encender Docker (pide permiso de administrador) y hay que reiniciar.
wsl --status *> $null
if ($LASTEXITCODE -ne 0) {
    if ($SoloRevisar) { Aviso "Falta WSL (lo que usa Docker)" }
    else {
        Aviso "Falta WSL, que es lo que usa Docker. Se instala ahora (acepte el permiso de administrador)."
        $orden = 'wsl --install --no-distribution; if ($LASTEXITCODE -ne 0) { wsl --install }; wsl --update'
        Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $orden
        Falla "WSL instalado. REINICIE EL PC y vuelva a abrir este archivo para seguir."
    }
} else { Bien "WSL instalado" }
if (-not (Docker-Responde)) {
    if ($SoloRevisar) { Aviso "Docker no responde (esta apagado)" } else { Abrir-Docker }
}
if (Docker-Responde) {
    $delPc = [int]$env:NUMBER_OF_PROCESSORS
    $deDocker = [int](docker info --format "{{.NCPU}}" 2>$null)
    if ($deDocker -ge $delPc) { Bien "Docker ve los $deDocker procesadores del PC" }
    else {
        Aviso "El PC tiene ${delPc} procesadores y Docker solo ve ${deDocker}; el bot iria mas lento."
        if (-not $SoloRevisar -and (Pregunta "Darle a Docker los ${delPc} procesadores (reinicia Docker)")) {
            $wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
            $lineas = @()
            if (Test-Path $wslconfig) { $lineas = @(Get-Content $wslconfig | Where-Object { $_ -notmatch '^\s*processors\s*=' }) }
            if (-not ($lineas | Where-Object { $_ -match '^\s*\[wsl2\]' })) { $lineas = @("[wsl2]") + $lineas }
            $salida = @()
            foreach ($linea in $lineas) { $salida += $linea; if ($linea -match '^\s*\[wsl2\]') { $salida += "processors=$delPc" } }
            [System.IO.File]::WriteAllLines($wslconfig, $salida, (New-Object System.Text.UTF8Encoding($false)))
            Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
            wsl --shutdown
            Start-Sleep -Seconds 5
            Abrir-Docker
            $deDocker = [int](docker info --format "{{.NCPU}}" 2>$null)
            if ($deDocker -ge $delPc) { Bien "Ahora Docker ve $deDocker procesadores" }
            else { Aviso "Docker sigue viendo $deDocker. Suba los CPUs en Docker Desktop > Settings > Resources." }
        }
    }
}

# -- 3. La carpeta de destino ------------------------------------------------------
Paso "3. Carpeta de destino ($Recurso)"
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress })
$esElDelDestino = $ips -contains $Servidor
$Letra = $null
if ($esElDelDestino) {
    Bien "Este PC es ${Servidor}; el destino es local, no hace falta conectarlo"
} else {
    # La letra que ya lo tenga conectado, si hay una.
    $discos = @(Get-CimInstance Win32_LogicalDisk -ErrorAction SilentlyContinue)
    $yaConectada = $discos | Where-Object { $_.ProviderName -and ($_.ProviderName.TrimEnd('\') -ieq $Recurso) } | Select-Object -First 1
    if ($yaConectada) {
        $Letra = $yaConectada.DeviceID.TrimEnd(':')
        Bien "Ya esta conectado en ${Letra}: ($Recurso)"
    } else {
        # Si no, la primera letra libre: ni disco, ni unidad de red, ni recordada por Windows.
        $ocupadas = @($discos | ForEach-Object { $_.DeviceID.TrimEnd(':').ToUpper() })
        $ocupadas += @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue | ForEach-Object { $_.Name.ToUpper() })
        $ocupadas += @(net use 2>$null | Select-String '^\S*\s+([A-Z]):\s' | ForEach-Object { $_.Matches[0].Groups[1].Value })
        $Letra = ($LetrasPosibles.ToCharArray() | ForEach-Object { "$_" } | Where-Object { $ocupadas -notcontains $_ } | Select-Object -First 1)
        if (-not $Letra) { Falla "No hay ninguna letra libre para conectar $Recurso." }
    }
    if ($yaConectada) {
        # Nada que hacer.
    } elseif ($SoloRevisar) {
        Aviso "No esta conectado; se conectaria en ${Letra}:"
    } else {
        net use "$($Letra):" $Recurso /persistent:yes
        if ($LASTEXITCODE -ne 0) {
            Aviso "No se pudo conectar. Si fue el error 1219, este PC ya tiene otra conexion a $Servidor con otro usuario."
            $viejas = @(net use | Select-String -SimpleMatch "\\$Servidor\" | ForEach-Object { ($_.Line -split '\s+') | Where-Object { $_ -like "\\$Servidor\*" } | Select-Object -First 1 })
            if ($viejas.Count -gt 0) {
                Write-Host "    Conexiones a $($Servidor):"; $viejas | ForEach-Object { Write-Host "      $_" }
                if (Pregunta "Quitarlas y conectar ${Letra}: con ${Cuenta}") {
                    $viejas | ForEach-Object { net use $_ /delete /y | Out-Null }
                }
            }
            net use "$($Letra):" $Recurso /user:$Cuenta /persistent:yes
            if ($LASTEXITCODE -ne 0) { Falla "No se pudo conectar $($Letra):. Cierre las ventanas del Explorador abiertas en \\$Servidor y vuelva a intentarlo." }
        }
        Bien "$($Letra): conectada a $Recurso"
    }
}

# -- 4. El bot: descargarlo o ponerlo al dia ---------------------------------------
Paso "4. El bot en $Carpeta"
if (Test-Path (Join-Path $Carpeta ".git")) {
    Bien "Ya esta descargado: se pondra al dia al instalar"
} elseif ($SoloRevisar) {
    Aviso "No esta descargado"
} else {
    if (Test-Path $Carpeta) { Falla "Ya existe $Carpeta pero no es el repositorio. Muevala o borrela y vuelva a correr este archivo." }
    git clone --branch $Rama $Repositorio $Carpeta
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo descargar. Revise internet y que la cuenta de GitHub tenga acceso." }
    Bien "Descargado"
}

# -- 5. La llave de Mistral --------------------------------------------------------
Paso "5. Llave de Mistral (.env)"
$env_ = Join-Path $Carpeta ".env"
if (-not $SoloRevisar -and (Test-Path $Carpeta)) {
    if (-not (Test-Path $env_)) { Copy-Item (Join-Path $Carpeta ".env.example") $env_ }
    $lineas = @(Get-Content $env_)
    $actual = $lineas | Where-Object { $_ -match '^\s*MISTRAL_API_KEY\s*=' } | Select-Object -First 1
    $tieneLlave = $actual -and ($actual -replace '^\s*MISTRAL_API_KEY\s*=\s*', '').Trim()
    if ($tieneLlave) { Bien "Ya tiene llave (no se muestra)" }
    else {
        $segura = Read-Host "    Pegue la llave de Mistral (no se muestra; Enter para seguir sin ella)" -AsSecureString
        $llave = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($segura)).Trim()
        if ($llave) {
            $nuevas = @(); $puesta = $false
            foreach ($linea in $lineas) {
                if ($linea -match '^\s*MISTRAL_API_KEY\s*=') { $nuevas += "MISTRAL_API_KEY=$llave"; $puesta = $true } else { $nuevas += $linea }
            }
            if (-not $puesta) { $nuevas += "MISTRAL_API_KEY=$llave" }
            [System.IO.File]::WriteAllLines($env_, $nuevas, (New-Object System.Text.UTF8Encoding($false)))
            Bien "Llave guardada en .env"
        } else { Aviso "Sin llave: 'OCR + IA' no estara disponible hasta ponerla en $env_" }
    }
} elseif (Test-Path $env_) { Bien ".env existe" } else { Aviso "Falta .env" }

# -- 6. El puerto de la pantalla ------------------------------------------------------
Paso "6. Puerto de la pantalla"
function Ocupado-Por-Otro($p) {
    $escucha = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $escucha) { return $false }
    $quien = (Get-Process -Id $escucha.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($quien -match 'docker|wslrelay|vpnkit') {
        # De Docker: libre si es el propio bot; ocupado si es otro contenedor.
        $duenos = @(docker ps --filter "publish=$p" --format "{{.Names}}" 2>$null)
        return ($duenos.Count -gt 0 -and -not ($duenos -contains 'botpdf'))
    }
    return $true
}
$Puerto = $PuertosPosibles | Where-Object { -not (Ocupado-Por-Otro $_) } | Select-Object -First 1
if (-not $Puerto) { Falla "Todos los puertos de la lista estan ocupados ($($PuertosPosibles -join ', '))." }
if ($Puerto -ne $PuertosPosibles[0]) {
    $quien = (Get-Process -Id (Get-NetTCPConnection -LocalPort $PuertosPosibles[0] -State Listen | Select-Object -First 1).OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Aviso "El puerto $($PuertosPosibles[0]) lo usa '$quien' (no se toca): el bot usara el $Puerto."
}
Bien "Puerto $Puerto (la pantalla sera http://localhost:$Puerto)"

if ($SoloRevisar) { Write-Host ""; Bien "Revision terminada (no se cambio nada)."; exit 0 }

# -- 7. Instalar o actualizar en Docker ---------------------------------------------
Paso "7. Instalar el bot en Docker (puerto $Puerto)"
docker container inspect botpdf 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $codigo = Ejecutar-Script (Join-Path $Carpeta "scripts\actualizar-docker.ps1") @("-Puerto", "$Puerto")
} else {
    $codigo = Ejecutar-Script (Join-Path $Carpeta "scripts\instalar-escritorio.ps1") @("-Puerto", "$Puerto", "-SinNavegador")
}
if ($codigo -ne 0) { Falla "La instalacion fallo (vea el mensaje de arriba)." }
Bien "Bot instalado"

# -- 8. Que el bot pueda escribir en el destino de red ------------------------------
if (-not $esElDelDestino) {
    Paso "8. Montar $($Letra): para que el bot escriba en ella"
    docker volume inspect "botpdf-red-$($Letra.ToLower())" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Bien "$($Letra): ya esta montada para el bot" }
    else {
        Write-Host "    Usuario: $Cuenta  (y su clave)"
        $codigo = Ejecutar-Script (Join-Path $Carpeta "scripts\montar-unidad-de-red.ps1") @($Letra)
        if ($codigo -ne 0) { Falla "No se pudo montar $($Letra): (vea el mensaje de arriba)." }
        Bien "$($Letra): montada"
    }
}

# -- 9. Comprobar ---------------------------------------------------------------
Paso "9. Comprobacion"
$version = (docker exec botpdf python -c "from resolutions.api.corrida_compartida import version_del_bot; print(version_del_bot())" 2>$null | Select-Object -Last 1)
$procesos = (docker exec botpdf python -c "from resolutions.api.settings import Settings; s=Settings.from_env(); print(s.document_workers, s.folder_documents)" 2>$null | Select-Object -Last 1)
$commit = (git -C $Carpeta rev-parse --short HEAD)
Write-Host "    Version del bot : $version   (commit $commit)"
Write-Host "    Procesos        : $procesos   (tope y automatico; debe ser 31 8)"
Write-Host "    La version tiene que ser LA MISMA en todos los PC de la corrida." -ForegroundColor Yellow

# Igual en todos los PC: la ruta de red. En el propio PC del destino, su carpeta.
$destinoAqui = if ($esElDelDestino) { "C:\Users\SIAR1\Desktop\$Destino" } else { "$Recurso\$Destino" }
Write-Host ""
Write-Host "LISTO. Abra http://localhost:$Puerto  ->  Carpeta local:" -ForegroundColor Green
Write-Host "    Origen : $Origen"
Write-Host "    Destino: $destinoAqui"
Write-Host "    Las mismas opciones que los demas PC (Correspondencia, OCR + IA, el mismo agrupar) -> Procesar."
Write-Host "    En los avisos debe salir: 'Corrida compartida ... con N equipo(s) mas'."
Start-Process "http://localhost:$Puerto"
exit 0
