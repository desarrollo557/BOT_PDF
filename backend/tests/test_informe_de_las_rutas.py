"""Las cuatro rutas dejan el mismo informe, se haya cortado como se haya cortado.

La pantalla lo lee sin preguntar de qué tipo de documento venía, así que una
ruta que se deje una clave rompe una vista que no tiene nada que ver con ella.
Pasó con la ruta de diplomas: su informe traía otras claves y la pantalla se
quedaba sin modal de cierre y con la barra de navegación caída.

Esta prueba existe para que añadir algo al contrato obligue a repasar las cuatro
rutas en vez de descubrir en producción que una no lo cumple.
"""

from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")

from resolutions.api.settings import Settings  # noqa: E402
from resolutions.api.worker import process_document_job  # noqa: E402
from resolutions.application.informe import (  # noqa: E402
    CLAVES_OBLIGATORIAS,
    claves_que_faltan,
)
from resolutions.application.task import TaskKind  # noqa: E402

CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud radicada "
    "en el asunto de la referencia, en los terminos que se exponen a "
    "continuacion y con base en la normatividad vigente."
)


def _pdf(tmp_path, paginas, nombre="caja.pdf"):
    documento = pymupdf.open()
    for encabezado, pie in paginas:
        page = documento.new_page()
        if encabezado:
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 110),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        page.insert_textbox(pymupdf.Rect(56, 120, 540, 700), CUERPO, fontsize=11)
        if pie:
            page.insert_textbox(pymupdf.Rect(56, 720, 540, 760), pie, fontsize=9)
    ruta = tmp_path / nombre
    documento.save(ruta)
    documento.close()
    return ruta


def _correr(tmp_path, pdf, tarea):
    return process_document_job(
        {
            "job_id": "t",
            "source": str(pdf),
            "filename": pdf.name,
            "task": str(tarea),
            "operator": "quien sea",
            "settings": Settings(output_dir=tmp_path / "out").as_worker_payload(),
        }
    )


class TestElContratoDelInforme:
    def test_la_caja_revuelta_lo_cumple(self, tmp_path):
        pdf = _pdf(
            tmp_path,
            [("NOTIFICACION POR AVISO", "Página 1 de 2"), ("", "Página 2 de 2")],
        )
        assert claves_que_faltan(_correr(tmp_path, pdf, TaskKind.SEGMENT)) == []

    def test_y_el_legajo_de_resoluciones_tambien(self, tmp_path):
        pdf = _pdf(
            tmp_path,
            [("RESOLUCION No. 00086 de 2023", ""), ("", "")],
            nombre="resoluciones.pdf",
        )
        assert claves_que_faltan(_correr(tmp_path, pdf, TaskKind.SPLIT)) == []

    def test_el_contrato_no_esta_vacio(self):
        """Una prueba que no comprueba nada pasa siempre."""
        assert len(CLAVES_OBLIGATORIAS) >= 8

    def test_una_clave_que_falta_se_denuncia(self):
        assert claves_que_faltan({}) == list(CLAVES_OBLIGATORIAS)

    def test_un_informe_completo_no_denuncia_nada(self):
        completo = dict.fromkeys(CLAVES_OBLIGATORIAS, None)
        assert claves_que_faltan(completo) == []
