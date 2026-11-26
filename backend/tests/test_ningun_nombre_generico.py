"""Ningún nombre genérico: el FORMATO DE RELACION DIARIA DE PAGOS y lo que F6 dejaba en «DOCUMENTO».

El operador, 2026-11-26, ante «01_DOCUMENTO.pdf» de UPD2995828 (MAGANGUE, SIN
NIC): «no quiero nombres genéricos como no sé, documento, anexo… sino originales
evidenciados en el mismo documento, eso sin saltar las reglas que ya tenemos,
apliquémoslo solo a este formato». Y después: «solo para los casos en los que el
bot no sepa qué nombre colocarle a un documento, simplemente le coloque el del
PDF, o que la IA lo determine, pero necesito que no sea genérico».

La hoja es la planilla del recaudador, «FORMATO DE RELACIÓN DIARIA DE PAGOS No.
…». El catálogo la leía FACTURA por su columna «VR. A PAGAR FACTURA», y F6
(``nombrar_sin_soporte``) le quitaba ese nombre de anexo y la dejaba en
DOCUMENTO, después de que la cascada de nombres ya había corrido.

Los textos son sintéticos, con los errores que la capa y Tesseract dejaron en
esas hojas; nada del PDF del cliente. La IA es un nombrador falso: nada se paga.
"""

from __future__ import annotations

import pytest

from resolutions.application.anexos_declarados import TIPOS_DE_SOPORTE
from resolutions.domain.nombre_oficial import (
    es_nombre_generico,
    nombre_de_la_ia,
    nombre_documental,
)
from resolutions.domain.titulo_impreso import (
    RELACION_DIARIA_DE_PAGOS,
    titulo_impreso,
    titulo_por_su_formato,
)

#: La capa del escáner, con lo que rompe: «DIARIA Di: PAGOS», «VR, PAGADO»,
#: «Pyme/Recaudadorj», «consignar ¡$)».
CAPA = (
    "FECHA: ,\nFORMATO DE RELACIÓN \nDIARIA Di: PAGOS No. 1234567\nPUNTO DEPAGO: \nGESTOR:\n"
    "VO.BO.TÉC. DE COBRO:\nNo. REGISTRO\n/sv fácturÍa CÓDIGO del USUARIO nombre del USÜARIO\n"
    "VR. A PAGAR \nSUMINISTRO \nFACTURA\nABONO A\nVR, PAGADO\nMES\nAPLICADO\n"
    "SARRIO OBSERVACIÓN FIRMA DEL CLII\nI Vo.Bo. Representante Legal Pyme/Recaudadorj\n"
    "[NOTA: Cualquier enmendadura anula el registro, en caso de errores repita el registro en la siguiente fila.\n"
    "Valor Recaudado ($):\nValor a consignar ¡$):"
)
#: La franja de arriba leída con Tesseract: «Df:», «PAGO5».
FRANJA = "FORMATO DE RELACIÓN\nDIARIA Df: PAGO5 No. 1234567\nO -00 7"
#: Con ruido delante del título y una letra suelta en su segundo renglón.
FRANJA_CON_RUIDO = "_NO Abi 707 FORMATO DE RELACIÓN\nl DIARIA DE PAGOS No. 1234567\nVo.Bo.TÉC. DE COBRO"
#: La OCR de casa de la hoja entera, que de la tabla no leyó nada: sólo el recuadro del título.
SOLO_EL_RECUADRO = "FORMATO DE RELACIÓN\nDIARIA DE PAGOS No. 1234567"
#: Los dos renglones del título separados por lo que el escáner lee en medio.
PARTIDO = (
    "FORMATO DE RELACIÓN\nTesal\n[\nS\nO\nDIARIA DE PAGOS No. 1234567\n"
    "NOTA: Cualquier enmendadura anula e! registro"
)
#: Sin tildes, con el espacio roto y el número en otro renglón: lo confirma su tabla.
SIN_TILDES = "FORMATODE RELACION\nDIARIA DE PAGOS No.\nFECHA:\n1234567\nVR.PAGADO\nValor Recaudado ($):"
#: El precedente, la «RELACIÓN DE PAGOS RECIBIDOS» de Electricaribe (2026-11-24).
RELACION_DE_PAGOS_RECIBIDOS = (
    "Elertocarib^ RELACIÓM DE PAGOS nECiOIDOS /.-.V siar\nResponsaKff PEDRO PEREZ PAEZ Fecha 25/10/2019\n"
    "a. Oíiciales Propios b. Oriciatcs GDEL | X TP c. Liberalizado\n2. Sopoiledcpago"
)


class TestLaRelacionDiariaDePagos:
    @pytest.mark.parametrize("texto", [CAPA, FRANJA, FRANJA_CON_RUIDO, SOLO_EL_RECUADRO, PARTIDO, SIN_TILDES])
    def test_se_llama_con_su_titulo_impreso_entero(self, texto):
        """Sin el número de la planilla: es de cada hoja, no del formato."""
        assert titulo_por_su_formato(texto) == RELACION_DIARIA_DE_PAGOS == "FORMATO DE RELACION DIARIA DE PAGOS"
        assert titulo_impreso(texto) == RELACION_DIARIA_DE_PAGOS

    @pytest.mark.parametrize(
        "texto",
        [
            RELACION_DE_PAGOS_RECIBIDOS,
            # Otro formato que empieza igual.
            "FORMATO DE RELACION\nDIARIA DE PAGOS ANULADOS No. 1234567\nVR. PAGADO\nValor Recaudado ($):",
            # Sin «DIARIA».
            "FORMATO DE RELACION DE PAGOS No. 1234567\nVR. PAGADO\nValor Recaudado ($):",
            # El título solo, sin el número de la planilla ni una marca de su tabla.
            "FORMATO DE RELACION\nDIARIA DE PAGOS\nFECHA:",
            # La prosa que lo nombra.
            "Adjunto el formato de relacion diaria de pagos del mes, con el valor recaudado.",
        ],
    )
    def test_no_se_confunde_con_otro(self, texto):
        assert titulo_por_su_formato(texto) is None
        assert titulo_impreso(texto) != RELACION_DIARIA_DE_PAGOS

    def test_el_precedente_sigue_como_estaba(self):
        from resolutions.domain.asunto_del_documento import (
            RELACION_DE_PAGOS,
            titulo_del_documento,
        )

        assert titulo_del_documento(RELACION_DE_PAGOS_RECIBIDOS) == RELACION_DE_PAGOS == "RELACION DE PAGOS RECIBIDOS"

    def test_el_mismo_camino_que_relacion_de_pagos_recibidos(self):
        """Tipo del catálogo sin frases, nombre del operador que la IA no discute y fuera de la lista de la IA."""
        from resolutions.domain.asunto_del_documento import (
            NOMBRES_DEL_OPERADOR,
            formulario_que_abre,
            titulo_del_documento,
        )
        from resolutions.domain.catalogo import POR_NOMBRE
        from resolutions.domain.nombre_oficial import (
            CON_RE_EN_EL_NOMBRE,
            SOLO_POR_SU_FORMATO,
            estandarizar,
            instrucciones_para_nombrar,
            nombre_oficial,
        )

        assert POR_NOMBRE[RELACION_DIARIA_DE_PAGOS].frases == ()
        assert RELACION_DIARIA_DE_PAGOS in NOMBRES_DEL_OPERADOR and RELACION_DIARIA_DE_PAGOS in SOLO_POR_SU_FORMATO
        assert f"- {RELACION_DIARIA_DE_PAGOS}" not in instrucciones_para_nombrar().splitlines()
        assert nombre_oficial(RELACION_DIARIA_DE_PAGOS) == estandarizar(RELACION_DIARIA_DE_PAGOS) == RELACION_DIARIA_DE_PAGOS
        # Sólo nombra: no es un título que decida cortes, no abre documento ni pide RE por su tipo.
        assert titulo_del_documento(CAPA) == "DOCUMENTO" and formulario_que_abre(CAPA) is None
        assert RELACION_DIARIA_DE_PAGOS not in CON_RE_EN_EL_NOMBRE

    def test_el_archivo_y_su_fila_del_indice(self):
        from resolutions.api.worker.planillas import _nombre_de_la_fila
        from resolutions.domain.naming import output_filename
        from resolutions.domain.resolution_code import ResolutionCode

        nombre = output_filename(
            ResolutionCode(value="01", raw="01"),
            None,
            prefix=None,
            kind=RELACION_DIARIA_DE_PAGOS,
            mayusculas=True,
            sin_radicado=True,
        )
        assert nombre == "01_FORMATO-DE-RELACION-DIARIA-DE-PAGOS.pdf"
        fila = {"type": RELACION_DIARIA_DE_PAGOS, "file_name": nombre, "page_numbers": [1]}
        informe = {"agrupar": "tramite", "piezas": [{"pages": [1], "titulo": "DOCUMENTO"}]}
        assert _nombre_de_la_fila(fila, informe) == RELACION_DIARIA_DE_PAGOS

    def test_la_auditoria_avisa_si_sale_con_otro_nombre(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        mal = auditar_los_radicados([ArchivoEntregado("01_DOCUMENTO.pdf", (1,))], {1: CAPA})
        assert any(f"su formato es el de {RELACION_DIARIA_DE_PAGOS}" in duda for duda in mal.dudas)
        bien = auditar_los_radicados([ArchivoEntregado("01_FORMATO-DE-RELACION-DIARIA-DE-PAGOS.pdf", (1,))], {1: CAPA})
        assert not any("su formato es el de" in duda for duda in bien.dudas)


class TestNingunNombreGenerico:
    @pytest.mark.parametrize(
        "nombre", ["DOCUMENTO", "Documento", "No sé", "NO SE", "N/A", "Anexo", "ANEXOS", "Desconocido", "OTRO", "Sin título", "", None]
    )
    def test_lo_que_no_nombra_nada(self, nombre):
        assert es_nombre_generico(nombre)

    @pytest.mark.parametrize(
        "nombre", [RELACION_DIARIA_DE_PAGOS, "DERECHO DE PETICION", "ANEXO A RECLAMO", "SOLICITUD", "UPD2995828 PAGINAS 1-6"]
    )
    def test_lo_que_si_nombra(self, nombre):
        assert not es_nombre_generico(nombre)

    def test_la_ia_nunca_nombra_con_uno_generico(self):
        for respuesta in ("DOCUMENTO", "No sé.", "N/A", "Anexo", "Otro", "Desconocido"):
            assert nombre_de_la_ia(respuesta) is None
        # Lo que sí nombra sigue igual.
        assert nombre_de_la_ia("Derecho de petición") == "DERECHO DE PETICION"
        assert nombre_de_la_ia("«Formato de nuevos suministros»\n") == "FORMATO DE NUEVOS SUMINISTROS"

    def test_su_respuesta_pasa_por_el_nombre_oficial(self):
        assert nombre_documental("RECLAMACION") == "RECLAMO"
        assert nombre_documental("PETICION") == "DERECHO DE PETICION"
        assert nombre_documental("PLANILLA DE RECAUDO") == "PLANILLA DE RECAUDO"
        assert nombre_documental("DOCUMENTO") is None
        # Al que F6 le quitó el nombre de un anexo, nunca vuelve a dárselo.
        assert nombre_documental("FACTURA", vetados=TIPOS_DE_SOPORTE) is None


# -- de punta a punta: el worker de la caja con un PDF sintético ----------------------

pymupdf = pytest.importorskip("pymupdf")

#: Las celdas de la cabecera de su tabla, cada una en sus renglones, como las
#: deja la capa: «VR. A PAGAR / FACTURA» es lo que el catálogo leía como FACTURA.
CELDAS = (
    "No.", "No. REGISTRO\n/ SV FACTURA", "CÓDIGO DEL\nUSUARIO", "NOMBRE DEL\nUSUARIO", "DIRECCIÓN DEL\nSUMINISTRO",
    "VR. A PAGAR\nFACTURA", "VR. PAGADO", "ABONO A\nDEUDA", "MES\nAPLICADO", "BARRIO", "OBSERVACIÓN", "FIRMA DEL\nCLIENTE",
)
CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud radicada en el asunto de la referencia, "
    "en los terminos que se exponen a continuacion y con base en la normatividad vigente."
)


def _planilla(documento, numero: int | None) -> None:
    """Una planilla apaisada; sin ``numero``, sin título ni pie: nada impreso que la nombre."""
    hoja = documento.new_page(width=792, height=612)
    arriba = 220
    if numero is not None:
        arriba = 120
        hoja.insert_textbox(pymupdf.Rect(40, 30, 200, 50), "FECHA: 10-04-2022", fontsize=9)
        hoja.insert_textbox(
            pymupdf.Rect(250, 25, 560, 75),
            f"FORMATO DE RELACIÓN\nDIARIA DE PAGOS No. {numero}",
            fontsize=14,
            align=pymupdf.TEXT_ALIGN_CENTER,
        )
        hoja.insert_textbox(
            pymupdf.Rect(40, 55, 240, 110), "PUNTO DE PAGO: Banco\nGESTOR: Pedro Perez\nVo.Bo. TEC. DE COBRO:", fontsize=9
        )
        hoja.insert_textbox(
            pymupdf.Rect(40, 520, 760, 600),
            "Vo.Bo. Representante Legal Pyme/Recaudador\nValor Recaudado ($): $55.000\nValor a consignar ($):\n"
            "NOTA: Cualquier enmendadura anula el registro, en caso de errores repita el registro en la siguiente fila.",
            fontsize=8,
        )
    for puesto, celda in enumerate(CELDAS):
        hoja.insert_textbox(pymupdf.Rect(40 + puesto * 60, arriba, 98 + puesto * 60, arriba + 40), celda, fontsize=6)
    hoja.insert_textbox(
        pymupdf.Rect(40, arriba + 45, 760, arriba + 80), "1  123  7654321  JUAN LOPEZ  CALLE 1  $ 55.000  $ 55.000", fontsize=8
    )


def _notificacion(documento) -> None:
    hoja = documento.new_page()
    hoja.insert_textbox(pymupdf.Rect(56, 64, 540, 96), "NOTIFICACION POR AVISO", fontsize=12, align=pymupdf.TEXT_ALIGN_CENTER)
    hoja.insert_textbox(pymupdf.Rect(56, 110, 540, 700), CUERPO, fontsize=11)


def _procesar(tmp_path, nombre: str, *hojas):
    from resolutions.api.settings import Settings
    from resolutions.api.worker import process_document_job
    from resolutions.application.task import TaskKind

    documento = pymupdf.open()
    for hoja in hojas:
        hoja(documento)
    ruta = tmp_path / "caja.pdf"
    documento.save(ruta)
    documento.close()
    return process_document_job(
        {
            "job_id": "trabajo",
            "source": str(ruta),
            "filename": nombre,
            "task": str(TaskKind.SEGMENT),
            # Sin ninguna llave: ni el lector de pago ni el oráculo de bordes.
            "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
        }
    )


@pytest.fixture
def nombrador(monkeypatch):
    """El nombrador de la IA, falso: contesta lo que se le diga y cuenta las preguntas."""
    from resolutions.api.worker.taller import Taller

    class Falso:
        respuesta = ""
        preguntas: list[str] = []

        def resumir(self, texto, imagen=None):
            self.preguntas.append(texto)
            return self.respuesta

    falso = Falso()
    falso.preguntas = []
    monkeypatch.setattr(Taller, "nombrador", lambda self: falso)
    return falso


def _sin_titulo(informe) -> list[int]:
    from resolutions.api.worker.correspondencia import SIN_TITULO

    return [entrada["page"] for entrada in informe["review_queue"] if entrada["reason"] == SIN_TITULO]


class TestLaRutaQueDejabaDocumento:
    """F6 ya no deja «DOCUMENTO»: el título impreso, la IA si se eligió, o su caja y sus páginas."""

    def test_la_planilla_sale_con_su_titulo_impreso(self, tmp_path):
        """Era «01_DOCUMENTO.pdf»: FACTURA por el catálogo, DOCUMENTO por F6. Sin IA."""
        informe = _procesar(
            tmp_path, "UPD9999999.pdf", lambda d: _planilla(d, 1234567), lambda d: _planilla(d, 1234566)
        )
        assert informe["outputs"] == ["UPD9999999/01_FORMATO-DE-RELACION-DIARIA-DE-PAGOS.pdf"]
        assert [grupo["type"] for grupo in informe["groups"]] == [RELACION_DIARIA_DE_PAGOS]

    def test_sin_titulo_ni_ia_su_caja_y_sus_paginas_a_revision(self, tmp_path):
        """La regla de último recurso que ya existía, y lo que ya tenía nombre no cambia."""
        informe = _procesar(tmp_path, "UPD9999998.pdf", lambda d: _planilla(d, None), _notificacion)
        assert informe["outputs"] == [
            "UPD9999998/01_UPD9999998-PAGINA-1.pdf",
            "UPD9999998/02_NOTIFICACION-POR-AVISO.pdf",
        ]
        assert _sin_titulo(informe) == [1]

    def test_sin_titulo_y_con_ia_la_ia_lo_nombra(self, tmp_path, nombrador):
        """Una sola pregunta, sólo por el documento sin nombre: la notificación sigue como estaba."""
        nombrador.respuesta = "Planilla de recaudo"
        informe = _procesar(tmp_path, "UPD9999998.pdf", lambda d: _planilla(d, None), _notificacion)
        assert informe["outputs"] == [
            "UPD9999998/01_PLANILLA-DE-RECAUDO.pdf",
            "UPD9999998/02_NOTIFICACION-POR-AVISO.pdf",
        ]
        assert len(nombrador.preguntas) == 1
        assert _sin_titulo(informe) == []

    @pytest.mark.parametrize("respuesta", ["No sé", "DOCUMENTO", "FACTURA"])
    def test_una_respuesta_generica_o_de_anexo_se_descarta(self, tmp_path, nombrador, respuesta):
        nombrador.respuesta = respuesta
        informe = _procesar(tmp_path, "UPD9999998.pdf", lambda d: _planilla(d, None), _notificacion)
        assert informe["outputs"][0] == "UPD9999998/01_UPD9999998-PAGINA-1.pdf"
        assert len(nombrador.preguntas) == 1
        assert _sin_titulo(informe) == [1]
