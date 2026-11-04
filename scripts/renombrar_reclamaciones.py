"""Pipeline de las reclamaciones ya entregadas: el RE en su nombre y los índices en orden.

Lo pidió el operador para la carpeta de MAGANGUE ya procesada (2026-10-28) y lo
completó el 2026-11-04: «créame un pipeline donde se unan todos los procesos que
te pedí». Corre aparte del bot, en cuatro pasos seguidos; cada uno empieza cuando
el anterior terminó en todas las cajas:

1. **El RE.** Sólo a los PDF que se llaman exactamente ``NN_RECLAMO.pdf`` y
   ``NN_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION.pdf`` («a esos 2 tipos de
   documentos les agregarás el RE»). Ninguna variante: «NOTIFICACION PERSONAL
   RECLAMOS», «DESISTIMIENTO DEL RECLAMO» o «RECLAMO POR CONSUMO ESTIMADO» quedan
   como están. El número del principio se conserva:
   ``04_RECLAMO.pdf`` → ``04_RECLAMO-RE2310202315695.pdf``. El mismo nombre va a su
   fila del índice de la caja y a la constancia de la entrega
   (``.bot-entrega-UPD….json``): sin ésta, el bot vería la entrega incompleta y la
   volvería a procesar -- y a pagar --.

2. **El índice de cada caja.** En cada ``00.INDICE ELECTRONICO.xlsx``:
   * las filas se ordenan por «Fecha Creación Documento», lo más antiguo primero
     («lo antiguo va de primero y lo nuevo de último»); con la misma fecha quedan
     como estaban, y las que no tienen fecha (S.F.) van al final;
   * «Orden Documento» se renumera 1, 2, 3…; los PDF NO se renombran (el operador
     eligió «solo el índice»);
   * «Nombre del Expediente» lleva el mismo número que «Identificación / Nic».

3. **El índice general de la raíz.** La hoja de cada caja queda igual que el
   índice de su caja: los nombres con su RE, el mismo orden y el expediente.

4. **La revisión.** Se vuelve a recorrer el disco y se deja en la raíz:
   * «00.RECLAMACIONES SIN RE.csv»: cada RECLAMO o CONSTANCIA que siga sin RE, con
     el motivo;
   * «00.INDICES POR REVISAR.csv»: lo que no cuadre -- un índice sin ordenar, un
     expediente distinto del NIC, un RE que el índice no tiene, una hoja del
     general distinta de su caja --.

**En paralelo** («la idea es poder procesar en paralelo, para que sea más rápido»):
cada proceso toma una caja y le hace los pasos 1, 2 y 4 seguidos, mientras los
demás trabajan otras; por omisión, tantos procesos como núcleos menos uno
(``--procesos N`` para cambiarlo). El paso 3 es un solo archivo y va al final.
Lo que más tarda es leer el RE con OCR (unos 30 s un PDF que no lo tiene): queda
anotado en «00.RE Y ORDEN - LECTURAS.jsonl» con el tamaño y la fecha de cada PDF,
y la corrida siguiente -- el --aplicar después de la simulación -- lo reutiliza si
el archivo no cambió.

Uso, en CMD o PowerShell (sin nada más detrás del comando):

    python renombrar_reclamaciones.py              simula los cuatro pasos: no cambia nada
    python renombrar_reclamaciones.py --aplicar    hace los cambios
    python renombrar_reclamaciones.py --revisar    sólo el paso 4, sobre lo que hay en el disco
    python renombrar_reclamaciones.py --deshacer   todo como estaba antes del primer --aplicar
    ... --releer                                   vuelve a leer el RE de todos los PDF

Sin carpeta trabaja sobre «C:\\Users\\SIAR1\\Desktop\\FOLIA-BOT\\MAGANGUE PROCESADO»;
otra va antes de las opciones: ``python renombrar_reclamaciones.py "D:\\otra" --aplicar``.

Necesita Python 3.9 o más nuevo con ``pip install pymupdf openpyxl``, y Tesseract
para las hojas escaneadas sin texto (sin él sólo se lee el texto del PDF, y lo que
no lo tenga queda en la lista de los que siguen sin RE). En el contenedor del bot ya
está todo:

    docker cp renombrar_reclamaciones.py botpdf:/tmp/renombrar_reclamaciones.py
    docker exec -it botpdf python /tmp/renombrar_reclamaciones.py --aplicar

Seguridad:

* Antes de cambiar un índice o una constancia se copia, tal como estaba, a la
  carpeta hermana «<carpeta> - RESPALDO RE Y ORDEN» (sólo la primera vez: guarda lo
  de antes del primer --aplicar). --deshacer devuelve los nombres de los PDF y esas
  copias.
* Un Excel abierto o bloqueado: esa caja no se toca y queda anotada.
* Se puede cortar con Ctrl+C y volver a correr: lo que ya está hecho se salta.
* No corre mientras el bot procesa esa misma carpeta.
* El RE sólo se acepta escrito con «RE» delante y trece cifras con el año en su
  sitio; el «Consecutivo No.» de las respuestas no es el radicado.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from copy import copy
from datetime import date, datetime
from pathlib import Path

#: La carpeta de MAGANGUE ya procesada, en el equipo donde se corre.
CARPETA_POR_OMISION = r"C:\Users\SIAR1\Desktop\FOLIA-BOT\MAGANGUE PROCESADO"
#: Los únicos títulos que llevan el RE, como los deja ``_plano``.
TITULOS_CON_RE = ("RECLAMO", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION")
REGISTRO = "00.RE Y ORDEN - REGISTRO.csv"
SIMULACION = "00.RE Y ORDEN - SIMULACION.csv"
#: Lo que ya se leyó de cada PDF -- su RE o que no lo tiene --, con su tamaño y su
#: fecha. Leer el RE con OCR es lo que más tarda (unos 30 s un PDF sin él): la
#: simulación lo hace una vez y --aplicar y las corridas siguientes lo reutilizan.
LECTURAS = "00.RE Y ORDEN - LECTURAS.jsonl"
#: La evidencia de cada cambio, en vivo: lo mismo que sale en pantalla, con su hora.
#: Lo pidió el operador el 2026-11-04: «necesito evidencia de cada cosa que va
#: haciendo, de las 2 fases, en tiempo real».
EVIDENCIA = "00.RE Y ORDEN - EVIDENCIA.txt"
#: Tope del OCR de un PDF, y de cada llamada a Tesseract: un PDF dañado o enorme
#: no frena su caja («agrégale validaciones para que no se detenga»).
TIEMPO_MAXIMO_DE_OCR = 150
TIEMPO_MAXIMO_DE_TESSERACT = 90
#: Cada cuántos segundos se avisa que sigue trabajando, si no hubo nada que mostrar.
LATIDO = 15
SIN_RE = "00.RECLAMACIONES SIN RE.csv"
POR_REVISAR = "00.INDICES POR REVISAR.csv"
#: La carpeta del respaldo, al lado de la que se trabaja: así el bot no la ve.
SUFIJO_DEL_RESPALDO = " - RESPALDO RE Y ORDEN"
INDICE = "00.INDICE ELECTRONICO.xlsx"
CONSTANCIA = re.compile(r"^\.bot-entrega-.+\.json$", re.IGNORECASE)
NUMERADO = re.compile(r"^(\d{1,4})_(.+)\.pdf$", re.IGNORECASE)
CON_RE = re.compile(r"-RE\d{13}$", re.IGNORECASE)
#: Carpetas que no son cajas: lo apartado al rehacer y los originales movidos.
SALTAR = {"_reemplazados", "_procesados"}
#: «RE2310202101996», «RE9233202202670», con los espacios que mete la lectura:
#: oficina de cuatro cifras, año (2018-2029) y consecutivo. En MAGANGUE hay
#: oficinas que empiezan por 9 (2026-10-28).
#: Sin una letra delante: «SOBRE 2310…» o «NOMBRE 2310…» no son un radicado.
RE_ESTRICTO = re.compile(r"(?<![A-Z])R\s?E\W{0,2}(\d(?:\s?\d){12})(?!\s?\d)")
#: Lo que el OCR confunde con una cifra en un número impreso.
_CIFRA = r"[0-9OQDIL|SB]"
_A_CIFRA = str.maketrans("OQDIL|SB", "00011158")
#: El mismo RE como lo deja un OCR malo: «R E», «KE», «R3», «RE:», «RE-», y
#: letras por cifras («O» por «0», «I» por «1»).
RE_TOLERANTE = re.compile(rf"(?<![A-Z])[RK]\s?[E3]\W{{0,3}}({_CIFRA}(?:\s?{_CIFRA}){{12}})(?![0-9])")
#: Y si el OCR se comió el «RE»: el número de la etiqueta del radicado. En la
#: constancia del contenido de la reclamación es «N° PQR: RE2320202101914».
RE_DE_LA_ETIQUETA = re.compile(
    rf"(?:PQR|RADICAD[OA]|RADICACION)\W{{0,12}}(?:N[O0]?\W{{0,4}})?(?:[RK]\s?[E3]\W{{0,3}})?"
    rf"({_CIFRA}(?:\s?{_CIFRA}){{12}})(?![0-9])"
)
COLUMNAS = ["fecha", "paso", "caja", "archivo_antes", "archivo_despues", "re", "leido_de",
            "estado", "detalle", "indice_antes", "indice_despues"]
#: El índice: ocho columnas (A Nombre, B Fecha Creación, C Fecha Incorporación,
#: D Orden, E Páginas, F Formato, G Observaciones, H Responsable) y el pie.
ANCHO_DEL_INDICE = 8
CIERRE = "FECHA DE CIERRE DEL EXPEDIENTE"
#: Lo más largo que Excel admite en el nombre de una hoja (el general lleva una por caja).
LARGO_DE_HOJA = 31


# -- utilidades -----------------------------------------------------------------------


def _pymupdf():
    try:
        import pymupdf
    except ImportError:  # PyMuPDF anterior a la 1.24
        import fitz as pymupdf
    return pymupdf


def _plano(texto) -> str:
    sin_tildes = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", sin_tildes).strip()


def _base(texto) -> str:
    """El título sin su RE: «RECLAMO-RE2310202315695» y «RECLAMO» son el mismo documento."""
    return re.sub(r"\s*RE\d{13}$", "", _plano(texto))


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _entero(valor) -> int | None:
    try:
        return int(float(str(valor).strip()))
    except (TypeError, ValueError):
        return None


def _numero(nombre: str) -> int:
    hallado = NUMERADO.match(nombre)
    return int(hallado.group(1)) if hallado else 10**6


def _caja(carpeta: Path, raiz: Path) -> str:
    return str(carpeta.relative_to(raiz)) if carpeta != raiz else "."


def _fila_vacia(paso: str, caja: str, **datos) -> dict:
    return {**{c: "" for c in COLUMNAS}, "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "paso": paso, "caja": caja, **datos}


#: Las esperas entre intentos cuando otro programa tiene un archivo abierto un
#: momento: un visor, el antivirus, la sincronización de la nube.
ESPERAS = (0.5, 1.0, 2.0, 4.0)
#: El largo máximo de una ruta en Windows.
LARGO_MAXIMO = 255


def _con_reintentos(hacer):
    for espera in (*ESPERAS, None):
        try:
            return hacer()
        except PermissionError:
            if espera is None:
                raise
            time.sleep(espera)
    return None


def _bloqueado(ruta: Path) -> str | None:
    """Por qué no se puede escribir ``ruta`` (abierta en Excel, de sólo lectura), o ``None``."""
    for espera in (*ESPERAS, None):
        try:
            with ruta.open("r+b"):
                return None
        except FileNotFoundError:
            return None
        except OSError as error:
            if espera is None:
                return error.strerror or str(error)
            time.sleep(espera)
    return None


def _es_oculto(ruta: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        atributos = ctypes.windll.kernel32.GetFileAttributesW(str(ruta))
        return atributos not in (-1, 0xFFFFFFFF) and bool(atributos & 0x2)
    except Exception:  # noqa: BLE001 - sin poder mirarlo, se trata como visible
        return False


def _ocultar(ruta: Path, oculto: bool = True) -> None:
    """Pone o quita la marca de oculto: Windows no deja reemplazar un archivo oculto."""
    if os.name != "nt" or not ruta.exists():
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(ruta), 0x2 if oculto else 0x80)
    except Exception:  # noqa: BLE001 - es cortesía, no requisito
        pass


def _reemplazar(temporal: Path, ruta: Path, *, oculto: bool | None = None) -> None:
    """``temporal`` en el sitio de ``ruta``, entero o nada, aunque ``ruta`` esté oculta."""
    oculto = _es_oculto(ruta) if oculto is None else oculto
    if oculto:
        _ocultar(ruta, False)
    try:
        _con_reintentos(lambda: os.replace(temporal, ruta))
    finally:
        if oculto:
            _ocultar(ruta, True)


def _guardar_json(ruta: Path, datos: dict) -> None:
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    try:
        _reemplazar(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def _guardar_libro(libro, ruta: Path) -> None:
    temporal = ruta.with_name(f".{ruta.stem}.guardando.xlsx")
    try:
        libro.save(temporal)
        _reemplazar(temporal, ruta, oculto=False)
    finally:
        temporal.unlink(missing_ok=True)


def _respaldar(ruta: Path, raiz: Path, respaldo: Path) -> None:
    """Copia ``ruta`` al respaldo tal como está, sólo la primera vez.

    El respaldo guarda lo de antes del primer --aplicar: las corridas siguientes no
    lo pisan, y --deshacer vuelve siempre al estado original. Si la copia no sale
    entera, se lanza el error y quien llama no toca el original.
    """
    destino = respaldo / ruta.relative_to(raiz)
    if destino.exists():
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".copiando")
    shutil.copy2(ruta, temporal)
    if temporal.stat().st_size != ruta.stat().st_size:
        temporal.unlink(missing_ok=True)
        raise OSError(f"la copia de respaldo de «{ruta.name}» salió incompleta")
    os.replace(temporal, destino)


def ruta_del_servicio(texto: str) -> Path:
    """«C:\\Users\\…» como la ve el contenedor («/equipo/c/Users/…»); tal cual en Windows."""
    try:
        from resolutions.api.rutas_del_equipo import al_servicio

        return Path(al_servicio(texto))
    except Exception:  # noqa: BLE001 - sin el bot instalado, se traduce a mano
        hallado = re.match(r"^([A-Za-z]):[\\/](.*)$", texto.strip().strip('"'))
        if hallado and Path("/equipo").is_dir():
            return Path("/equipo") / hallado.group(1).lower() / hallado.group(2).replace("\\", "/")
        return Path(texto.strip().strip('"'))


# -- el RE ------------------------------------------------------------------------------


def _con_forma(cifras: str) -> bool:
    return len(cifras) == 13 and cifras.isdigit() and 2018 <= int(cifras[4:8]) <= 2029


def radicado(texto: str) -> str | None:
    """El radicado del texto: sólo el que va escrito con «RE» delante.

    Lo pidió el operador el 2026-10-28: «es importante que sea el radicado y que
    inicie por RE». Trece cifras sueltas no valen: la respuesta de la empresa
    trae también su «Consecutivo No. 9233202202670», que no es el radicado.
    """
    plano = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode().upper()
    for hallado in RE_ESTRICTO.finditer(plano):
        cifras = re.sub(r"\s", "", hallado.group(1))
        if _con_forma(cifras):
            return f"RE{cifras}"
    # Lo que leyó mal el OCR: el «RE» deformado, o la etiqueta del radicado
    # sin él. Sigue siendo el radicado -- nunca el «Consecutivo» --, y la forma
    # (trece cifras con el año en su sitio) descarta lo que no lo es.
    for patron in (RE_TOLERANTE, RE_DE_LA_ETIQUETA):
        for hallado in patron.finditer(plano):
            cifras = re.sub(r"\s", "", hallado.group(1)).translate(_A_CIFRA)
            if _con_forma(cifras):
                return f"RE{cifras}"
    return None


def buscar_tesseract() -> tuple[str | None, str]:
    """(ejecutable, idioma) de Tesseract, o ``(None, "")`` si no está instalado.

    En Windows el instalador no siempre lo pone en el PATH: se mira también donde
    lo deja, para todos los usuarios (Program Files) o sólo para el que lo instaló
    (AppData\\Local\\Programs). Sin el español, el inglés lee igual «RE» y las cifras.
    """
    del_usuario = os.environ.get("LOCALAPPDATA") or ""
    candidatos = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(del_usuario, "Programs", "Tesseract-OCR", "tesseract.exe") if del_usuario else None,
        os.path.join(del_usuario, "Tesseract-OCR", "tesseract.exe") if del_usuario else None,
    ]
    for ruta in candidatos:
        if not ruta or not Path(ruta).exists():
            continue
        try:
            salida = subprocess.run([ruta, "--list-langs"], capture_output=True, encoding="utf-8",
                                    errors="replace", timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        idiomas = set((salida.stdout or "").split()) | set((salida.stderr or "").split())
        return ruta, "spa" if "spa" in idiomas else "eng"
    return None, ""


def _avisos_del_pdf() -> str:
    """Lo que la librería avisó del último PDF abierto, en una línea.

    Un PDF con daños leves -- «object is not a stream», «invalid ICC colorspace»
    en MAGANGUE (2026-10-28) -- se lee igual: el aviso va a su fila del registro y
    no ensucia la pantalla.
    """
    pymupdf = _pymupdf()
    try:
        avisos = pymupdf.TOOLS.mupdf_warnings(reset=True)
    except Exception:  # noqa: BLE001 - sin avisos, nada que anotar
        return ""
    lineas = [linea.strip() for linea in str(avisos or "").splitlines() if linea.strip()]
    return ("avisos del PDF: " + "; ".join(dict.fromkeys(lineas)))[:300] if lineas else ""


#: Páginas en las que se busca el RE con OCR, y las pasadas por página: dpi,
#: modo de Tesseract y giro. La primera acierta casi siempre; las demás son
#: para el escaneo torcido, el sello débil o la hoja al revés.
PAGINAS_CON_OCR = 3
PASADAS = ((300, "6", 0), (400, "4", 0), (400, "11", 0), (300, "6", 180))


def _ocr(pagina, dpi: int, modo: str, giro: int, tesseract: str, idioma: str) -> str:
    pymupdf = _pymupdf()
    escala = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(giro)
    imagen = pagina.get_pixmap(matrix=escala, colorspace=pymupdf.csGRAY)
    with tempfile.TemporaryDirectory() as temporal:
        ruta = Path(temporal) / "pagina.png"
        imagen.save(str(ruta))
        # Tesseract escribe en UTF-8. Sin decirlo, Python en Windows lo lee con la
        # página de códigos del sistema (cp1252), se cae con un byte como 0x81 y lo
        # leído se pierde: el RE no aparecía aunque estuviera (2026-11-04).
        salida = subprocess.run(
            [tesseract, str(ruta), "stdout", "-l", idioma, "--psm", modo],
            capture_output=True, encoding="utf-8", errors="replace", timeout=TIEMPO_MAXIMO_DE_TESSERACT, check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    return salida.stdout or ""


def leer_el_re(pdf: Path, tesseract: str | None, idioma: str) -> tuple[str | None, str, str, int]:
    """(RE, de dónde salió, avisos del PDF, páginas).

    Primero el texto de todas las páginas, que es gratis. Si no está, OCR de las
    primeras páginas con varias pasadas: el 2026-10-28 quedaron constancias sin
    RE porque sólo se miraban dos páginas de texto y una pasada de OCR.
    """
    pymupdf = _pymupdf()
    for apagar in ("mupdf_display_errors", "mupdf_display_warnings"):
        if hasattr(pymupdf.TOOLS, apagar):
            getattr(pymupdf.TOOLS, apagar)(False)
    _avisos_del_pdf()  # lo que quedara del PDF anterior
    fallos: list[str] = []
    with pymupdf.open(str(pdf)) as documento:
        paginas = documento.page_count
        if paginas == 0:
            return None, "PDF sin páginas", _avisos_del_pdf(), 0
        for numero in range(paginas):
            try:
                texto = documento[numero].get_text()
            except Exception as error:  # noqa: BLE001 - una página rota no tapa las demás
                fallos.append(f"página {numero + 1} sin texto legible: {error}")
                continue
            if hallado := radicado(texto):
                return hallado, f"texto del PDF (página {numero + 1})", _avisos_del_pdf(), paginas
        if not tesseract:
            return (None, "el texto del PDF no trae el RE y este equipo no tiene Tesseract para leer la imagen",
                    _avisos_del_pdf(), paginas)
        inicio = time.monotonic()
        for dpi, modo, giro in PASADAS:
            for numero in range(min(PAGINAS_CON_OCR, paginas)):
                if time.monotonic() - inicio > TIEMPO_MAXIMO_DE_OCR:
                    return (None, f"se agotó el tiempo del OCR ({TIEMPO_MAXIMO_DE_OCR} s) sin encontrar el RE",
                            _avisos_del_pdf(), paginas)
                try:
                    leido = _ocr(documento[numero], dpi, modo, giro, tesseract, idioma)
                except Exception as error:  # noqa: BLE001 - se prueba la siguiente pasada
                    fallos.append(f"OCR de la página {numero + 1}: {error}")
                    continue
                if hallado := radicado(leido):
                    girada = ", girada" if giro else ""
                    return hallado, f"OCR de la página {numero + 1} ({dpi} dpi{girada})", _avisos_del_pdf(), paginas
    motivo = "no se encontró el RE en el texto ni con el OCR (todas las pasadas)"
    if fallos:
        motivo += "; " + "; ".join(dict.fromkeys(fallos))[:200]
    return None, motivo, _avisos_del_pdf(), paginas


# -- el índice ----------------------------------------------------------------------------


def _valores(hoja) -> list[tuple]:
    """Las ocho columnas de cada fila de la hoja, de una sola pasada."""
    return [
        tuple(fila) + (None,) * (ANCHO_DEL_INDICE - len(fila))
        for fila in hoja.iter_rows(min_row=1, max_col=ANCHO_DEL_INDICE, values_only=True)
    ]


def _tabla(valores: list[tuple]) -> tuple[int, int] | None:
    """Las filas de los documentos (desde 1): (primera, la siguiente a la última), o ``None``.

    La tabla empieza bajo el rótulo «Nombre Documento» y termina en la primera fila
    vacía o en el pie «FECHA DE CIERRE DEL EXPEDIENTE». Un libro sin esos rótulos no
    es el índice de la plantilla y no se toca.
    """
    for puesto, fila in enumerate(valores[:40]):
        if _plano(fila[0]) != "NOMBRE DOCUMENTO":
            continue
        if not (_plano(fila[1]).startswith("FECHA CREACION") and _plano(fila[3]).startswith("ORDEN")):
            return None
        primera = puesto + 2
        fin = primera
        while fin - 1 < len(valores):
            nombre = _plano(valores[fin - 1][0])
            if not nombre or nombre.startswith(_plano(CIERRE)):
                break
            fin += 1
        return primera, fin
    return None


def _cabecera(valores: list[tuple]) -> dict[str, tuple[int, object]]:
    """«expediente» y «nic»: (fila, valor de la columna B), por su rótulo en la columna A."""
    hallado: dict[str, tuple[int, object]] = {}
    for puesto, fila in enumerate(valores[:12]):
        rotulo = _plano(fila[0])
        if rotulo.startswith("NOMBRE DEL EXPEDIENTE"):
            hallado.setdefault("expediente", (puesto + 1, fila[1]))
        elif rotulo.startswith("IDENTIFICACION"):
            hallado.setdefault("nic", (puesto + 1, fila[1]))
    return hallado


_FECHA_DMA = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\b")
_FECHA_AMD = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _fecha(valor) -> date | None:
    """La «Fecha Creación Documento»: «dd/mm/aaaa» como la escribe el bot; «S.F.» no es fecha."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "")
    for patron, orden in ((_FECHA_DMA, (3, 2, 1)), (_FECHA_AMD, (1, 2, 3))):
        if hallado := patron.match(texto):
            try:
                return date(*(int(hallado.group(g)) for g in orden))
            except ValueError:
                return None
    return None


def orden_cronologico(fechas: list[date | None]) -> list[int]:
    """Los puestos de hoy, en el orden nuevo: lo más antiguo primero.

    Con la misma fecha, como estaban; sin fecha, al final, también como estaban.
    """
    return sorted(range(len(fechas)), key=lambda i: (fechas[i] is None, fechas[i] or date.min, i))


def _combinadas_en(hoja, primera: int, fin: int) -> bool:
    return any(rango.min_row < fin and rango.max_row >= primera for rango in hoja.merged_cells.ranges)


def _reordenar_filas(hoja, primera: int, puestos: list[int]) -> None:
    """La fila ``primera + k`` pasa a ser la que estaba en ``primera + puestos[k]``.

    Se mueve la fila entera -- valores, formato y alto, que el bot ajusta al largo
    del nombre -- y «Orden Documento» se renumera 1, 2, 3…
    """
    copia = []
    for k in range(len(puestos)):
        fila = primera + k
        copia.append((
            [hoja.cell(fila, c).value for c in range(1, ANCHO_DEL_INDICE + 1)],
            [copy(hoja.cell(fila, c)._style) for c in range(1, ANCHO_DEL_INDICE + 1)],
            hoja.row_dimensions[fila].height,
        ))
    for k, puesto in enumerate(puestos):
        valores, estilos, alto = copia[puesto]
        fila = primera + k
        for c in range(1, ANCHO_DEL_INDICE + 1):
            celda = hoja.cell(fila, c)
            celda.value = valores[c - 1]
            celda._style = copy(estilos[c - 1])
        hoja.cell(fila, 4).value = k + 1
        hoja.row_dimensions[fila].height = alto


def _filas_del_indice(valores: list[tuple], primera: int, fin: int) -> list[dict]:
    return [
        {"fila": primera + k, "nombre": _texto(fila[0]), "orden": _entero(fila[3]), "paginas": _entero(fila[4])}
        for k, fila in enumerate(valores[primera - 1:fin - 1])
    ]


def _en_orden_de_archivos(filas: list[dict], titulos: dict[int, str]) -> bool:
    """Si el «Orden Documento» de cada fila sigue siendo el número de su PDF.

    Es lo que entrega el bot. Deja de serlo cuando el paso 2 ordena por fecha: desde
    entonces la fila de un PDF se busca por su título.
    """
    return bool(filas) and all(
        fila["orden"] in titulos and _base(titulos[fila["orden"]]) == _base(fila["nombre"]) for fila in filas
    )


def _fila_del_pdf(filas: list[dict], usadas: set[int], numero: int, titulo: str, paginas: int,
                  en_orden: bool) -> tuple[int | None, str]:
    """(fila de Excel del PDF, por qué no se encontró): sólo una fila segura.

    Con el orden del bot, la del mismo número y título. Si no, la única con ese
    título sin RE; si hay varias, la única con sus mismas páginas. Con dos iguales
    no se adivina: el índice de ese PDF queda como está y la revisión lo lista.
    """
    buscado = _plano(titulo)
    libres = [fila for fila in filas if fila["fila"] not in usadas and _plano(fila["nombre"]) == buscado]
    if en_orden:
        for fila in libres:
            if fila["orden"] == numero:
                return fila["fila"], ""
        return None, "su fila del índice no coincide"
    if len(libres) == 1:
        return libres[0]["fila"], ""
    if not libres:
        return None, "el índice no tiene una fila con su título"
    por_paginas = [fila for fila in libres if paginas and fila["paginas"] == paginas]
    if len(por_paginas) == 1:
        return por_paginas[0]["fila"], ""
    return None, "hay varias filas iguales en el índice y no se sabe cuál es la suya"


# -- paso 1: el RE --------------------------------------------------------------------------


def _leer_constancias(carpeta: Path) -> list[tuple[Path, dict]]:
    leidas = []
    for ruta in sorted(carpeta.iterdir()):
        if ruta.is_file() and CONSTANCIA.match(ruta.name):
            try:
                leidas.append((ruta, json.loads(ruta.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    # En el orden en que el bot numera la caja: por el PDF de origen.
    leidas.sort(key=lambda par: str(par[1].get("origen") or "").casefold())
    return leidas


def _comprobar_el_renombre(carpeta: Path, antes: str, despues: str, bytes_antes: int) -> str:
    """Lo que dice el disco después de renombrar: la evidencia de que el cambio se hizo."""
    nuevo = carpeta / despues
    if not nuevo.exists():
        return "FALLA: el archivo con el nombre nuevo no está en el disco"
    if (carpeta / antes).exists():
        return "FALLA: el archivo con el nombre viejo sigue en el disco"
    if nuevo.stat().st_size != bytes_antes:
        return f"FALLA: el archivo cambió de tamaño ({bytes_antes} → {nuevo.stat().st_size} bytes)"
    return f"archivo OK (en el disco está el nombre nuevo y ya no el viejo, mismos {bytes_antes} bytes)"


def _comprobar_la_constancia(ruta: Path, despues: str) -> str:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"FALLA: la constancia no se pudo releer ({error})"
    if any(Path(str(a.get("ruta") or "")).name == despues for a in datos.get("archivos") or []):
        return "constancia OK"
    return "FALLA: la constancia releída no tiene el nombre nuevo"


def _releer_el_indice(ruta: Path) -> tuple[list[tuple], dict] | None:
    """(filas de documentos, cabecera) del índice tal como quedó en el disco."""
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True)
    try:
        hoja = libro.active
        hoja.reset_dimensions()
        valores = _valores(hoja)
    finally:
        libro.close()
    tabla = _tabla(valores)
    if tabla is None:
        return None
    return valores[tabla[0] - 1:tabla[1] - 1], _cabecera(valores)


def _comprobar_el_indice(ruta: Path, nombres: list, expediente) -> str:
    """Se vuelve a abrir el Excel ya guardado y se mira que diga lo que se quiso escribir."""
    try:
        releido = _releer_el_indice(ruta)
    except Exception as error:  # noqa: BLE001
        return f"FALLA: el índice no se pudo releer ({error})"
    if releido is None:
        return "FALLA: el índice releído ya no tiene la forma de la plantilla"
    documentos, cabecera = releido
    if [_texto(fila[0]) for fila in documentos] != [_texto(nombre) for nombre in nombres]:
        return "FALLA: en el índice releído las filas no quedaron en el orden esperado"
    if any(_entero(fila[3]) != k + 1 for k, fila in enumerate(documentos)):
        return "FALLA: en el índice releído «Orden Documento» no va 1, 2, 3…"
    fechas = [_fecha(fila[1]) for fila in documentos]
    if orden_cronologico(fechas) != list(range(len(fechas))):
        return "FALLA: en el índice releído las fechas no van de la más antigua a la más nueva"
    if expediente is not None and _texto(cabecera.get("expediente", (None, None))[1]) != _texto(expediente):
        return "FALLA: en el índice releído «Nombre del Expediente» no es el NIC"
    return ("OK: releído el Excel del disco, quedó en ese orden" + (" y con el expediente = NIC"
                                                                   if expediente is not None else ""))


def _pdfs_de(carpeta: Path) -> list[Path]:
    return sorted(
        (ruta for ruta in carpeta.iterdir() if ruta.is_file() and ruta.suffix.lower() == ".pdf"),
        key=lambda ruta: (_numero(ruta.name), ruta.name),
    )


def _leer_o_recordar(pdf: Path, caja: str, lecturas: dict[str, dict], nuevas: list[dict],
                     tesseract: str | None, idioma: str) -> tuple[str | None, str, str, int]:
    """El RE del PDF: lo ya leído si el archivo es el mismo (tamaño y fecha), si no, se lee.

    Un «sin RE» leído sin Tesseract no se cree si ahora sí lo hay: se vuelve a leer.
    """
    datos = pdf.stat()
    previa = lecturas.get(pdf.name)
    if (
        previa
        and previa.get("bytes") == datos.st_size
        and previa.get("mtime_ns") == datos.st_mtime_ns
        and (previa.get("re") or previa.get("con_tesseract") or not tesseract)
        and not str(previa.get("origen") or "").startswith("se agotó")
    ):
        return (previa.get("re"), f"{previa.get('origen') or ''} (leído en una corrida anterior)".strip(),
                previa.get("avisos") or "", int(previa.get("paginas") or 0))
    numero_re, origen, avisos, paginas = leer_el_re(pdf, tesseract, idioma)
    nuevas.append({"caja": caja, "archivo": pdf.name, "bytes": datos.st_size, "mtime_ns": datos.st_mtime_ns,
                   "re": numero_re, "origen": origen, "avisos": avisos, "paginas": paginas,
                   "con_tesseract": bool(tesseract)})
    return numero_re, origen, avisos, paginas


def paso_re(carpeta: str, raiz: str, raiz_en_windows: str, respaldo: str, aplicar: bool,
            tesseract: str | None, idioma: str, lecturas: dict[str, dict] | None = None,
            nuevas: list[dict] | None = None) -> list[dict]:
    """Paso 1 en una caja: el RE en el nombre del PDF, en su fila del índice y en su constancia.

    Un PDF que ya trae su RE -- de una corrida que se cortó a mitad de la caja --
    también se mira: si su constancia o su índice se quedaron con el nombre viejo,
    se completan. Si no, el bot vería la entrega incompleta y la volvería a procesar.
    ``lecturas``: lo ya leído de cada PDF de la caja; lo que se lea ahora va a ``nuevas``.
    """
    from openpyxl import load_workbook

    carpeta_p, raiz_p, respaldo_p = Path(carpeta), Path(raiz), Path(respaldo)
    caja = _caja(carpeta_p, raiz_p)
    lecturas = lecturas if lecturas is not None else {}
    nuevas = nuevas if nuevas is not None else []
    filas: list[dict] = []

    def anotar(**datos) -> None:
        filas.append(_fila_vacia("1 RE", caja, **datos))

    pdfs = _pdfs_de(carpeta_p)
    titulos = {}
    for pdf in pdfs:
        if hallado := NUMERADO.match(pdf.name):
            titulos.setdefault(int(hallado.group(1)), hallado.group(2))

    # 1. Qué cambiar. «renombrar» falso: el PDF ya tiene su RE y sólo se
    # completan su constancia y su índice si se quedaron atrás.
    cambios: list[dict] = []
    for pdf in pdfs:
        hallado = NUMERADO.match(pdf.name)
        if not hallado:
            continue
        numero, titulo = int(hallado.group(1)), hallado.group(2)
        ya = CON_RE.search(titulo)
        sin_re = titulo[: ya.start()] if ya else titulo
        if _plano(sin_re) not in TITULOS_CON_RE:
            continue
        if ya:
            cambios.append({"antes": f"{hallado.group(1)}_{sin_re}.pdf", "despues": pdf.name, "numero": numero,
                            "titulo": sin_re, "re": ya.group(0)[1:].upper(), "origen": "", "renombrar": False,
                            "avisos": "", "paginas": 0})
            continue
        try:
            numero_re, origen, avisos, paginas = _leer_o_recordar(pdf, caja, lecturas, nuevas, tesseract, idioma)
        except Exception as error:  # noqa: BLE001 - un PDF ilegible no para el resto
            anotar(archivo_antes=pdf.name, estado="error", detalle=f"no se pudo abrir: {error}")
            continue
        if not numero_re:
            anotar(archivo_antes=pdf.name, estado="sin RE", detalle="; ".join(x for x in (origen, avisos) if x))
            continue
        nuevo = f"{hallado.group(1)}_{titulo.upper()}-{numero_re}.pdf"
        largo = len(raiz_en_windows.rstrip("\\/")) + len(str(carpeta_p / nuevo)) - len(str(raiz_p))
        if largo > LARGO_MAXIMO:
            anotar(archivo_antes=pdf.name, archivo_despues=nuevo, re=numero_re, leido_de=origen,
                   estado="nombre muy largo",
                   detalle=f"la ruta quedaría de {largo} caracteres y Windows admite {LARGO_MAXIMO}")
            continue
        if (carpeta_p / nuevo).exists():
            anotar(archivo_antes=pdf.name, archivo_despues=nuevo, re=numero_re, leido_de=origen,
                   estado="choque de nombre", detalle="ya hay un archivo con ese nombre")
            continue
        cambios.append({"antes": pdf.name, "despues": nuevo, "numero": numero, "titulo": titulo, "re": numero_re,
                        "origen": origen, "renombrar": True, "avisos": avisos, "paginas": paginas})
    if not cambios:
        return filas

    # 2. El índice de la caja, si tiene la forma de la plantilla.
    ruta_del_indice = carpeta_p / INDICE
    libro = hoja = None
    filas_del_indice: list[dict] = []
    en_orden = False
    sin_indice = ""
    if ruta_del_indice.exists():
        try:
            libro = load_workbook(ruta_del_indice)
            if len(libro.sheetnames) != 1:
                sin_indice, libro = "el índice de la caja tiene varias hojas: no se tocó", None
            else:
                hoja = libro.active
                valores = _valores(hoja)
                tabla = _tabla(valores)
                if tabla is None:
                    sin_indice, libro = "el índice no tiene la forma de la plantilla: no se tocó", None
                else:
                    filas_del_indice = _filas_del_indice(valores, *tabla)
                    en_orden = _en_orden_de_archivos(filas_del_indice, titulos)
        except Exception as error:  # noqa: BLE001 - sin índice legible, el PDF y su constancia igual
            sin_indice, libro = f"no se pudo leer el índice: {error}", None
    else:
        sin_indice = "la caja no tiene índice"

    # 3. Antes de tocar nada: que el índice y las constancias se dejen escribir,
    # y su copia en el respaldo. Si algo de eso falla, la caja no se toca.
    constancias = _leer_constancias(carpeta_p)
    if aplicar:
        tocar = ([ruta_del_indice] if libro is not None else []) + [ruta for ruta, _ in constancias]
        motivo = next((f"«{ruta.name}» está abierto o bloqueado ({m}); ciérrelo y vuelva a correr"
                       for ruta in tocar if (m := _bloqueado(ruta))), "")
        if not motivo:
            try:
                for ruta in tocar:
                    _respaldar(ruta, raiz_p, respaldo_p)
            except OSError as error:
                motivo = f"no se pudo copiar al respaldo: {error}"
        if motivo:
            for cambio in cambios:
                anotar(archivo_antes=cambio["antes"] if cambio["renombrar"] else cambio["despues"],
                       re=cambio["re"], estado="error", detalle=f"no se tocó la caja: {motivo}")
            return filas

    usadas: set[int] = set()
    cambio_el_indice = False
    for cambio in cambios:
        antes, despues, numero_re, origen = cambio["antes"], cambio["despues"], cambio["re"], cambio["origen"]
        renombrar = cambio["renombrar"]
        sufijo = f"-{numero_re}"
        en_disco = antes if renombrar else despues
        if not (carpeta_p / en_disco).exists():
            anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, estado="error",
                   detalle="el PDF ya no está en la caja")
            continue

        # Su fila del índice, sólo si es segura.
        indice_antes = indice_despues = ""
        fila_de_la_hoja, sin_fila = None, sin_indice
        if libro is not None:
            fila_de_la_hoja, sin_fila = _fila_del_pdf(filas_del_indice, usadas, cambio["numero"], cambio["titulo"],
                                                      cambio["paginas"], en_orden)
            if fila_de_la_hoja is not None:
                usadas.add(fila_de_la_hoja)
                indice_antes = _texto(hoja.cell(fila_de_la_hoja, 1).value)
                indice_despues = f"{indice_antes}{sufijo}"

        # En la constancia: el archivo con su nombre de antes, y su fila en la
        # copia del índice.
        suya = None
        for ruta, datos in constancias:
            de_la_constancia = sorted(
                (a for a in datos.get("archivos") or [] if str(a.get("ruta") or "").lower().endswith(".pdf")),
                key=lambda a: (_numero(Path(str(a.get("ruta"))).name), str(a.get("ruta"))),
            )
            for puesto, archivo in enumerate(de_la_constancia):
                if Path(str(archivo.get("ruta"))).name == antes:
                    suya = (ruta, datos, archivo, puesto, len(de_la_constancia))
                    break
            if suya:
                break

        if not renombrar and suya is None and fila_de_la_hoja is None:
            anotar(archivo_antes=despues, re=numero_re, estado="ya tenía RE")
            continue
        detalle = [cambio["avisos"]] if cambio["avisos"] else []
        if not renombrar:
            completar = [que for que, falta in (("su constancia", suya), ("su índice", fila_de_la_hoja))
                         if falta is not None]
            detalle.append(("se completaría " if not aplicar else "se completó ") + " y ".join(completar)
                           + ": quedaron con el nombre viejo")
        if renombrar and suya is None:
            detalle.append("sin constancia que lo nombre")
        if fila_de_la_hoja is None and renombrar:
            detalle.append(f"índice sin cambiar: {sin_fila}")

        if not aplicar:
            anotar(archivo_antes=antes if renombrar else despues, archivo_despues=despues, re=numero_re,
                   leido_de=origen, estado="se cambiaría" if renombrar else "ya tenía RE",
                   indice_antes=indice_antes, indice_despues=indice_despues, detalle="; ".join(detalle))
            continue

        # 4. Aplicar: el PDF y, en seguida, su constancia; si la constancia no se
        # deja escribir, el PDF vuelve a su nombre (que nunca queden desparejos).
        bytes_antes = (carpeta_p / en_disco).stat().st_size
        if renombrar:
            try:
                _con_reintentos(lambda a=antes, d=despues: (carpeta_p / a).rename(carpeta_p / d))
            except OSError as error:
                anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
                       estado="error", detalle=f"no se pudo renombrar: {error}")
                if fila_de_la_hoja is not None:
                    usadas.discard(fila_de_la_hoja)
                continue
        if suya:
            ruta, datos, archivo, puesto, cuantos = suya
            ruta_vieja = str(archivo["ruta"])
            con_barras = ruta_vieja.replace("\\", "/")
            archivo["ruta"] = (str(Path(con_barras).with_name(despues)).replace("\\", "/")
                               if "/" in con_barras else despues)
            filas_suyas = ((datos.get("indice") or {}).get("filas")) or []
            nombre_viejo = None
            if len(filas_suyas) == cuantos:
                nombre = str(filas_suyas[puesto].get("nombre") or "")
                if _plano(nombre) == _plano(cambio["titulo"]):
                    nombre_viejo = nombre
                    filas_suyas[puesto]["nombre"] = f"{nombre}{sufijo}"
            try:
                _guardar_json(ruta, datos)
            except OSError as error:
                archivo["ruta"] = ruta_vieja
                if nombre_viejo is not None:
                    filas_suyas[puesto]["nombre"] = nombre_viejo
                if renombrar:
                    _con_reintentos(lambda a=antes, d=despues: (carpeta_p / d).rename(carpeta_p / a))
                anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
                       estado="error", detalle=f"no se pudo actualizar la constancia: {error}")
                if fila_de_la_hoja is not None:
                    usadas.discard(fila_de_la_hoja)
                continue
        if fila_de_la_hoja is not None:
            hoja.cell(fila_de_la_hoja, 1).value = indice_despues
            cambio_el_indice = True
        anotar(archivo_antes=antes if renombrar else despues, archivo_despues=despues, re=numero_re,
               leido_de=origen, estado="renombrado" if renombrar else "ya tenía RE",
               indice_antes=indice_antes, indice_despues=indice_despues, detalle="; ".join(detalle))
        # La evidencia: lo que dice el disco, no lo que se quiso hacer.
        pruebas = [_comprobar_el_renombre(carpeta_p, antes, despues, bytes_antes)] if renombrar else []
        if suya:
            pruebas.append(_comprobar_la_constancia(suya[0], despues))
        filas[-1]["comprobado"] = " · ".join(pruebas)

    if cambio_el_indice and libro is not None:
        try:
            _guardar_libro(libro, ruta_del_indice)
        except OSError as error:
            for fila in filas:
                if fila["indice_despues"]:
                    fila["estado"] = "error"
                    fila["detalle"] = (f"el PDF y su constancia quedaron con el RE pero no se pudo guardar el "
                                       f"índice ({error}); vuelva a correr para completarlo")
    if aplicar:
        # El índice, releído del disco después de guardarlo.
        nombres_releidos: set[str] = set()
        if cambio_el_indice:
            try:
                releido = _releer_el_indice(ruta_del_indice)
                nombres_releidos = {_texto(fila[0]) for fila in releido[0]} if releido else set()
            except Exception:  # noqa: BLE001 - queda como FALLA en su fila
                nombres_releidos = set()
        for fila in filas:
            if "comprobado" not in fila:
                continue
            if fila["indice_despues"]:
                prueba = ("índice OK" if fila["indice_despues"] in nombres_releidos
                          else "FALLA: el índice releído no tiene el nombre nuevo")
            else:
                prueba = "índice sin cambiar (ver el detalle)"
            fila["comprobado"] = " · ".join(x for x in (fila["comprobado"], prueba) if x)
    return filas


# -- paso 2: el índice de la caja -------------------------------------------------------------


def paso_indice(carpeta: str, raiz: str, respaldo: str, aplicar: bool) -> dict:
    """Paso 2 en una caja: filas por fecha, «Orden Documento» 1, 2, 3… y el expediente = NIC.

    Devuelve lo que quedó (o quedaría) en el índice, para el paso 3, y las filas
    del registro.
    """
    from openpyxl import load_workbook

    carpeta_p, raiz_p = Path(carpeta), Path(raiz)
    caja = _caja(carpeta_p, raiz_p)
    resultado = {"caja": caja, "estado": "", "filas": [], "indice": None, "ordenado": False, "expediente": False,
                 "antes": [], "despues": [], "expediente_antes": "", "nic": "", "comprobado": ""}

    def terminar(estado: str, detalle: str = "", anotar: bool = True) -> dict:
        resultado["estado"] = estado
        if anotar:
            resultado["filas"].append(_fila_vacia("2 INDICE", caja, archivo_antes=INDICE, estado=estado,
                                                  detalle=detalle))
        return resultado

    ruta = carpeta_p / INDICE
    if not ruta.exists():
        return terminar("sin índice", anotar=False)
    try:
        libro = load_workbook(ruta)
    except Exception as error:  # noqa: BLE001 - un índice ilegible no para las demás cajas
        return terminar("error", f"no se pudo leer el índice: {error}")
    if len(libro.sheetnames) != 1:
        return terminar("error", "el índice de la caja tiene varias hojas: no se tocó")
    hoja = libro.active
    valores = _valores(hoja)
    tabla = _tabla(valores)
    if tabla is None:
        return terminar("error", "el índice no tiene la forma de la plantilla: no se tocó")
    primera, fin = tabla
    documentos = valores[primera - 1:fin - 1]
    fechas = [_fecha(fila[1]) for fila in documentos]
    puestos = orden_cronologico(fechas)
    finales = [tuple(documentos[i][:3]) + (k + 1,) + tuple(documentos[i][4:ANCHO_DEL_INDICE])
               for k, i in enumerate(puestos)]
    reordenar = puestos != list(range(len(puestos))) or any(
        _entero(fila[3]) != k + 1 for k, fila in enumerate(documentos)
    )
    cabecera = _cabecera(valores)
    nic = cabecera.get("nic", (None, None))[1]
    fila_del_expediente, expediente = cabecera.get("expediente", (None, None))
    poner_expediente = fila_del_expediente is not None and bool(_texto(nic)) and _texto(expediente) != _texto(nic)
    resultado["indice"] = {"nic": nic, "documentos": finales}
    resultado["antes"] = [(_texto(fila[0]), _texto(fila[1]) or "sin fecha") for fila in documentos]
    resultado["despues"] = [(_texto(documentos[i][0]), _texto(documentos[i][1]) or "sin fecha") for i in puestos]
    resultado["expediente_antes"], resultado["nic"] = _texto(expediente), _texto(nic)

    avisos = []
    if not _texto(nic):
        avisos.append("el índice no tiene «Identificación / Nic»: «Nombre del Expediente» quedó como estaba")
    elif fila_del_expediente is None:
        avisos.append("no se encontró la celda «Nombre del Expediente»")
    sin_fecha = [_texto(documentos[i][0]) for i, fecha in enumerate(fechas) if fecha is None]
    if sin_fecha:
        avisos.append(f"{len(sin_fecha)} sin fecha, al final: " + "; ".join(sin_fecha)[:200])
    if not reordenar and not poner_expediente:
        return terminar("ya estaba bien", "; ".join(avisos), anotar=bool(avisos))

    detalle = []
    if reordenar:
        detalle.append("orden nuevo: " + " | ".join(
            f"{k + 1}. {_texto(documentos[i][0])} ({_texto(documentos[i][1]) or 'sin fecha'})"
            for k, i in enumerate(puestos)
        ))
    if poner_expediente:
        detalle.append(f"Nombre del Expediente: «{_texto(expediente)}» → «{_texto(nic)}»")
    detalle.extend(avisos)
    resultado["ordenado"], resultado["expediente"] = reordenar, poner_expediente
    if not aplicar:
        return terminar("se cambiaría", "; ".join(detalle)[:2000])

    if motivo := _bloqueado(ruta):
        resultado["ordenado"] = resultado["expediente"] = False
        return terminar("error", f"«{INDICE}» está abierto o bloqueado ({motivo}); ciérrelo y vuelva a correr")
    if reordenar and _combinadas_en(hoja, primera, fin):
        resultado["ordenado"] = resultado["expediente"] = False
        return terminar("error", "la tabla del índice tiene celdas combinadas: no se tocó")
    try:
        _respaldar(ruta, raiz_p, Path(respaldo))
        if reordenar:
            _reordenar_filas(hoja, primera, puestos)
        if poner_expediente:
            hoja.cell(fila_del_expediente, 2).value = nic
        _guardar_libro(libro, ruta)
    except OSError as error:
        resultado["ordenado"] = resultado["expediente"] = False
        return terminar("error", f"no se pudo guardar el índice: {error}")
    resultado["comprobado"] = _comprobar_el_indice(ruta, [fila[0] for fila in finales],
                                                   nic if poner_expediente else None)
    detalle.append(f"comprobado: {resultado['comprobado']}")
    return terminar("cambiado", "; ".join(detalle)[:2000])


# -- paso 3: el índice general ----------------------------------------------------------------


def nombre_de_hoja(nombre: str) -> str:
    """El nombre que el bot le da a la hoja de una caja en el índice general."""
    return (re.sub(r"[\[\]:*?/\\]+", " ", nombre).strip() or "Caja")[:LARGO_DE_HOJA]


def _clave_de_la_fila(fila: tuple) -> tuple:
    """Lo que identifica un documento en una hoja, sin su RE ni su orden."""
    return (_base(fila[0]),) + tuple(_texto(valor) for valor in (fila[1], fila[2], *fila[4:ANCHO_DEL_INDICE]))


def paso_general(raiz: Path, respaldo: Path, aplicar: bool, indices: dict[str, dict], informar=None,
                 evidencias: list | None = None) -> tuple[list[dict], dict]:
    """Paso 3: la hoja de cada caja en el índice general, igual que el índice de su caja.

    Sólo se cambian los nombres (su RE), el orden de las filas, «Orden Documento» y
    el expediente. Una hoja que no tiene los mismos documentos que su caja, o con
    otro NIC, no se toca y queda anotada. ``informar`` recibe en qué va (el libro
    puede tener treinta mil hojas y tardar minutos); ``evidencias``, (caja, qué se
    hizo en su hoja).
    """
    from openpyxl import load_workbook

    informar = informar or (lambda texto: None)
    evidencias = evidencias if evidencias is not None else []
    filas: list[dict] = []
    cuentas = {"hojas": 0, "cambiadas": 0, "iguales": 0, "no cuadran": 0}

    def anotar(caja: str, estado: str, detalle: str) -> None:
        filas.append(_fila_vacia("3 GENERAL", caja, archivo_antes=INDICE, estado=estado, detalle=detalle))

    ruta = raiz / INDICE
    if not ruta.exists():
        return filas, {**cuentas, "sin general": 1}
    por_hoja: dict[str, list[str]] = {}
    for caja in indices:
        if caja != ".":
            por_hoja.setdefault(nombre_de_hoja(Path(caja).name).lower(), []).append(caja)
    if aplicar and (motivo := _bloqueado(ruta)):
        anotar(".", "error", f"«{INDICE}» de la raíz está abierto o bloqueado ({motivo}); ciérrelo y vuelva a correr")
        return filas, cuentas
    informar(f"abriendo el índice general ({ruta.stat().st_size / 1e6:.0f} MB; con miles de hojas tarda minutos)")
    libro = load_workbook(ruta, read_only=not aplicar)
    try:
        total = len(libro.sheetnames)
        for numero, titulo in enumerate(libro.sheetnames, start=1):
            if numero % 200 == 0:
                informar(f"revisando las hojas del índice general: {numero}/{total}")
            cajas = por_hoja.get(titulo.lower())
            if not cajas:
                continue
            cuentas["hojas"] += 1
            if len(cajas) > 1:
                anotar(" · ".join(cajas), "no cuadra", f"la hoja «{titulo}» puede ser de varias cajas: no se tocó")
                cuentas["no cuadran"] += 1
                continue
            caja = cajas[0]
            datos = indices[caja]
            hoja = libro[titulo]
            if not aplicar:
                hoja.reset_dimensions()
            valores = _valores(hoja)
            tabla = _tabla(valores)
            if tabla is None:
                anotar(caja, "no cuadra", f"la hoja «{titulo}» no tiene la forma de la plantilla: no se tocó")
                cuentas["no cuadran"] += 1
                continue
            primera, fin = tabla
            actuales = valores[primera - 1:fin - 1]
            objetivo = datos["documentos"]
            cabecera = _cabecera(valores)
            nic_de_la_hoja = cabecera.get("nic", (None, None))[1]
            if _texto(nic_de_la_hoja) and _texto(datos["nic"]) and _texto(nic_de_la_hoja) != _texto(datos["nic"]):
                anotar(caja, "no cuadra", f"la hoja «{titulo}» tiene el NIC {_texto(nic_de_la_hoja)} y la caja "
                                          f"{_texto(datos['nic'])}: no se tocó")
                cuentas["no cuadran"] += 1
                continue
            nic = datos["nic"] if _texto(datos["nic"]) else nic_de_la_hoja
            fila_del_expediente, expediente = cabecera.get("expediente", (None, None))
            poner_expediente = (fila_del_expediente is not None and bool(_texto(nic))
                                and _texto(expediente) != _texto(nic))
            iguales = [tuple(_texto(v) for v in fila) for fila in actuales] == [
                tuple(_texto(v) for v in fila) for fila in objetivo
            ]
            if iguales and not poner_expediente:
                cuentas["iguales"] += 1
                continue
            puestos: list[int] = []
            if not iguales:
                libres = list(range(len(actuales)))
                for fila in objetivo:
                    clave = _clave_de_la_fila(fila)
                    puesto = next((i for i in libres if _clave_de_la_fila(actuales[i]) == clave), None)
                    if puesto is None:
                        break
                    libres.remove(puesto)
                    puestos.append(puesto)
                if len(puestos) != len(objetivo) or libres:
                    anotar(caja, "no cuadra", f"la hoja «{titulo}» del general no tiene los mismos documentos que "
                                              f"el índice de la caja ({len(actuales)} filas y {len(objetivo)}): "
                                              "no se tocó")
                    cuentas["no cuadran"] += 1
                    continue
            que = ", ".join(x for x in (
                "las filas como en el índice de su caja (nombres con RE y orden por fecha)" if not iguales else "",
                f"«Nombre del Expediente» «{_texto(expediente)}» -> «{_texto(nic)}»" if poner_expediente else "",
            ) if x)
            if not aplicar:
                cuentas["cambiadas"] += 1
                evidencias.append((caja, f"hoja «{titulo}»: se cambiaría {que}"))
                continue
            if not iguales:
                if _combinadas_en(hoja, primera, fin):
                    anotar(caja, "no cuadra", f"la hoja «{titulo}» tiene celdas combinadas en la tabla: no se tocó")
                    cuentas["no cuadran"] += 1
                    continue
                _reordenar_filas(hoja, primera, puestos)
                for k, fila in enumerate(objetivo):
                    hoja.cell(primera + k, 1).value = fila[0]
            if poner_expediente:
                hoja.cell(fila_del_expediente, 2).value = nic
            cuentas["cambiadas"] += 1
            evidencias.append((caja, f"hoja «{titulo}»: {que}"))
        if aplicar and cuentas["cambiadas"]:
            try:
                informar("copiando el índice general al respaldo")
                _respaldar(ruta, raiz, respaldo)
                informar(f"guardando el índice general ({cuentas['cambiadas']} hojas cambiadas)")
                _guardar_libro(libro, ruta)
            except OSError as error:
                anotar(".", "error", f"no se pudo guardar el índice general: {error}; vuelva a correr")
                evidencias.clear()
                evidencias.append((".", f"FALLA: no se pudo guardar el índice general: {error}"))
                cuentas["cambiadas"] = 0
    finally:
        if not aplicar:
            libro.close()
    return filas, cuentas


# -- paso 4: la revisión ---------------------------------------------------------------------


def paso_revision(carpeta: str, raiz: str, motivos: dict[str, str], se_cambiarian: list[str],
                  revisar_indices: bool) -> dict:
    """Paso 4 en una caja, sobre lo que hay en el disco.

    ``motivos``: por qué el paso 1 no le puso el RE a cada archivo. En la
    simulación, ``se_cambiarian`` son los que el paso 1 sí renombraría: no cuentan
    como «sin RE», y los índices no se revisan (todavía no se ordenaron).
    """
    from openpyxl import load_workbook

    carpeta_p, raiz_p = Path(carpeta), Path(raiz)
    caja = _caja(carpeta_p, raiz_p)
    resultado = {"caja": caja, "sin_re": [], "por_revisar": [], "indice": None, "con_re": 0}
    pdfs = _pdfs_de(carpeta_p)
    con_re = []
    for pdf in pdfs:
        hallado = NUMERADO.match(pdf.name)
        if not hallado:
            continue
        titulo = hallado.group(2)
        ya = CON_RE.search(titulo)
        es_de_los_dos = _plano(titulo[: ya.start()] if ya else titulo) in TITULOS_CON_RE
        if es_de_los_dos and ya:
            con_re.append(pdf.name)
        elif es_de_los_dos and pdf.name not in se_cambiarian:
            resultado["sin_re"].append((pdf.name, motivos.get(pdf.name) or "sin RE en el nombre"))
        elif ya:
            resultado["por_revisar"].append(
                (pdf.name, ("lleva RE en el nombre y no es RECLAMO ni CONSTANCIA DEL CONTENIDO DE LA "
                            "RECLAMACION: no se tocó, sólo se avisa")))
    resultado["con_re"] = len(con_re)
    if not revisar_indices:
        return resultado

    ruta = carpeta_p / INDICE
    if not ruta.exists():
        if pdfs:
            resultado["por_revisar"].append((INDICE, "la caja no tiene índice"))
        return resultado
    try:
        libro = load_workbook(ruta, read_only=True)
        try:
            varias = len(libro.sheetnames) != 1
            hoja = libro.active
            hoja.reset_dimensions()
            valores = _valores(hoja)
        finally:
            libro.close()
    except Exception as error:  # noqa: BLE001 - se anota y se sigue con la próxima caja
        resultado["por_revisar"].append((INDICE, f"no se pudo leer: {error}"))
        return resultado
    tabla = None if varias else _tabla(valores)
    if tabla is None:
        resultado["por_revisar"].append((INDICE, "no tiene la forma de la plantilla"))
        return resultado
    primera, fin = tabla
    documentos = valores[primera - 1:fin - 1]
    fechas = [_fecha(fila[1]) for fila in documentos]
    if orden_cronologico(fechas) != list(range(len(fechas))):
        resultado["por_revisar"].append((INDICE, "las filas no están en orden de «Fecha Creación Documento»"))
    if any(_entero(fila[3]) != k + 1 for k, fila in enumerate(documentos)):
        resultado["por_revisar"].append((INDICE, "«Orden Documento» no va 1, 2, 3…"))
    cabecera = _cabecera(valores)
    nic = _texto(cabecera.get("nic", (None, None))[1])
    expediente = _texto(cabecera.get("expediente", (None, None))[1])
    if not nic:
        resultado["por_revisar"].append((INDICE, "no tiene «Identificación / Nic»"))
    elif expediente != nic:
        resultado["por_revisar"].append(
            (INDICE, f"«Nombre del Expediente» ({expediente or 'vacío'}) no es el NIC ({nic})"))
    nombres = [_plano(fila[0]) for fila in documentos]
    for archivo in con_re:
        titulo = NUMERADO.match(archivo).group(2)
        if _plano(titulo) not in nombres:
            resultado["por_revisar"].append((archivo, "el índice no tiene este nombre con su RE"))
    if len(documentos) != len(pdfs):
        resultado["por_revisar"].append((INDICE, f"el índice tiene {len(documentos)} filas y la caja {len(pdfs)} PDF"))
    resultado["indice"] = {"nic": nic, "expediente": expediente,
                           "documentos": [tuple(_texto(v) for v in fila) for fila in documentos]}
    return resultado


def revisar_el_general(raiz: Path, indices: dict[str, dict], informar=None) -> tuple[list[tuple[str, str, str]], int]:
    """Que la hoja de cada caja en el índice general diga lo mismo que el índice de su caja.

    Devuelve los problemas y cuántas hojas se releyeron y compararon.
    """
    from openpyxl import load_workbook

    informar = informar or (lambda texto: None)
    ruta = raiz / INDICE
    if not ruta.exists():
        return [], 0
    por_hoja = {nombre_de_hoja(Path(caja).name).lower(): caja for caja in indices if caja != "."}
    problemas = []
    comparadas = 0
    informar("releyendo el índice general del disco")
    libro = load_workbook(ruta, read_only=True)
    try:
        total = len(libro.sheetnames)
        for numero, titulo in enumerate(libro.sheetnames, start=1):
            if numero % 200 == 0:
                informar(f"releyendo las hojas del índice general: {numero}/{total}")
            caja = por_hoja.get(titulo.lower())
            if caja is None:
                continue
            comparadas += 1
            hoja = libro[titulo]
            hoja.reset_dimensions()
            valores = _valores(hoja)
            tabla = _tabla(valores)
            if tabla is None:
                problemas.append((caja, f"{INDICE} (raíz), hoja «{titulo}»", "no tiene la forma de la plantilla"))
                continue
            primera, fin = tabla
            documentos = [tuple(_texto(v) for v in fila) for fila in valores[primera - 1:fin - 1]]
            if documentos != indices[caja]["documentos"]:
                problemas.append((caja, f"{INDICE} (raíz), hoja «{titulo}»", "no dice lo mismo que el índice de la caja"))
            expediente = _texto(_cabecera(valores).get("expediente", (None, None))[1])
            if indices[caja]["nic"] and expediente != indices[caja]["nic"]:
                problemas.append((caja, f"{INDICE} (raíz), hoja «{titulo}»",
                                  f"«Nombre del Expediente» ({expediente or 'vacío'}) no es el NIC ({indices[caja]['nic']})"))
    finally:
        libro.close()
    return problemas, comparadas


# -- deshacer ------------------------------------------------------------------------------


def deshacer(raiz: Path, respaldo: Path) -> int:
    """Todo como estaba antes del primer --aplicar: los nombres de los PDF y las copias del respaldo.

    Una caja cuyos PDF no se pueden devolver a su nombre no recibe sus copias (su
    constancia dejaría de coincidir con los archivos) y queda anotada; el registro y
    el respaldo se conservan para volver a intentarlo.
    """
    registro = raiz / REGISTRO
    if not registro.exists() and not respaldo.exists():
        print(f"No hay nada que deshacer: no encuentro {registro} ni {respaldo}")
        return 2
    renombrados = []
    if registro.exists():
        with registro.open(encoding="utf-8-sig", newline="") as archivo:
            renombrados = [fila for fila in csv.DictReader(archivo, delimiter=";")
                           if str(fila.get("paso") or "").startswith("1") and fila.get("estado") == "renombrado"]
    print(f"Deshaciendo: {len(renombrados)} PDF a su nombre de antes, y lo guardado en {respaldo}")
    con_problemas: dict[str, str] = {}
    devueltos = 0
    for fila in reversed(renombrados):
        carpeta = raiz / fila["caja"] if fila["caja"] != "." else raiz
        despues, antes = carpeta / fila["archivo_despues"], carpeta / fila["archivo_antes"]
        if despues.exists() and not antes.exists():
            try:
                _con_reintentos(lambda d=despues, a=antes: d.rename(a))
                devueltos += 1
            except OSError as error:
                con_problemas[fila["caja"]] = f"no se pudo devolver «{despues.name}»: {error}"
        elif not (antes.exists() and not despues.exists()):
            con_problemas[fila["caja"]] = f"no se sabe qué hacer con «{despues.name}» / «{antes.name}»"
    restaurados = 0
    if respaldo.exists():
        for copia in sorted(respaldo.rglob("*")):
            if not copia.is_file() or copia.name.endswith(".copiando"):
                continue
            relativa = copia.relative_to(respaldo)
            caja = str(relativa.parent) if str(relativa.parent) != "." else "."
            if caja in con_problemas:
                continue
            destino = raiz / relativa
            temporal = destino.with_name(destino.name + ".restaurando")
            try:
                shutil.copy2(copia, temporal)
                _reemplazar(temporal, destino, oculto=_es_oculto(destino) or CONSTANCIA.match(destino.name) is not None)
                if os.name == "nt" and CONSTANCIA.match(destino.name):
                    _ocultar(destino, True)
                restaurados += 1
            except OSError as error:
                temporal.unlink(missing_ok=True)
                con_problemas[caja] = f"no se pudo devolver «{relativa}»: {error}"
    print(f"PDF devueltos a su nombre: {devueltos} · índices y constancias devueltos: {restaurados}")
    if con_problemas:
        print(f"\n{len(con_problemas)} cajas no se pudieron deshacer del todo (cierre lo que esté abierto y "
              "vuelva a correr --deshacer):")
        for caja, motivo in sorted(con_problemas.items())[:200]:
            print(f"  {caja} · {motivo}")
        return 1
    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    if registro.exists():
        registro.rename(registro.with_name(f"{registro.stem} (DESHECHO {sello}).csv"))
    if respaldo.exists():
        respaldo.rename(respaldo.with_name(f"{respaldo.name} (DESHECHO {sello})"))
    print("Listo: todo quedó como antes del primer --aplicar.")
    return 0


# -- la carpeta --------------------------------------------------------------------------------


def cajas_de(raiz: Path, contador: dict | None = None):
    """Cada carpeta del destino con PDF: la raíz y sus subcarpetas, sin lo apartado."""
    for actual, carpetas, archivos in os.walk(raiz):
        if contador is not None:
            contador["carpetas"] = contador.get("carpetas", 0) + 1
        carpetas[:] = sorted(c for c in carpetas if c.lower() not in SALTAR and not c.startswith("."))
        if any(a.lower().endswith(".pdf") for a in archivos):
            yield Path(actual)


def corridas_del_bot_sobre(carpeta_en_windows: str) -> list[str] | None:
    """Los orígenes de las corridas del bot que entregan ahora en esa carpeta; ``None`` si no contesta."""
    import urllib.request

    try:
        pedido = urllib.request.Request("http://127.0.0.1:8000/api/folder-runs", headers={"x-operator": "siar"})
        with urllib.request.urlopen(pedido, timeout=10) as respuesta:
            corridas = json.loads(respuesta.read()).get("runs") or []
    except Exception:  # noqa: BLE001 - sin respuesta, se avisa y se sigue
        return None
    activas = {"scanning", "processing", "watching", "recovering"}
    objetivo = _plano(carpeta_en_windows)
    return [
        str(corrida.get("source") or "")
        for corrida in corridas
        if corrida.get("state") in activas and _plano(str(corrida.get("destination") or "")) == objetivo
    ]


# -- el avance, en vivo ------------------------------------------------------------------------

#: Cada cuántos segundos se imprime el avance.
CADA = 10
#: Lo que cuenta como resuelto en el paso 1, y lo que hay que mirar.
BIEN = {"renombrado", "se cambiaría", "ya tenía RE"}
MIRAR = {"sin RE", "choque de nombre", "nombre muy largo"}
#: Cuántos de los que quedaron sin RE se listan al final; el CSV los tiene todos.
MOSTRAR_PENDIENTES = 200


def _cifra(numero: float) -> str:
    return f"{numero:,.0f}".replace(",", ".")


def _duracion(segundos: float) -> str:
    segundos = int(max(0, segundos))
    horas, resto = divmod(segundos, 3600)
    return f"{horas} h {resto // 60:02d} min" if horas else f"{resto // 60} min {resto % 60:02d} s"


class Voz:
    """Lo que sale en pantalla, con su hora, y a la vez al archivo de evidencia.

    El operador (2026-11-04): «necesito evidencia de cada cosa que va haciendo, de
    las 2 fases, en tiempo real». Cada cambio sale apenas su caja termina, y queda en
    «00.RE Y ORDEN - EVIDENCIA.txt» para revisarlo después.
    """

    def __init__(self, ruta: Path | None, *, agregar: bool) -> None:
        self.cerrojo = threading.Lock()
        self.ultimo = time.monotonic()
        self.archivo = ruta.open("a" if agregar else "w", encoding="utf-8") if ruta is not None else None

    def __call__(self, texto: str, *, al_archivo: bool = True) -> None:
        ahora = datetime.now()
        linea = f"[{ahora:%H:%M:%S}] {texto}"
        with self.cerrojo:
            print(linea, flush=True)
            if al_archivo and self.archivo is not None:
                self.archivo.write(f"{ahora:%Y-%m-%d} {linea}\n")
                self.archivo.flush()
            self.ultimo = time.monotonic()

    def cerrar(self) -> None:
        with self.cerrojo:
            if self.archivo is not None:
                self.archivo.close()
                self.archivo = None


class Latido(threading.Thread):
    """Cada ``LATIDO`` segundos sin nada nuevo en pantalla, dice qué está haciendo y cuánto lleva.

    Para que una espera larga -- el OCR de una caja grande, el índice general con
    treinta mil hojas -- no parezca que el programa se detuvo.
    """

    def __init__(self, voz: Voz) -> None:
        super().__init__(daemon=True)
        self.voz = voz
        self.estado = "empezando"
        self.desde = time.monotonic()
        self.parar = threading.Event()

    def cambiar(self, estado) -> None:
        self.estado, self.desde = estado, time.monotonic()

    def run(self) -> None:
        while not self.parar.wait(LATIDO):
            if time.monotonic() - self.voz.ultimo >= LATIDO:
                try:
                    estado = self.estado() if callable(self.estado) else self.estado
                except Exception:  # noqa: BLE001 - el latido nunca tumba la corrida
                    estado = "trabajando"
                self.voz(f"… sigue trabajando: {estado} (lleva {_duracion(time.monotonic() - self.desde)})",
                         al_archivo=False)


class Avance:
    """Las cifras mientras corre: cajas hechas, ritmo, lo que falta y sus cuentas.

    Lo pidió el operador el 2026-10-28: «necesito ver un análisis estadístico del
    progreso en tiempo real». Sale cada ``CADA`` segundos.
    """

    def __init__(self, paso: str, total: int, voz: Voz) -> None:
        self.paso, self.total, self.voz = paso, total, voz
        self.hechas = 0
        self.inicio = time.monotonic()
        self.ultimo = 0.0
        self.cuentas: dict[str, int] = {}

    def caja(self) -> None:
        self.hechas += 1
        self.imprimir(siempre=self.hechas in (1, self.total))

    def imprimir(self, *, siempre: bool = False) -> None:
        ahora = time.monotonic()
        if not siempre and ahora - self.ultimo < CADA:
            return
        self.ultimo = ahora
        transcurrido = ahora - self.inicio
        ritmo = self.hechas / transcurrido * 60 if transcurrido > 0 else 0
        falta = (self.total - self.hechas) / (self.hechas / transcurrido) if self.hechas and transcurrido > 0 else 0
        porcentaje = self.hechas / self.total * 100 if self.total else 100
        cuentas = " · ".join(f"{clave} {_cifra(valor)}" for clave, valor in self.cuentas.items())
        self.voz(f"AVANCE {self.paso}: {_cifra(self.hechas)}/{_cifra(self.total)} cajas ({porcentaje:.1f} %) · "
                 f"{ritmo:.0f} cajas/min · lleva {_duracion(transcurrido)} · falta ~{_duracion(falta)}"
                 + (f" · {cuentas}" if cuentas else ""))


def _sin_pausa_al_hacer_clic():
    """Apaga la «edición rápida» de la consola de Windows; devuelve cómo dejarla como estaba.

    Con ella, un clic dentro de la ventana de CMD pausa el programa hasta que se
    pulsa Enter, y parece que se detuvo («agrégale validaciones para que no se detenga»).
    """
    if os.name != "nt":
        return lambda: None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        entrada = kernel32.GetStdHandle(-10)
        modo = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(entrada, ctypes.byref(modo)):
            return lambda: None
        original = modo.value
        kernel32.SetConsoleMode(entrada, (original | 0x80) & ~0x40)
        return lambda: kernel32.SetConsoleMode(entrada, original)
    except Exception:  # noqa: BLE001 - sin consola de Windows, nada que apagar
        return lambda: None


def _escribir_csv(ruta: Path, columnas: list[str], filas: list[tuple]) -> None:
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(columnas)
        escritor.writerows(filas)


def procesar_la_caja(carpeta: str, raiz: str, raiz_en_windows: str, respaldo: str, aplicar: bool,
                     solo_revisar: bool, tesseract: str | None, idioma: str,
                     lecturas: dict[str, dict] | None = None) -> dict:
    """Los pasos 1, 2 y 4 de una caja, uno detrás de otro, en un proceso del pool.

    Lo pidió el operador el 2026-11-04: «la idea es poder procesar en paralelo, para
    que sea más rápido y más ágil». Cada caja es independiente de las demás: mientras
    un proceso lee el RE de una, otros ordenan o revisan otras, y cada caja se recorre
    una sola vez. Dentro de la caja el orden se respeta: el RE (1) antes que el
    índice (2), y la revisión (4) al final, sobre lo que quedó en el disco. Un paso
    que falla se anota y no impide los siguientes.
    """
    caja = _caja(Path(carpeta), Path(raiz))
    if os.environ.get("RE_Y_ORDEN_CAIDA_DE_PRUEBA") == caja:
        # Sólo para probar que una caja que tumba su proceso no detiene la corrida.
        os._exit(3)
    resultado: dict = {"caja": caja, "re": [], "indice": None, "revision": None, "lecturas": []}
    if not solo_revisar:
        try:
            resultado["re"] = paso_re(carpeta, raiz, raiz_en_windows, respaldo, aplicar, tesseract, idioma,
                                      lecturas, resultado["lecturas"])
        except Exception as error:  # noqa: BLE001 - se anota y la caja sigue con el paso 2
            resultado["re"] = [_fila_vacia("1 RE", caja, estado="error", detalle=f"falló el paso 1: {error}")]
        try:
            resultado["indice"] = paso_indice(carpeta, raiz, respaldo, aplicar)
        except Exception as error:  # noqa: BLE001
            resultado["indice"] = {"caja": caja, "estado": "error", "indice": None, "ordenado": False,
                                   "expediente": False,
                                   "filas": [_fila_vacia("2 INDICE", caja, estado="error",
                                                         detalle=f"falló el paso 2: {error}")]}
    motivos = {fila["archivo_antes"]: fila["detalle"] or fila["estado"] for fila in resultado["re"]
               if fila["estado"] in MIRAR or fila["estado"] == "error"}
    se_cambiarian = [fila["archivo_antes"] for fila in resultado["re"] if fila["estado"] == "se cambiaría"]
    try:
        resultado["revision"] = paso_revision(carpeta, raiz, motivos, se_cambiarian, aplicar or solo_revisar)
    except Exception as error:  # noqa: BLE001
        resultado["revision"] = {"caja": caja, "sin_re": [], "indice": None, "con_re": 0,
                                 "por_revisar": [("", f"falló la revisión: {error}")]}
    return resultado


def _correr_en_paralelo(cajas: list[Path], procesos: int, tarea, al_terminar, al_fallar, latido: Latido,
                        voz: Voz) -> None:
    """Reparte las cajas entre ``procesos`` procesos, con pocas en espera a la vez.

    Si un proceso se cae -- un PDF tan dañado que tumba la librería --, el pool se
    rehace y las cajas que estaban en curso se repiten de a una: la que lo vuelve a
    tumbar se anota y se salta, y la corrida sigue con las demás.
    """
    from collections import deque
    from concurrent.futures import FIRST_COMPLETED, wait
    from concurrent.futures.process import BrokenProcessPool

    def entregar(caja: Path, resultado=None, fallo: str | None = None) -> None:
        try:
            if fallo is None:
                al_terminar(caja, resultado)
            else:
                al_fallar(caja, fallo)
        except Exception as error:  # noqa: BLE001 - anotar una caja nunca para la corrida
            voz(f"{_caja(caja, caja.parent)} | ERROR al anotar la caja: {type(error).__name__}: {error}")

    pendientes = deque(cajas)
    sospechosas: deque = deque()
    total, hechas = len(cajas), 0
    ventana = max(1, procesos) * 3
    while pendientes or sospechosas:
        if sospechosas:
            caja = sospechosas.popleft()
            latido.estado = f"repitiendo sola la caja {caja.name}, cuyo proceso se cayó"
            pool = ProcessPoolExecutor(max_workers=1)
            try:
                entregar(caja, pool.submit(*tarea(caja)).result())
            except BrokenProcessPool:
                entregar(caja, fallo="el proceso que la trabajaba se cayó dos veces (¿un PDF dañado?): se saltó")
            except Exception as error:  # noqa: BLE001
                entregar(caja, fallo=f"{type(error).__name__}: {error}")
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            hechas += 1
            continue
        pool = ProcessPoolExecutor(max_workers=procesos)
        en_curso: dict = {}
        roto = False
        try:
            while (pendientes or en_curso) and not roto:
                while pendientes and len(en_curso) < ventana:
                    caja = pendientes.popleft()
                    try:
                        en_curso[pool.submit(*tarea(caja))] = caja
                    except BrokenProcessPool:
                        pendientes.appendleft(caja)
                        roto = True
                        break
                if roto:
                    break
                listos, _ = wait(list(en_curso), timeout=LATIDO, return_when=FIRST_COMPLETED)
                for futuro in listos:
                    caja = en_curso.pop(futuro)
                    try:
                        resultado = futuro.result()
                    except BrokenProcessPool:
                        sospechosas.append(caja)
                        roto = True
                        continue
                    except Exception as error:  # noqa: BLE001
                        entregar(caja, fallo=f"{type(error).__name__}: {error}")
                    else:
                        entregar(caja, resultado)
                    hechas += 1
                latido.estado = f"{_cifra(hechas)}/{_cifra(total)} cajas hechas, {len(en_curso)} en curso"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if roto:
            sospechosas.extend(en_curso.values())
            voz(f"AVISO: se cayó un proceso (¿un PDF dañado?). Se rehace y se repiten de a una las "
                f"{len(sospechosas)} cajas que estaban en curso; la corrida sigue.")


def _lista(pares: list[tuple[str, str]]) -> str:
    return " · ".join(f"{numero}. {nombre} ({fecha})" for numero, (nombre, fecha) in enumerate(pares, start=1))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Pipeline: el RE en RECLAMO y CONSTANCIA DEL CONTENIDO DE LA RECLAMACION, los índices "
                    "por fecha con el expediente = NIC, el índice general y la revisión.")
    parser.add_argument("carpeta", nargs="?", default=CARPETA_POR_OMISION,
                        help=f"la carpeta que entregó el bot, como la ve Windows (por omisión {CARPETA_POR_OMISION})")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--aplicar", action="store_true", help="hacer los cambios (sin esto, sólo simula)")
    modo.add_argument("--revisar", action="store_true", help="sólo el paso 4, la revisión de lo que hay")
    modo.add_argument("--deshacer", action="store_true", help="todo como estaba antes del primer --aplicar")
    parser.add_argument("--procesos", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="cuántas cajas se trabajan a la vez (por omisión, los núcleos del equipo menos uno)")
    parser.add_argument("--releer", action="store_true",
                        help="volver a leer el RE de todos los PDF, sin usar lo leído en corridas anteriores")
    args = parser.parse_args()

    try:
        import openpyxl  # noqa: F401

        _pymupdf()
    except ImportError as error:
        print(f"Falta una librería de Python ({error.name}). Instálela con:\n    pip install pymupdf openpyxl")
        return 2

    raiz = ruta_del_servicio(args.carpeta)
    if not raiz.is_dir():
        print(f"No encuentro la carpeta: {args.carpeta} (vista como {raiz})")
        return 2
    respaldo = raiz.parent / f"{raiz.name}{SUFIJO_DEL_RESPALDO}"
    if args.aplicar or args.deshacer:
        en_marcha = corridas_del_bot_sobre(args.carpeta)
        if en_marcha is None:
            print("Aviso: no se pudo preguntar al bot si está trabajando en esta carpeta. "
                  "Asegúrese de que no la esté procesando.")
        elif en_marcha:
            print("El bot está procesando esta carpeta ahora mismo (origen: " + ", ".join(en_marcha) + "). "
                  "Deténgalo en la pantalla o espere a que termine, y vuelva a correr el script.")
            return 3
    if args.deshacer:
        return deshacer(raiz, respaldo)
    restaurar_la_consola = _sin_pausa_al_hacer_clic()
    try:
        return _correr(args, raiz, respaldo)
    except KeyboardInterrupt:
        print("\nCortado con Ctrl+C. Lo hecho quedó hecho y anotado: vuelva a correr el mismo comando para "
              "seguir donde iba.", flush=True)
        return 130
    finally:
        restaurar_la_consola()


def _correr(args, raiz: Path, respaldo: Path) -> int:
    aplicar, solo_revisar = args.aplicar, args.revisar
    sufijo = "" if aplicar or solo_revisar else " (SIMULACION)"
    nombre_del_modo = "REVISIÓN" if solo_revisar else "APLICAR" if aplicar else "SIMULACIÓN (no cambia nada)"
    voz = Voz(raiz / EVIDENCIA.replace(".txt", f"{sufijo}.txt"), agregar=bool(sufijo == ""))
    latido = Latido(voz)
    latido.start()
    archivo = archivo_de_lecturas = None
    try:
        voz("=" * 70, al_archivo=True)
        voz(f"PIPELINE · {nombre_del_modo} · {raiz}")
        contador = {"carpetas": 0}
        latido.cambiar(lambda: f"buscando las cajas: {_cifra(contador['carpetas'])} carpetas recorridas")
        voz(f"Buscando las cajas de {raiz} …")
        cajas = list(cajas_de(raiz, contador))
        voz(f"{_cifra(len(cajas))} cajas · {nombre_del_modo} · {args.procesos} cajas a la vez, en paralelo")
        tesseract, idioma = (None, "") if solo_revisar else buscar_tesseract()
        if not solo_revisar:
            voz(f"Tesseract: {tesseract} ({idioma})" if tesseract else
                "Aviso: este equipo no tiene Tesseract. Sólo se leerá el RE del texto de los PDF; los escaneados "
                "sin texto quedarán en la lista de los que siguen sin RE.")
        if aplicar:
            voz(f"Respaldo de lo que se cambie: {respaldo}")
        voz(f"Evidencia de cada cambio, en pantalla y en: {raiz / EVIDENCIA.replace('.txt', f'{sufijo}.txt')}")

        lecturas: dict[str, dict[str, dict]] = {}
        ruta_de_lecturas = raiz / LECTURAS
        if not solo_revisar and not args.releer and ruta_de_lecturas.exists():
            with ruta_de_lecturas.open(encoding="utf-8") as leido:
                for linea in leido:
                    try:
                        datos = json.loads(linea)
                    except ValueError:
                        continue  # una línea cortada por un Ctrl+C
                    lecturas.setdefault(str(datos.get("caja")), {})[str(datos.get("archivo"))] = datos
            voz(f"Ya leídos en corridas anteriores: {_cifra(sum(len(v) for v in lecturas.values()))} PDF; se "
                "reutilizan si el archivo no cambió (--releer para leerlos todos otra vez).")
        voz("Se puede cortar con Ctrl+C y volver a correr: lo hecho se salta. Un clic en la ventana ya no la pausa.")

        indices_de_las_cajas: dict[str, dict] = {}
        indices_revisados: dict[str, dict] = {}
        sin_re: list[tuple] = []
        por_revisar: list[tuple] = []
        salida = None if solo_revisar else raiz / (REGISTRO if aplicar else SIMULACION)
        escritor = None
        if salida is not None:
            nueva = not salida.exists() or not aplicar
            archivo = salida.open("a" if aplicar else "w", encoding="utf-8-sig", newline="")
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            if nueva:
                escritor.writeheader()
        if not solo_revisar:
            archivo_de_lecturas = ruta_de_lecturas.open("a", encoding="utf-8")

        cuentas_re: dict[str, int] = {}
        cuentas_indice: dict[str, int] = {}
        cuentas_revision: dict[str, int] = {}
        evidencia: dict[str, int] = {}
        avance = Avance("cajas", len(cajas), voz)

        def contar(cuentas: dict[str, int], clave: str, cuanto: int = 1) -> None:
            if cuanto:
                cuentas[clave] = cuentas.get(clave, 0) + cuanto

        def anotar_en_el_registro(fila: dict) -> None:
            if escritor is None:
                return
            comprobado = fila.get("comprobado") or ""
            escritor.writerow({**fila, "detalle": "; ".join(
                x for x in (fila.get("detalle") or "", f"comprobado: {comprobado}" if comprobado else "") if x)})

        def evidencia_de(comprobado: str) -> None:
            if comprobado:
                contar(evidencia, "FALLA" if "FALLA" in comprobado else "comprobados OK")

        def al_terminar(_caja: Path, resultado: dict) -> None:
            caja = resultado["caja"]
            # Paso 1: cada archivo, antes -> después, y lo que dice el disco.
            for fila in resultado["re"]:
                anotar_en_el_registro(fila)
                estado, comprobado = fila["estado"], fila.get("comprobado") or ""
                contar(cuentas_re, estado)
                evidencia_de(comprobado)
                if estado in ("renombrado", "se cambiaría"):
                    voz(f"{caja} | PASO 1 RE | {fila['archivo_antes']} -> {fila['archivo_despues']} | RE leído de: "
                        f"{fila['leido_de']} | " + (comprobado if aplicar else "simulación: no se cambió nada"))
                elif estado == "ya tenía RE" and "complet" in (fila.get("detalle") or ""):
                    voz(f"{caja} | PASO 1 COMPLETADO | {fila['archivo_antes']} | {fila['detalle']}"
                        + (f" | {comprobado}" if comprobado else ""))
                elif estado in MIRAR or estado == "error":
                    voz(f"{caja} | PASO 1 {estado.upper()} | {fila['archivo_antes']} | {(fila['detalle'] or '')[:220]}")
            # Paso 2: el índice antes y ahora, y lo que dice el Excel releído.
            indice = resultado["indice"]
            if indice is not None:
                for fila in indice["filas"]:
                    anotar_en_el_registro(fila)
                contar(cuentas_indice, indice["estado"])
                contar(cuentas_indice, "filas reordenadas" if aplicar else "se reordenarían", int(indice["ordenado"]))
                contar(cuentas_indice, "expediente = NIC" if aplicar else "expediente por poner",
                       int(indice["expediente"]))
                if indice["estado"] in ("cambiado", "se cambiaría"):
                    if indice["ordenado"]:
                        voz(f"{caja} | PASO 2 ÍNDICE ANTES | {_lista(indice.get('antes') or [])}")
                        voz(f"{caja} | PASO 2 ÍNDICE AHORA | {_lista(indice.get('despues') or [])}")
                    if indice["expediente"]:
                        voz(f"{caja} | PASO 2 EXPEDIENTE | «{indice.get('expediente_antes') or ''}» -> "
                            f"«{indice.get('nic') or ''}»")
                    comprobado = indice.get("comprobado") or ""
                    evidencia_de(comprobado)
                    voz(f"{caja} | PASO 2 " + (f"COMPROBADO | {comprobado}" if aplicar
                                               else "SIMULACIÓN | no se cambió nada"))
                elif indice["estado"] == "error":
                    voz(f"{caja} | PASO 2 ERROR | {indice['filas'][0]['detalle'] if indice['filas'] else ''}")
                if indice.get("indice") is not None:
                    indices_de_las_cajas[caja] = indice["indice"]
            # Paso 4: lo que quedó, mirado otra vez en el disco.
            revision = resultado["revision"]
            sin_re.extend((caja, nombre, motivo) for nombre, motivo in revision["sin_re"])
            for que, problema in revision["por_revisar"]:
                por_revisar.append((caja, que, problema))
                voz(f"{caja} | REVISIÓN | {que} | {problema}")
            contar(cuentas_revision, "con RE", revision["con_re"])
            contar(cuentas_revision, "sin RE", len(revision["sin_re"]))
            contar(cuentas_revision, "por revisar", len(revision["por_revisar"]))
            if revision["indice"] is not None:
                indices_revisados[caja] = revision["indice"]
            if archivo is not None:
                archivo.flush()
            if archivo_de_lecturas is not None and resultado["lecturas"]:
                for lectura in resultado["lecturas"]:
                    archivo_de_lecturas.write(json.dumps(lectura, ensure_ascii=False) + "\n")
                archivo_de_lecturas.flush()
            avance.cuentas = {"RE cambiados" if aplicar else "RE por cambiar":
                              cuentas_re.get("renombrado", 0) + cuentas_re.get("se cambiaría", 0),
                              "sin RE": cuentas_re.get("sin RE", 0),
                              "índices ordenados" if aplicar else "índices por ordenar":
                              cuentas_indice.get("filas reordenadas", 0) + cuentas_indice.get("se reordenarían", 0),
                              **({"comprobados OK": evidencia.get("comprobados OK", 0),
                                  "FALLAS": evidencia.get("FALLA", 0)} if aplicar else {})}
            avance.caja()

        def al_fallar(caja_p: Path, motivo: str) -> None:
            caja = _caja(caja_p, raiz)
            por_revisar.append((caja, "", f"no se pudo trabajar la caja: {motivo}"))
            if escritor is not None:
                escritor.writerow(_fila_vacia("-", caja, estado="error", detalle=motivo))
            contar(evidencia, "FALLA")
            voz(f"{caja} | ERROR | no se pudo trabajar la caja: {motivo}")
            avance.caja()

        pasos = "4 (revisión)" if solo_revisar else "1 (RE), 2 (índice de la caja) y 4 (revisión)"
        voz(f"PASOS {pasos}: cada caja de principio a fin, {args.procesos} a la vez")
        latido.cambiar("empezando las cajas")
        _correr_en_paralelo(
            cajas, args.procesos,
            lambda caja: (procesar_la_caja, str(caja), str(raiz), args.carpeta, str(respaldo), aplicar,
                          solo_revisar, tesseract, idioma, lecturas.get(_caja(caja, raiz), {})),
            al_terminar, al_fallar, latido, voz,
        )
        avance.imprimir(siempre=True)

        # Paso 3: el índice general es un solo archivo; lo escribe un solo proceso al final.
        resumen_general = ""
        if not solo_revisar:
            voz("PASO 3 · el índice general de la raíz")
            latido.cambiar("paso 3, el índice general")
            inicio = time.monotonic()
            evidencias_del_general: list = []

            def informar(texto: str) -> None:
                latido.estado = f"paso 3: {texto}"

            try:
                filas, cuentas = paso_general(raiz, respaldo, aplicar, indices_de_las_cajas, informar,
                                              evidencias_del_general)
            except Exception as error:  # noqa: BLE001 - las cajas ya están hechas
                filas = [_fila_vacia("3 GENERAL", ".", estado="error", detalle=f"{type(error).__name__}: {error}")]
                cuentas = {"error": 1}
            for caja, texto in evidencias_del_general:
                voz(f"{caja} | PASO 3 GENERAL | {texto}")
            for fila in filas:
                anotar_en_el_registro(fila)
                if fila["estado"] in ("error", "no cuadra"):
                    por_revisar.append((fila["caja"], f"{INDICE} (raíz)", fila["detalle"]))
                    voz(f"{fila['caja']} | PASO 3 {fila['estado'].upper()} | {fila['detalle']}")
            if cuentas.get("error"):
                resumen_general = f"error: {filas[0]['detalle']}"
            elif cuentas.get("sin general"):
                resumen_general = "no hay índice general en la raíz"
            else:
                resumen_general = (
                    f"hojas de cajas {_cifra(cuentas.get('hojas', 0))} · "
                    f"{'actualizadas' if aplicar else 'se actualizarían'} {_cifra(cuentas.get('cambiadas', 0))} · "
                    f"ya iguales {_cifra(cuentas.get('iguales', 0))} · no cuadran {_cifra(cuentas.get('no cuadran', 0))}"
                )
            voz(f"PASO 3 · {resumen_general} ({_duracion(time.monotonic() - inicio)})")
            if archivo is not None:
                archivo.flush()

        # La comprobación del índice general: releído del disco, hoja por hoja.
        if aplicar or solo_revisar:
            latido.cambiar("comprobando el índice general")
            try:
                problemas, comparadas = revisar_el_general(
                    raiz, indices_revisados, lambda texto: setattr(latido, "estado", texto))
                por_revisar.extend(problemas)
                for caja, que, problema in problemas:
                    voz(f"{caja} | PASO 3 FALLA | {que} | {problema}")
                voz(f"PASO 3 COMPROBADO | releídas del disco {_cifra(comparadas)} hojas del índice general: "
                    + ("todas dicen lo mismo que el índice de su caja" if not problemas
                       else f"{_cifra(len(problemas))} problemas (ver 00.INDICES POR REVISAR.csv)"))
                if comparadas:
                    contar(evidencia, "FALLA" if problemas else "comprobados OK", len(problemas) or 1)
            except Exception as error:  # noqa: BLE001
                por_revisar.append((".", INDICE, f"no se pudo revisar el índice general: {error}"))
                voz(f"PASO 3 FALLA | no se pudo releer el índice general: {error}")

        sin_re.sort()
        por_revisar.sort()
        ruta_sin_re = raiz / SIN_RE.replace(".csv", f"{sufijo}.csv")
        ruta_por_revisar = raiz / POR_REVISAR.replace(".csv", f"{sufijo}.csv")
        _escribir_csv(ruta_sin_re, ["caja", "archivo", "motivo"], sin_re)
        _escribir_csv(ruta_por_revisar, ["caja", "archivo o índice", "qué pasa"], por_revisar)

        voz("=" * 70)
        voz(f"RESUMEN · {nombre_del_modo} · {_cifra(len(cajas))} cajas · {_duracion(time.monotonic() - avance.inicio)}")
        if not solo_revisar:
            voz("Paso 1, el RE:                " + (" · ".join(f"{k} {_cifra(v)}" for k, v in cuentas_re.items()) or "nada"))
            voz("Paso 2, índices de las cajas: " + (" · ".join(f"{k} {_cifra(v)}" for k, v in cuentas_indice.items()) or "nada"))
            voz(f"Paso 3, índice general:       {resumen_general}")
        voz("Paso 4, revisión:             " + (" · ".join(f"{k} {_cifra(v)}" for k, v in cuentas_revision.items()) or "nada"))
        if aplicar or solo_revisar:
            voz(f"EVIDENCIA: cambios comprobados en el disco {_cifra(evidencia.get('comprobados OK', 0))} · "
                f"FALLAS {_cifra(evidencia.get('FALLA', 0))}"
                + (" (búsquelas con la palabra FALLA en el archivo de evidencia)" if evidencia.get("FALLA") else ""))
        if sin_re:
            voz(f"Los {_cifra(len(sin_re))} RECLAMO y CONSTANCIA que "
                f"{'quedaron' if aplicar or solo_revisar else 'quedarían'} sin RE están en {ruta_sin_re.name}")
        if salida is not None:
            voz(f"Registro de cada cambio: {salida}")
        voz(f"Evidencia en vivo:        {raiz / EVIDENCIA.replace('.txt', f'{sufijo}.txt')}")
        voz(f"Sin RE:                   {ruta_sin_re} ({_cifra(len(sin_re))})")
        voz(f"Por revisar:              {ruta_por_revisar} ({_cifra(len(por_revisar))})")
        if not aplicar and not solo_revisar:
            voz("No se cambió nada. Revise la evidencia y los CSV y, si está bien, vuelva a correrlo con --aplicar.")
        return 0
    finally:
        latido.parar.set()
        if archivo is not None:
            archivo.close()
        if archivo_de_lecturas is not None:
            archivo_de_lecturas.close()
        voz.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
