"""Pone el número RE en el nombre de las reclamaciones ya entregadas: «01_TITULO-RE…pdf».

Lo pidió el operador el 2026-10-28, para la carpeta de MAGANGUE ya procesada:
«los documentos que la OCR logre tomar, que me agregue el número-título-RE». El
cambio va en todos los sitios de la caja, para que nada quede desparejo:

* el nombre del PDF:            01_CONSTANCIA-DEL-CONTENIDO-DE-LA-RECLAMACION-RE2310202101996.pdf
* el índice de la caja:         «CONSTANCIA DEL CONTENIDO DE LA RECLAMACION-RE2310202101996»
* la constancia de la entrega   (.bot-entrega-UPD….json): el nombre del archivo y la copia
  del índice que guarda. Sin esto el bot vería la entrega incompleta y la volvería a
  procesar -- y a pagar --, y al ordenar la caja rehiciría el índice sin el RE.

El índice general de la raíz no se toca: lo rehace el bot en su próxima corrida con
los índices de cada caja.

El RE se lee primero del texto que ya trae el PDF -- gratis -- y, si no está, con
Tesseract sobre la primera página. Sólo se acepta el radicado escrito con «RE» delante:
oficina (cuatro cifras), año (2018-2029) y consecutivo: trece cifras. Lo que no se
logra leer se deja como está y se anota.

Corre dentro del contenedor del bot, que ya trae Python, PyMuPDF, Tesseract en
español y el lector de radicados del bot:

    docker cp renombrar_reclamaciones.py botpdf:/tmp/renombrar_reclamaciones.py
    docker exec -it botpdf python /tmp/renombrar_reclamaciones.py              (simula)
    docker exec -it botpdf python /tmp/renombrar_reclamaciones.py --aplicar
    docker exec -it botpdf python /tmp/renombrar_reclamaciones.py --deshacer

Sin carpeta trabaja sobre «C:\\Users\\SIAR1\\Desktop\\FOLIA-BOT\\MAGANGUE PROCESADO»;
otra se pasa delante de las opciones: ... renombrar_reclamaciones.py "C:\\otra\\carpeta".

Sin --aplicar no cambia nada: deja en la raíz «00.RENOMBRE DE RECLAMACIONES
(SIMULACION).csv» con lo que haría. Con --aplicar, «00.RENOMBRE DE
RECLAMACIONES.csv» con cada cambio hecho; --deshacer lo lee y lo revierte. Se puede
cortar y volver a correr: lo que ya tiene su RE en el nombre se salta.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

#: La carpeta de MAGANGUE ya procesada, en el equipo donde corre el bot.
CARPETA_POR_OMISION = r"C:\Users\SIAR1\Desktop\FOLIA-BOT\MAGANGUE PROCESADO"
REGISTRO = "00.RENOMBRE DE RECLAMACIONES.csv"
SIMULACION = "00.RENOMBRE DE RECLAMACIONES (SIMULACION).csv"
INDICE = "00.INDICE ELECTRONICO.xlsx"
CONSTANCIA = re.compile(r"^\.bot-entrega-.+\.json$", re.IGNORECASE)
NUMERADO = re.compile(r"^(\d{1,4})_(.+)\.pdf$", re.IGNORECASE)
CON_RE = re.compile(r"-RE\d{13}$", re.IGNORECASE)
#: Carpetas que no son cajas: lo apartado al rehacer y los originales movidos.
SALTAR = {"_reemplazados", "_procesados"}
#: «RE2310202101996», «RE9233202202670», con los espacios que mete la lectura:
#: oficina de cuatro cifras, año (2018-2029) y consecutivo. En MAGANGUE hay
#: oficinas que empiezan por 9 (2026-10-28).
RE_ESTRICTO = re.compile(r"R\s?E\W{0,2}(\d(?:\s?\d){12})(?!\s?\d)")
COLUMNAS = ["fecha", "caja", "archivo_antes", "archivo_despues", "re", "leido_de",
            "estado", "detalle", "indice_antes", "indice_despues"]


# -- rutas -------------------------------------------------------------------------


def ruta_del_servicio(texto: str) -> Path:
    """«C:\\Users\\…» como la ve el contenedor («/equipo/c/Users/…»); tal cual si ya es suya."""
    try:
        from resolutions.api.rutas_del_equipo import al_servicio

        return Path(al_servicio(texto))
    except Exception:  # noqa: BLE001 - sin el bot instalado, se traduce a mano
        hallado = re.match(r"^([A-Za-z]):[\\/](.*)$", texto.strip().strip('"'))
        if hallado and Path("/equipo").is_dir():
            return Path("/equipo") / hallado.group(1).lower() / hallado.group(2).replace("\\", "/")
        return Path(texto.strip().strip('"'))


# -- el RE --------------------------------------------------------------------------


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
    return None


def leer_el_re(pdf: Path) -> tuple[str | None, str]:
    """(RE, de dónde salió): del texto del PDF y, si no está, de Tesseract en la 1ª página."""
    import pymupdf

    with pymupdf.open(pdf) as documento:
        if documento.page_count == 0:
            return None, "PDF sin páginas"
        for numero in range(min(2, documento.page_count)):
            if hallado := radicado(documento[numero].get_text()):
                return hallado, f"texto del PDF (página {numero + 1})"
        imagen = documento[0].get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "pagina.png"
            imagen.save(ruta)
            try:
                salida = subprocess.run(
                    ["tesseract", str(ruta), "stdout", "-l", "spa", "--psm", "6"],
                    capture_output=True, text=True, timeout=180,
                    env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                )
            except (OSError, subprocess.SubprocessError) as error:
                return None, f"no se pudo pasar el OCR: {error}"
    if hallado := radicado(salida.stdout):
        return hallado, "OCR de la página 1"
    return None, "no se encontró un RE válido en el texto ni con el OCR"


# -- la caja ------------------------------------------------------------------------


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", sin_tildes).strip()


def _numero(nombre: str) -> int:
    hallado = NUMERADO.match(nombre)
    return int(hallado.group(1)) if hallado else 10**6


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


def _guardar_json(ruta: Path, datos: dict) -> None:
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def _filas_del_indice(hoja) -> dict[int, int]:
    """Número de orden del documento -> fila de la hoja (columna A el nombre, D el orden)."""
    filas = {}
    for fila in range(1, hoja.max_row + 1):
        orden = hoja.cell(fila, 4).value
        if isinstance(orden, (int, float)) and hoja.cell(fila, 1).value:
            filas.setdefault(int(orden), fila)
    return filas


def trabajar_la_caja(carpeta: str, raiz: str, patron: str, aplicar: bool, deshacer: list[dict] | None) -> list[dict]:
    """Lee el RE de las reclamaciones de una caja y, si se pide, lo pone en todos sus sitios."""
    carpeta_p, raiz_p = Path(carpeta), Path(raiz)
    caja = str(carpeta_p.relative_to(raiz_p)) if carpeta_p != raiz_p else "."
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filas: list[dict] = []

    def anotar(**datos) -> None:
        filas.append({**{c: "" for c in COLUMNAS}, "fecha": ahora, "caja": caja, **datos})

    # 1. Qué cambiar: (nombre de antes, nombre nuevo, RE, de dónde salió).
    cambios: list[tuple[str, str, str, str]] = []
    if deshacer is not None:
        for fila in deshacer:
            cambios.append((fila["archivo_despues"], fila["archivo_antes"], fila["re"], "deshacer"))
    else:
        for pdf in sorted(carpeta_p.glob("*.pdf"), key=lambda p: (_numero(p.name), p.name)):
            hallado = NUMERADO.match(pdf.name)
            if not hallado or patron not in _plano(hallado.group(2)):
                continue
            titulo = hallado.group(2)
            if CON_RE.search(titulo):
                anotar(archivo_antes=pdf.name, estado="ya tenía RE")
                continue
            try:
                numero_re, origen = leer_el_re(pdf)
            except Exception as error:  # noqa: BLE001 - un PDF ilegible no para el resto
                anotar(archivo_antes=pdf.name, estado="error", detalle=f"no se pudo abrir: {error}")
                continue
            if not numero_re:
                anotar(archivo_antes=pdf.name, estado="sin RE", detalle=origen)
                continue
            nuevo = f"{hallado.group(1)}_{titulo}-{numero_re}.pdf".upper().replace(".PDF", ".pdf")
            if (carpeta_p / nuevo).exists():
                anotar(archivo_antes=pdf.name, archivo_despues=nuevo, re=numero_re, leido_de=origen,
                       estado="choque de nombre", detalle="ya hay un archivo con ese nombre")
                continue
            cambios.append((pdf.name, nuevo, numero_re, origen))
    if not cambios:
        return filas

    # 2. Dónde está cada PDF en las constancias y en el índice de la caja.
    constancias = _leer_constancias(carpeta_p)
    libro = hoja = None
    filas_de_la_hoja: dict[int, int] = {}
    if (carpeta_p / INDICE).exists():
        from openpyxl import load_workbook

        libro = load_workbook(carpeta_p / INDICE)
        hoja = libro.active
        filas_de_la_hoja = _filas_del_indice(hoja)
    cambio_el_indice = False

    for antes, despues, numero_re, origen in cambios:
        sufijo = f"-{numero_re}"
        titulo_antes = NUMERADO.match(antes).group(2) if NUMERADO.match(antes) else antes
        if not (carpeta_p / antes).exists():
            anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, estado="error",
                   detalle="el PDF ya no está en la caja")
            continue

        # El nombre en el índice: el de la fila con su número de orden, si su
        # título es el del archivo (sin RE, o con él al deshacer).
        indice_antes = indice_despues = ""
        fila_de_la_hoja = filas_de_la_hoja.get(_numero(antes)) if hoja is not None else None
        if fila_de_la_hoja is not None:
            actual = str(hoja.cell(fila_de_la_hoja, 1).value or "")
            if deshacer is not None and actual.upper().endswith(sufijo):
                indice_antes, indice_despues = actual, actual[: -len(sufijo)]
            elif deshacer is None and _plano(actual) == _plano(titulo_antes):
                indice_antes, indice_despues = actual, f"{actual}{sufijo}"
            else:
                fila_de_la_hoja = None

        # En la constancia: el archivo, y su fila en la copia del índice.
        suya = None
        for ruta, datos in constancias:
            pdfs = sorted(
                (a for a in datos.get("archivos") or [] if str(a.get("ruta") or "").lower().endswith(".pdf")),
                key=lambda a: (_numero(Path(str(a.get("ruta"))).name), str(a.get("ruta"))),
            )
            for puesto, archivo in enumerate(pdfs):
                if Path(str(archivo.get("ruta"))).name == antes:
                    suya = (ruta, datos, archivo, puesto, len(pdfs))
                    break
            if suya:
                break

        if not aplicar:
            anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
                   estado="se cambiaría", indice_antes=indice_antes, indice_despues=indice_despues,
                   detalle="" if suya else "sin constancia que lo nombre")
            continue

        # 3. Aplicar: el PDF y, en seguida, su constancia; si la constancia no
        # se deja escribir, el PDF vuelve a su nombre (que nunca queden desparejos).
        try:
            (carpeta_p / antes).rename(carpeta_p / despues)
        except OSError as error:
            anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
                   estado="error", detalle=f"no se pudo renombrar: {error}")
            continue
        detalle = []
        if suya:
            ruta, datos, archivo, puesto, cuantos = suya
            ruta_vieja = str(archivo["ruta"])
            archivo["ruta"] = str(Path(ruta_vieja).with_name(despues)).replace("\\", "/") if "/" in ruta_vieja.replace("\\", "/") else despues
            filas_suyas = ((datos.get("indice") or {}).get("filas")) or []
            if len(filas_suyas) == cuantos:
                nombre = str(filas_suyas[puesto].get("nombre") or "")
                if deshacer is not None and nombre.upper().endswith(sufijo):
                    filas_suyas[puesto]["nombre"] = nombre[: -len(sufijo)]
                elif deshacer is None and _plano(nombre) == _plano(titulo_antes):
                    filas_suyas[puesto]["nombre"] = f"{nombre}{sufijo}"
            try:
                _guardar_json(ruta, datos)
            except OSError as error:
                archivo["ruta"] = ruta_vieja
                (carpeta_p / despues).rename(carpeta_p / antes)
                anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
                       estado="error", detalle=f"no se pudo actualizar la constancia: {error}")
                continue
        else:
            detalle.append("sin constancia que lo nombre")
        if fila_de_la_hoja is not None:
            hoja.cell(fila_de_la_hoja, 1).value = indice_despues
            cambio_el_indice = True
        else:
            detalle.append("su fila del índice no coincide: no se cambió")
            indice_antes = indice_despues = ""
        anotar(archivo_antes=antes, archivo_despues=despues, re=numero_re, leido_de=origen,
               estado="deshecho" if deshacer is not None else "renombrado",
               indice_antes=indice_antes, indice_despues=indice_despues, detalle="; ".join(detalle))

    if cambio_el_indice and libro is not None:
        temporal = carpeta_p / f".{INDICE}.tmp"
        try:
            libro.save(temporal)
            temporal.replace(carpeta_p / INDICE)
        except OSError as error:
            for fila in filas:
                if fila["indice_despues"]:
                    fila["detalle"] = f"no se pudo guardar el índice ({error})"
    return filas


# -- la carpeta ---------------------------------------------------------------------


def cajas_de(raiz: Path):
    """Cada carpeta del destino con PDF: la raíz y sus subcarpetas, sin lo apartado."""
    for actual, carpetas, archivos in os.walk(raiz):
        carpetas[:] = sorted(c for c in carpetas if c.lower() not in SALTAR and not c.startswith("."))
        if any(a.lower().endswith(".pdf") for a in archivos):
            yield Path(actual)


# -- el avance, en vivo ---------------------------------------------------------------

#: Cada cuántos segundos se imprime el avance.
CADA = 10
#: Lo que cuenta como resuelto, y lo que hay que mirar.
BIEN = {"renombrado", "se cambiaría", "deshecho", "ya tenía RE"}
MIRAR = {"sin RE", "choque de nombre"}


def _cifra(numero: float) -> str:
    return f"{numero:,.0f}".replace(",", ".")


def _duracion(segundos: float) -> str:
    segundos = int(max(0, segundos))
    horas, resto = divmod(segundos, 3600)
    return f"{horas} h {resto // 60:02d} min" if horas else f"{resto // 60} min {resto % 60:02d} s"


class Tablero:
    """Las cifras del avance mientras corre, y el análisis al terminar.

    Lo pidió el operador el 2026-10-28: «necesito ver un análisis estadístico del
    progreso en tiempo real». Sale en la misma consola cada ``CADA`` segundos.
    """

    def __init__(self, total_de_cajas: int) -> None:
        self.total = total_de_cajas
        self.cajas = 0
        self.inicio = time.monotonic()
        self.ultimo = 0.0
        self.estados: dict[str, int] = {}
        self.origenes: dict[str, int] = {}
        self.por_tipo: dict[str, dict[str, int]] = {}
        self.motivos: dict[str, int] = {}

    def sumar(self, filas: list[dict]) -> None:
        self.cajas += 1
        for fila in filas:
            estado = fila["estado"]
            self.estados[estado] = self.estados.get(estado, 0) + 1
            if fila.get("leido_de") and fila["leido_de"] != "deshacer":
                origen = "OCR" if "OCR" in fila["leido_de"] else "texto del PDF"
                self.origenes[origen] = self.origenes.get(origen, 0) + 1
            hallado = NUMERADO.match(fila.get("archivo_antes") or "")
            tipo = CON_RE.sub("", hallado.group(2)).replace("-", " ") if hallado else "(otro)"
            del_tipo = self.por_tipo.setdefault(tipo, {})
            del_tipo[estado] = del_tipo.get(estado, 0) + 1
            if estado in MIRAR or estado == "error":
                motivo = fila.get("detalle") or estado
                self.motivos[motivo] = self.motivos.get(motivo, 0) + 1

    def documentos(self) -> int:
        return sum(self.estados.values())

    def imprimir_si_toca(self, *, siempre: bool = False) -> None:
        ahora = time.monotonic()
        if not siempre and ahora - self.ultimo < CADA:
            return
        self.ultimo = ahora
        transcurrido = ahora - self.inicio
        ritmo = self.cajas / transcurrido * 60 if transcurrido > 0 else 0
        falta = (self.total - self.cajas) / (self.cajas / transcurrido) if self.cajas and transcurrido > 0 else 0
        documentos = self.documentos()
        bien = sum(self.estados.get(e, 0) for e in BIEN)
        mirar = sum(self.estados.get(e, 0) for e in MIRAR)
        errores = self.estados.get("error", 0)
        leidos = sum(self.origenes.values())
        texto = self.origenes.get("texto del PDF", 0)
        porcentaje = self.cajas / self.total * 100 if self.total else 100
        linea = (
            f"[{datetime.now():%H:%M:%S}] {_cifra(self.cajas)}/{_cifra(self.total)} cajas ({porcentaje:.1f} %) · "
            f"{ritmo:.0f} cajas/min · lleva {_duracion(transcurrido)} · falta ~{_duracion(falta)}\n"
            f"           documentos {_cifra(documentos)}: con RE {_cifra(bien)}"
            f" ({bien / documentos * 100 if documentos else 0:.1f} %) · sin RE {_cifra(mirar)}"
            f" ({mirar / documentos * 100 if documentos else 0:.1f} %) · errores {_cifra(errores)}"
        )
        if leidos:
            linea += f" · RE leído del texto {texto / leidos * 100:.0f} %, por OCR {100 - texto / leidos * 100:.0f} %"
        print(linea, flush=True)

    def resumen(self) -> None:
        documentos = self.documentos()
        print("\n" + "=" * 78)
        print(f"ANÁLISIS · {_cifra(self.cajas)} cajas · {_cifra(documentos)} documentos · "
              f"{_duracion(time.monotonic() - self.inicio)}")
        print("=" * 78)
        print("\nPor resultado:")
        for estado, veces in sorted(self.estados.items(), key=lambda par: -par[1]):
            print(f"  {estado:<20} {_cifra(veces):>8}  {veces / documentos * 100 if documentos else 0:5.1f} %")
        if self.origenes:
            leidos = sum(self.origenes.values())
            print("\nDe dónde salió el RE:")
            for origen, veces in sorted(self.origenes.items(), key=lambda par: -par[1]):
                print(f"  {origen:<20} {_cifra(veces):>8}  {veces / leidos * 100:5.1f} %")
        if self.por_tipo:
            print("\nPor tipo de documento:")
            print(f"  {'tipo':<50} {'total':>7} {'con RE':>7} {'sin RE':>7}   éxito")
            for tipo, estados in sorted(self.por_tipo.items(), key=lambda par: -sum(par[1].values())):
                total = sum(estados.values())
                bien = sum(estados.get(e, 0) for e in BIEN)
                print(f"  {tipo[:50]:<50} {_cifra(total):>7} {_cifra(bien):>7} {_cifra(total - bien):>7}"
                      f"   {bien / total * 100:5.1f} %")
        if self.motivos:
            print("\nPor qué quedaron sin RE o fallaron (los más repetidos):")
            for motivo, veces in sorted(self.motivos.items(), key=lambda par: -par[1])[:8]:
                print(f"  {_cifra(veces):>7}  {motivo[:100]}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Pone el RE en el nombre de las reclamaciones entregadas.")
    parser.add_argument(
        "carpeta",
        nargs="?",
        default=CARPETA_POR_OMISION,
        help=f"la carpeta de destino que entregó el bot, como la ve Windows (por omisión {CARPETA_POR_OMISION})",
    )
    parser.add_argument("--aplicar", action="store_true", help="hacer los cambios (sin esto, sólo simula)")
    parser.add_argument("--deshacer", action="store_true", help="revertir lo que dice el registro")
    parser.add_argument("--patron", default="RECLAM", help="lo que tiene que decir el título (por omisión RECLAM)")
    parser.add_argument("--procesos", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()

    raiz = ruta_del_servicio(args.carpeta)
    if not raiz.is_dir():
        print(f"No encuentro la carpeta: {args.carpeta} (vista como {raiz})")
        return 2
    patron = _plano(args.patron)
    aplicar = args.aplicar or args.deshacer

    deshacer_por_caja: dict[str, list[dict]] = {}
    if args.deshacer:
        try:
            with (raiz / REGISTRO).open(encoding="utf-8-sig", newline="") as archivo:
                for fila in csv.DictReader(archivo, delimiter=";"):
                    if fila.get("estado") == "renombrado":
                        deshacer_por_caja.setdefault(fila["caja"], []).append(fila)
        except OSError as error:
            print(f"No hay registro que deshacer ({raiz / REGISTRO}): {error}")
            return 2
        cajas = [raiz / caja if caja != "." else raiz for caja in deshacer_por_caja]
    else:
        print(f"Buscando las cajas de {raiz} …")
        cajas = list(cajas_de(raiz))
    print(f"{len(cajas)} cajas · {'DESHACER' if args.deshacer else 'APLICAR' if aplicar else 'SIMULACIÓN (no cambia nada)'} · "
          f"{args.procesos} a la vez")

    salida = raiz / (REGISTRO if aplicar else SIMULACION)
    nueva = not salida.exists() or not aplicar
    tablero = Tablero(len(cajas))
    with salida.open("a" if aplicar else "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        if nueva:
            escritor.writeheader()
        with ProcessPoolExecutor(max_workers=args.procesos) as pool:
            futuros = {}
            for caja in cajas:
                clave = str(caja.relative_to(raiz)) if caja != raiz else "."
                futuros[pool.submit(trabajar_la_caja, str(caja), str(raiz), patron, aplicar,
                                    deshacer_por_caja.get(clave) if args.deshacer else None)] = clave
            print(f"Avance cada {CADA} s. Se puede cortar con Ctrl+C y volver a correr: lo hecho se salta.\n", flush=True)
            for hechas, futuro in enumerate(as_completed(futuros), start=1):
                try:
                    filas = futuro.result()
                except Exception as error:  # noqa: BLE001 - una caja que falla no para las demás
                    filas = [{**{c: "" for c in COLUMNAS}, "caja": futuros[futuro], "estado": "error", "detalle": str(error)}]
                for fila in filas:
                    escritor.writerow(fila)
                archivo.flush()
                tablero.sumar(filas)
                tablero.imprimir_si_toca(siempre=hechas == 1 or hechas == len(futuros))
    tablero.resumen()
    print(f"\nRegistro, con cada documento y su motivo: {salida}")
    if not aplicar:
        print("\nNo se cambió nada. Revise el registro y, si está bien, vuelva a correrlo con --aplicar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
