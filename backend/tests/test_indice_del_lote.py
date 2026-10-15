"""El Índice Electrónico de varias cajas: un libro, una hoja por PDF procesado.

Lo pidió el operador: una caja de correspondencia sólo se inventaría con la
plantilla del cliente -- también al exportar el Archivo --, y un lote deja
además su inventario general, con una hoja por caja.
"""

from __future__ import annotations

import io
from datetime import date

import pytest

openpyxl = pytest.importorskip("openpyxl")

from resolutions.adapters import indice_electronico  # noqa: E402
from resolutions.adapters.indice_electronico import (  # noqa: E402
    FilaDelIndice,
    escribir_indice,
    escribir_indices_por_hoja,
    leer_indice,
)
from resolutions.api import main  # noqa: E402
from resolutions.api.indices import carpeta_del_lote, libro_de_indices  # noqa: E402
from resolutions.api.janitor import _guarda_un_producto  # noqa: E402

HOY = date(2026, 10, 13)


def _filas(n: int, prefijo: str) -> list[FilaDelIndice]:
    return [
        FilaDelIndice(
            nombre=f"{prefijo} {orden}",
            fecha_creacion=date(2022, 1, orden) if orden % 2 else None,
            fecha_incorporacion=HOY,
            orden=orden,
            paginas=orden * 2,
            responsable="SIAR",
        )
        for orden in range(1, n + 1)
    ]


def _caja(output_dir, job_id: str, caja: str, filas: list[FilaDelIndice]) -> None:
    escribir_indice(
        output_dir / job_id / caja, filas, territorial="CESAR", nombre_del_expediente=caja
    )


def _filas_de(hoja) -> list[str]:
    nombres = []
    for fila in range(indice_electronico.PRIMERA_FILA, hoja.max_row + 1):
        valor = str(hoja[f"A{fila}"].value or "")
        if valor.startswith(indice_electronico.CIERRE):
            break
        nombres.append(valor)
    return nombres


def _registrar(job_id: str, caja: str, origen: dict | None = None) -> None:
    report = {
        "document": f"{caja}.pdf",
        "inventory": {
            "items": [
                {
                    "code": "01",
                    "file_name": f"{caja}/01_DERECHO-DE-PETICION.pdf",
                    "page_count": 2,
                    "first_page": 1,
                    "last_page": 2,
                }
            ]
        },
    }
    if origen:
        report["origen"] = origen
    main.contexto.ledger.record(job_id, report, operator="SIAR")


class TestLectura:
    def test_lo_que_se_escribe_se_lee_igual(self, tmp_path):
        filas = _filas(3, "DERECHO DE PETICION")
        escribir_indice(tmp_path, filas, territorial="CESAR", nombre_del_expediente="UPD1")

        leido = leer_indice(tmp_path / indice_electronico.NOMBRE_DEL_INDICE)

        assert leido.filas == filas
        assert leido.territorial == "CESAR"
        assert leido.nombre_del_expediente == "UPD1"
        assert leido.nic is None


class TestUnaHojaPorCaja:
    def test_cada_caja_en_su_hoja_con_su_propio_orden(self, tmp_path):
        _caja(tmp_path, "a", "UPD2320047", _filas(4, "UNO"))
        _caja(tmp_path, "b", "UPD2321099", _filas(2, "DOS"))

        ruta = libro_de_indices(tmp_path, ["b", "a"], tmp_path / "lote")

        libro = openpyxl.load_workbook(ruta)
        assert libro.sheetnames == ["UPD2320047", "UPD2321099"]
        primera, segunda = libro["UPD2320047"], libro["UPD2321099"]
        assert _filas_de(primera) == ["UNO 1", "UNO 2", "UNO 3", "UNO 4"]
        assert _filas_de(segunda) == ["DOS 1", "DOS 2"]
        assert [segunda[f"D{f}"].value for f in (8, 9)] == [1, 2]
        # La plantilla entera en cada hoja: su encabezado y su cierre.
        assert segunda["B2"].value == "HISTORIALES DE CLIENTES"
        assert segunda[indice_electronico.CELDA_NOMBRE_DEL_EXPEDIENTE].value == "UPD2321099"
        assert str(segunda["A10"].value).startswith(indice_electronico.CIERRE)

    def test_la_misma_caja_dos_veces_no_choca(self, tmp_path):
        _caja(tmp_path, "a", "UPD1", _filas(1, "X"))
        _caja(tmp_path, "b", "UPD1", _filas(1, "Y"))

        libro = openpyxl.load_workbook(libro_de_indices(tmp_path, ["a", "b"], tmp_path / "l"))

        assert libro.sheetnames == ["UPD1", "UPD1 (2)"]

    def test_sin_cajas_de_correspondencia_no_hay_libro(self, tmp_path):
        (tmp_path / "a").mkdir()
        assert libro_de_indices(tmp_path, ["a"], tmp_path / "l") is None

    def test_un_nombre_de_hoja_imposible_se_limpia(self, tmp_path):
        ruta = escribir_indices_por_hoja(
            tmp_path, [("CAJA: 1/2 [x]" + "Z" * 40, leer_indice_de(tmp_path))]
        )
        nombre = openpyxl.load_workbook(ruta).sheetnames[0]
        assert len(nombre) <= indice_electronico.LARGO_DE_HOJA
        assert not set(nombre) & set("[]:*?/\\")


def leer_indice_de(tmp_path):
    escribir_indice(tmp_path / "suelta", _filas(1, "A"), territorial=None)
    return leer_indice(tmp_path / "suelta" / indice_electronico.NOMBRE_DEL_INDICE)


class TestExportarElArchivo:
    def test_las_cajas_salen_en_la_plantilla_y_no_en_la_planilla(self, client):
        salidas = main.contexto.settings.output_dir
        _caja(salidas, "job-a", "UPD2320047", _filas(2, "A"))
        _caja(salidas, "job-b", "UPD2321099", _filas(1, "B"))
        _registrar("job-a", "UPD2320047")
        _registrar("job-b", "UPD2321099")

        respuesta = client.get("/api/inventory.xlsx")

        assert respuesta.status_code == 200
        assert indice_electronico.NOMBRE_DEL_INDICE in respuesta.headers["content-disposition"]
        libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
        assert libro.sheetnames == ["UPD2320047", "UPD2321099"]

    def test_el_listado_dice_cual_es_una_caja(self, client):
        salidas = main.contexto.settings.output_dir
        _caja(salidas, "job-a", "UPD2320047", _filas(1, "A"))
        _registrar("job-a", "UPD2320047")
        _registrar("job-r", "RESOLUCIONES")

        documentos = {d["job_id"]: d for d in client.get("/api/documents").json()["documents"]}

        assert documentos["job-a"]["indice"] is True
        assert documentos["job-r"]["indice"] is False


class TestInventarioDelLote:
    LOTE = "a" * 32

    def test_el_lote_baja_su_libro_aunque_sea_de_antes(self, client):
        salidas = main.contexto.settings.output_dir
        origen = {"id": self.LOTE, "nombre": "Lote de 2", "tipo": "lote"}
        _caja(salidas, "job-a", "UPD2320047", _filas(2, "A"))
        _caja(salidas, "job-b", "UPD2321099", _filas(1, "B"))
        _registrar("job-a", "UPD2320047", origen)
        _registrar("job-b", "UPD2321099", origen)

        respuesta = client.get(f"/api/origenes/{self.LOTE}/inventario.xlsx")

        assert respuesta.status_code == 200
        libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
        assert libro.sheetnames == ["UPD2320047", "UPD2321099"]
        assert (carpeta_del_lote(salidas, self.LOTE) / indice_electronico.NOMBRE_DEL_INDICE).is_file()

    def test_el_barrendero_no_se_lleva_el_indice_del_lote(self, tmp_path):
        _caja(tmp_path, "x", "UPD1", _filas(1, "A"))
        libro_de_indices(tmp_path, ["x"], carpeta_del_lote(tmp_path, self.LOTE))

        assert _guarda_un_producto(carpeta_del_lote(tmp_path, self.LOTE))


class TestAlTerminarUnaCaja:
    def test_el_lote_rehace_su_libro_con_las_cajas_terminadas(self, client, tmp_path):
        import asyncio

        from resolutions.api.ejecucion import _indice_del_lote

        ctx = main.contexto
        lote = ctx.registry.create_batch("Lote de prueba")
        hechos = []
        for job_id_caja in ("UPD2320047", "UPD2321099", "UPD2555083"):
            job = ctx.registry.create(
                filename=f"{job_id_caja}.pdf", source=tmp_path / "x.pdf", batch_id=lote.id
            )
            _caja(ctx.settings.output_dir, job.id, job_id_caja, _filas(1, job_id_caja))
            hechos.append(job)
        # La tercera sigue en curso: el libro dice sólo lo terminado.
        for job in hechos[:2]:
            ctx.registry.mark_done(job, {"indice_electronico": "00.INDICE ELECTRONICO.xlsx"})

        asyncio.run(_indice_del_lote(ctx, lote.id))

        ruta = carpeta_del_lote(ctx.settings.output_dir, lote.id) / indice_electronico.NOMBRE_DEL_INDICE
        assert openpyxl.load_workbook(ruta).sheetnames == ["UPD2320047", "UPD2321099"]


class TestInventarioDeProcesos:
    """El general del bot: una fila por PDF procesado, termine bien o falle."""

    def test_el_lote_deja_los_dos_generales(self, client, tmp_path):
        import asyncio

        from resolutions.adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS
        from resolutions.api.ejecucion import _indice_del_lote

        ctx = main.contexto
        lote = ctx.registry.create_batch("Caja 108C000033")
        bien = ctx.registry.create(
            filename="UPD2326299.pdf", source=tmp_path / "a.pdf", batch_id=lote.id,
            task="segment", agrupar="tramite", operator="SIAR",
        )
        _caja(ctx.settings.output_dir, bien.id, "UPD2326299", _filas(1, "A"))
        ctx.registry.mark_running(bien)
        ctx.registry.mark_done(
            bien,
            {"indice_electronico": "00.INDICE ELECTRONICO.xlsx", "agrupar": "tramite",
             "page_count": 5, "groups": [{}], "review_queue": []},
        )
        mal = ctx.registry.create(
            filename="UPD2326300.pdf", source=tmp_path / "b.pdf", batch_id=lote.id, task="segment"
        )
        ctx.registry.mark_failed(mal, "El PDF está dañado")

        asyncio.run(_indice_del_lote(ctx, lote.id))

        carpeta = carpeta_del_lote(ctx.settings.output_dir, lote.id)
        assert (carpeta / indice_electronico.NOMBRE_DEL_INDICE).is_file()
        libro = openpyxl.load_workbook(carpeta / NOMBRE_DEL_INVENTARIO_DE_PROCESOS)
        assert libro.sheetnames == ["Resumen", "Procesos"]
        hoja = libro["Procesos"]
        filas = [
            [c.value for c in fila]
            for fila in hoja.iter_rows()
            if fila[1].value and str(fila[1].value).endswith(".pdf")
        ]
        assert [(f[1], f[2], f[4], f[5], f[8]) for f in filas] == [
            ("UPD2326299.pdf", "Caja de correspondencia", "Por trámite", 5, "Listo"),
            ("UPD2326300.pdf", "Caja de correspondencia", "Por documento", 0, "Falló"),
        ]
        assert filas[1][-1] == "El PDF está dañado"

        respuesta = client.get(f"/api/origenes/{lote.id}/procesos.xlsx")
        assert respuesta.status_code == 200

    def test_sin_procesos_terminados_no_hay_inventario(self, client):
        respuesta = client.get(f"/api/origenes/{'b' * 32}/procesos.xlsx")
        assert respuesta.status_code == 404
