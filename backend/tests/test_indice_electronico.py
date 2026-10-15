"""El Índice Electrónico: el inventario de toda caja de correspondencia.

Es el formato del cliente -- «00.INDICE ELECTRONICO.xlsx» -- y sustituye a la
planilla en esa ruta. Estas pruebas cubren las tres cosas que se acordaron:
de dónde sale cada columna, que el archivo conserve la plantilla y que la
pantalla lo encuentre para bajarlo.
"""

from __future__ import annotations

from datetime import date

import pytest

openpyxl = pytest.importorskip("openpyxl")

from resolutions.adapters import indice_electronico  # noqa: E402
from resolutions.adapters.indice_electronico import (  # noqa: E402
    FilaDelIndice,
    escribir_indice,
)
from resolutions.api import main  # noqa: E402
from resolutions.api.routers import salidas  # noqa: E402
from resolutions.api.routers.trabajos import _territorial  # noqa: E402
from resolutions.api.worker.planillas import _escribir_indice  # noqa: E402


def _filas(hoja) -> list[tuple]:
    """Las filas de documentos, de la 8 hasta antes del cierre."""
    filas = []
    for fila in range(indice_electronico.PRIMERA_FILA, hoja.max_row + 1):
        if str(hoja[f"A{fila}"].value or "").startswith(indice_electronico.CIERRE):
            break
        filas.append(tuple(hoja[f"{c}{fila}"].value for c in indice_electronico.COLUMNAS))
    return filas


def _report(items):
    return {"document": "UPD2320043.pdf", "nic": "1004014", "inventory": {"items": items}}


ITEMS = [
    {
        "file_name": "UPD2320043/01_SOLICITUD-DE-SERVICIO.pdf",
        "type": "Solicitud de servicio electrico en baja tension",
        "fecha": "2022-06-14",
        "page_count": 8,
    },
    {
        "file_name": "UPD2320043/02_DOCUMENTO.pdf",
        "type": None,
        "fecha": None,
        "page_count": 2,
    },
]


class TestColumnas:
    def test_cada_columna_sale_de_donde_se_acordo(self, tmp_path):
        payload = {"operator": "María Pérez", "territorial": "CESAR"}
        report = _report(ITEMS)

        _escribir_indice(report, tmp_path, payload)

        hoja = openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        hoy = date.today().strftime("%d/%m/%Y")
        assert _filas(hoja) == [
            # El tipo en mayúsculas, la del documento (la creación), la de hoy
            # (la incorporación por el bot), el orden, las páginas, el formato,
            # las observaciones vacías y quien lo procesó.
            (
                # Título directo y fecha del documento, en mayúsculas.
                "SOLICITUD DE SERVICIO ELECTRICO EN BAJA TENSION - 14/06/2022",
                "14/06/2022",
                hoy,
                1,
                8,
                "pdf",
                None,
                "María Pérez",
            ),
            # Sin tipo es DOCUMENTO, como el archivo; sin fecha, S.F.
            ("DOCUMENTO", "S.F.", hoy, 2, 2, "pdf", None, "María Pérez"),
        ]
        assert report["indice_electronico"] == indice_electronico.NOMBRE_DEL_INDICE

    def test_el_encabezado_lleva_la_territorial_y_deja_el_nic_vacio(self, tmp_path):
        """El NIC no se extrae: aunque el informe lo traiga, la celda queda
        vacía para llenarla a mano."""
        _escribir_indice(_report(ITEMS), tmp_path, {"territorial": "CESAR"})

        hoja = openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        assert hoja["B2"].value == "HISTORIALES DE CLIENTES"
        assert hoja["B4"].value is None
        assert hoja["B5"].value == "CESAR"

    def test_sin_territorial_ni_responsable_queda_la_raya_y_la_celda_vacia(self, tmp_path):
        _escribir_indice(_report(ITEMS[:1]), tmp_path, {})

        hoja = openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        assert hoja["B5"].value == indice_electronico.SIN_DATO
        assert hoja["H8"].value is None


class TestPlantilla:
    def test_el_cierre_baja_debajo_del_ultimo_documento(self, tmp_path):
        filas = [
            FilaDelIndice(
                nombre="RECLAMO",
                fecha_creacion=None,
                fecha_incorporacion=date(2026, 10, 13),
                orden=orden,
                paginas=1,
            )
            for orden in range(1, 6)
        ]

        ruta = escribir_indice(tmp_path, filas, nic="1004014", territorial="CESAR")

        hoja = openpyxl.load_workbook(ruta).active
        cierre = indice_electronico.PRIMERA_FILA + len(filas)
        assert hoja[f"A{cierre}"].value.startswith(indice_electronico.CIERRE)
        assert f"A{cierre}:H{cierre}" in {str(rango) for rango in hoja.merged_cells.ranges}
        # El formato de la primera fila llega a todas: mismos bordes y letra.
        assert hoja[f"A{cierre - 1}"].border.left.style == hoja["A8"].border.left.style
        assert hoja[f"A{cierre - 1}"].font.name == hoja["A8"].font.name


class TestTerritorial:
    @pytest.mark.parametrize(
        ("escrita", "queda"),
        [("  cesar ", "CESAR"), ("la  guajira", "LA GUAJIRA"), ("", None), (None, None)],
    )
    def test_se_recorta_y_va_en_mayusculas(self, escrita, queda):
        assert _territorial(escrita) == queda


class TestDescarga:
    def test_el_nombre_que_busca_la_api_es_el_que_escribe_el_adaptador(self):
        assert salidas.INDICE == indice_electronico.NOMBRE_DEL_INDICE

    def test_la_pantalla_baja_el_indice_de_una_caja(self, client, tmp_path):
        caja = main.contexto.settings.output_dir / "job-caja" / "UPD2320043"
        _escribir_indice(_report(ITEMS), caja, {"territorial": "CESAR"})

        respuesta = client.get("/api/jobs/job-caja/inventory.xlsx")

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == salidas.XLSX_MEDIA
        listado = client.get("/api/jobs/job-caja/archivos").json()
        assert listado["inventario"] == indice_electronico.NOMBRE_DEL_INDICE


class TestEntregaEnCarpeta:
    """Una corrida sobre carpeta copia el índice junto a los PDF de la caja, y
    no escribe encima la planilla de las otras rutas."""

    def test_el_indice_viaja_con_los_pdf_y_no_cuenta_como_entrega(self, tmp_path):
        from resolutions.adapters.excel_inventory import SUFFIX
        from resolutions.api.folders import FolderRun, FolderRunner
        from resolutions.api.jobs import JobRegistry
        from resolutions.api.settings import Settings

        async def _no_corre(job) -> None:
            pass

        ajustes = Settings(output_dir=tmp_path / "outputs")
        registro = JobRegistry()
        runner = FolderRunner(registro, ajustes, run_job=_no_corre)
        origen = tmp_path / "origen"
        run = FolderRun(id="corrida", source=origen, destination=tmp_path / "destino")
        job = registro.create("UPD2320043.pdf", origen / "UPD2320043.pdf")
        report = _report(ITEMS[:1])
        caja = ajustes.output_dir / job.id / "UPD2320043"
        caja.mkdir(parents=True)
        (caja / "01_SOLICITUD-DE-SERVICIO.pdf").write_bytes(b"%PDF-1.4")
        _escribir_indice(report, caja, {"territorial": "CESAR"})
        job.report = report

        runner._entregar(run, job, origen / "UPD2320043.pdf")

        entregados = {ruta.name for ruta in run.destination.rglob("*") if ruta.is_file()}
        assert entregados == {"01_SOLICITUD-DE-SERVICIO.pdf", indice_electronico.NOMBRE_DEL_INDICE}
        assert not any(nombre.endswith(SUFFIX) for nombre in entregados)
        # Entregado cuenta documentos, y el índice no es uno.
        assert run.delivered == 1


class TestObservaciones:
    def test_quedan_vacias_aunque_el_bot_sepa_cosas_de_la_fila(self, tmp_path):
        """Son las observaciones del negocio, no un rastro técnico: ni el
        archivo, ni el detalle del trámite, ni la verificación de anexos."""
        item = {**ITEMS[0], "page_numbers": [1, 2, 3, 4]}
        report = {
            **_report([item]),
            "anexos_declarados": [
                {"pagina": 3, "observacion": "Anexos declarados: 3 (pág. 3); hallados: 2; faltan: Cédula"},
                # La de otro documento no se cuela en esta fila.
                {"pagina": 9, "observacion": "Anexos declarados: 1 (pág. 9); hallados: 1"},
            ],
        }

        _escribir_indice(report, tmp_path, {})

        hoja = openpyxl.load_workbook(tmp_path / indice_electronico.NOMBRE_DEL_INDICE).active
        assert hoja["G8"].value is None
