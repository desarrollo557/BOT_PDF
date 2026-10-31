"""El FUID general de una carpeta o un lote de libros de diplomas.

Lo que entrega el archivo es un solo inventario con todos los libros uno detrás
de otro, una fila por diploma. Se arma con los FUID que quedaron junto a cada
libro, para que lo de la raíz y lo de cada carpeta no puedan discrepar.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("openpyxl")

from resolutions.adapters.fuid_inventory import FuidInventory  # noqa: E402
from resolutions.adapters.fuid_reader import leer_fuid  # noqa: E402
from resolutions.api.indices import NOMBRE_DEL_FUID_GENERAL, fuid_general  # noqa: E402
from resolutions.application.fuid import FuidRow  # noqa: E402
from resolutions.application.inventory_document import template_for  # noqa: E402
from resolutions.domain.doctype import DocumentType  # noqa: E402


def _libro(output_dir, job_id: str, upd: str, nombres: list[str], estado: str = "done"):
    """Un trabajo de libro de diplomas con su FUID escrito donde lo deja el worker."""
    fuid = f"{upd}__FUID.xlsx"
    filas = [
        FuidRow(
            orden=i,
            asunto=f"{nombre} - ESPECIALISTA EN SALUD OCUPACIONAL",
            otro=f"{i}-8",
            notas=f"Archivo: {i}_DIPLOMA.pdf",
        )
        for i, nombre in enumerate(nombres, start=1)
    ]
    FuidInventory(template_for(DocumentType.DIPLOMA)).write(filas, output_dir / job_id / upd / fuid)
    return SimpleNamespace(
        id=job_id,
        filename=f"{upd}.pdf",
        state=estado,
        task="both",
        tipo="diploma",
        report={"fuid": fuid, "stats": {"document_type": "diploma"}},
    )


def test_los_libros_van_seguidos_con_el_orden_corrido(tmp_path):
    salidas = tmp_path / "salidas"
    trabajos = [
        _libro(salidas, "b" * 32, "UPD3858080", ["LUIS GOMEZ"]),
        _libro(salidas, "a" * 32, "UPD3858079", ["ANA PEREZ", "JUAN DIAZ"]),
    ]
    ruta = fuid_general(salidas, trabajos, tmp_path / "destino", destino_de=lambda t: t.filename[:-4])

    assert ruta is not None and ruta.name == NOMBRE_DEL_FUID_GENERAL
    filas = leer_fuid(ruta).filas
    assert [f[0] for f in filas] == ["1", "2", "3"]
    assert [f[2].split(" - ")[0] for f in filas] == ["ANA PEREZ", "JUAN DIAZ", "LUIS GOMEZ"]
    assert [f[10] for f in filas] == ["1-8", "2-8", "1-8"]


def test_la_nota_del_general_va_vacia(tmp_path):
    """NOTAS va vacía en el FUID que se entrega al cliente: lo pidió el operador el 2026-10-30."""
    salidas = tmp_path / "salidas"
    trabajos = [_libro(salidas, "a" * 32, "UPD3858079", ["ANA PEREZ"])]
    ruta = fuid_general(salidas, trabajos, tmp_path, destino_de=lambda t: t.filename[:-4])
    nota = leer_fuid(ruta).filas[0][15]
    assert nota == ""  # NOTAS va vacía en el FUID que se entrega (2026-10-30)


def test_sin_libros_terminados_no_escribe_nada(tmp_path):
    salidas = tmp_path / "salidas"
    trabajos = [_libro(salidas, "a" * 32, "UPD3858079", ["ANA PEREZ"], estado="failed")]
    assert fuid_general(salidas, trabajos, tmp_path) is None
    assert not (tmp_path / NOMBRE_DEL_FUID_GENERAL).exists()


def test_otras_habilidades_no_entran(tmp_path):
    caja = SimpleNamespace(
        id="c" * 32,
        filename="UPD2326299.pdf",
        state="done",
        task="segment",
        tipo=None,
        report={"indice_electronico": "x.xlsx", "fuid": "x.xlsx"},
    )
    assert fuid_general(tmp_path, [caja], tmp_path) is None
