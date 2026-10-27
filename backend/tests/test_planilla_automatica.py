"""La planilla del inventario se escribe sola, y se baja de un clic.

El operador no tiene que pedirla: al terminar un documento queda junto a los
PDF que describe. Hasta ahora sólo la escribía la ruta de resoluciones, así que
quien separaba una caja revuelta o partía un libro de folios se quedaba con los
archivos y sin el papel que dice qué son -- que en la ruta de cajas es
especialmente grave, porque sus PDF se llaman por un número de orden y sin el
listado no dicen nada por sí solos.
"""

from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("openpyxl")

from resolutions.adapters.excel_inventory import SUFFIX  # noqa: E402
from resolutions.adapters.indice_electronico import (  # noqa: E402
    NOMBRE_DEL_INDICE,
    PRIMERA_FILA,
)
from resolutions.api.settings import Settings  # noqa: E402
from resolutions.api.worker import process_document_job  # noqa: E402
from resolutions.application.task import TaskKind  # noqa: E402

CUERPO = (
    "Por medio de la presente me permito dar respuesta a la solicitud radicada "
    "en el asunto de la referencia, en los terminos que se exponen a "
    "continuacion y con base en la normatividad vigente."
)

PAGINAS = [
    ("NOTIFICACION POR AVISO", "Página 1 de 2"),
    ("", "Página 2 de 2"),
    ("FACTURA DE VENTA", "Página 1 de 1"),
]


@pytest.fixture
def caja(tmp_path):
    documento = pymupdf.open()
    for encabezado, paginacion in PAGINAS:
        page = documento.new_page()
        if encabezado:
            page.insert_textbox(
                pymupdf.Rect(56, 64, 540, 96),
                encabezado,
                fontsize=12,
                align=pymupdf.TEXT_ALIGN_CENTER,
            )
        page.insert_textbox(pymupdf.Rect(56, 110, 540, 700), CUERPO, fontsize=11)
        page.insert_textbox(pymupdf.Rect(56, 720, 540, 760), paginacion, fontsize=9)
    ruta = tmp_path / "caja.pdf"
    documento.save(ruta)
    documento.close()
    return ruta


@pytest.fixture
def procesada(caja, tmp_path):
    informe = process_document_job(
        {
            "job_id": "trabajo",
            "source": str(caja),
            "filename": "UPD2365925.pdf",
            "task": str(TaskKind.SEGMENT),
            "operator": "Eduver Andrés",
            "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
        }
    )
    return informe, tmp_path / "outputs" / "trabajo"


class TestLaPlanillaSeEscribeSola:
    """En una caja de correspondencia la planilla es el Índice Electrónico del
    cliente: sustituye a la de las otras rutas, y se escribe igual de sola."""

    def test_queda_el_indice_en_el_trabajo_y_no_la_planilla(self, procesada):
        _, salida = procesada
        assert list(salida.rglob(NOMBRE_DEL_INDICE))
        # Uno solo por caja: el archivo no recibe dos Excel discrepando.
        assert not list(salida.rglob(f"*{SUFFIX}"))

    def test_junto_a_los_pdf_que_describe(self, procesada):
        """En la carpeta de la caja, no en la raíz del trabajo: quien abre el
        disco encuentra el listado al lado de los archivos que lista."""
        _, salida = procesada
        hoja = next(iter(salida.rglob(NOMBRE_DEL_INDICE)))
        assert hoja.parent.name == "UPD2365925"
        assert list(hoja.parent.glob("*.pdf"))

    def test_el_informe_dice_como_se_llama(self, procesada):
        informe, _ = procesada
        assert informe["indice_electronico"] == NOMBRE_DEL_INDICE

    def test_y_lista_lo_que_de_verdad_salio(self, procesada):
        """Una fila por archivo, en el orden de la caja, y Observaciones vacía."""
        import openpyxl

        informe, salida = procesada
        hoja = openpyxl.load_workbook(next(iter(salida.rglob(NOMBRE_DEL_INDICE)))).active
        archivos = [item["file_name"].rsplit("/", 1)[-1] for item in informe["inventory"]["items"]]
        filas = range(PRIMERA_FILA, PRIMERA_FILA + len(archivos))
        assert [hoja[f"G{fila}"].value for fila in filas] == [None] * len(archivos)
        assert [hoja[f"D{fila}"].value for fila in filas] == list(range(1, len(archivos) + 1))
        # Y quien la procesó, como responsable.
        assert hoja[f"H{PRIMERA_FILA}"].value == "Eduver Andrés"

    def test_el_tipo_documental_es_el_nombre_del_documento(self, procesada):
        import openpyxl

        _, salida = procesada
        hoja = openpyxl.load_workbook(next(iter(salida.rglob(NOMBRE_DEL_INDICE)))).active
        assert hoja[f"A{PRIMERA_FILA}"].value == "NOTIFICACION POR AVISO"

    def test_un_fallo_del_indice_no_se_lleva_el_trabajo(self, caja, tmp_path, monkeypatch):
        """Los PDF ya están escritos cuando esto corre."""
        from resolutions.adapters import indice_electronico

        def roto(*_a, **_k):
            raise OSError("el disco dijo que no")

        monkeypatch.setattr(indice_electronico, "escribir_indice", roto)
        informe = process_document_job(
            {
                "job_id": "otro",
                "source": str(caja),
                "filename": "caja.pdf",
                "task": str(TaskKind.SEGMENT),
                "settings": Settings(output_dir=tmp_path / "outputs").as_worker_payload(),
            }
        )
        assert informe["outputs"]
        assert "el disco dijo que no" in informe["indice_electronico_error"]
        # Y la pantalla lo enseña: el error suelto en el informe no lo pintaba nadie.
        assert any("INDICE ELECTRONICO" in aviso for aviso in informe.get("notices") or [])

    def test_un_fallo_de_la_planilla_queda_en_el_informe_y_a_la_vista(self, tmp_path, monkeypatch):
        """Antes sólo quedaba en el registro del servicio: el informe no decía nada."""
        from resolutions.adapters.excel_inventory import ExcelInventory
        from resolutions.api.worker.planillas import _escribir_planilla

        def abierta(self, *_a, **_k):
            raise PermissionError(13, "Permission denied", "x__inventario.xlsx")

        monkeypatch.setattr(ExcelInventory, "write", abierta)
        informe: dict = {"groups": []}
        _escribir_planilla(informe, tmp_path, {})

        assert informe["planilla_error"]
        assert "PermissionError" not in informe["planilla_error"]
        assert any("planilla" in aviso for aviso in informe["notices"])


class TestSeBajaDeUnClic:
    def test_el_endpoint_la_encuentra_dentro_de_la_carpeta_de_la_caja(
        self, client, tmp_path, monkeypatch
    ):
        """Buscándola sólo en la raíz del trabajo contestaba 404 justo en la
        ruta que más la necesita."""
        pytest.importorskip("httpx")
        from resolutions.adapters.excel_inventory import SUFFIX as sufijo
        from resolutions.api import main

        carpeta = main.contexto.settings.output_dir / "trabajo" / "UPD2365925"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"UPD2365925{sufijo}").write_bytes(b"PK\x03\x04 planilla")

        respuesta = client.get("/api/jobs/trabajo/inventory.xlsx")
        assert respuesta.status_code == 200

    def test_sin_planilla_lo_dice_en_vez_de_reventar(self, client):
        pytest.importorskip("httpx")
        assert client.get("/api/jobs/fantasma/inventory.xlsx").status_code == 404
