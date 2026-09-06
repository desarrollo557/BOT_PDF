"""La cuarta acción: separar una caja revuelta en los documentos que la forman.

Las tres que ya existían suponen un número impreso -- una resolución trae el
suyo, un folio de diplomas el suyo. Una caja de correspondencia no trae ninguno:
el número de reclamación que llevan todas sus hojas identifica el expediente
entero, no la factura ni el recurso que hay dentro, y leerlo como continuidad
suelda la caja en un solo documento.

Lo que se fija aquí es que la acción viaje desde la pantalla hasta el worker por
el mismo camino que las otras tres, que la caja salga como PDF que alguien pueda
abrir, y que lo que la estructura no pudo decidir termine en la cola de revisión
en vez de convertirse en un corte inventado.
"""

from __future__ import annotations

import pytest

from resolutions.api.settings import Settings
from resolutions.api.worker import _boundary_oracle, process_document_job
from resolutions.application.task import TaskKind

pytest.importorskip("httpx")

#: Lo que la pantalla lee de cualquier informe sin preguntar de qué tipo es.
CLAVES_DE_LA_PANTALLA = (
    "document",
    "page_count",
    "groups",
    "quarantine",
    "repairs",
    "review_queue",
    "outputs",
    "stats",
)


class TestLaAccion:
    def test_se_reconoce(self):
        assert TaskKind.parse("segment") is TaskKind.SEGMENT

    def test_no_distingue_mayusculas_ni_espacios(self):
        assert TaskKind.parse("  SEGMENT  ") is TaskKind.SEGMENT

    def test_escribe_documentos(self):
        assert TaskKind.SEGMENT.writes_documents is True

    def test_no_inventaria_por_su_cuenta(self):
        """El FUID de una caja sin clasificar no tendría qué poner en sus columnas."""
        assert TaskKind.SEGMENT.writes_inventory is False

    def test_tiene_nombre_para_la_pantalla(self):
        assert TaskKind.SEGMENT.label


class TestApi:
    def test_la_api_la_acepta_y_la_recuerda(self, client):
        respuesta = client.post(
            "/api/jobs?task=segment",
            files={"file": ("caja.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert respuesta.status_code == 202
        assert respuesta.json()["task"] == "segment"

    def test_sale_en_el_mensaje_de_error_de_una_accion_desconocida(self, client):
        respuesta = client.post(
            "/api/jobs?task=ninguna",
            files={"file": ("caja.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert "segment" in respuesta.json()["detail"]


class TestElOraculo:
    """Quién juzga las costuras que la estructura no pudo decidir."""

    def test_sin_llaves_ninguna_duda_llega_a_un_modelo(self):
        from resolutions.adapters.boundary_prompt import NullBoundaryOracle

        assert isinstance(_boundary_oracle({}), NullBoundaryOracle)

    def test_con_la_llave_de_gemini_responde_gemini(self):
        from resolutions.adapters.gemini_boundary import GeminiBoundaryOracle

        oraculo = _boundary_oracle({"gemini_api_key": "xyz"})
        assert isinstance(oraculo, GeminiBoundaryOracle)

    def test_claude_manda_cuando_estan_las_dos(self):
        """Es el que puede cachear el prompt, que en una caja se paga por página."""
        from resolutions.adapters.claude_boundary import ClaudeBoundaryOracle

        oraculo = _boundary_oracle({"anthropic_api_key": "abc", "gemini_api_key": "xyz"})
        assert isinstance(oraculo, ClaudeBoundaryOracle)

    def test_con_la_llave_de_mistral_responde_mistral(self):
        from resolutions.adapters.mistral_boundary import MistralBoundaryOracle

        oraculo = _boundary_oracle({"mistral_api_key": "mmm"})
        assert isinstance(oraculo, MistralBoundaryOracle)

    def test_gemini_manda_sobre_mistral(self):
        """Gemini tiene capa gratuita que aguanta una caja; Mistral no."""
        from resolutions.adapters.gemini_boundary import GeminiBoundaryOracle

        oraculo = _boundary_oracle({"gemini_api_key": "xyz", "mistral_api_key": "mmm"})
        assert isinstance(oraculo, GeminiBoundaryOracle)

    def test_claude_manda_sobre_las_tres(self):
        from resolutions.adapters.claude_boundary import ClaudeBoundaryOracle

        oraculo = _boundary_oracle(
            {"anthropic_api_key": "abc", "gemini_api_key": "xyz", "mistral_api_key": "mmm"}
        )
        assert isinstance(oraculo, ClaudeBoundaryOracle)

    def test_la_llave_de_gemini_viaja_al_worker(self):
        payload = Settings(gemini_api_key="xyz").as_worker_payload()
        assert payload["gemini_api_key"] == "xyz"

    def test_la_llave_de_mistral_viaja_al_worker(self):
        payload = Settings(mistral_api_key="mmm").as_worker_payload()
        assert payload["mistral_api_key"] == "mmm"


pymupdf = pytest.importorskip("pymupdf")

CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud radicada "
    "en el asunto de la referencia, en los terminos que se exponen a "
    "continuacion y con base en la normatividad vigente."
)

#: Una caja con las dos mitades del problema: dos hojas que el papel encadena
#: solo, y dos que no declaran nada y que sin modelo nadie puede juntar.
PAGINAS = [
    ("RESPUESTA A RECLAMACION", "Página 1 de 2"),
    ("", "Página 2 de 2"),
    ("FACTURA DE VENTA", ""),
    ("", ""),
]


@pytest.fixture
def caja(tmp_path):
    document = pymupdf.open()
    for encabezado, paginacion in PAGINAS:
        page = document.new_page()
        if encabezado:
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 96),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        page.insert_textbox(pymupdf.Rect(56, 110, 540, 700), CUERPO, fontsize=11)
        if paginacion:
            page.insert_textbox(pymupdf.Rect(56, 720, 540, 760), paginacion, fontsize=9)
    path = tmp_path / "caja.pdf"
    document.save(path)
    document.close()
    return path


@pytest.fixture
def informe(caja, tmp_path):
    """La caja procesada por el mismo worker que atiende a la pantalla."""
    return process_document_job(
        {
            "job_id": "trabajo",
            "source": str(caja),
            "filename": "caja de correspondencia.pdf",
            "task": str(TaskKind.SEGMENT),
            "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
        }
    )


class TestElTrabajo:
    def test_la_caja_sale_como_un_pdf_por_documento(self, informe, tmp_path):
        assert informe["outputs"] == [
            "DOCUMENTO_01.pdf",
            "DOCUMENTO_02.pdf",
            "DOCUMENTO_03.pdf",
        ]
        escritos = sorted(
            path.name for path in (tmp_path / "outputs" / "trabajo").glob("*.pdf")
        )
        assert escritos == informe["outputs"]

    def test_el_informe_trae_las_claves_que_la_pantalla_lee(self, informe):
        faltan = [clave for clave in CLAVES_DE_LA_PANTALLA if clave not in informe]
        assert faltan == []

    def test_dice_de_que_documento_se_trata_con_el_nombre_del_operador(self, informe):
        assert informe["document"] == "caja de correspondencia.pdf"
        assert informe["page_count"] == 4
        assert informe["task"] == "segment"

    def test_los_grupos_son_los_documentos_de_la_caja(self, informe):
        assert [grupo["pages"] for grupo in informe["groups"]] == [[1, 2], [3], [4]]
        assert [grupo["code"] for grupo in informe["groups"]] == ["01", "02", "03"]

    def test_nada_va_a_cuarentena(self, informe):
        assert informe["quarantine"] == []

    def test_la_costura_sin_evidencia_va_a_la_cola_de_revision(self, informe):
        """Sin modelo, la duda se corta y se avisa. Cortar de más se ve y se
        arregla; soldar dos documentos esconde el segundo donde nadie lo busca."""
        assert [item["page"] for item in informe["review_queue"]] == [4]

    def test_las_cuentas_dicen_cuanto_resolvio_la_estructura_gratis(self, informe):
        stats = informe["stats"]
        assert stats["documents"] == 3
        assert stats["seams"] == 3
        assert stats["undecided"] == 1
        assert stats["model_decided"] == 0
        # Las tres reparten las costuras sin que sobre ni falte ninguna.
        assert stats["settled_free"] == 2
        assert stats["settled_free"] + stats["model_decided"] + stats["undecided"] == 3


class TestPararUnaCaja:
    def test_una_caja_cancelada_se_abandona_sin_escribir_nada(self, caja, tmp_path):
        """La orden llega por el mismo diccionario compartido que las otras
        acciones, así que el botón de la pantalla ya la mueve sin tocar nada."""
        from resolutions.application.control import Cancelled

        destino = tmp_path / "outputs"
        with pytest.raises(Cancelled):
            process_document_job(
                {
                    "job_id": "trabajo",
                    "source": str(caja),
                    "filename": "caja.pdf",
                    "task": str(TaskKind.SEGMENT),
                    "controls": {"trabajo": "cancelled"},
                    "settings": Settings(output_dir=destino).as_worker_payload(),
                }
            )
        assert not (destino / "trabajo").exists()
