"""Inventario Kingspan: el FUID oficial de la UPD, una fila por asunto.

Se elige como plantilla de la caja de correspondencia. Cada PDF es una UPD -- un
paquete de documentos con su sticker -- y lo que se entrega es su fila en el
inventario oficial de Kingspan (F-PSD-001, hoja «FUID», datos desde la fila 7),
escrita sobre la plantilla oficial con su logo y su formato.

La regla de la fila vive en el dominio (`domain/kingspan.py`); aquí se lee el
PDF, se pide el OCR donde la capa de texto no alcanza y se escribe la planilla.

De dónde sale cada columna:

- ASUNTO, DESDE, HASTA, INICIAL y FINAL, del papel.
- CAJA, de la carpeta de la caja en la ruta («100C000235»); UPD, del nombre del
  archivo («UPD3869754.pdf»).
- ENTIDAD REMITENTE y ENTIDAD PRODUCTORA, fijas: KINGSPAN SAS.
- OFICINA PRODUCTORA y OBJETO, los fijos del oficial, salvo que los ajustes
  digan otra cosa.
- No. ACTA DE TRANSFERENCIA, la que el operador eligió en el asistente.
- FECHA DE INVENTARIO, el día en que corre.
- Lo que el sistema no puede saber -- quién lo elaboró, la fecha de
  transferencia, el tomo, los folios, las notas -- sale N/A, como en el oficial.
  No se saca de fechas sueltas del texto: eso sería inventarlo.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import openpyxl

from ...adapters.fuid_psd001 import FuidPsd001
from ...application.fuid import caja_de_la_ruta, upd_del_archivo
from ...application.ports import Band
from ...application.progress import ProgressEvent, Stage
from ...domain.ficha import fichar
from ...domain.kingspan import (
    ACTAS_DE_TRANSFERENCIA,
    ENTIDAD,
    NO_APLICA,
    Documento,
    FilaKingspan,
    documento_de,
    filas_de,
)
from .taller import Taller

logger = logging.getLogger(__name__)

#: Cómo se llama el libro que se deja junto a los PDF.
INVENTORY_SUFFIX = "_INVENTARIO_KINGSPAN.xlsx"

#: La plantilla: el inventario oficial de Kingspan sin sus filas.
PLANTILLA = Path(__file__).resolve().parents[2] / "assets" / "fuid-kingspan.xlsx"
HOJA = "FUID"
PRIMERA_FILA = 7

#: Los valores fijos del oficial en todas sus filas recientes.
OFICINA_PRODUCTORA = "CONTABILIDAD"
OBJETO = "TRANSFERENCIA PRIMARIA"

#: La franja de la página donde va el encabezado: «Número» y «Fecha».
ENCABEZADO = Band(0.0, 0.0, 1.0, 0.30)

#: Lo que delata un encabezado emitido por el sistema contable de Kingspan. Una
#: página que lo trae y cuyo número no se leyó es la que merece OCR: la capa de
#: texto de estos escaneos perdió el número de algunas notas (páginas 106 y 316
#: de la UPD3869754) y Tesseract lo recupera de la franja de arriba. Mirar sólo
#: éstas, y no todas, es lo que separa leer una UPD en segundos de leerla en
#: cinco minutos: medido, el OCR de las 330 páginas restantes no encontró nada.
_PISTAS_DE_ENCABEZADO = (
    "NOTA INTERNA",
    "COMPROBANTE",
    "RECIBO DE CAJA",
    "RECIBOS DE CAJA",
    "NOTA DE AJUSTE",
    "NOTA BANCARIA",
    "NOTAS BANCARIAS",
    "RECLASIFICACIONES",
    "ORDEN DE SERVICIO",
    "DOCUMENTO SOPORTE",
)


def _merece_ocr(texto: str) -> bool:
    if not texto.strip():
        return True
    mayusculas = texto.upper()
    return any(pista in mayusculas for pista in _PISTAS_DE_ENCABEZADO) and "MERO" in mayusculas


def _leer(taller: Taller, source) -> tuple[list[str], list[Documento], int]:
    """El texto de cada página y los documentos que abren alguna, en orden."""
    textos: list[str] = []
    documentos: list[Documento] = []
    ocr_usado = 0
    ocr = None
    total = source.page_count

    for pagina in range(1, total + 1):
        taller.control.check()
        taller.progress.emit(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=pagina - 1,
                total=total,
                detail=f"leyendo página {pagina} de {total}",
            )
        )
        try:
            texto = source.text_of(pagina)
        except Exception as error:  # noqa: BLE001 - una hoja ilegible no tumba el trabajo
            logger.debug("no se pudo leer la página %s: %s", pagina, error)
            texto = ""

        documento = documento_de(texto, pagina)
        if documento is None and _merece_ocr(texto):
            # Sin capa de texto se lee la página entera; con capa pero sin
            # número, sólo la franja del encabezado, que es donde está.
            banda = None if not texto.strip() else ENCABEZADO
            try:
                ocr = ocr or taller.ocr()
                leido = ocr.read(source.render(pagina, banda, dpi=300)).text
                ocr_usado += 1
                documento = documento_de(leido, pagina)
                if not texto.strip():
                    texto = leido
            except Exception as error:  # noqa: BLE001 - el OCR es una ayuda, no un requisito
                logger.warning("el OCR de la página %s falló: %s", pagina, error)

        textos.append(texto)
        if documento is not None:
            documentos.append(documento)
    return textos, documentos, ocr_usado


def _confirmar(
    taller: Taller, source, documentos: list[Documento]
) -> tuple[list[Documento], dict[str, list[str]], int]:
    """Relee en la imagen los documentos que van al inventario y corrige la capa.

    La capa de texto de estos escaneos es un OCR viejo y a veces cambia una
    cifra: en la UPD3869754 la página 107 dice «001-NI-00014346» y la capa
    traía 14345. Dentro del rango no se nota, pero en una punta cambiaría el
    DESDE o el HASTA sin que nadie lo viera. Por eso se releen con Tesseract,
    sobre la franja del encabezado, los que salen escritos: las dos puntas de
    cada serie y los que quedan fuera del rango. Son unas pocas páginas por UPD.

    Si las dos lecturas no coinciden manda la de la imagen, y se anota para que
    alguien lo mire con el papel delante. Si Tesseract no lee nada, se queda la
    de la capa: no es una contradicción, es una lectura que falta.
    """
    a_releer: dict[int, Documento] = {}
    for fila in filas_de(documentos):
        if not fila.documentos:
            continue
        puntas = {fila.documentos[0], fila.documentos[-1]}
        desde = min(documento.numero for documento in puntas)
        hasta = max(documento.numero for documento in puntas)
        for documento in fila.documentos:
            if documento in puntas or not desde <= documento.numero <= hasta:
                a_releer[documento.pagina] = documento
    if not a_releer:
        return documentos, {}, 0

    ocr = taller.ocr()
    corregidos: dict[int, Documento] = {}
    notas: dict[str, list[str]] = {}
    for pagina, documento in sorted(a_releer.items()):
        taller.control.check()
        try:
            leido = documento_de(ocr.read(source.render(pagina, ENCABEZADO, dpi=300)).text, pagina)
        except Exception as error:  # noqa: BLE001 - confirmar es una ayuda, no un requisito
            logger.warning("no se pudo releer la página %s: %s", pagina, error)
            continue
        if leido is None or leido.serie != documento.serie:
            continue
        if (leido.numero, leido.fecha) == (documento.numero, documento.fecha):
            continue
        corregido = Documento(
            pagina=pagina,
            serie=documento.serie,
            numero=leido.numero,
            fecha=leido.fecha or documento.fecha,
        )
        corregidos[pagina] = corregido
        notas.setdefault(documento.serie, []).append(
            f"verificar p.{pagina}: la imagen dice {corregido.codigo}"
            f"{' del ' + corregido.fecha.strftime('%d/%m/%Y') if corregido.fecha else ''}"
            f" y el texto del escaneo {documento.codigo}"
        )
    return [corregidos.get(d.pagina, d) for d in documentos], notas, len(a_releer)


def _sin_numeros(textos: list[str]) -> FilaKingspan:
    """La fila de una UPD sin documentos numerados: conciliaciones, cartas, formatos.

    El asunto sale del título impreso y las fechas de punta a punta del
    archivo, como en el inventario de un PDF entero.
    """
    ficha = fichar(textos)
    notas = []
    if ficha.asunto is None:
        notas.append("no se pudo leer el encabezado")
    if not ficha.esta_fechada:
        notas.append("no se encontró ninguna fecha en el documento")
    return FilaKingspan(
        asunto=ficha.asunto or "DOCUMENTO SIN IDENTIFICAR",
        fecha_inicial=ficha.fecha_inicial,
        fecha_final=ficha.fecha_final,
        notas="; ".join(notas),
    )


def _caja(taller: Taller) -> str:
    """La caja que dice la ruta del PDF: la relativa con que llegó, la de entrega o la suya."""
    for ruta in (taller.name, taller.delivered_to, str(taller.source)):
        if ruta:
            caja = caja_de_la_ruta(str(ruta))
            if caja != NO_APLICA:
                return caja
    return NO_APLICA


def _serie(fila: FilaKingspan) -> str | None:
    return fila.documentos[0].serie if fila.documentos else None


def _upd(nombre: str) -> str:
    """El UPD como lo escribe el oficial: «UPD3869754»."""
    numero = upd_del_archivo(nombre)
    return f"UPD{numero}" if numero != NO_APLICA else NO_APLICA


def celdas_kingspan(
    fila: FilaKingspan,
    *,
    orden: int,
    caja: str,
    upd: str,
    settings: dict,
    inventariado: date,
    acta: str | None = None,
) -> list[object]:
    """Los valores de la fila en las columnas A a AA del formato."""

    def ajuste(clave: str, por_omision: str) -> str:
        return settings.get(clave) or por_omision

    return [
        orden,                                                   # A  N° ORDEN
        NO_APLICA,                                               # B  CÓDIGO
        ENTIDAD,                                                 # C  ENTIDAD REMITENTE
        ENTIDAD,                                                 # D  ENTIDAD PRODUCTORA
        NO_APLICA,                                               # E  UNIDAD ADMINISTRATIVA
        ajuste("fuid_oficina", OFICINA_PRODUCTORA),              # F  OFICINA PRODUCTORA
        ajuste("fuid_objeto", OBJETO),                           # G  OBJETO
        NO_APLICA,                                               # H  SERIE
        NO_APLICA,                                               # I  SUBSERIE
        fila.asunto,                                             # J  ASUNTO
        fila.desde,                                              # K  DESDE
        fila.hasta,                                              # L  HASTA
        fila.fecha_inicial or NO_APLICA,                         # M  INICIAL
        fila.fecha_final or NO_APLICA,                           # N  FINAL
        caja,                                                    # O  CAJA
        upd,                                                     # P  UPD
        NO_APLICA,                                               # Q  TOMO
        NO_APLICA,                                               # R  OTRO
        NO_APLICA,                                               # S  CAJA INTERNA
        NO_APLICA,                                               # T  FOLIOS
        NO_APLICA,                                               # U  SOPORTE
        NO_APLICA,                                               # V  FRECUENCIA
        # Las notas del archivo son del archivista, como en el oficial: lo que
        # el bot encuentra para revisar va a los avisos del trabajo, no aquí.
        NO_APLICA,                                               # W  NOTAS
        ajuste("fuid_elaborado_por", NO_APLICA),                 # X  ELABORADO POR
        inventariado,                                            # Y  FECHA DE INVENTARIO
        acta or NO_APLICA,                                       # Z  No. ACTA DE TRANSFERENCIA
        NO_APLICA,                                               # AA FECHA DE TRANSFERENCIA
    ]


def escritor() -> FuidPsd001:
    return FuidPsd001(PLANTILLA, hoja=HOJA, primera_fila=PRIMERA_FILA, formato_de_la_plantilla=True)


def _dividir(taller: Taller, fila: FilaKingspan, total: int, *, con_portada: bool) -> list[Path]:
    """Un PDF por documento de la serie, con sus anexos detrás.

    Cada documento empieza en su página y se queda con todo lo que viene hasta el
    siguiente de la serie: las facturas y causaciones grapadas detrás son suyas.
    Lo que haya antes del primero -- la portada -- va con el primero.
    """
    import pymupdf

    documentos = fila.documentos
    if not documentos:
        return []
    taller.destination.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []
    with pymupdf.open(taller.source) as origen:
        for indice, documento in enumerate(documentos):
            taller.control.check()
            taller.progress.emit(
                ProgressEvent(
                    stage=Stage.ASSEMBLING,
                    done=indice,
                    total=len(documentos),
                    detail=f"escribiendo {documento.codigo}",
                )
            )
            inicio = 1 if indice == 0 and con_portada else documento.pagina
            fin = documentos[indice + 1].pagina - 1 if indice + 1 < len(documentos) else total
            destino = taller.destination / f"{documento.codigo}.pdf"
            with pymupdf.open() as salida:
                salida.insert_pdf(origen, from_page=inicio - 1, to_page=fin - 1)
                salida.save(destino, garbage=3, deflate=True)
            escritos.append(destino)
    return escritos


def _kingspan_job(payload: dict, task, *, avisos: list[str] = ()) -> dict:
    """Inventaría una UPD de Kingspan y, si se pidió, la divide por documento."""
    from ...application.task import TaskKind

    taller = Taller.desde(payload)
    notices = list(avisos)

    source = _open_source(taller)
    try:
        textos, documentos, ocr_usado = _leer(taller, source)
        taller.progress.emit(
            ProgressEvent(
                stage=Stage.IDENTIFYING,
                done=0,
                total=1,
                detail="confirmando en la imagen el primer y el último documento",
            )
        )
        documentos, discrepancias, releidas = _confirmar(taller, source, documentos)
    finally:
        source.close()

    filas = [
        replace(fila, notas="; ".join(filter(None, [fila.notas, *discrepancias.get(_serie(fila), [])])))
        for fila in filas_de(documentos)
    ] or [_sin_numeros(textos)]

    taller.progress.emit(
        ProgressEvent(
            stage=Stage.INVENTORYING,
            done=0,
            total=1,
            detail=f"escribiendo el inventario ({len(filas)} fila(s))",
        )
    )
    # El nombre con que llegó el trabajo, no el del archivo guardado: una
    # subida se almacena con un nombre generado («C157F939….pdf») y con él la
    # UPD y el Excel salían sin nombre. En una carpeta llega con su ruta
    # relativa, «100C000235/UPD3869754.pdf», que también trae la caja.
    caja = _caja(taller)
    upd = _upd(Path(taller.name).name)
    # La que eligió el operador en el asistente. El servicio ya rechazó una que
    # no fuera de la lista; si aun así llega otra, no se escribe.
    acta = payload.get("acta") if payload.get("acta") in ACTAS_DE_TRANSFERENCIA else None
    hoy = date.today()
    celdas = [
        celdas_kingspan(
            fila,
            orden=orden,
            caja=caja,
            upd=upd,
            settings=taller.settings,
            inventariado=hoy,
            acta=acta,
        )
        for orden, fila in enumerate(filas, start=1)
    ]
    destino = taller.destination / f"{Path(taller.name).stem.upper()}{INVENTORY_SUFFIX}"
    inventario = escritor().write_cells(celdas, destino)

    outputs: list[str] = [str(inventario)]
    if task is TaskKind.BOTH:
        for indice, fila in enumerate(filas):
            divididos = _dividir(taller, fila, len(textos), con_portada=indice == 0)
            outputs.extend(str(ruta) for ruta in divididos)

    # Lo que hay que revisar con el papel delante -- documentos fuera del rango,
    # fechas que no se leyeron, una cifra en que la imagen y el texto del
    # escaneo no coinciden -- se dice aquí y no en la columna NOTAS.
    for fila in filas:
        if fila.notas:
            notices.append(f"{fila.asunto}: {fila.notas}")
    if not documentos:
        notices.append(
            "la UPD no trae documentos numerados (001-XX-NNNNNNNN): la fila sale del "
            "título impreso y de las fechas de punta a punta del archivo."
        )
    if ocr_usado:
        notices.append(f"{ocr_usado} página(s) se leyeron por OCR.")
    if releidas:
        corregidas = sum(len(notas) for notas in discrepancias.values())
        notices.append(
            f"se confirmaron en la imagen {releidas} documento(s) del inventario"
            + (f"; {corregidas} no coincidía(n) con el texto del escaneo (ver NOTAS)." if corregidas else ".")
        )

    taller.progress.emit(ProgressEvent(stage=Stage.DONE, done=1, total=1))

    principal = filas[0]
    return {
        "document": taller.name,
        "page_count": len(textos),
        "groups": [],
        "quarantine": [],
        "repairs": [],
        "review_queue": [],
        "outputs": outputs,
        "unwritable_pages": [],
        "inventory": {
            "source_document": taller.name,
            "source_pages": len(textos),
            "generated_files": len(outputs) - 1,
            "pages_accounted_for": len(textos),
            "items": [],
            "quarantine_pages": [],
            "review_pages": [],
            "stats": {
                "kingspan_inventory": True,
                "rows": len(filas),
                "documents": sum(len(fila.documentos) for fila in filas),
                "first_document": principal.desde,
                "last_document": principal.hasta,
                "ocr_pages": ocr_usado,
            },
        },
        "stats": {
            "escalated": 0,
            "no_leidas": [],
            "kingspan_rows": len(filas),
            "kingspan_documents": sum(len(fila.documentos) for fila in filas),
            "outputs": len(outputs),
        },
        "task": str(task),
        "notices": notices,
    }


#: El libro de toda la corrida, en la raíz del destino.
NOMBRE_DEL_GENERAL = "00.INVENTARIO DOCUMENTAL KINGSPAN.xlsx"

#: Columnas de orden, caja y UPD (A, O y P) en la lista de celdas.
_ORDEN, _CAJA, _UPD = 0, 14, 15


def _filas_escritas(planilla: Path) -> list[list[object]]:
    """Las filas de un inventario de UPD ya escrito, tal como quedaron."""
    libro = openpyxl.load_workbook(planilla, read_only=True)
    try:
        hoja = libro[HOJA]
        return [
            list(valores)
            for valores in hoja.iter_rows(min_row=PRIMERA_FILA, max_col=27, values_only=True)
            if any(valor not in (None, "") for valor in valores)
        ]
    finally:
        libro.close()


def inventario_general(destino: Path) -> Path | None:
    """El inventario de toda la carpeta: las filas de cada UPD en un solo libro.

    Es como se entrega el oficial: un libro, ordenado por caja y UPD, con el
    N° ORDEN empezando en 1 en cada caja. Se arma con lo que hay en el destino,
    así que también cuenta las UPD de una corrida anterior que se retoma.
    """
    filas: list[list[object]] = []
    raiz = Path(destino)
    for planilla in sorted(raiz.rglob(f"*{INVENTORY_SUFFIX}")):
        # Lo apartado al rehacer una entrega (`_reemplazados`) ya no cuenta:
        # está ahí para no perderlo, no porque siga entregado.
        if any(parte.startswith("_") for parte in planilla.relative_to(raiz).parts[:-1]):
            continue
        try:
            filas.extend(_filas_escritas(planilla))
        except Exception:  # noqa: BLE001 - una planilla ilegible no tumba el general
            logger.warning("no se pudo leer el inventario %s", planilla, exc_info=True)
    if not filas:
        return None
    filas.sort(key=lambda fila: (str(fila[_CAJA]), str(fila[_UPD]), fila[_ORDEN] or 0))
    caja_anterior, orden = None, 0
    for fila in filas:
        orden = orden + 1 if fila[_CAJA] == caja_anterior else 1
        caja_anterior = fila[_CAJA]
        fila[_ORDEN] = orden
    return escritor().write_cells(filas, Path(destino) / NOMBRE_DEL_GENERAL)


def _open_source(taller: Taller):
    from ...adapters.pymupdf_source import PyMuPDFPageSource

    return PyMuPDFPageSource(taller.source, taller.name)
