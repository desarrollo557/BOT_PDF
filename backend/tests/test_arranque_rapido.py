"""Arranque rápido: lo pendiente primero, sin esperar a verificar lo ya entregado (2026-11-26).

El operador: «que no se demore mucho buscando los ya procesados para comenzar a
procesar». Esa mañana cada equipo tardó de 3 a 28 min desde que se unió a la
corrida hasta su primer PDF: el origen de Magangué se recorría en orden de ruta,
lo pendiente quedaba detrás de unos 35.000 PDF ya entregados, cada uno con su
constancia leída en el destino, y recorrer y verificar iban en serie.

Lo que fija cada clase:

- ``TestLoPendientePrimero``: con 300 carpetas entregadas delante de 5 nuevas,
  el primer PDF nuevo se toma antes de leer ninguna constancia; al final las
  300 cuentan como entregadas y las 5 se procesan una vez. Los PDF sueltos de
  la raíz siguen en su sitio, y al retomar lo que falta sólo cambia el orden.
- ``TestElCarrilRapido``: sólo la raíz del destino, listada una vez, dice que
  algo no está; un PDF nuevo en una carpeta que ya está en el destino lee su
  constancia como siempre; sin carpeta de destino, nada se lee.
- ``TestConOtrosEquipos``: un PDF del carril rápido que otro equipo entregó
  mientras tanto no se entrega dos veces (``_tomar_el_pdf``).
- ``TestElListadoEnSuHilo``: el listado no espera a la verificación; un error
  del origen a mitad relanza el recorrido sin repetir nada; cerrar el recorrido
  detiene el hilo del listado.
- ``TestEnLaRed``: la raíz de red con un solo listado y las subcarpetas con sus
  listados pedidos por delante, lo pendiente primero.
"""

from __future__ import annotations

import asyncio
import errno
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters import red_smb
from resolutions.adapters.indice_electronico import FilaDelIndice, escribir_indice
from resolutions.api import constancia as constancias
from resolutions.api import folders
from resolutions.api.folders import DestinoListado, FolderRun, FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.repetidos import buscar_repetidos
from resolutions.api.settings import Settings

INDICE = "00.INDICE ELECTRONICO.xlsx"
EMPIEZA = "Se empieza por"


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


def _pdf(carpeta: Path, nombre: str) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre
    ruta.write_bytes(b"%PDF-1.4 " + nombre.encode())
    return ruta


def _entregado(origen: Path, destino: Path, caja: str, upd: str) -> Path:
    """Una caja ya entregada: su PDF en el origen y, en el destino, lo suyo con su constancia vigente."""
    pdf = _pdf(origen / caja, f"{upd}.pdf")
    carpeta = destino / caja / upd
    entregado = _pdf(carpeta, "01_X.pdf")
    tamano, fecha = constancias.huella_del_origen(pdf)
    constancias.escribir(
        carpeta / constancias.NOMBRE,
        constancias.Constancia(
            origen=f"{caja}/{upd}.pdf",
            tamano=tamano,
            modificado_ns=fecha,
            estado=constancias.EstadoDeEntrega.COMPLETA,
            archivos=constancias.archivos_de(carpeta, [entregado]),
        ),
    )
    return pdf


def _relativa(*partes: str) -> str:
    return str(Path(*partes))


def _motor(ajustes: Settings, hechos: list[str]) -> FolderRunner:
    """Un PDF de cada PDF de origen, en su carpeta de trabajo, sin leer nada."""
    registro = JobRegistry()

    async def run_job(job):
        hechos.append(job.filename)
        salida = ajustes.output_dir / job.id
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "01_X.pdf").write_bytes(b"%PDF-1.4 out " + job.filename.encode())
        registro.mark_done(
            job,
            {
                "groups": [{"code": "01"}],
                "review_queue": [],
                "inventory": {"items": [{"file_name": "01_X.pdf", "first_page": 1}]},
            },
        )

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _motor_plano(ajustes: Settings, documentos: dict[str, list[str]], leidos: list[str] | None = None) -> FolderRunner:
    """Como el worker de la caja de correspondencia: los documentos de cada UPD, con su índice."""
    registro = JobRegistry()

    async def run_job(job):
        if leidos is not None:
            leidos.append(job.filename)
        origen = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / origen
        salida.mkdir(parents=True, exist_ok=True)
        for orden, documento in enumerate(documentos[origen], start=1):
            (salida / f"{orden:02d}_{documento}.pdf").write_bytes(b"%PDF-1.4 " + f"{origen} {documento}".encode())
        filas = [
            FilaDelIndice(
                nombre=f"{documento} DE {origen}",
                fecha_creacion=date(2024, 2, 8),
                fecha_incorporacion=date(2026, 10, 22),
                orden=orden,
                paginas=3,
            )
            for orden, documento in enumerate(documentos[origen], start=1)
        ]
        escribir_indice(salida, filas, nic="1000001", territorial="MAGANGUE", nombre_del_expediente=origen)
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE})

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _vaciar(motor: FolderRunner, origen: Path, destino: Path, *, segundos: float = 90.0, **opciones) -> FolderRun:
    async def ir():
        run = motor.start(str(origen), str(destino), **opciones)
        limite = time.monotonic() + segundos
        while run.active and time.monotonic() < limite:
            await asyncio.sleep(0.02)
        # Lo que la corrida deja de fondo -- los generales -- ya terminó.
        if run.escritor is not None and not run.escritor.done():
            await run.escritor
        return run

    return asyncio.run(ir())


class _Vigencias:
    """Las constancias que se leen: cada llamada a ``_vigencia``, en el hilo que sea."""

    def __init__(self, motor: FolderRunner, *, tarda: float = 0.0) -> None:
        self.rutas: list[str] = []
        self.terminadas = 0
        self._cerrojo = threading.Lock()
        original = motor._vigencia

        def contada(run, path):
            with self._cerrojo:
                self.rutas.append(path.name)
            if tarda:
                time.sleep(tarda)
            try:
                return original(run, path)
            finally:
                with self._cerrojo:
                    self.terminadas += 1

        motor._vigencia = contada

    @property
    def llamadas(self) -> int:
        with self._cerrojo:
            return len(self.rutas)


def _al_tomar(motor: FolderRunner, vigencias: _Vigencias) -> dict[str, list[str]]:
    """Por cada PDF que se toma, las constancias que ya se habían leído en ese momento."""
    leidas: dict[str, list[str]] = {}
    consumir = motor._consume

    async def contando(run, path):
        leidas.setdefault(path.name, list(vigencias.rutas))
        await consumir(run, path)

    motor._consume = contando
    return leidas


def _sueno_corto(dormir):
    async def corto(segundos, *args, **kwargs):
        return await dormir(min(segundos, 0.01), *args, **kwargs)

    return corto


class TestLoPendientePrimero:
    def test_el_primer_pdf_nuevo_no_espera_a_verificar_lo_entregado(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        for numero in range(300):
            _entregado(origen, destino, f"A{numero:03d}", f"UPD{numero:03d}")
        # Las nuevas, al final del orden de ruta: antes se llegaba a ellas
        # después de leer las 300 constancias de delante.
        for numero in range(5):
            _pdf(origen / f"Z{numero}", f"NUEVO{numero}.pdf")
        hechos: list[str] = []
        motor = _motor(ajustes, hechos)
        vigencias = _Vigencias(motor)
        leidas = _al_tomar(motor, vigencias)

        run = _vaciar(motor, origen, destino)

        assert run.state is RunState.DONE, run.error
        # Ninguna constancia leída antes de tomar el primer PDF nuevo.
        assert leidas["NUEVO0.pdf"] == []
        nuevos = [_relativa(f"Z{numero}", f"NUEVO{numero}.pdf") for numero in range(5)]
        # El orden en que se toman, que es lo que el motor garantiza: el de
        # empezar a leerse depende de qué hilo vuelve primero.
        tomados = [motor._registry.get(job_id).filename for job_id in run.job_ids]
        assert tomados == nuevos and sorted(hechos) == nuevos
        assert run.processed == 5 and run.ya_entregados == 300 and run.failed == 0
        assert run.verificaciones[nuevos[0]] == (folders.DECISION_NUEVO, folders.MOTIVO_SIN_CARPETA)
        assert run.verificaciones[_relativa("A000", "UPD000.pdf")][0] == folders.DECISION_YA_ENTREGADO
        assert (
            "Se empieza por 5 carpetas que no están en el destino; las otras 300 se verifican mientras tanto."
            in run.avisos
        )
        # Lo nuevo, entregado una vez.
        assert sorted(p.parent.name for p in destino.glob("Z*/*/01_X.pdf")) == [f"NUEVO{n}" for n in range(5)]

    def test_los_sueltos_de_la_raiz_siguen_en_su_sitio(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _entregado(origen, destino, "b", "UPD1")
        _pdf(origen, "a.pdf")
        _pdf(origen, "c.pdf")
        _pdf(origen / "d", "UPD2.pdf")
        motor = _motor(ajustes, [])
        run = FolderRun(id="r", source=origen, destination=destino)
        run.destino_listado = DestinoListado(destino)

        orden = [str(motor._relative(run, path)) for path, _ in motor._pdfs_locales(run)]

        # Lo que no está en el destino, en su orden de ruta de siempre (los
        # sueltos entre las carpetas); al final, la que ya está.
        assert orden == ["a.pdf", "c.pdf", _relativa("d", "UPD2.pdf"), _relativa("b", "UPD1.pdf")]
        assert "Se empieza por 1 carpeta que no está en el destino; la otra se verifica mientras tanto." in run.avisos

    def test_al_retomar_lo_que_falta_solo_cambia_el_orden(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _entregado(origen, destino, "A", "UPD1")
        _pdf(origen / "B", "UPD2.pdf")
        motor = _motor(ajustes, [])
        vigencias = _Vigencias(motor)
        run = FolderRun(id="r", source=origen, destination=destino, retomar="faltantes", tipo="diploma")

        lotes = list(motor._lotes_del_origen(run))

        pendientes = [str(motor._relative(run, path)) for lote, _ in lotes for path in lote]
        assert pendientes == [_relativa("B", "UPD2.pdf"), _relativa("A", "UPD1.pdf")]
        # Ni carril rápido ni constancias al recorrer: cada uno se compara con
        # el destino al procesarlo, como siempre.
        assert vigencias.llamadas == 0
        assert {decision for decision, _ in run.verificaciones.values()} == {folders.DECISION_SE_COMPARA}
        assert run.destino_listado is None


class TestElCarrilRapido:
    def test_solo_la_raiz_del_destino_dice_que_no_esta(self, tmp_path, monkeypatch):
        destino = tmp_path / "destino"
        (destino / "1000265" / "UPD1").mkdir(parents=True)
        (destino / "Caja B").mkdir()
        listados: list[str] = []
        escanear = folders.os.scandir

        def contando(ruta):
            listados.append(str(ruta))
            return escanear(ruta)

        monkeypatch.setattr(folders.os, "scandir", contando)
        listado = DestinoListado(destino)

        assert listado.nombres_de_la_raiz() == frozenset({"1000265", "caja b"})
        # Una carpeta cuyo padre no está, no está: el carril rápido.
        assert listado.existe(destino / "9000001" / "UPD9") is False
        # La de la raíz sí, sin mayúsculas; lo de dentro lo dice su constancia.
        assert listado.existe(destino / "CAJA B") is True
        assert listado.existe(destino / "1000265" / "UPD2") is None
        # Fuera del destino no se sabe.
        assert listado.existe(tmp_path / "otra" / "UPD1") is None
        # Y la raíz, listada una sola vez.
        assert listados.count(str(destino)) == 1

        sin_destino = DestinoListado(tmp_path / "no-existe")
        assert sin_destino.nombres_de_la_raiz() == frozenset()
        assert sin_destino.existe(tmp_path / "no-existe") is False
        assert sin_destino.existe(tmp_path / "no-existe" / "1000265" / "UPD1") is False

    def test_un_pdf_nuevo_en_una_carpeta_que_ya_esta_lee_su_constancia(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {"UPD1": ["RECLAMO"], "UPD2": ["RESPUESTA"]}
        _pdf(origen / "1000001", "UPD1.pdf")
        primera = _vaciar(_motor_plano(ajustes, documentos), origen, destino, task="segment")
        assert primera.state is RunState.DONE and primera.processed == 1, primera.error
        # Llega otro UPD del mismo NIC: su carpeta de entrega -- la del NIC -- ya
        # está en el destino, con lo del primero.
        _pdf(origen / "1000001", "UPD2.pdf")
        leidos: list[str] = []
        motor = _motor_plano(ajustes, documentos, leidos)
        vigencias = _Vigencias(motor)
        leidas = _al_tomar(motor, vigencias)

        segunda = _vaciar(motor, origen, destino, task="segment")

        assert segunda.state is RunState.DONE, segunda.error
        assert leidos == [_relativa("1000001", "UPD2.pdf")]
        assert segunda.processed == 1 and segunda.ya_entregados == 1
        # El carril normal: su constancia se buscó antes de tomarlo.
        assert "UPD2.pdf" in leidas["UPD2.pdf"]
        decision, motivo = segunda.verificaciones[_relativa("1000001", "UPD2.pdf")]
        assert decision == folders.DECISION_NUEVO and motivo != folders.MOTIVO_SIN_CARPETA
        assert sorted(p.name for p in (destino / "1000001").glob("*.pdf")) == ["01_RECLAMO.pdf", "02_RESPUESTA.pdf"]

    def test_procesar_todo_otra_vez_tambien_va_por_el_carril_rapido(self, ajustes, tmp_path):
        # Con «todo otra vez», lo que no tiene carpeta en el destino va como NUEVO
        # sin leer su constancia -- no hay nada que apartar --, y lo que sí la
        # tiene se lee y queda para rehacer, apartando lo de antes. Si un día la
        # rama de «todo» de ``_repartir`` cambiara, esto lo diría (2026-11-26).
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _entregado(origen, destino, "A", "UPD1")
        _pdf(origen / "B", "UPD2.pdf")
        motor = _motor(ajustes, [])
        vigencias = _Vigencias(motor)
        run = FolderRun(id="r", source=origen, destination=destino, retomar="todo")

        pendientes = [str(motor._relative(run, path)) for lote, _ in motor._lotes_del_origen(run) for path in lote]

        # Lo que falta, primero; lo que ya está, también se rehace.
        assert pendientes == [_relativa("B", "UPD2.pdf"), _relativa("A", "UPD1.pdf")]
        assert vigencias.rutas == ["UPD1.pdf"]
        assert run.verificaciones[_relativa("B", "UPD2.pdf")] == (folders.DECISION_NUEVO, folders.MOTIVO_SIN_CARPETA)
        assert run.verificaciones[_relativa("A", "UPD1.pdf")][0] == folders.DECISION_OTRA_VEZ
        assert set(run.a_rehacer) == {str(origen / "A" / "UPD1.pdf")}

    def test_sin_carpeta_de_destino_todo_va_por_el_carril_rapido(self, ajustes, tmp_path):
        origen = tmp_path / "origen"
        for caja in ("A", "B", "C"):
            _pdf(origen / caja, f"UPD{caja}.pdf")
        _pdf(origen, "suelto.pdf")
        motor = _motor(ajustes, [])
        vigencias = _Vigencias(motor)
        run = FolderRun(id="r", source=origen, destination=tmp_path / "no-existe")

        pendientes = [path for lote, _ in motor._lotes_del_origen(run) for path in lote]

        # Sin nada en el destino, el orden de ruta de siempre y ni una constancia leída.
        assert pendientes == list(folders.en_orden_de_ruta(origen))
        assert vigencias.llamadas == 0
        assert {run.verificaciones[str(motor._relative(run, path))] for path in pendientes} == {
            (folders.DECISION_NUEVO, folders.MOTIVO_SIN_CARPETA)
        }
        # Su huella, como la de cualquier otro que se va a procesar.
        assert set(run.huellas_del_origen) == {str(path) for path in pendientes}
        assert not any(aviso.startswith(EMPIEZA) for aviso in run.avisos)


class TestConOtrosEquipos:
    def test_lo_que_otro_equipo_entrego_mientras_tanto_no_se_entrega_dos_veces(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
        _pdf(origen / "1000001", "UPD1.pdf")
        destino.mkdir()
        relativa = _relativa("1000001", "UPD1.pdf")
        procesados: list[str] = []
        tomado_por_el_otro = threading.Event()
        por_el_carril_rapido = threading.Event()

        def ajustes_de(nombre: str) -> Settings:
            ajustes = replace(
                Settings(),
                upload_dir=tmp_path / nombre / "uploads",
                output_dir=tmp_path / nombre / "outputs",
                ledger_path=tmp_path / nombre / "inventory.jsonl",
                pausa_tras_fallos=0.01,
            )
            ajustes.ensure_directories()
            return ajustes

        def motor(nombre: str) -> FolderRunner:
            ajustes = ajustes_de(nombre)
            registro = JobRegistry()

            async def run_job(job):
                procesados.append(job.filename)
                tomado_por_el_otro.set()
                # El otro equipo termina de leerlo cuando éste ya lo dio por
                # nuevo sin mirar su constancia: su carpeta no estaba.
                await asyncio.to_thread(por_el_carril_rapido.wait, 20)
                carpeta = ajustes.output_dir / job.id
                carpeta.mkdir(parents=True, exist_ok=True)
                (carpeta / "01_UPD1.pdf").write_bytes(b"%PDF de un solo equipo")
                registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

            corredor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
            corredor.SEGUNDOS_DEL_LATIDO = 0.05
            corredor.ESPERA_DE_LOS_OTROS = 0.05
            return corredor

        otro, este = motor("pc-otro"), motor("pc-este")
        repartir = este._repartir

        def repartir_y_avisar(run, encontrados, huellas):
            repartido = repartir(run, encontrados, huellas)
            if run.verificaciones.get(relativa) == (folders.DECISION_NUEVO, folders.MOTIVO_SIN_CARPETA):
                por_el_carril_rapido.set()
            return repartido

        tomar = este._tomar_el_pdf

        def tomar_cuando_lo_entrego_el_otro(run, path, relativa_del_pdf):
            # Entretanto el otro equipo lo entregó entero y lo marcó «hecho».
            limite = time.monotonic() + 20
            while time.monotonic() < limite:
                estado = run.coordinacion.estado_de(relativa_del_pdf)
                if estado is not None and estado.estado == "hecho":
                    break
                time.sleep(0.02)
            return tomar(run, path, relativa_del_pdf)

        este._repartir = repartir_y_avisar
        este._tomar_el_pdf = tomar_cuando_lo_entrego_el_otro
        # Lo intenta en la primera pasada, sea su carpeta de quien sea.
        este._para_la_segunda_pasada = lambda run, path: False

        async def correr():
            del_otro = otro.start(str(origen), str(destino))
            await asyncio.to_thread(tomado_por_el_otro.wait, 20)
            de_este = este.start(str(origen), str(destino))
            limite = time.monotonic() + 60
            while (del_otro.active or de_este.active) and time.monotonic() < limite:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
            return del_otro, de_este

        del_otro, de_este = asyncio.run(correr())

        assert del_otro.state is RunState.DONE, del_otro.error
        assert de_este.state is RunState.DONE, de_este.error
        assert por_el_carril_rapido.is_set()
        # Uno solo lo leyó y lo entregó; el otro lo cuenta como entregado.
        assert procesados == [relativa]
        assert del_otro.processed == 1 and de_este.processed == 0
        assert de_este.ya_entregados == 1 and de_este.de_otros_equipos == 1
        assert de_este.verificaciones[relativa][0] == folders.DECISION_YA_ENTREGADO
        entregados = [p for p in destino.rglob("*.pdf") if "_reemplazados" not in p.parts]
        assert len(entregados) == 1
        assert buscar_repetidos(destino) == []


class TestElListadoEnSuHilo:
    def test_el_listado_no_espera_a_la_verificacion(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        for numero in range(80):
            _entregado(origen, destino, f"A{numero:02d}", f"UPD{numero:02d}")
        # Una constancia de cada vez y lenta, como un destino de red cargado.
        motor = _motor(replace(ajustes, verificar_a_la_vez=1), [])
        vigencias = _Vigencias(motor, tarda=0.01)
        listados: list[int] = []
        pdfs_locales = motor._pdfs_locales

        def contando(run):
            for elemento in pdfs_locales(run):
                listados.append(vigencias.terminadas)
                yield elemento

        motor._pdfs_locales = contando
        run = FolderRun(id="r", source=origen, destination=destino)

        lotes = list(motor._lotes_del_origen(run))

        assert sum(len(entregados) for _, entregados in lotes) == 80
        assert vigencias.terminadas == 80 and len(listados) == 80
        # Todo el origen listado mientras se verificaban las primeras. En serie,
        # el PDF 51 esperaba a que se verificara el primer lote de 50.
        assert listados[-1] < 10, listados

    def test_un_error_del_origen_a_mitad_relanza_el_recorrido_sin_repetir(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        for caja in ("A", "B", "C"):
            _entregado(origen, destino, caja, f"UPD{caja}")
        for caja in ("X", "Y", "Z"):
            _pdf(origen / caja, f"NUEVO{caja}.pdf")
        monkeypatch.setattr(folders.asyncio, "sleep", _sueno_corto(folders.asyncio.sleep))
        en_orden = folders.en_orden_de_ruta
        caidas: list[str] = []

        def con_una_caida(raiz, al_fallar=None):
            # La red se cae al llegar a «Y», una vez: «X» ya salió.
            if Path(raiz).name == "Y" and not caidas:
                caidas.append(str(raiz))
                raise OSError(errno.ENETDOWN, "la red no está")
            yield from en_orden(raiz, al_fallar)

        monkeypatch.setattr(folders, "en_orden_de_ruta", con_una_caida)
        hechos: list[str] = []

        run = _vaciar(_motor(ajustes, hechos), origen, destino)

        assert run.state is RunState.DONE, run.error
        assert caidas
        assert any("No se pudo recorrer el origen" in aviso for aviso in run.avisos)
        assert sorted(hechos) == [_relativa(caja, f"NUEVO{caja}.pdf") for caja in ("X", "Y", "Z")]
        assert run.processed == 3 and run.ya_entregados == 3

    def test_cerrar_el_recorrido_detiene_el_hilo_del_listado(self, ajustes, tmp_path):
        motor = _motor(ajustes, [])
        cerrado = threading.Event()

        def sin_fin(run):
            # Un origen que no se acaba: el hilo se para porque lo cierran.
            numero = 0
            try:
                while True:
                    numero += 1
                    yield tmp_path / "origen" / f"P{numero:06d}.pdf", (1, 1)
            finally:
                cerrado.set()

        motor._pdfs_locales = sin_fin
        run = FolderRun(id="r", source=tmp_path / "origen", destination=tmp_path / "destino")
        antes = set(threading.enumerate())

        lotes = motor._lotes_del_origen(run)
        primero, _ = next(lotes)
        hilos = [hilo for hilo in threading.enumerate() if hilo not in antes and hilo.name == "recorrido-del-origen"]
        lotes.close()
        for hilo in hilos:
            hilo.join(timeout=5)

        assert len(primero) == FolderRunner.PRIMER_LOTE
        assert len(hilos) == 1 and not hilos[0].is_alive()
        assert cerrado.is_set()
        assert run.destino_listado is None


class TestEnLaRed:
    def test_la_raiz_de_una_vez_y_lo_pendiente_primero(self, ajustes, tmp_path, monkeypatch):
        destino = tmp_path / "destino"
        for nic in ("1000265", "210847"):
            (destino / nic).mkdir(parents=True)
        raiz = "//200.100.20.97/afinia/MAGANGUE"

        def archivo(ruta: str) -> red_smb.ArchivoDeRed:
            return red_smb.ArchivoDeRed(ruta, 10, 7)

        sueltos = [archivo(f"{raiz}/0001.pdf"), archivo(f"{raiz}/5000000.pdf")]
        subcarpetas = [f"{raiz}/{nic}" for nic in ("1000265", "210847", "3000001", "8000001", "910349")]
        pedidas: list[list[str]] = []

        def listar_nivel(ruta, *, extension=".pdf", saltar=frozenset()):
            assert saltar == frozenset({folders.CONSUMED_DIR})
            return sueltos, subcarpetas

        def iterar_carpetas(carpetas, *, extension=".pdf", saltar=frozenset(), al_fallar=None, adelantadas=None):
            carpetas = list(carpetas)
            assert saltar == frozenset({folders.CONSUMED_DIR}) and al_fallar is not None
            pedidas.append([carpeta.rsplit("/", 1)[-1] for carpeta in carpetas])
            for carpeta in carpetas:
                yield archivo(f"{carpeta}/UPD.pdf")

        monkeypatch.setattr(red_smb, "listar_nivel", listar_nivel)
        monkeypatch.setattr(red_smb, "iterar_carpetas", iterar_carpetas)
        motor = _motor(ajustes, [])
        run = FolderRun(id="r", source=Path(raiz), destination=destino)
        run.destino_listado = DestinoListado(destino)

        rutas = [(Path(path).parent.name, Path(path).name, huella) for path, huella in motor._pdfs_en_la_red(run)]

        # Lo que falta y los sueltos, en su orden de ruta; al final lo que ya está.
        assert [nombre if nombre.endswith(".pdf") and carpeta == "MAGANGUE" else carpeta for carpeta, nombre, _ in rutas] == [
            "0001.pdf",
            "3000001",
            "5000000.pdf",
            "8000001",
            "910349",
            "1000265",
            "210847",
        ]
        assert all(huella == (10, 7) for _, _, huella in rutas)
        # Cada tramo de carpetas seguidas, de una vez: el último de lo que falta
        # sigue con lo que ya está, sin cortar los listados pedidos por delante.
        assert pedidas == [["3000001"], ["8000001", "910349", "1000265", "210847"]]
        assert "Se empieza por 3 carpetas que no están en el destino; las otras 2 se verifican mientras tanto." in run.avisos
