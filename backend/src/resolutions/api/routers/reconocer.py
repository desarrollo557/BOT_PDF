"""Qué parece ser lo que se va a cargar, antes de procesarlo.

Dos preguntas: la de un PDF que el operador acaba de soltar en la pantalla, y la
de una carpeta local entera con sus subcarpetas. Las dos se contestan con la
capa de texto y el nombre, sin OCR y sin proveedor de pago: es una sugerencia
para elegir la habilidad, no el trabajo.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile

from ...adapters import red_smb
from ...application.sugerencia import sugerir
from ...domain.doctype import DocumentType
from ..contexto import Ctx
from ..folders import CONSUMED_DIR, clean_path, en_orden_de_ruta
from ..rutas_del_equipo import al_operador, al_servicio
from .trabajos import _stream_to_disk

router = APIRouter()

#: Cuántos PDF de una carpeta se miran como mucho. Mirar uno son milisegundos
#: de texto, pero abrir un escaneo de cien megas no; con esto la respuesta
#: llega en segundos y no deja la pantalla esperando por una caja gigante.
MAXIMO_DE_LA_CARPETA = 400


def _sugerencia(ruta: Path, nombre: str) -> dict[str, object]:
    from ...adapters.pymupdf_source import PyMuPDFPageSource

    source = PyMuPDFPageSource(ruta, nombre)
    try:
        resultado = sugerir(source, nombre)
        paginas = source.page_count
    finally:
        source.close()
    return {
        "tipo": str(resultado.tipo),
        "etiqueta": resultado.tipo.label,
        "por": resultado.por,
        "motivo": resultado.motivo,
        "paginas": paginas,
    }


@router.post("/api/reconocer")
async def reconocer_archivo(ctx: Ctx, file: UploadFile) -> dict[str, object]:
    """Qué parece un PDF recién soltado: tipo, cómo se supo y por qué."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Solo se aceptan archivos PDF")
    temporal = ctx.settings.upload_dir / f"reconocer-{uuid4().hex}.pdf"
    try:
        if await _stream_to_disk(ctx, file, temporal) == 0:
            raise HTTPException(status_code=400, detail="El archivo llegó vacío")
        return await asyncio.to_thread(_sugerencia, temporal, file.filename or temporal.name)
    finally:
        temporal.unlink(missing_ok=True)


#: En una carpeta de red, cuántos PDF se bajan para sugerir el tipo. Cada uno
#: viaja entero por la red; el total se sabe igual por el listado.
MUESTRA_DE_LA_RED = 12


def _sin_abrir(relativa: str, error: Exception) -> dict[str, object]:
    return {
        "ruta": relativa,
        "tipo": str(DocumentType.DESCONOCIDO),
        "etiqueta": DocumentType.DESCONOCIDO.label,
        "por": "",
        "motivo": f"no se pudo abrir: {type(error).__name__}",
        "paginas": 0,
    }


@router.post("/api/reconocer-carpeta")
async def reconocer_carpeta(payload: dict) -> dict[str, object]:
    """Qué hay en una carpeta local o de red y sus subcarpetas, PDF por PDF."""
    escrita = clean_path(str((payload or {}).get("ruta") or ""))
    # Dentro de Docker «C:\Users\…» es «/equipo/c/Users/…», como en la corrida,
    # y «Z:\…» puede ser una unidad que se lee por la red.
    ruta_del_servicio = al_servicio(escrita)
    if red_smb.es_de_red(ruta_del_servicio):
        # Si el servidor pide usuario y clave, 401 y la pantalla los pide.
        await asyncio.to_thread(red_smb.asegurar, ruta_del_servicio)
    if red_smb.por_smb(ruta_del_servicio):
        return await asyncio.to_thread(_reconocer_en_la_red, ruta_del_servicio)
    raiz = Path(ruta_del_servicio)
    if not raiz.is_dir():
        raise HTTPException(status_code=404, detail="La carpeta no existe")

    def recorrer() -> dict[str, object]:
        muestra, total, exacto = contar_por_lotes(_pdfs_de(raiz), MAXIMO_DE_LA_CARPETA)
        archivos = []
        for ruta in muestra:
            relativa = ruta.relative_to(raiz).as_posix()
            try:
                archivos.append({"ruta": relativa, **_sugerencia(ruta, relativa)})
            except Exception as error:  # noqa: BLE001 - uno roto no tapa a los demás
                archivos.append(_sin_abrir(relativa, error))
        return _resumen(al_operador(raiz), total, archivos, exacto=exacto)

    return await asyncio.to_thread(recorrer)


#: Hasta cuántos PDF se cuentan, y cuánto tiempo, antes de decir «más de N».
#: Una carpeta del repositorio puede tener cientos de miles: contarlos todos
#: para una sugerencia dejaba la pantalla esperando (2026-10-20, «hagámoslo por
#: conteo por lotes»). El número exacto lo da la corrida, que sí los recorre.
TOPE_DEL_CONTEO = 50_000
SEGUNDOS_DEL_CONTEO = 4.0
#: Cada cuántos PDF se mira el reloj.
LOTE_DEL_CONTEO = 500


def contar_por_lotes(pdfs, muestra: int) -> tuple[list, int, bool]:
    """Los primeros ``muestra`` y la cuenta del resto, con tope: (muestra, total, exacto).

    ``exacto`` es falso si se paró por el tope de cantidad o de tiempo: el
    total es entonces «al menos».
    """
    tomados: list = []
    total = 0
    limite = time.monotonic() + SEGUNDOS_DEL_CONTEO
    for pdf in pdfs:
        total += 1
        if len(tomados) < muestra:
            tomados.append(pdf)
        if total >= TOPE_DEL_CONTEO or (total % LOTE_DEL_CONTEO == 0 and time.monotonic() > limite):
            return tomados, total, False
    return tomados, total, True


def _pdfs_de(raiz: Path) -> Iterator[Path]:
    """Los PDF de la carpeta y sus subcarpetas, a medida que se leen, como los recorre la corrida."""
    return en_orden_de_ruta(raiz)


def _reconocer_en_la_red(ruta: str) -> dict[str, object]:
    """Una carpeta de red: el total por el listado y el tipo por una muestra."""
    import tempfile

    if not red_smb.es_carpeta(ruta):
        raise HTTPException(status_code=404, detail="La carpeta no existe")
    muestra, total, exacto = contar_por_lotes(
        red_smb.iterar(ruta, saltar=frozenset({CONSUMED_DIR})), MUESTRA_DE_LA_RED
    )
    archivos = []
    with tempfile.TemporaryDirectory(prefix="reconocer-red-") as temporal:
        for indice, pdf in enumerate(muestra):
            relativa = pdf.ruta[len(ruta.rstrip("/")) + 1 :]
            try:
                copia = red_smb.traer(pdf.ruta, Path(temporal) / f"{indice}.pdf")
                archivos.append({"ruta": relativa, **_sugerencia(copia, relativa)})
            except red_smb.CredencialesDeRed:
                raise
            except Exception as error:  # noqa: BLE001 - uno roto no tapa a los demás
                archivos.append(_sin_abrir(relativa, error))
    return _resumen(al_operador(ruta), total, archivos, exacto=exacto)


def _resumen(
    ruta: str, total: int, archivos: list[dict[str, object]], *, exacto: bool = True
) -> dict[str, object]:
    cuenta = Counter(archivo["tipo"] for archivo in archivos)
    return {
        "ruta": ruta,
        # Si se lee por la red -- también «Z:\…» si esa unidad es de red --:
        # la pantalla sólo deja «Dejarlo», como hace la corrida.
        "de_red": red_smb.es_de_red(al_servicio(ruta)),
        "total": total,
        # Falso si el conteo se paró en su tope: hay al menos `total`.
        "total_exacto": exacto,
        "mirados": len(archivos),
        "por_tipo": [
            {"tipo": tipo, "etiqueta": DocumentType(tipo).label, "cantidad": cantidad}
            for tipo, cantidad in cuenta.most_common()
        ],
        "archivos": archivos,
    }
