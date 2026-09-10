"""Que el inventario se pueda bajar y diga a dónde va la entrega.

Dos fallos que el operador vio en pantalla y que tienen la misma forma: el
sistema sabía algo y no lo decía.

El primero dejaba el botón «Inventario» girando para siempre. Levantar el FUID
de un documento puede terminar sin escribir nada -- un escaneo sin capa de
texto no produce ni una fila -- y eso no era ni un error ni un éxito: el estado
quedaba en "ni listo ni fallido" y la pantalla se quedaba en «levantando…» sin
nada más que decir.

El segundo dejaba vacía la columna «Carpeta de destino» de la planilla. La
escribe el worker, que no conoce la corrida de carpeta, así que no tenía forma
de saber dónde acabaría lo que estaba escribiendo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")


class TestElInventarioQueNoSePudoLevantar:
    """Terminar sin excepción no es lo mismo que haber escrito la planilla.

    Se prueba sobre `_levantar_fuid`, que es donde vive la decisión, y no a
    través del endpoint: éste lanza la lectura en una tarea aparte -- son
    minutos en un libro de cuatrocientos folios -- y esperarla desde una
    prueba sólo mediría el reloj.
    """

    @staticmethod
    async def _levantar(main, job_id, monkeypatch):
        # En hilos y no en procesos: el servicio usa un proceso por documento
        # -- partir un PDF de 400 páginas es trabajo de CPU -- y un doble
        # definido dentro de una prueba no se puede enviar a otro proceso.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(1) as pool:
            monkeypatch.setattr(main.app.state, "pool", pool)
            await main._levantar_fuid(job_id)
        return await main.job_fuid_status(job_id)

    @pytest.mark.asyncio
    async def test_si_no_quedo_planilla_el_estado_lo_dice(self, client, monkeypatch):
        from resolutions.api import main

        job = main.registry.create("libro.pdf", Path("libro.pdf"))
        main.registry.mark_done(job, {"document": "libro.pdf"})
        # El worker termina bien y no escribe FUID: es lo que le pasa a un
        # libro del que no se pudo leer ni una fila.
        monkeypatch.setattr(main, "process_document_job", lambda payload: {})

        estado = await self._levantar(main, job.id, monkeypatch)
        assert estado["ready"] is False
        assert estado["error"], "el estado tiene que decir por qué no hay planilla"
        assert "ni una fila" in str(estado["error"])

    @pytest.mark.asyncio
    async def test_y_deja_de_estar_trabajando(self, client, monkeypatch):
        """Es lo que la pantalla mira para dejar de esperar."""
        from resolutions.api import main

        job = main.registry.create("libro.pdf", Path("libro.pdf"))
        main.registry.mark_done(job, {"document": "libro.pdf"})
        monkeypatch.setattr(main, "process_document_job", lambda payload: {})

        estado = await self._levantar(main, job.id, monkeypatch)
        assert estado["working"] is False

    @pytest.mark.asyncio
    async def test_cuando_si_queda_planilla_no_hay_error(self, client, monkeypatch):
        from resolutions.api import main
        from resolutions.api.worker import FUID_SUFFIX

        job = main.registry.create("libro.pdf", Path("libro.pdf"))
        main.registry.mark_done(job, {"document": "libro.pdf"})

        def escribe(payload):
            carpeta = main.settings.output_dir / payload["job_id"]
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / f"libro{FUID_SUFFIX}").write_bytes(b"PK")
            return {}

        monkeypatch.setattr(main, "process_document_job", escribe)

        estado = await self._levantar(main, job.id, monkeypatch)
        assert estado["ready"] is True
        assert estado["error"] is None


class TestLaCarpetaDeDestinoEnLaPlanilla:
    def test_el_trabajo_de_una_carpeta_sabe_adonde_entrega(self, tmp_path):
        """Se calcula al crearlo, porque quien lo procesa no conoce la corrida."""
        from resolutions.api.folders import FolderRun, FolderRunner
        from resolutions.api.jobs import JobRegistry

        registro = JobRegistry()
        run = FolderRun(
            id="corrida", source=tmp_path / "origen", destination=tmp_path / "destino"
        )
        trabajo = registro.create(
            filename="caja/UPD2365925.pdf",
            source=tmp_path / "origen" / "caja" / "UPD2365925.pdf",
            destination=str(
                FolderRunner._output_dir(
                    run, tmp_path / "origen" / "caja" / "UPD2365925.pdf"
                )
            ),
        )
        assert trabajo.destination is not None
        assert "destino" in trabajo.destination

    def test_una_subida_suelta_no_tiene_destino_que_declarar(self):
        from resolutions.api.jobs import JobRegistry

        trabajo = JobRegistry().create("suelto.pdf", Path("suelto.pdf"))
        assert trabajo.destination is None

    def test_la_planilla_escribe_el_destino_que_le_dan(self, tmp_path):
        pytest.importorskip("openpyxl")
        import openpyxl

        from resolutions.adapters.excel_inventory import ExcelInventory

        informe = {
            "document": "UPD2365925.pdf",
            "page_count": 1,
            "inventory": {
                "source_document": "UPD2365925.pdf",
                "source_pages": 1,
                "items": [
                    {
                        "code": "01",
                        "title": "página 1",
                        "type": "FACTURA",
                        "fecha": "2022-02-18",
                        "file_name": "UPD2365925/01_FACTURA.pdf",
                        "page_count": 1,
                        "first_page": 1,
                        "last_page": 1,
                        "page_numbers": [1],
                    }
                ],
            },
        }
        destino = r"C:\Destino\108C000094\5825181"
        hoja = ExcelInventory().write(informe, tmp_path, delivered_to=destino)

        libro = openpyxl.load_workbook(hoja)
        texto = "\n".join(
            str(celda.value)
            for fila in libro["Resoluciones"].iter_rows()
            for celda in fila
            if celda.value is not None
        )
        assert destino in texto
        # Y de paso, que el tipo y la fecha viajan con él.
        assert "FACTURA" in texto
        assert "2022-02-18" in texto
