# Prueba de aceptacion de BOT_PDF en Docker: se ejecuta despues de instalar la
# imagen en cualquier equipo y responde, punto por punto, si la instalacion
# funciona de verdad. No gasta IA y borra todo lo que crea.
#
#   probar-instalacion            (CMD)  /  .\probar-instalacion.cmd   (PowerShell)
#   .\probar-instalacion.cmd -Rapida      sin la corrida de punta a punta
#
# Deja el informe en "prueba-instalacion.txt", en la raiz del repositorio.
# Sale con codigo 0 si todo paso, 1 si algo fallo.

param([switch]$Rapida)

$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# -- el puerto, el mismo que uso el instalador -----------------------------------
$puerto = 8000
$rutaEnv = Join-Path $raiz ".env"
$llaveMistral = $false
if (Test-Path $rutaEnv) {
    foreach ($linea in Get-Content $rutaEnv) {
        if ($linea -match '^\s*BOTPDF_PUERTO\s*=\s*(\d+)') { $puerto = [int]$Matches[1] }
        if ($linea -match '^\s*MISTRAL_API_KEY\s*=\s*\S+') { $llaveMistral = $true }
    }
}
$url = "http://localhost:$puerto"

# Windows PowerShell 5.1 reutiliza las conexiones HTTP y a veces se cuelga con
# ellas: cada peticion abre la suya (-DisableKeepAlive).
[System.Net.ServicePointManager]::DefaultConnectionLimit = 64

# -- registro de resultados ------------------------------------------------------
$resultados = New-Object System.Collections.ArrayList
function Anotar($bloque, $nombre, $estado, $detalle) {
    [void]$resultados.Add([pscustomobject]@{ Bloque = $bloque; Prueba = $nombre; Estado = $estado; Detalle = $detalle })
    $color = @{ "OK" = "Green"; "FALLO" = "Red"; "AVISO" = "Yellow"; "OMITIDA" = "DarkGray" }[$estado]
    Write-Host ("  [{0,-7}] {1}: {2}" -f $estado, $nombre, $detalle) -ForegroundColor $color
}
function Comprobar($bloque, $nombre, [scriptblock]$prueba) {
    try {
        $r = & $prueba
        if ($r -is [array]) { $r = $r[-1] }
        if ($r -and $r.Estado) { Anotar $bloque $nombre $r.Estado $r.Detalle }
        else { Anotar $bloque $nombre "FALLO" "la prueba no devolvio resultado" }
    } catch {
        Anotar $bloque $nombre "FALLO" ("{0}" -f $_.Exception.Message)
    }
}
function Ok($detalle) { [pscustomobject]@{ Estado = "OK"; Detalle = $detalle } }
function Falla($detalle) { [pscustomobject]@{ Estado = "FALLO"; Detalle = $detalle } }
function Aviso($detalle) { [pscustomobject]@{ Estado = "AVISO"; Detalle = $detalle } }
function EnContenedor { param([Parameter(ValueFromRemainingArguments = $true)] $argumentos) (& docker exec botpdf @argumentos 2>&1 | ForEach-Object { "$_" }) -join "`n" }
function Pedir($ruta) { Invoke-RestMethod -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url$ruta" }

Write-Host ""
Write-Host "Prueba de la instalacion de BOT_PDF en $url" -ForegroundColor Cyan
Write-Host ""

# =============================================================================
Write-Host "1. Docker" -ForegroundColor Cyan
Comprobar "Docker" "Motor de Docker" {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { Ok (docker version --format "motor {{.Server.Version}}") } else { Falla "Docker no responde: abra Docker Desktop" }
}
$estado = docker inspect botpdf --format "{{.State.Status}}" 2>$null
Comprobar "Docker" "Contenedor botpdf" {
    if ($estado -eq "running") { Ok "corriendo" } elseif ($estado) { Falla "estado '$estado': ejecute .\instalar-docker.cmd" } else { Falla "no existe: ejecute .\instalar-docker.cmd" }
}
if ($estado -ne "running") {
    Write-Host ""
    Write-Host "Sin contenedor corriendo no se puede probar lo demas." -ForegroundColor Red
    $resultados | Format-Table -AutoSize | Out-String | Out-File (Join-Path $raiz "prueba-instalacion.txt") -Encoding utf8
    exit 1
}
Comprobar "Docker" "Salud del contenedor" {
    $limite = (Get-Date).AddSeconds(90)
    do {
        $salud = docker inspect botpdf --format "{{if .State.Health}}{{.State.Health.Status}}{{end}}" 2>$null
        if ($salud -ne "starting") { break }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $limite)
    if ($salud -eq "healthy") { Ok "healthy" } else { Falla "salud '$salud': vea docker compose logs --tail 100" }
}
Comprobar "Docker" "Sin reinicios ni falta de memoria" {
    $datos = docker inspect botpdf --format "{{.RestartCount}} {{.State.OOMKilled}}" 2>$null
    $partes = "$datos".Split(" ")
    if ($partes[1] -eq "true") { Falla "Docker lo mato por falta de memoria: suba la memoria de Docker Desktop" }
    elseif ([int]$partes[0] -gt 0) { Aviso "se reinicio $($partes[0]) vez/veces: vea docker compose logs" }
    else { Ok "0 reinicios" }
}

# =============================================================================
Write-Host "2. Servicio" -ForegroundColor Cyan
$salud = $null
Comprobar "Servicio" "API de salud" {
    $script:salud = Pedir "/api/health"
    if ($script:salud.status -eq "ok") { Ok ("revision {0}, {1} procesos, {2} documentos de carpeta a la vez" -f $script:salud.api_revision, $script:salud.document_workers, $script:salud.folder_documents) } else { Falla "contesto '$($script:salud.status)'" }
}
Comprobar "Servicio" "Pantalla" {
    $inicio = Invoke-WebRequest -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/"
    if ($inicio.StatusCode -eq 200 -and $inicio.Content -match "<html") { Ok "se sirve en $url" } else { Falla "la pagina inicial no contesto bien" }
}
Comprobar "Servicio" "Paginas internas al recargar" {
    $archivo = Invoke-WebRequest -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/archivo"
    if ($archivo.StatusCode -eq 200 -and $archivo.Content -match "<html") { Ok "/archivo devuelve la pantalla" } else { Falla "/archivo no devuelve la pantalla" }
}
Comprobar "Servicio" "Rutas de la API que no existen" {
    try { Invoke-WebRequest -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/api/no-existe-prueba" | Out-Null; Falla "devolvio 200 en vez de 404" }
    catch { if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { Ok "404, como debe" } else { Falla $_.Exception.Message } }
}

# =============================================================================
Write-Host "3. Dentro de la imagen" -ForegroundColor Cyan
Comprobar "Imagen" "Tesseract con espanol" {
    $idiomas = EnContenedor tesseract --list-langs
    $version = (EnContenedor tesseract --version).Split("`n")[0]
    if ($idiomas -match "(?m)^spa\s*$") { Ok "$version, idioma spa" } else { Falla "falta el idioma spa: reconstruya la imagen" }
}
Comprobar "Imagen" "Versiones fijas" {
    $fijas = @{}
    foreach ($linea in Get-Content (Join-Path $raiz "backend\constraints-docker.txt")) {
        if ($linea -match '^\s*([A-Za-z0-9_.-]+)==([^\s#]+)') { $fijas[$Matches[1].ToLower()] = $Matches[2] }
    }
    $instaladas = EnContenedor python -c "import importlib.metadata as m; [print(d.metadata['Name'].lower(), d.version) for d in m.distributions()]"
    $distintas = @()
    foreach ($nombre in $fijas.Keys) {
        $linea = ($instaladas -split "`n") | Where-Object { $_ -match "^$([regex]::Escape($nombre)) " } | Select-Object -First 1
        $tiene = if ($linea) { ($linea -split " ")[1].Trim() } else { "no instalada" }
        if ($tiene -ne $fijas[$nombre]) { $distintas += "$nombre $tiene (se pide $($fijas[$nombre]))" }
    }
    if ($distintas.Count -eq 0) { Ok ("{0} paquetes en la version probada" -f $fijas.Count) } else { Falla ($distintas -join "; ") }
}
Comprobar "Imagen" "Plantillas oficiales" {
    $lista = EnContenedor python -c "import resolutions, pathlib; a = pathlib.Path(resolutions.__file__).parent / 'assets'; print(len([p for p in a.rglob('*') if p.is_file()]))"
    if ([int]"$lista".Trim() -ge 5) { Ok "$("$lista".Trim()) plantillas (FUID, Indice Electronico, nombres)" } else { Falla "solo $lista plantillas: el paquete no las lleva" }
}
Comprobar "Imagen" "Datos escribibles y espacio" {
    $escribe = EnContenedor sh -c "touch /data/.prueba && rm /data/.prueba && echo si"
    $libre = EnContenedor sh -c "df -Pk /data | tail -1 | awk '{print int(`$4/1048576)}'"
    if ($escribe -notmatch "si") { Falla "no se puede escribir en /data" }
    elseif ([int]"$libre".Trim() -lt 5) { Aviso "quedan $("$libre".Trim()) GB libres en /data" }
    else { Ok "/data escribible, $("$libre".Trim()) GB libres" }
}
Comprobar "Imagen" "Registro diario" {
    $logs = EnContenedor sh -c "ls /data/logs/bot-*.log 2>/dev/null | tail -1"
    if ($logs -match "bot-") { Ok "$("$logs".Trim())" } else { Aviso "todavia no hay registro diario en /data/logs" }
}

# =============================================================================
Write-Host "4. Equipo" -ForegroundColor Cyan
$unidades = (EnContenedor printenv BOTPDF_UNIDADES).Trim()
Comprobar "Equipo" "Discos montados" {
    if (-not $unidades -or $unidades -match "Error") { return (Falla "sin BOTPDF_UNIDADES: ejecute .\instalar-docker.cmd para montar los discos") }
    # Las unidades de red y los discos virtuales ("X:=//servidor/recurso/...") no
    # se montan: el servicio las lee con su cliente SMB. De esas se comprueba que
    # el contenedor encuentra el servidor y llega a su puerto 445; el usuario y la
    # clave los pide la pantalla la primera vez.
    $faltan = @()
    $montadas = @()
    $porRed = @()
    foreach ($par in $unidades.Split(";")) {
        $letra, $montaje = $par -split "=", 2
        if ($montaje -like "//*") {
            $servidor = ($montaje.Substring(2) -split "/", 2)[0]
            $llega = EnContenedor python -c "import socket; socket.create_connection(('$servidor', 445), 5).close(); print('si')"
            if ($llega -match "^si") { $porRed += "$letra (red: $servidor)" } else { $faltan += "$letra (no se llega a $servidor)" }
        } else {
            $hay = EnContenedor sh -c "test -d '$montaje' && echo si"
            if ($hay -match "^si") { $montadas += $letra } else { $faltan += $par }
        }
    }
    $detalle = "montadas: " + ($montadas -join " ")
    if ($porRed.Count) { $detalle += "; por la red: " + ($porRed -join ", ") }
    if ($faltan.Count -eq 0) { Ok $detalle } else { Falla ("no se ven: " + ($faltan -join ", ")) }
}
Comprobar "Equipo" "Carpetas de red" {
    # El cliente SMB en la imagen y la cadena entera -- API, cliente, traduccion
    # del error -- sin credenciales: un servidor que no existe tiene que contestar
    # "no se pudo conectar" (503), no tumbar nada ni colgarse.
    $cliente = EnContenedor python -c "import smbclient; print('si')"
    if ($cliente -notmatch "si") { return (Falla "la imagen no trae el cliente de red (smbprotocol)") }
    $cuerpo = @{ ruta = '\\127.0.0.1\prueba' } | ConvertTo-Json
    try {
        Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body $cuerpo "$url/api/reconocer-carpeta" | Out-Null
        Falla "un servidor de red inexistente no dio error"
    } catch {
        $codigo = $_.Exception.Response.StatusCode.value__
        if ($codigo -eq 503) { Ok "cliente SMB listo; un servidor que no existe se informa (503) sin colgar nada" }
        else { Falla "se esperaba 503 y llego $codigo" }
    }
}
Comprobar "Equipo" "Explorador de carpetas" {
    $inicio = Pedir "/api/folders"
    $raices = @($inicio.drives | ForEach-Object { $_.path })
    if (-not $raices) { return (Falla "el explorador no ofrece ninguna unidad") }
    $primera = Pedir ("/api/folders?path=" + [uri]::EscapeDataString($raices[0]))
    Ok ("unidades {0}; {1} carpetas en {2}" -f ($raices -join " "), @($primera.folders).Count, $raices[0])
}
Comprobar "Equipo" "Llaves de la IA" {
    $mistral = $script:salud.readers.mistral
    if ($llaveMistral -and $mistral) { Ok "Mistral disponible (no se gasta: solo se comprueba que llego)" }
    elseif ($llaveMistral) { Falla "hay MISTRAL_API_KEY en .env pero el servicio no la ve: docker compose up -d" }
    else { Aviso "sin llave de IA: funciona con Solo OCR" }
}

# =============================================================================
Write-Host "5. De punta a punta" -ForegroundColor Cyan
if ($Rapida) {
    Anotar "Punta a punta" "Corrida de carpeta" "OMITIDA" "con -Rapida"
} else {
    $sello = Get-Date -Format "yyyyMMdd-HHmmss"
    $base = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "BOT_PDF-prueba\$sello"
    $entrada = Join-Path $base "ENTRADA"
    $salida = Join-Path $base "SALIDA"
    $trabajos = @()
    $corridas = @()
    try {
        Comprobar "Punta a punta" "Reconocer un PDF subido" {
            $minimo = Join-Path $env:TEMP "botpdf-prueba-$sello.pdf"
            $pdf = "%PDF-1.4`n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj`n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj`n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj`ntrailer<</Root 1 0 R>>`n%%EOF`n"
            [System.IO.File]::WriteAllText($minimo, $pdf, (New-Object System.Text.ASCIIEncoding))
            $respuesta = curl.exe -sS -m 120 -o NUL -w "%{http_code}" -F "file=@$minimo;type=application/pdf" "$url/api/reconocer"
            Remove-Item $minimo -ErrorAction SilentlyContinue
            if ("$respuesta" -eq "200") { Ok "la subida y la lectura del PDF funcionan" } else { Falla "HTTP $respuesta" }
        }

        # La unidad de la carpeta de prueba, vista desde el contenedor.
        $letra = $base.Substring(0, 1).ToUpper()
        $montaje = $null
        foreach ($par in $unidades.Split(";")) { if ($par -match "^${letra}:=(.+)$") { $montaje = $Matches[1] } }
        if (-not $montaje -or $montaje -like "//*") { throw "la unidad ${letra}: no esta montada en el contenedor; no se puede probar una corrida de carpeta" }
        $enContenedor = $montaje + "/" + ($base.Substring(3) -replace "\\", "/")

        # Los PDF de prueba los hace el propio contenedor: el equipo no necesita Python.
        $hacerPdfs = @'
import sys, pathlib, pymupdf
destino = pathlib.Path(sys.argv[1]) / "ENTRADA"
destino.mkdir(parents=True, exist_ok=True)
def pagina(doc, texto):
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 90), texto, fontsize=13)
d = pymupdf.open()
for n, tema in ((1, "se designan los docentes de catedra"), (2, "se hace un encargo")):
    pagina(d, "UNIVERSIDAD DE CARTAGENA\nRESOLUCION No. 0000%d DE 2025\nPor medio de la cual %s\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nCONSIDERANDO:\nQue es necesario." % (n, tema))
    pagina(d, "RESUELVE:\nARTICULO PRIMERO: Lo dicho.\nDada en Cartagena de Indias, a los 3 dias del mes de marzo de 2025.")
d.save(str(destino / "DIGITAL 00001-00002.pdf"))
fuente = pymupdf.open()
pagina(fuente, "UNIVERSIDAD DE CARTAGENA\nRESOLUCION No. 00003 DE 2025\nPor medio de la cual se hace un nombramiento\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nCONSIDERANDO:")
pagina(fuente, "RESUELVE:\nARTICULO PRIMERO: Nombrar.\nDada en Cartagena de Indias, a los 5 dias del mes de marzo de 2025.")
escaneado = pymupdf.open()
for p in fuente:
    pix = p.get_pixmap(dpi=200)
    nueva = escaneado.new_page(width=p.rect.width, height=p.rect.height)
    nueva.insert_image(nueva.rect, pixmap=pix)
escaneado.save(str(destino / "ESCANEADO 00003.pdf"))
print("listo")
'@
        $hecho = $hacerPdfs | docker exec -i botpdf python - $enContenedor 2>&1
        if (-not (Test-Path (Join-Path $entrada "ESCANEADO 00003.pdf"))) { throw "no se pudieron crear los PDF de prueba en $entrada ($hecho)" }

        function Correr-Carpeta {
            $cuerpo = @{ source = $entrada; destination = $salida; task = "both"; lectura = "local"; tipo = "auto" } | ConvertTo-Json
            $corrida = Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body $cuerpo "$url/api/folder-runs"
            $script:corridas += $corrida.id
            $limite = (Get-Date).AddMinutes(10)
            do {
                Start-Sleep -Seconds 2
                $corrida = Pedir "/api/folder-runs/$($corrida.id)"
            } while ($corrida.state -in "scanning", "processing", "recovering" -and (Get-Date) -lt $limite)
            $script:trabajos += @($corrida.job_ids)
            return $corrida
        }

        # Lo primero que hace la pantalla al pulsar «Procesar carpeta»: reconocerla.
        Comprobar "Punta a punta" "Reconocer la carpeta de origen" {
            $cuerpo = @{ ruta = $entrada } | ConvertTo-Json
            $r = Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body $cuerpo "$url/api/reconocer-carpeta"
            if ($r.total -eq 2) { Ok ("2 PDF reconocidos en {0}" -f $r.ruta) } else { Falla ("se esperaban 2 PDF y hay {0}" -f $r.total) }
        }

        $primera = $null
        Comprobar "Punta a punta" "Corrida de carpeta con rutas de Windows" {
            $script:primera = Correr-Carpeta
            $c = $script:primera
            if ($c.state -eq "done" -and $c.processed -eq 2 -and $c.failed -eq 0) { Ok ("2 PDF procesados desde {0}" -f $c.source) }
            else { Falla ("estado {0}, procesados {1}, fallidos {2} {3}" -f $c.state, $c.processed, $c.failed, $c.error) }
        }
        Comprobar "Punta a punta" "PDF digital partido por resolucion" {
            $pdfs = @(Get-ChildItem (Join-Path $salida "DIGITAL 00001-00002") -Filter *.pdf -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
            if ($pdfs.Count -eq 2) { Ok ($pdfs -join ", ") } else { Falla ("se esperaban 2 resoluciones y hay {0}: {1}" -f $pdfs.Count, ($pdfs -join ", ")) }
        }
        Comprobar "Punta a punta" "PDF escaneado leido con Tesseract" {
            $pdfs = @(Get-ChildItem (Join-Path $salida "ESCANEADO 00003") -Filter *.pdf -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
            if ($pdfs -match "00003") { Ok ($pdfs -join ", ") } else { Falla ("no salio la resolucion 00003: {0}" -f ($pdfs -join ", ")) }
        }
        Comprobar "Punta a punta" "Inventarios y constancias" {
            $general = Test-Path (Join-Path $salida "00.INVENTARIO GENERAL DE PROCESOS.xlsx")
            $planillas = @(Get-ChildItem $salida -Recurse -Filter "*__inventario.xlsx" -ErrorAction SilentlyContinue).Count
            $constancias = @(Get-ChildItem $salida -Recurse -Force -Filter ".bot-entrega.json" -ErrorAction SilentlyContinue).Count
            if ($general -and $planillas -ge 2 -and $constancias -eq 2) { Ok "inventario general, $planillas planillas y $constancias constancias" }
            else { Falla "general=$general planillas=$planillas constancias=$constancias" }
        }
        Comprobar "Punta a punta" "No repite lo ya entregado" {
            $c = Correr-Carpeta
            if ($c.state -eq "done" -and $c.ya_entregados -eq 2 -and $c.processed -eq 0) { Ok "la segunda corrida salto los 2 PDF sin leerlos" }
            else { Falla ("ya entregados {0}, procesados {1}, estado {2}" -f $c.ya_entregados, $c.processed, $c.state) }
        }

        # -- Detener a la mitad y retomar ------------------------------------
        # Un PDF corto y uno largo escaneado, de uno en uno: cuando el corto ya
        # se entrego y el largo va leyendo, se detiene. Tiene que responder al
        # instante, dejar de leer y, al relanzar, saltar el corto y rehacer el largo.
        $entradaD = Join-Path $base "ENTRADA-DETENER"
        $salidaD = Join-Path $base "SALIDA-DETENER"
        $hacerLargo = @'
import sys, pathlib, pymupdf
destino = pathlib.Path(sys.argv[1]) / "ENTRADA-DETENER"
destino.mkdir(parents=True, exist_ok=True)
def pagina(doc, texto):
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 90), texto, fontsize=13)
d = pymupdf.open()
pagina(d, "UNIVERSIDAD DE CARTAGENA\nRESOLUCION No. 00010 DE 2025\nPor medio de la cual se hace un encargo\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA")
d.save(str(destino / "A CORTO 00010.pdf"))
fuente = pymupdf.open()
for n in range(60):
    pagina(fuente, "RESOLUCION No. %05d DE 2025\nPor medio de la cual se hace un nombramiento\nEL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nCONSIDERANDO: pagina %d" % (100 + n // 2, n + 1))
largo = pymupdf.open()
for p in fuente:
    pix = p.get_pixmap(dpi=150)
    nueva = largo.new_page(width=p.rect.width, height=p.rect.height)
    nueva.insert_image(nueva.rect, pixmap=pix)
largo.save(str(destino / "B LARGO ESCANEADO.pdf"))
print("listo")
'@
        $hecho = $hacerLargo | docker exec -i botpdf python - $enContenedor 2>&1
        if (-not (Test-Path (Join-Path $entradaD "B LARGO ESCANEADO.pdf"))) { throw "no se pudieron crear los PDF de la prueba de detener ($hecho)" }

        $detenida = $null
        Comprobar "Punta a punta" "Detener es inmediato" {
            $cuerpo = @{ source = $entradaD; destination = $salidaD; task = "both"; lectura = "local"; tipo = "auto"; paralelo = 1 } | ConvertTo-Json
            $corrida = Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body $cuerpo "$url/api/folder-runs"
            $script:corridas += $corrida.id
            # Esperar a que el corto este entregado y el largo vaya leyendo.
            $largo = $null
            $limite = (Get-Date).AddMinutes(4)
            do {
                Start-Sleep -Milliseconds 700
                $corrida = Pedir "/api/folder-runs/$($corrida.id)"
                $script:trabajos += @($corrida.job_ids)
                $enCurso = @($corrida.en_curso | Where-Object { $_.nombre -match "LARGO" })
                if ($enCurso.Count -and $corrida.processed -ge 1) {
                    $largo = Pedir "/api/jobs/$($enCurso[0].job_id)"
                    if ($largo.progress.pages_done -ge 2) { break }
                }
            } while ($corrida.state -in "scanning", "processing" -and (Get-Date) -lt $limite)
            if (-not $largo) { return (Falla "el PDF largo no llego a leerse; no se pudo probar detener") }

            $reloj = [Diagnostics.Stopwatch]::StartNew()
            Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/api/folder-runs/$($corrida.id)/stop" | Out-Null
            $respuesta = $reloj.Elapsed.TotalSeconds
            # El documento en curso, cancelado en pantalla al momento.
            $cancelado = $false
            $limite = (Get-Date).AddSeconds(10)
            do {
                $l = Pedir "/api/jobs/$($largo.id)"
                if ($l.state -eq "cancelled") { $cancelado = $true; break }
                Start-Sleep -Milliseconds 300
            } until ((Get-Date) -gt $limite)
            $enCancelar = $reloj.Elapsed.TotalSeconds
            # Y el worker deja de leer: las paginas no siguen subiendo.
            Start-Sleep -Seconds 3
            $antes = (Pedir "/api/jobs/$($largo.id)").progress.pages_done
            Start-Sleep -Seconds 8
            $despues = (Pedir "/api/jobs/$($largo.id)").progress.pages_done
            # Y la pantalla sigue contestando mientras se escriben los inventarios.
            $reloj2 = [Diagnostics.Stopwatch]::StartNew()
            Pedir "/api/health" | Out-Null
            $salud = $reloj2.Elapsed.TotalSeconds
            $estadoCorrida = (Pedir "/api/folder-runs/$($corrida.id)").state
            $script:detenida = $corrida.id
            if ($respuesta -gt 3) { Falla ("detener tardo {0:N1} s en contestar" -f $respuesta) }
            elseif (-not $cancelado) { Falla "el documento en curso no quedo cancelado en 10 s" }
            elseif ($despues -gt $antes) { Falla ("siguio leyendo despues de detener: {0} -> {1} paginas" -f $antes, $despues) }
            elseif ($estadoCorrida -ne "stopped") { Falla "la carpeta quedo en '$estadoCorrida'" }
            else { Ok ("contesto en {0:N2} s, cancelado en {1:N1} s, sin leer mas paginas ({2}), salud en {3:N2} s" -f $respuesta, $enCancelar, $antes, $salud) }
        }
        Comprobar "Punta a punta" "Retomar tras detener no repite" {
            $cuerpo = @{ source = $entradaD; destination = $salidaD; task = "both"; lectura = "local"; tipo = "auto"; paralelo = 1 } | ConvertTo-Json
            $corrida = Invoke-RestMethod -Method Post -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body $cuerpo "$url/api/folder-runs"
            $script:corridas += $corrida.id
            $limite = (Get-Date).AddMinutes(10)
            do {
                Start-Sleep -Seconds 2
                $corrida = Pedir "/api/folder-runs/$($corrida.id)"
            } while ($corrida.state -in "scanning", "processing", "recovering" -and (Get-Date) -lt $limite)
            $script:trabajos += @($corrida.job_ids)
            if ($corrida.state -eq "done" -and $corrida.ya_entregados -eq 1 -and $corrida.processed -eq 1 -and $corrida.failed -eq 0) {
                Ok "salto el PDF ya entregado y rehizo solo el que se habia detenido"
            } else {
                Falla ("estado {0}, ya entregados {1}, procesados {2}, fallidos {3}" -f $corrida.state, $corrida.ya_entregados, $corrida.processed, $corrida.failed)
            }
        }
    } catch {
        Anotar "Punta a punta" "Corrida de carpeta" "FALLO" $_.Exception.Message
    } finally {
        # Todo lo que la prueba creo se borra: archivos, filas del Archivo y corridas.
        $ids = @($trabajos | Where-Object { $_ } | Select-Object -Unique)
        if ($ids.Count) {
            try { Invoke-RestMethod -Method Delete -UseBasicParsing -DisableKeepAlive -TimeoutSec 60 -ContentType "application/json" -Body (@{ job_ids = $ids } | ConvertTo-Json) "$url/api/documents" | Out-Null } catch {}
            foreach ($id in $ids) { try { Invoke-RestMethod -Method Delete -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/api/jobs/$id" | Out-Null } catch {} }
        }
        foreach ($id in $corridas) { try { Invoke-RestMethod -Method Delete -UseBasicParsing -DisableKeepAlive -TimeoutSec 30 "$url/api/folder-runs/$id" | Out-Null } catch {} }
        Remove-Item (Split-Path $base -Parent) -Recurse -Force -ErrorAction SilentlyContinue
        Anotar "Punta a punta" "Limpieza" "OK" "se borro lo que creo la prueba"
    }
}

# =============================================================================
$fallos = @($resultados | Where-Object { $_.Estado -eq "FALLO" }).Count
$avisos = @($resultados | Where-Object { $_.Estado -eq "AVISO" }).Count
$informe = @(
    "Prueba de la instalacion de BOT_PDF - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - equipo $env:COMPUTERNAME - $url",
    "Version: $(git log -1 --format='%h %s' 2>$null)",
    ""
) + ($resultados | Format-Table Bloque, Prueba, Estado, Detalle -AutoSize -Wrap | Out-String -Width 220)
$informe += "Resultado: $($resultados.Count) pruebas, $fallos fallos, $avisos avisos."
$informe -join "`n" | Out-File (Join-Path $raiz "prueba-instalacion.txt") -Encoding utf8

Write-Host ""
if ($fallos -eq 0) {
    Write-Host "TODO EN ORDEN: $($resultados.Count) pruebas, $avisos avisos." -ForegroundColor Green
} else {
    Write-Host "HAY $fallos FALLO(S) de $($resultados.Count) pruebas. Detalle en prueba-instalacion.txt" -ForegroundColor Red
}
Write-Host "Informe: $(Join-Path $raiz 'prueba-instalacion.txt')"
if ($fallos -eq 0) { exit 0 } else { exit 1 }
