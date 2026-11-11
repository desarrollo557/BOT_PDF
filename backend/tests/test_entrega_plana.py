"""La caja de correspondencia se entrega directo en la carpeta de su NIC.

Lo pidió el operador el 2026-10-21: «DESTINO\\210847» con los archivos de su UPD
dentro, no «DESTINO\\210847\\UPD2998726\\…». Y el 2026-10-22, al ver dos UPD en
un mismo NIC: «no hay necesidad de que crees otro índice electrónico, o que en
el nombre le coloques primero la UPD; la idea es que por NIC estén sus archivos
en la raíz, con la estructura número-título». Así: los PDF de todos sus UPD
numerados seguidos y un solo índice. Las demás habilidades siguen con su
carpeta por PDF.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.indice_electronico import (
    FilaDelIndice,
    escribir_indice,
    leer_indice,
)
from resolutions.api import constancia as constancias
from resolutions.api.folders import REEMPLAZADOS_DIR, FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings

INDICE = "00.INDICE ELECTRONICO.xlsx"


@pytest.fixture
def ajustes(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
        pausa_tras_fallos=0.01,
    )
    settings.ensure_directories()
    return settings


def _caja(origen: Path, caja: str, *upds: str) -> None:
    (origen / caja).mkdir(parents=True, exist_ok=True)
    for upd in upds:
        (origen / caja / f"{upd}.pdf").write_bytes(b"%PDF-1.4 " + upd.encode())


def _indice(carpeta: Path, upd: str, *nombres: str) -> Path:
    """Un Índice Electrónico de verdad, como el que deja el worker."""
    filas = [
        FilaDelIndice(
            nombre=nombre,
            fecha_creacion=date(2024, 2, 8),
            fecha_incorporacion=date(2026, 10, 22),
            orden=orden,
            paginas=3,
        )
        for orden, nombre in enumerate(nombres, start=1)
    ]
    return escribir_indice(carpeta, filas, nic="1000265", territorial="MAGANGUE", nombre_del_expediente=upd)


def _motor(ajustes, registro, hechos):
    async def run_job(job):
        hechos.append(job.filename)
        # Como el worker: dentro de su carpeta de trabajo, en una subcarpeta.
        upd = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / upd
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 " + job.filename.encode())
        _indice(salida, upd, f"RECLAMO DE {upd}")
        registro.mark_done(
            job,
            {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE},
        )

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _correr(motor, origen, destino, **opciones):
    async def ir():
        run = motor.start(str(origen), str(destino), **opciones)
        for _ in range(800):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(ir())


def _nombres(carpeta: Path) -> list[str]:
    return sorted(p.name for p in carpeta.iterdir() if p.name != REEMPLAZADOS_DIR)


def _motor_de(ajustes, registro, hechos, documentos: dict[str, list[str]]):
    """Como `_motor`, con los documentos que da cada PDF de origen (por su nombre sin «.pdf»)."""

    async def run_job(job):
        hechos.append(job.filename)
        origen = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / origen
        salida.mkdir(parents=True, exist_ok=True)
        suyos = documentos[origen]
        for orden, documento in enumerate(suyos, start=1):
            (salida / f"{orden:02d}_{documento}.pdf").write_bytes(
                b"%PDF-1.4 " + f"{origen} {documento} (procesado)".encode()
            )
        _indice(salida, origen, *(f"{documento} DE {origen}" for documento in suyos))
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE})

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _caja_mal_numerada(tmp_path: Path, documentos: dict[str, list[str]]) -> Path:
    """La caja de Afinia como salió el 2026-11-10 -- «01_NIC 5940155-11_01_DOCUMENTO.pdf» --, con sus constancias."""
    _caja(tmp_path / "origen", "5940155", *documentos)
    caja = tmp_path / "destino" / "5940155"
    caja.mkdir(parents=True)
    numero = 0
    for origen, suyos in documentos.items():
        archivos = []
        for orden, documento in enumerate(suyos, start=1):
            numero += 1
            pdf = caja / f"{numero:02d}_{origen}_{orden:02d}_{documento}.pdf"
            pdf.write_bytes(b"%PDF-1.4 " + f"{origen} {documento}".encode())
            archivos.append(pdf)
        tamano, modificado = constancias.huella_del_origen(tmp_path / "origen" / "5940155" / f"{origen}.pdf")
        constancias.escribir(
            caja / f".bot-entrega-{origen}.json",
            constancias.Constancia(
                origen=f"5940155/{origen}.pdf",
                tamano=tamano,
                modificado_ns=modificado,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=constancias.archivos_de(caja, archivos),
                habilidad="Caja de correspondencia",
            ),
        )
    return caja


def _huerfanos(caja: Path) -> list[str]:
    """Los PDF de la caja que ninguna constancia nombra: lo que el cliente recibe sin que el bot lo sepa."""
    nombrados = {
        str(archivo.get("ruta"))
        for ruta in caja.glob(".bot-entrega-*.json")
        for archivo in constancias.leer(ruta).archivos
    }
    return [n for n in _nombres(caja) if n.endswith(".pdf") and n not in nombrados]


class TestLaEntregaPlana:
    def test_un_nic_con_dos_upd_numerado_seguido_y_un_solo_indice(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        _caja(tmp_path / "origen", "210847", "UPD3")
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert run.state is RunState.DONE and run.processed == 3
        caja = tmp_path / "destino" / "1000265"
        assert _nombres(caja) == [
            ".bot-entrega-UPD1.json",
            ".bot-entrega-UPD2.json",
            INDICE,
            "01_RECLAMO.pdf",
            "02_RECLAMO.pdf",
        ]
        # Por el orden de sus UPD, cada uno con lo suyo.
        assert (caja / "01_RECLAMO.pdf").read_bytes().endswith(b"UPD1.pdf")
        assert (caja / "02_RECLAMO.pdf").read_bytes().endswith(b"UPD2.pdf")
        # Un solo índice, con las filas de los dos en ese mismo orden.
        indice = leer_indice(caja / INDICE)
        assert [(f.orden, f.nombre) for f in indice.filas] == [(1, "RECLAMO DE UPD1"), (2, "RECLAMO DE UPD2")]
        # «Nombre del Expediente» = el NIC (el operador, 2026-11-04); nunca el
        # UPD (2026-10-22).
        assert indice.nombre_del_expediente == "1000265"
        assert indice.nic == "1000265"
        assert _nombres(tmp_path / "destino" / "210847") == [".bot-entrega-UPD3.json", INDICE, "01_RECLAMO.pdf"]

    def test_un_origen_que_no_se_llama_upd_tampoco_deja_su_nombre_delante(self, ajustes, tmp_path):
        """Afinia (2026-11-10): los PDF de origen se llamaban «NIC 5940155-11», «-13» y «-15», y salía
        «01_NIC 5940155-11_01_DOCUMENTO.pdf». Sólo se quitaba el prefijo si era «UPD…»."""
        _caja(tmp_path / "origen", "5940155", "NIC 5940155-11", "NIC 5940155-13", "NIC 5940155-15")
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert run.state is RunState.DONE and run.processed == 3
        caja = tmp_path / "destino" / "5940155"
        pdfs = [n for n in _nombres(caja) if n.endswith(".pdf")]
        assert pdfs == ["01_RECLAMO.pdf", "02_RECLAMO.pdf", "03_RECLAMO.pdf"]
        assert (caja / "01_RECLAMO.pdf").read_bytes().endswith(b"NIC 5940155-11.pdf")
        assert (caja / "03_RECLAMO.pdf").read_bytes().endswith(b"NIC 5940155-15.pdf")

    def test_el_indice_del_nic_va_por_fecha_y_los_pdf_conservan_su_numero(self, ajustes, tmp_path):
        """Lo dictó el operador el 2026-11-04: lo antiguo primero, sólo en el índice."""
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        fechas = {"UPD1": date(2024, 3, 1), "UPD2": date(2024, 1, 15)}
        registro = JobRegistry()

        async def run_job(job):
            upd = Path(job.filename).stem
            salida = ajustes.output_dir / job.id / upd
            salida.mkdir(parents=True, exist_ok=True)
            (salida / "01_RECLAMO.pdf").write_bytes(b"%PDF-1.4 " + job.filename.encode())
            fila = FilaDelIndice(f"RECLAMO DE {upd}", fechas[upd], date(2026, 11, 4), 1, 3)
            escribir_indice(salida, [fila], nic="1000265", territorial="MAGANGUE", nombre_del_expediente="1000265")
            registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE})

        motor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
        _correr(motor, tmp_path / "origen", tmp_path / "destino", task="segment")

        caja = tmp_path / "destino" / "1000265"
        # Los PDF, por el orden de sus UPD: no se renumeran por fecha.
        assert (caja / "01_RECLAMO.pdf").read_bytes().endswith(b"UPD1.pdf")
        assert (caja / "02_RECLAMO.pdf").read_bytes().endswith(b"UPD2.pdf")
        # El índice, por fecha: el de UPD2 (enero) antes que el de UPD1 (marzo).
        indice = leer_indice(caja / INDICE)
        assert [(f.orden, f.nombre) for f in indice.filas] == [(1, "RECLAMO DE UPD2"), (2, "RECLAMO DE UPD1")]
        assert indice.nombre_del_expediente == indice.nic == "1000265"

    def test_los_pdf_del_nic_van_por_fecha_como_su_indice(self, ajustes, tmp_path):
        """Lo dictó el operador el 2026-11-11 (Afinia): «como esté en el Excel, también estará en el
        orden de archivos y numeración». El PDF «NN_» es la fila con «Orden Documento» NN, también
        cruzando los UPD del NIC. La prueba de arriba es la entrega de antes, sin la marca."""
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        documentos = {
            "UPD1": [("RECLAMO", date(2024, 2, 1)), ("RESPUESTA", date(2024, 3, 1)), ("GUIA", None)],
            "UPD2": [("PETICION", date(2024, 1, 15)), ("NOTIFICACION", date(2024, 2, 20))],
        }
        registro = JobRegistry()

        async def run_job(job):
            upd = Path(job.filename).stem
            salida = ajustes.output_dir / job.id / upd
            salida.mkdir(parents=True, exist_ok=True)
            filas = []
            # Como el worker: cada UPD, numerado ya por la fecha de sus documentos.
            for orden, (documento, fecha) in enumerate(documentos[upd], start=1):
                (salida / f"{orden:02d}_{documento}.pdf").write_bytes(b"%PDF-1.4 " + f"{upd} {documento}".encode())
                filas.append(FilaDelIndice(f"{documento} DE {upd}", fecha, date(2026, 11, 11), orden, 1))
            escribir_indice(salida, filas, nic="1000265", territorial="MAGANGUE", nombre_del_expediente="1000265")
            registro.mark_done(
                job,
                {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE, "numerado_por_fecha": True},
            )

        motor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
        _correr(motor, tmp_path / "origen", tmp_path / "destino", task="segment")

        caja = tmp_path / "destino" / "1000265"
        esperado = [
            ("01_PETICION.pdf", b"UPD2 PETICION"),
            ("02_RECLAMO.pdf", b"UPD1 RECLAMO"),
            ("03_NOTIFICACION.pdf", b"UPD2 NOTIFICACION"),
            ("04_RESPUESTA.pdf", b"UPD1 RESPUESTA"),
            # Sin fecha, al final, como en el índice.
            ("05_GUIA.pdf", b"UPD1 GUIA"),
        ]
        assert [n for n in _nombres(caja) if n.endswith(".pdf")] == [nombre for nombre, _ in esperado]
        for nombre, contenido in esperado:
            assert (caja / nombre).read_bytes().endswith(contenido)
        indice = leer_indice(caja / INDICE)
        assert [(f.orden, f.nombre) for f in indice.filas] == [
            (1, "PETICION DE UPD2"),
            (2, "RECLAMO DE UPD1"),
            (3, "NOTIFICACION DE UPD2"),
            (4, "RESPUESTA DE UPD1"),
            (5, "GUIA DE UPD1"),
        ]
        # Relanzarla no cambia nada: el orden de la carpeta es estable.
        otra =_correr(motor, tmp_path / "origen", tmp_path / "destino", task="segment")
        assert otra.ya_entregados == 2
        for nombre, contenido in esperado:
            assert (caja / nombre).read_bytes().endswith(contenido)

    def test_relanzarla_no_repite_nada(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        registro = JobRegistry()
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="segment")
        hechos: list[str] = []
        otra = _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and otra.ya_entregados == 2
        assert _nombres(tmp_path / "destino" / "1000265")[-2:] == ["01_RECLAMO.pdf", "02_RECLAMO.pdf"]


class TestUnaEntregaAnteriorConOtroNombre:
    """El operador, 2026-11-04: «la idea es no reprocesar nada» de MAGANGUE.

    Se entregó el 2026-10-28 en «MAGANGUE PROCESADO», antes de la regla de
    «<carpeta> - PROCESADO». Relanzada para las cajas que faltaban, el bot abría
    «MAGANGUE PROCESADO\\MAGANGUE - PROCESADO», vacía, y lo rehacía todo.
    """

    def test_se_sigue_en_ella_y_solo_se_procesa_lo_que_falta(self, ajustes, tmp_path):
        from resolutions.api.folders import destino_de_la_corrida

        origen, entregada = tmp_path / "MAGANGUE", tmp_path / "MAGANGUE PROCESADO"
        _caja(origen, "1000265", "UPD1", "UPD2")
        _caja(origen, "210847", "UPD3")
        registro = JobRegistry()
        # La entrega de antes, directa en «MAGANGUE PROCESADO».
        _correr(_motor(ajustes, registro, []), origen, entregada, task="segment")
        assert (entregada / INDICE).is_file()
        # Las cajas que quedaron sin procesar.
        _caja(origen, "7720382", "UPD9")

        destino = destino_de_la_corrida(str(origen), str(entregada))
        assert destino == str(entregada)
        hechos: list[str] = []
        run = _correr(_motor(ajustes, registro, hechos), origen, destino, task="segment")

        assert [Path(hecho).name for hecho in hechos] == ["UPD9.pdf"] and run.ya_entregados == 3
        assert run.en_su_carpeta
        assert _nombres(entregada / "7720382") == [".bot-entrega-UPD9.json", INDICE, "01_RECLAMO.pdf"]
        assert not (entregada / "MAGANGUE - PROCESADO").exists()
        assert not (entregada / "MAGANGUE").exists()

    def test_la_de_otra_carpeta_o_una_carpeta_cualquiera_lleva_la_suya(self, ajustes, tmp_path):
        from resolutions.api.folders import destino_de_la_corrida

        _caja(tmp_path / "KINGSPAN", "1000265", "UPD1")
        _correr(_motor(ajustes, JobRegistry(), []), tmp_path / "KINGSPAN", tmp_path / "KINGSPAN PROCESADO", task="segment")
        origen = tmp_path / "MAGANGUE"
        _caja(origen, "210847", "UPD3")

        # Una entrega de otra carpeta no se mezcla con ésta.
        otra = tmp_path / "KINGSPAN PROCESADO"
        assert destino_de_la_corrida(str(origen), str(otra)) == str(otra / "MAGANGUE - PROCESADO")
        # Con el nombre de la carpeta pero sin nada del bot dentro: la de siempre.
        vacia = tmp_path / "MAGANGUE PROCESADO"
        vacia.mkdir()
        assert destino_de_la_corrida(str(origen), str(vacia)) == str(vacia / "MAGANGUE - PROCESADO")
        # La carpeta donde se juntan las entregas: la de siempre.
        assert destino_de_la_corrida(str(origen), str(tmp_path)) == str(tmp_path / "MAGANGUE - PROCESADO")

    def test_rehacer_uno_no_toca_al_otro_upd_de_la_caja(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        registro = JobRegistry()
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="segment")
        # UPD1 se escaneó otra vez: sólo él se rehace.
        (tmp_path / "origen" / "1000265" / "UPD1.pdf").write_bytes(b"%PDF-1.4 escaneado de nuevo")
        hechos: list[str] = []
        _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [str(Path("1000265") / "UPD1.pdf")]
        caja = tmp_path / "destino" / "1000265"
        assert (caja / "02_RECLAMO.pdf").read_bytes().endswith(b"UPD2.pdf")
        apartados = [p for p in (caja / REEMPLAZADOS_DIR).rglob("*") if p.is_file()]
        assert apartados and not any(p.read_bytes().endswith(b"UPD2.pdf") for p in apartados)

    def test_las_otras_habilidades_siguen_con_su_carpeta_por_pdf(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1")
        _correr(_motor(ajustes, JobRegistry(), []), tmp_path / "origen", tmp_path / "destino", task="both")
        assert (tmp_path / "destino" / "1000265" / "UPD1" / "01_RECLAMO.pdf").exists()


class TestLaEntregaDeAntes:
    """Lo entregado antes, en su subcarpeta UPD o con el UPD delante, no se vuelve a pagar."""

    def _de_antes(self, ajustes, tmp_path):
        _caja(tmp_path / "origen", "1000265", "UPD1")
        registro = JobRegistry()
        # La forma de antes es la de las otras habilidades: una carpeta por PDF.
        _correr(_motor(ajustes, registro, []), tmp_path / "origen", tmp_path / "destino", task="both")
        assert (tmp_path / "destino" / "1000265" / "UPD1" / "01_RECLAMO.pdf").exists()
        return registro

    def test_saltar_lo_entregado_la_reconoce(self, ajustes, tmp_path):
        registro = self._de_antes(ajustes, tmp_path)
        hechos: list[str] = []
        run = _correr(_motor(ajustes, registro, hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and run.ya_entregados == 1

    def test_procesar_todo_otra_vez_aparta_la_subcarpeta_y_deja_la_caja_plana(self, ajustes, tmp_path):
        registro = self._de_antes(ajustes, tmp_path)
        hechos: list[str] = []
        _correr(
            _motor(ajustes, registro, hechos),
            tmp_path / "origen",
            tmp_path / "destino",
            task="segment",
            retomar="todo",
        )
        caja = tmp_path / "destino" / "1000265"
        assert hechos == [str(Path("1000265") / "UPD1.pdf")]
        assert not (caja / "UPD1").exists()
        assert (caja / "01_RECLAMO.pdf").exists()
        assert any((caja / REEMPLAZADOS_DIR).rglob("UPD1/01_RECLAMO.pdf"))

    def test_una_caja_que_no_se_pudo_ordenar_se_ordena_la_vez_siguiente(self, ajustes, tmp_path, monkeypatch):
        """Un PDF abierto en un visor cortaba el orden; las constancias volvían a decir «vigente»
        y la corrida siguiente ya no la miraba: sin numerar y sin índice para siempre (2026-10-27).
        """
        from resolutions.api import folders

        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        caja = tmp_path / "destino" / "1000265"
        caja.mkdir(parents=True)
        for upd, documento in (("UPD1", "CONSTANCIA"), ("UPD2", "RECLAMO")):
            pdf = caja / f"{upd}_01_{documento}.pdf"
            pdf.write_bytes(b"%PDF-1.4 " + f"{upd} {documento}".encode())
            hoja = _indice(caja, upd, documento)
            suelto = caja / f"00.INDICE ELECTRONICO {upd}.xlsx"
            hoja.rename(suelto)
            origen = tmp_path / "origen" / "1000265" / f"{upd}.pdf"
            tamano, modificado = constancias.huella_del_origen(origen)
            constancias.escribir(
                caja / f".bot-entrega-{upd}.json",
                constancias.Constancia(
                    origen=f"1000265/{upd}.pdf",
                    tamano=tamano,
                    modificado_ns=modificado,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(caja, [pdf, suelto]),
                    habilidad="Caja de correspondencia",
                ),
            )

        mover = folders._mover

        def abierto_en_un_visor(desde, hasta):
            if Path(desde).name.endswith("UPD2_01_RECLAMO.pdf"):
                raise PermissionError(13, "Permission denied", str(desde))
            return mover(desde, hasta)

        monkeypatch.setattr(folders, "_mover", abierto_en_un_visor)
        hechos: list[str] = []
        primera = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert any("no se pudo ordenar" in aviso for aviso in primera.avisos)
        assert not (caja / INDICE).exists()

        monkeypatch.setattr(folders, "_mover", mover)
        _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert hechos == []
        assert (caja / INDICE).exists()
        assert {"01_CONSTANCIA.pdf", "02_RECLAMO.pdf"} <= set(_nombres(caja))

    def test_la_caja_mal_numerada_de_afinia_se_arregla_al_relanzar(self, ajustes, tmp_path):
        """«01_NIC 5940155-11_01_DOCUMENTO.pdf», como salió el 2026-11-10: al relanzar, sin procesar otra vez."""
        _caja(tmp_path / "origen", "5940155", "NIC 5940155-11", "NIC 5940155-13")
        caja = tmp_path / "destino" / "5940155"
        caja.mkdir(parents=True)
        numero = 0
        for origen, documentos in (("NIC 5940155-11", ["DOCUMENTO", "RECONOCIMIENTO"]), ("NIC 5940155-13", ["RECLAMO"])):
            archivos = []
            for orden, documento in enumerate(documentos, start=1):
                numero += 1
                pdf = caja / f"{numero:02d}_{origen}_{orden:02d}_{documento}.pdf"
                pdf.write_bytes(b"%PDF-1.4 " + f"{origen} {documento}".encode())
                archivos.append(pdf)
            tamano, modificado = constancias.huella_del_origen(tmp_path / "origen" / "5940155" / f"{origen}.pdf")
            constancias.escribir(
                caja / f".bot-entrega-{origen}.json",
                constancias.Constancia(
                    origen=f"5940155/{origen}.pdf",
                    tamano=tamano,
                    modificado_ns=modificado,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(caja, archivos),
                    habilidad="Caja de correspondencia",
                ),
            )
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert hechos == [] and run.ya_entregados == 2
        assert [n for n in _nombres(caja) if n.endswith(".pdf")] == [
            "01_DOCUMENTO.pdf",
            "02_RECONOCIMIENTO.pdf",
            "03_RECLAMO.pdf",
        ]
        assert (caja / "03_RECLAMO.pdf").read_bytes().endswith(b"NIC 5940155-13 RECLAMO")

    def test_rehacer_un_pdf_de_la_caja_mal_numerada_aparta_lo_suyo_sin_duplicar(self, ajustes, tmp_path):
        """Ordenar la caja renombraba sus PDF antes de rehacerlo, y apartar buscaba los nombres viejos:
        lo viejo quedaba sin constancia junto a lo nuevo con «(2)» (la revisión, 2026-11-10)."""
        documentos = {"NIC 5940155-11": ["DOCUMENTO", "RECONOCIMIENTO"], "NIC 5940155-13": ["RECLAMO", "RESPUESTA"]}
        caja = _caja_mal_numerada(tmp_path, documentos)
        # Se volvió a escanear: otra huella, así que se rehace.
        (tmp_path / "origen" / "5940155" / "NIC 5940155-13.pdf").write_bytes(b"%PDF-1.4 otro escaneo, mas largo")
        hechos: list[str] = []
        run = _correr(
            _motor_de(ajustes, JobRegistry(), hechos, documentos),
            tmp_path / "origen",
            tmp_path / "destino",
            task="segment",
        )

        assert run.state is RunState.DONE
        assert hechos == [str(Path("5940155") / "NIC 5940155-13.pdf")]
        assert [n for n in _nombres(caja) if n.endswith(".pdf")] == [
            "01_DOCUMENTO.pdf",
            "02_RECONOCIMIENTO.pdf",
            "03_RECLAMO.pdf",
            "04_RESPUESTA.pdf",
        ]
        assert _huerfanos(caja) == []
        assert (caja / "03_RECLAMO.pdf").read_bytes().endswith(b"RECLAMO (procesado)")
        # Lo de antes, apartado y no borrado: es trabajo entregado.
        apartados = list((caja / REEMPLAZADOS_DIR).rglob("*.pdf"))
        assert len(apartados) == 2
        assert not any(p.read_bytes().endswith(b"(procesado)") for p in apartados)

    def test_un_origen_de_solo_digitos_conserva_su_orden_al_relanzar(self, ajustes, tmp_path):
        """De «01.pdf» el prefijo es «01_», como el puesto en la caja de «01_RECLAMO.pdf»: cada
        relanzamiento lo quitaba y cambiaba el orden de la caja (la revisión, 2026-11-10)."""
        documentos = {"01": ["RECLAMO", "RESPUESTA"]}
        _caja(tmp_path / "origen", "5940155", "01")
        registro = JobRegistry()
        _correr(_motor_de(ajustes, registro, [], documentos), tmp_path / "origen", tmp_path / "destino", task="segment")
        caja = tmp_path / "destino" / "5940155"
        primera = {n: (caja / n).read_bytes() for n in _nombres(caja) if n.endswith(".pdf")}
        assert sorted(primera) == ["01_RECLAMO.pdf", "02_RESPUESTA.pdf"]
        assert primera["01_RECLAMO.pdf"].endswith(b"RECLAMO (procesado)")

        for vuelta in range(3):
            hechos: list[str] = []
            run = _correr(
                _motor_de(ajustes, registro, hechos, documentos), tmp_path / "origen", tmp_path / "destino", task="segment"
            )
            assert hechos == [] and run.ya_entregados == 1, vuelta
            assert {n: (caja / n).read_bytes() for n in _nombres(caja) if n.endswith(".pdf")} == primera, vuelta

    def test_dos_origenes_de_solo_digitos_no_se_apartan_lo_ajeno(self, ajustes, tmp_path):
        """Al entregar «02.pdf», el «02_RESPUESTA.pdf» de «01.pdf» parecía suyo: se apartaba, y la
        auditoría veía un PDF de menos y el relanzamiento pagaba otra vez «01.pdf» (la revisión, 2026-11-10)."""
        documentos = {"01": ["RECLAMO", "RESPUESTA"], "02": ["CONSTANCIA", "NOTIFICACION"]}
        _caja(tmp_path / "origen", "5940155", *documentos)
        run = _correr(
            _motor_de(ajustes, JobRegistry(), [], documentos),
            tmp_path / "origen",
            tmp_path / "destino",
            task="segment",
            paralelo=1,
        )

        caja = tmp_path / "destino" / "5940155"
        assert run.state is RunState.DONE
        assert [n for n in _nombres(caja) if n.endswith(".pdf")] == [
            "01_RECLAMO.pdf",
            "02_RESPUESTA.pdf",
            "03_CONSTANCIA.pdf",
            "04_NOTIFICACION.pdf",
        ]
        assert _huerfanos(caja) == []
        assert not list(caja.glob(f"{REEMPLAZADOS_DIR}/**/*.pdf"))
        hechos: list[str] = []
        _correr(_motor_de(ajustes, JobRegistry(), hechos, documentos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == []

    def test_el_orden_de_sus_upd_no_depende_de_la_barra_de_su_constancia(self, ajustes, tmp_path):
        """Una caja empezada en Windows y seguida en Docker: la constancia del -11 dice «5940155\\NIC…»
        y la del -13 «5940155/NIC…». Por el texto «/» va antes que «\\», y el -13 quedaba primero
        (la revisión, 2026-11-10)."""
        from resolutions.api.folders import FolderRun

        caja = tmp_path / "destino" / "5940155"
        caja.mkdir(parents=True)
        for origen, barra, nombres in (
            ("NIC 5940155-11", "\\", ["01_DOCUMENTO.pdf", "02_RECONOCIMIENTO.pdf"]),
            ("NIC 5940155-13", "/", ["NIC 5940155-13_01_RECLAMO.pdf"]),
        ):
            archivos = []
            for nombre in nombres:
                (caja / nombre).write_bytes(b"%PDF-1.4 " + f"{origen} {nombre}".encode())
                archivos.append(caja / nombre)
            constancias.escribir(
                caja / f".bot-entrega-{origen}.json",
                constancias.Constancia(
                    origen=f"5940155{barra}{origen}.pdf",
                    tamano=1,
                    modificado_ns=1,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(caja, archivos),
                    habilidad="Caja de correspondencia",
                ),
            )
        motor = _motor(ajustes, JobRegistry(), [])
        run = FolderRun(id="r", source=tmp_path / "origen", destination=tmp_path / "destino")

        motor._ordenar_la_caja(run, caja)

        assert [n for n in _nombres(caja) if n.endswith(".pdf")] == [
            "01_DOCUMENTO.pdf",
            "02_RECONOCIMIENTO.pdf",
            "03_RECLAMO.pdf",
        ]
        assert (caja / "01_DOCUMENTO.pdf").read_bytes().endswith(b"NIC 5940155-11 01_DOCUMENTO.pdf")
        assert _huerfanos(caja) == []

    def test_la_caja_con_el_upd_delante_se_ordena_sin_volver_a_procesarla(self, ajustes, tmp_path):
        """Como se entregaba el 2026-10-21: «UPD1_01_…», «00.INDICE ELECTRONICO UPD1.xlsx»."""
        _caja(tmp_path / "origen", "1000265", "UPD1", "UPD2")
        caja = tmp_path / "destino" / "1000265"
        caja.mkdir(parents=True)
        for upd, documentos in (("UPD1", ["CONSTANCIA", "RECONOCIMIENTO"]), ("UPD2", ["RECLAMO"])):
            archivos = []
            for orden, documento in enumerate(documentos, start=1):
                pdf = caja / f"{upd}_{orden:02d}_{documento}.pdf"
                pdf.write_bytes(b"%PDF-1.4 " + f"{upd} {documento}".encode())
                archivos.append(pdf)
            hoja = _indice(caja, upd, *documentos)
            suelto = caja / f"00.INDICE ELECTRONICO {upd}.xlsx"
            hoja.rename(suelto)
            archivos.append(suelto)
            origen = tmp_path / "origen" / "1000265" / f"{upd}.pdf"
            tamano, modificado = constancias.huella_del_origen(origen)
            constancias.escribir(
                caja / f".bot-entrega-{upd}.json",
                constancias.Constancia(
                    origen=f"1000265/{upd}.pdf",
                    tamano=tamano,
                    modificado_ns=modificado,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(caja, archivos),
                    habilidad="Caja de correspondencia",
                ),
            )
        hechos: list[str] = []
        run = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")

        assert hechos == [] and run.ya_entregados == 2
        assert _nombres(caja) == [
            ".bot-entrega-UPD1.json",
            ".bot-entrega-UPD2.json",
            INDICE,
            "01_CONSTANCIA.pdf",
            "02_RECONOCIMIENTO.pdf",
            "03_RECLAMO.pdf",
        ]
        assert (caja / "03_RECLAMO.pdf").read_bytes().endswith(b"UPD2 RECLAMO")
        indice = leer_indice(caja / INDICE)
        assert [f.nombre for f in indice.filas] == ["CONSTANCIA", "RECONOCIMIENTO", "RECLAMO"]
        assert [f.orden for f in indice.filas] == [1, 2, 3]
        # Los índices sueltos de cada UPD, apartados, no borrados.
        assert sorted(p.name for p in (caja / REEMPLAZADOS_DIR).rglob("*.xlsx")) == [
            "00.INDICE ELECTRONICO UPD1.xlsx",
            "00.INDICE ELECTRONICO UPD2.xlsx",
        ]
        # Y la próxima vez sigue saltándolos: sus constancias dicen los nombres nuevos.
        otra = _correr(_motor(ajustes, JobRegistry(), hechos), tmp_path / "origen", tmp_path / "destino", task="segment")
        assert hechos == [] and otra.ya_entregados == 2
