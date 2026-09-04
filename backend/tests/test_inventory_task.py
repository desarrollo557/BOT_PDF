"""La acción que se le pide al sistema: partir el documento o sólo inventariarlo.

Estas pruebas cubren el contrato de la API y la decisión de tipo de documento.
El proceso completo -- leer un libro de cuatrocientas páginas y escribir su
FUID -- se comprueba contra el servicio en marcha, no aquí: lo que se fija aquí
es que una acción desconocida no se adivine, que la elegida viaje con el
trabajo, y que el reconocimiento del documento se haga por lo que está impreso
y nunca por el nombre del archivo.
"""

from __future__ import annotations

import pytest

from resolutions.application.task import TaskKind
from resolutions.domain.doctype import DocumentType, classify_pages

pytest.importorskip("httpx")


# -----------------------------------------------------------------------------
#  La acción
# -----------------------------------------------------------------------------


class TestAccion:
    def test_sin_indicar_nada_se_parte_el_documento(self):
        """El valor por omisión no cambia lo que el sistema ya hacía."""
        assert TaskKind.parse(None) is TaskKind.SPLIT
        assert TaskKind.parse("") is TaskKind.SPLIT

    def test_se_reconocen_las_dos_acciones(self):
        assert TaskKind.parse("split") is TaskKind.SPLIT
        assert TaskKind.parse("inventory") is TaskKind.INVENTORY

    def test_no_distingue_mayusculas_ni_espacios(self):
        assert TaskKind.parse("  INVENTORY  ") is TaskKind.INVENTORY

    def test_una_accion_desconocida_no_se_adivina(self):
        with pytest.raises(ValueError, match="acción desconocida"):
            TaskKind.parse("inventar")

    def test_solo_partir_escribe_documentos(self):
        assert TaskKind.SPLIT.writes_documents is True
        assert TaskKind.INVENTORY.writes_documents is False


class TestApi:
    def test_una_accion_desconocida_se_rechaza_sin_escribir_nada(self, client):
        response = client.post(
            "/api/jobs?task=inventar",
            files={"file": ("libro.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert response.status_code == 422
        assert "acción desconocida" in response.json()["detail"]

    def test_el_trabajo_recuerda_lo_que_se_le_pidio(self, client):
        response = client.post(
            "/api/jobs?task=inventory",
            files={"file": ("libro.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert response.status_code == 202
        assert response.json()["task"] == "inventory"

    def test_sin_accion_el_trabajo_se_parte_como_siempre(self, client):
        response = client.post(
            "/api/jobs",
            files={"file": ("acta.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert response.json()["task"] == "split"

    def test_un_documento_partido_no_tiene_fuid(self, client):
        """Y el 404 dice por qué, en vez de dejar al operador adivinando."""
        response = client.get("/api/jobs/no-existe/fuid.xlsx")
        assert response.status_code == 404
        assert "Solo inventariar" in response.json()["detail"]

    def test_la_salud_anuncia_las_dos_capacidades_nuevas(self, client):
        features = client.get("/api/health").json()["features"]
        assert "inventory-task" in features
        assert "job-fuid" in features


# -----------------------------------------------------------------------------
#  Qué documento es
# -----------------------------------------------------------------------------
#  Los textos son de páginas reales de los libros digitalizados, con el daño de
#  OCR que traen. Uno inventado no habría probado nada.
# -----------------------------------------------------------------------------

PAGINA_DE_DIPLOMA = """
UNIVERSIDAD DE CARTAGENA
Fundada en 1827
LIBRO DE REGISTRO DE DIPLOMAS DE POSTGRADOS
LA REPUBLICA DE COLOMBIA, Ministerio de Educación Nacional
Folio 336BIS
ALIX JOSEFINA MARIN RODRIGUEZ
Nombres y apellidos del graduando
Identificado con C.C. No. 22793650
Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD
Fecha de graduación: 29/03/2012
FUNCIONARIOS QUE FIRMAN EL DIPLOMA
Registrado a folio No. 336BIS
libro No. 8
Para constancia es firmado el presente registro de diploma
"""

PAGINA_DE_RESOLUCION = """
UNIVERSIDAD DE CARTAGENA
RESOLUCION No. 00072 de 2023
POR MEDIO DE LA CUAL SE HACE UN NOMBRAMIENTO PROVISIONAL EN UN CARGO
EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA
en uso de sus facultades legales y estatutarias
CONSIDERANDO
RESUELVE
COMUNIQUESE Y CUMPLASE
"""

PAGINA_DE_MATRICULA = """
UNIVERSIDAD DE CARTAGENA
FACULTAD DE CIENCIAS ECONOMICAS
REGISTRO DEL ALUMNO
Nombre del alumno:
Lugar de nacimiento
Bachiller del Colegio
Cédula o tarjeta No.
REGISTRO DE ESTUDIOS
ASIGNATURAS
Promedio Semestral
"""


class TestReconocimiento:
    def test_reconoce_un_libro_de_diplomas(self):
        verdict = classify_pages([(1, PAGINA_DE_DIPLOMA)])
        assert verdict.document_type is DocumentType.DIPLOMA
        assert verdict.is_identified

    def test_reconoce_una_resolucion(self):
        verdict = classify_pages([(1, PAGINA_DE_RESOLUCION)])
        assert verdict.document_type is DocumentType.RESOLUCION

    def test_reconoce_un_registro_de_alumno(self):
        verdict = classify_pages([(1, PAGINA_DE_MATRICULA)])
        assert verdict.document_type is DocumentType.MATRICULA

    def test_una_pagina_en_blanco_no_se_reconoce(self):
        """El folio en blanco tachado con una X existe, y no es ningún tipo."""
        verdict = classify_pages([(1, "")])
        assert verdict.document_type is DocumentType.DESCONOCIDO
        assert verdict.confidence == 0.0

    def test_no_se_deja_engañar_por_una_resolucion_citada(self):
        """Los diplomas modernos citan la resolución que autorizó el título.

        Un reconocimiento que se quedara con la primera palabra que le suena
        archivaría el libro entero como resoluciones.
        """
        texto = PAGINA_DE_DIPLOMA + (
            "\nResolución que autoriza el otorgamiento del título: 00867 "
            "del 13 de Marzo de 2012\n"
        )
        assert classify_pages([(1, texto)]).document_type is DocumentType.DIPLOMA

    def test_aguanta_el_daño_del_ocr_en_las_leyendas(self):
        dañado = PAGINA_DE_DIPLOMA.replace(
            "Nombres y apellidos del graduando", "Nombres y apellidos de! graduando"
        ).replace("LIBRO DE REGISTRO DE DIPLOMAS", "LiBRO DE REGiSTRO DE DiPLOMAS")
        assert classify_pages([(1, dañado)]).document_type is DocumentType.DIPLOMA

    def test_la_decision_se_puede_auditar(self):
        """Cada marca que disparó queda registrada con la página en que lo hizo."""
        verdict = classify_pages([(1, PAGINA_DE_DIPLOMA)])
        assert verdict.evidence
        assert all(item.page_number == 1 for item in verdict.evidence)
        assert any("GRADUANDO" in item.marker for item in verdict.evidence)

    def test_el_nombre_del_archivo_no_decide_nada(self):
        """Un libro llamado "resoluciones.pdf" sigue siendo un libro de diplomas.

        El reconocimiento no recibe el nombre del archivo, y esta prueba existe
        para que nadie se lo pase en el futuro creyendo que ayuda.
        """
        verdict = classify_pages([(1, PAGINA_DE_DIPLOMA)])
        assert verdict.document_type is DocumentType.DIPLOMA

    def test_promedia_por_pagina_y_no_suma(self):
        """Leer doce páginas y leer una tienen que dar el mismo veredicto."""
        una = classify_pages([(1, PAGINA_DE_DIPLOMA)])
        muchas = classify_pages([(n, PAGINA_DE_DIPLOMA) for n in range(1, 13)])
        assert una.document_type is muchas.document_type
        assert una.scores == pytest.approx(muchas.scores)


class TestLasDosCosas:
    """La tercera acción: partir e inventariar sobre una sola lectura."""

    def test_se_reconoce(self):
        assert TaskKind.parse("both") is TaskKind.BOTH

    def test_escribe_documentos_y_tambien_el_inventario(self):
        assert TaskKind.BOTH.writes_documents is True
        assert TaskKind.BOTH.writes_inventory is True

    def test_partir_no_inventaria_por_su_cuenta(self):
        assert TaskKind.SPLIT.writes_inventory is False

    def test_inventariar_no_escribe_ningun_documento(self):
        assert TaskKind.INVENTORY.writes_documents is False

    def test_la_api_la_acepta_y_la_recuerda(self, client):
        response = client.post(
            "/api/jobs?task=both",
            files={"file": ("libro.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        assert response.status_code == 202
        assert response.json()["task"] == "both"

    def test_las_tres_salen_en_el_mensaje_de_error(self, client):
        response = client.post(
            "/api/jobs?task=ninguna",
            files={"file": ("libro.pdf", b"%PDF-1.4 ...", "application/pdf")},
        )
        detalle = response.json()["detail"]
        assert "split" in detalle and "inventory" in detalle and "both" in detalle


# -----------------------------------------------------------------------------
#  La forma del informe
# -----------------------------------------------------------------------------
#  La pantalla es una sola para los tres tipos de documento, y hasta ahora sólo
#  conocía las claves que produce la división de resoluciones. Un libro de
#  folios devolvía otras y la pantalla moría al terminarlo: sin modal de cierre
#  y con la barra de navegación caída detrás. El contrato es que todo informe
#  trae las mismas claves, aunque algunas vengan vacías porque ese documento
#  genuinamente no las tiene.
# -----------------------------------------------------------------------------

from resolutions.application.inventory_document import InventoryOutcome  # noqa: E402
from resolutions.domain.doctype import TypeVerdict  # noqa: E402
from resolutions.domain.grouping import GroupingResult, PageGroup  # noqa: E402
from resolutions.domain.resolution_code import ResolutionCode  # noqa: E402
from resolutions.domain.validation import Issue, Severity  # noqa: E402

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


def _resultado() -> InventoryOutcome:
    return InventoryOutcome(
        document="REGISTRO DE DIPLOMAS N°08 2013.pdf",
        page_count=3,
        verdict=TypeVerdict(document_type=DocumentType.DIPLOMA, confidence=1.0),
        provenance={"text_layer": 2, "ocr_full_page": 1},
        grouping=GroupingResult(
            groups=[
                PageGroup(
                    code=ResolutionCode(value="728", raw="728"),
                    page_numbers=[1],
                    title="ANGELICA MARIA CUELLO SALCEDO",
                )
            ]
        ),
        issues=[
            Issue(
                field="folio",
                reason="el folio del encabezado (81) no coincide con el del pie (810)",
                severity=Severity.ERROR,
                page_number=2,
            ),
            Issue(field="folio", reason="faltan 3 folios entre el 812 y el 816"),
        ],
    )


class TestFormaDelInforme:
    def test_trae_todas_las_claves_que_la_pantalla_lee(self):
        informe = _resultado().as_dict()
        faltan = [clave for clave in CLAVES_DE_LA_PANTALLA if clave not in informe]
        assert faltan == []

    def test_las_unidades_documentales_son_las_del_libro(self):
        informe = _resultado().as_dict()
        assert informe["groups"] == [
            {"code": "728", "title": "ANGELICA MARIA CUELLO SALCEDO", "pages": [1], "size": 1}
        ]

    def test_la_cola_de_revision_agrupa_los_hallazgos_por_pagina(self):
        informe = _resultado().as_dict()
        assert informe["review_queue"] == [
            {
                "page": 2,
                "reason": "el folio del encabezado (81) no coincide con el del pie (810)",
            }
        ]

    def test_un_hallazgo_del_documento_entero_no_se_atribuye_a_ninguna_pagina(self):
        # "faltan 3 folios entre el 812 y el 816" es del libro, no de una hoja.
        paginas = [item["page"] for item in _resultado().as_dict()["review_queue"]]
        assert paginas == [2]

    def test_la_procedencia_es_la_que_midio_el_lector(self):
        stats = _resultado().as_dict()["stats"]
        assert stats["by_provenance"] == {"text_layer": 2, "ocr_full_page": 1}
        # Lo escalado es todo lo que no respondió la capa de texto.
        assert stats["escalated"] == 1

    def test_un_inventario_no_escribe_ningun_pdf(self):
        assert _resultado().as_dict()["outputs"] == []
