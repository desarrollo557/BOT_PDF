"""La entrega al destino de red, en paralelo y con pocas operaciones (2026-11-26).

El operador, con siete PC sobre el Escritorio de un Windows compartido: «¿será
por la descarga de cada PDF?». Medido el 2026-11-25: no. Cada PC entregaba de
uno en uno -- unos 20 s por PDF --, con unas 400 aperturas y 17 renombres de
casi un segundo por PDF, y los ya leídos esperaban 14-29 min para entregarse.

Lo que fija cada clase:

- ``TestEntregasALaVez``: a NIC distintos van a la vez; al mismo NIC, en fila;
  nunca con el cerrojo de la corrida tomado; ocho UPD del mismo NIC salen
  01..08, sin repetidos ni nombres de paso.
- ``TestUnNicNuevo``: se copia con su nombre final, sin un solo renombre.
- ``TestLoQueYaNoSeRepite``: una entrega cortada con nombres finales se aparta
  entera al rehacerla; lo que otro equipo entregó mientras se leía no se
  entrega otra vez; un PDF que entra dos veces en la cola se lee una vez.
- ``TestElExpedienteSinReleer``: sin un RE corregible no se abre ningún PDF; con
  las citas guardadas en la constancia se corrige igual, sin abrirlos.
- ``TestLosGeneralesDeUnoSolo``: con varios equipos, los de a mitad de corrida
  los escribe sólo el del rol «generales», sin el índice general.
- ``TestLaSegundaPasada``: los reclamos de los demás se miran antes de encolar;
  lo hecho se cuenta, y el que cierra lee su constancia.
- ``TestElArchivoRetenido``: EAGAIN y EBUSY del cliente SMB se reintentan.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from resolutions.adapters.coordinacion_en_disco import Ajeno
from resolutions.adapters.indice_electronico import FilaDelIndice, escribir_indice
from resolutions.api import constancia as constancias
from resolutions.api import folders
from resolutions.api.folders import REEMPLAZADOS_DIR, FolderRun, FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.repetidos import buscar_repetidos
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
        entregas_a_la_vez=4,
    )
    settings.ensure_directories()
    return settings


def _caja(origen: Path, caja: str, *upds: str) -> None:
    (origen / caja).mkdir(parents=True, exist_ok=True)
    for upd in upds:
        (origen / caja / f"{upd}.pdf").write_bytes(b"%PDF-1.4 " + upd.encode())


def _indice(carpeta: Path, upd: str, *nombres: str) -> Path:
    filas = [
        FilaDelIndice(nombre=nombre, fecha_creacion=date(2024, 2, 8), fecha_incorporacion=date(2026, 10, 22), orden=orden, paginas=3)
        for orden, nombre in enumerate(nombres, start=1)
    ]
    return escribir_indice(carpeta, filas, nic="1000265", territorial="MAGANGUE", nombre_del_expediente=upd)


def _motor(ajustes: Settings, documentos: dict[str, list[str]], leidos: list[str] | None = None, antes=None) -> FolderRunner:
    """Como el worker: los documentos de cada PDF de origen, con su índice, en su carpeta de trabajo."""
    registro = JobRegistry()

    async def run_job(job):
        if leidos is not None:
            leidos.append(job.filename)
        if antes is not None:
            antes(job)
        origen = Path(job.filename).stem
        salida = ajustes.output_dir / job.id / origen
        salida.mkdir(parents=True, exist_ok=True)
        suyos = documentos[origen]
        for orden, documento in enumerate(suyos, start=1):
            (salida / f"{orden:02d}_{documento}.pdf").write_bytes(b"%PDF-1.4 " + f"{origen} {documento}".encode())
        _indice(salida, origen, *(f"{documento} DE {origen}" for documento in suyos))
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": [], "indice_electronico": INDICE})

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _correr(motor: FolderRunner, origen: Path, destino: Path, **opciones) -> FolderRun:
    async def ir():
        run = motor.start(str(origen), str(destino), task="segment", **opciones)
        for _ in range(3000):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(ir())


def _nombres(carpeta: Path) -> list[str]:
    return sorted(p.name for p in carpeta.iterdir() if p.name != REEMPLAZADOS_DIR and not p.name.startswith("."))


class TestEntregasALaVez:
    def test_nic_distintos_a_la_vez_y_el_mismo_nic_en_fila(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {f"UPD{n}": ["RECLAMO"] for n in range(1, 7)}
        for n in range(1, 5):
            _caja(origen, f"100000{n}", f"UPD{n}")
        _caja(origen, "1000005", "UPD5", "UPD6")
        motor = _motor(ajustes, documentos)
        tramos: list[tuple[str, float, float, bool]] = []
        copiar = folders._copiar_directo

        def lento(desde, carpeta, nombre, medir=None, **opciones):
            # Lo que tarda escribir en un destino de red lento.
            inicio = time.monotonic()
            con_el_de_la_corrida = any(run.cerrojo._is_owned() for run in motor._runs.values())
            time.sleep(0.3)
            hecho = copiar(desde, carpeta, nombre, medir, **opciones)
            tramos.append((carpeta.name, inicio, time.monotonic(), con_el_de_la_corrida))
            return hecho

        monkeypatch.setattr(folders, "_copiar_directo", lento)
        run = _correr(motor, origen, destino)
        assert run.state is RunState.DONE, run.error
        assert len(tramos) == 6
        # Nunca con el cerrojo de la corrida tomado: si no, irían en fila.
        assert not any(tramo[3] for tramo in tramos)
        # NIC distintos, a la vez.
        assert any(a[0] != b[0] and a[1] < b[2] and b[1] < a[2] for a in tramos for b in tramos)
        # El mismo NIC, uno detrás de otro.
        uno, otro = (tramo for tramo in tramos if tramo[0] == "1000005")
        assert not (uno[1] < otro[2] and otro[1] < uno[2])
        assert _nombres(destino / "1000005") == [INDICE, "01_RECLAMO.pdf", "02_RECLAMO.pdf"]

    def test_ocho_upd_del_mismo_nic_salen_seguidos_y_sin_repetidos(self, ajustes, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "no")
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {f"UPD{n}": [f"DOCUMENTO{n}"] for n in range(1, 9)}
        _caja(origen, "1000001", *documentos)
        run = _correr(_motor(ajustes, documentos), origen, destino)
        assert run.state is RunState.DONE, run.error
        nic = destino / "1000001"
        assert _nombres(nic) == [INDICE, *(f"{n:02d}_DOCUMENTO{n}.pdf" for n in range(1, 9))]
        assert not any(n.startswith(("UPD", folders.PREFIJO_DE_PASO)) for n in os.listdir(nic))
        assert buscar_repetidos(destino) == []
        # Cada UPD, con su constancia completa y su archivo.
        for n in range(1, 9):
            constancia = constancias.leer(nic / f".bot-entrega-UPD{n}.json")
            assert constancia.estado == constancias.EstadoDeEntrega.COMPLETA
            assert [a["ruta"] for a in constancia.archivos] == [f"{n:02d}_DOCUMENTO{n}.pdf"]


class TestUnNicNuevo:
    def test_se_copia_con_su_nombre_final_sin_renombrar(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {"UPD1": ["RECLAMO", "RESPUESTA", "RECURSO"]}
        _caja(origen, "1000001", "UPD1")
        movidos: list[tuple[str, str]] = []
        mover = folders._mover

        def espia(desde, hasta):
            movidos.append((desde.name, hasta.name))
            mover(desde, hasta)

        monkeypatch.setattr(folders, "_mover", espia)
        run = _correr(_motor(ajustes, documentos), origen, destino)
        assert run.state is RunState.DONE, run.error
        nic = destino / "1000001"
        assert _nombres(nic) == [INDICE, "01_RECLAMO.pdf", "02_RESPUESTA.pdf", "03_RECURSO.pdf"]
        # Ni un renombre: antes eran tres por PDF (.part, nombre de paso y número).
        assert movidos == []
        assert not [n for n in os.listdir(nic) if n.endswith((".part", ".tmp"))]
        constancia = constancias.leer(nic / ".bot-entrega-UPD1.json")
        assert constancia.estado == constancias.EstadoDeEntrega.COMPLETA
        assert [a["ruta"] for a in constancia.archivos] == ["01_RECLAMO.pdf", "02_RESPUESTA.pdf", "03_RECURSO.pdf"]
        assert all(a["bytes"] == (nic / a["ruta"]).stat().st_size for a in constancia.archivos)

    def test_el_segundo_upd_del_nic_se_numera_como_siempre(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {"UPD1": ["RECLAMO"], "UPD2": ["RECURSO", "RESPUESTA"]}
        _caja(origen, "1000001", "UPD1", "UPD2")
        run = _correr(_motor(ajustes, documentos), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert _nombres(destino / "1000001") == [INDICE, "01_RECLAMO.pdf", "02_RECURSO.pdf", "03_RESPUESTA.pdf"]
        assert buscar_repetidos(destino) == []


class TestLoQueYaNoSeRepite:
    def test_una_entrega_cortada_con_nombres_finales_se_aparta_al_rehacerla(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        # Lo que dejó una entrega cortada: su constancia «entregando» con lo
        # que iba a copiar, y el primer PDF a medias con su nombre final.
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF-")
        constancias.escribir(
            nic / ".bot-entrega-UPD1.json",
            constancias.Constancia(
                origen="1000001/UPD1.pdf",
                tamano=1,
                modificado_ns=1,
                archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 40}, {"ruta": "02_RESPUESTA.pdf", "bytes": 40}],
            ),
        )
        run = _correr(_motor(ajustes, {"UPD1": ["RECLAMO", "RESPUESTA"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert _nombres(nic) == [INDICE, "01_RECLAMO.pdf", "02_RESPUESTA.pdf"]
        apartados = [p.name for p in (nic / REEMPLAZADOS_DIR).rglob("*.pdf")]
        assert apartados == ["01_RECLAMO.pdf"]
        assert buscar_repetidos(destino) == []
        assert constancias.leer(nic / ".bot-entrega-UPD1.json").estado == constancias.EstadoDeEntrega.COMPLETA

    def test_lo_que_otro_entrego_mientras_se_leia_no_se_entrega_otra_vez(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        nic = destino / "1000001"

        def lo_entrega_otro(job):
            # Otro equipo, que lo dio por caído un momento, lo entrega entero
            # mientras éste todavía lo está leyendo.
            nic.mkdir(parents=True, exist_ok=True)
            (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF de otro equipo")
            constancias.escribir(
                nic / ".bot-entrega-UPD1.json",
                constancias.Constancia(
                    origen="1000001/UPD1.pdf",
                    tamano=1,
                    modificado_ns=1,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=constancias.archivos_de(nic, [nic / "01_RECLAMO.pdf"]),
                    job_id="trabajo-de-otro-equipo",
                ),
            )

        run = _correr(_motor(ajustes, {"UPD1": ["RECLAMO"]}, antes=lo_entrega_otro), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert _nombres(nic) == ["01_RECLAMO.pdf"]
        assert (nic / "01_RECLAMO.pdf").read_bytes() == b"%PDF de otro equipo"
        assert constancias.leer(nic / ".bot-entrega-UPD1.json").job_id == "trabajo-de-otro-equipo"
        assert run.processed == 0 and run.ya_entregados == 1
        assert any("ya lo había entregado" in aviso for aviso in run.avisos)

    def test_un_pdf_que_entra_dos_veces_en_la_cola_se_lee_una_vez(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        documentos = {f"UPD{n}": ["RECLAMO"] for n in range(1, 4)}
        _caja(origen, "1000001", *documentos)
        leidos: list[str] = []
        motor = _motor(ajustes, documentos, leidos)
        pdfs_locales = FolderRunner._pdfs_locales

        def cada_uno_dos_veces(self, run):
            # El recorrido que vuelve a empezar tras una caída del origen los
            # encontraba otra vez, con los primeros todavía en la cola.
            for path, huella in pdfs_locales(self, run):
                yield path, huella
                yield path, huella

        monkeypatch.setattr(FolderRunner, "_pdfs_locales", cada_uno_dos_veces)
        run = _correr(motor, origen, destino)
        assert run.state is RunState.DONE, run.error
        assert sorted(leidos) == sorted({*leidos}) and len(leidos) == 3
        assert _nombres(destino / "1000001") == [INDICE, "01_RECLAMO.pdf", "02_RECLAMO.pdf", "03_RECLAMO.pdf"]

    def test_una_copia_que_no_sale_no_deja_nada_y_el_pdf_se_rehace(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        copiar = folders._copiar_directo
        cortes: list[str] = []

        def sin_red(desde, carpeta, nombre, medir=None, **opciones):
            # El destino no contesta mientras se copia el segundo PDF, en el
            # primer intento y sus reintentos: el PDF va a la vuelta final.
            if nombre.startswith("02_") and len(cortes) < 4:
                cortes.append(nombre)
                raise OSError(errno.EHOSTDOWN, "Host is down")
            return copiar(desde, carpeta, nombre, medir, **opciones)

        monkeypatch.setattr(folders, "_copiar_directo", sin_red)
        monkeypatch.setattr(FolderRunner, "ESPERAS_DE_LA_COPIA", (0.01, 0.01, 0.01))
        run = _correr(_motor(ajustes, {"UPD1": ["RECLAMO", "RESPUESTA"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert len(cortes) == 4
        nic = destino / "1000001"
        assert _nombres(nic) == [INDICE, "01_RECLAMO.pdf", "02_RESPUESTA.pdf"]
        # Lo copiado en el intento cortado se borró: nada que apartar ni repetido.
        assert not (nic / REEMPLAZADOS_DIR).exists()
        assert buscar_repetidos(destino) == []
        assert run.recuperados == 1

    def test_el_resto_de_una_entrega_cortada_no_hace_un_dos(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD2")
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        # La entrega de UPD1 se cortó con su primer PDF ya con su nombre final.
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF resto de UPD1")
        constancias.escribir(
            nic / ".bot-entrega-UPD1.json",
            constancias.Constancia(
                origen="1000001/UPD1.pdf", tamano=1, modificado_ns=1, archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 18}]
            ),
        )
        run = _correr(_motor(ajustes, {"UPD2": ["RECLAMO"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert _nombres(nic) == [INDICE, "01_RECLAMO.pdf"]
        assert (nic / "01_RECLAMO.pdf").read_bytes() != b"%PDF resto de UPD1"
        assert [p.read_bytes() for p in (nic / REEMPLAZADOS_DIR).rglob("*.pdf")] == [b"%PDF resto de UPD1"]
        assert buscar_repetidos(destino) == []

    def test_al_rehacer_no_se_aparta_lo_que_es_de_otro_upd(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        # UPD2 entregado entero y con su «01_RECLAMO.pdf»; la constancia cortada
        # de UPD1 nombra ese mismo archivo (su resto ya se apartó antes).
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF de UPD2")
        constancias.escribir(
            nic / ".bot-entrega-UPD2.json",
            constancias.Constancia(
                origen="1000001/UPD2.pdf",
                tamano=1,
                modificado_ns=1,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=constancias.archivos_de(nic, [nic / "01_RECLAMO.pdf"]),
                job_id="trabajo-de-upd2",
            ),
        )
        constancias.escribir(
            nic / ".bot-entrega-UPD1.json",
            constancias.Constancia(
                origen="1000001/UPD1.pdf", tamano=1, modificado_ns=1, archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 12}]
            ),
        )
        run = _correr(_motor(ajustes, {"UPD1": ["RECURSO"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        # Lo de UPD2 sigue en la carpeta (renumerado detrás de UPD1), no apartado.
        assert _nombres(nic) == [INDICE, "01_RECURSO.pdf", "02_RECLAMO.pdf"]
        assert (nic / "02_RECLAMO.pdf").read_bytes() == b"%PDF de UPD2"
        assert not list((nic / REEMPLAZADOS_DIR).rglob("*.pdf"))
        assert buscar_repetidos(destino) == []

    def test_el_reintento_reescribe_su_propia_copia_a_medias_sin_hacer_un_dos(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        copiar = folders._copiar_directo
        cortes: list[str] = []

        def corte_con_resto(desde, carpeta, nombre, medir=None, *, encima_de=None):
            # El primer intento deja el PDF a medias con su nombre final y el
            # borrado tampoco sale: el servidor no contesta.
            if not cortes:
                cortes.append(nombre)
                (carpeta / nombre).write_bytes(b"%PDF- a medias")
                error = OSError(errno.EHOSTDOWN, "Host is down")
                error.filename = str(carpeta / nombre)
                raise error
            return copiar(desde, carpeta, nombre, medir, encima_de=encima_de)

        monkeypatch.setattr(folders, "_copiar_directo", corte_con_resto)
        monkeypatch.setattr(FolderRunner, "ESPERAS_DE_LA_COPIA", (0.01, 0.01, 0.01))
        run = _correr(_motor(ajustes, {"UPD1": ["RECLAMO", "RESPUESTA"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        nic = destino / "1000001"
        assert _nombres(nic) == [INDICE, "01_RECLAMO.pdf", "02_RESPUESTA.pdf"]
        assert (nic / "01_RECLAMO.pdf").read_bytes() != b"%PDF- a medias"
        assert buscar_repetidos(destino) == []

    def test_una_constancia_de_otro_upd_que_no_se_deja_leer_no_deja_apartar_nada(self, ajustes, tmp_path, monkeypatch):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF de UPD2")
        constancias.escribir(
            nic / ".bot-entrega-UPD2.json",
            constancias.Constancia(
                origen="1000001/UPD2.pdf",
                tamano=1,
                modificado_ns=1,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=constancias.archivos_de(nic, [nic / "01_RECLAMO.pdf"]),
                job_id="trabajo-de-upd2",
            ),
        )
        # La constancia cortada de UPD1 nombra ese mismo archivo.
        constancias.escribir(
            nic / ".bot-entrega-UPD1.json",
            constancias.Constancia(
                origen="1000001/UPD1.pdf", tamano=1, modificado_ns=1, archivos=[{"ruta": "01_RECLAMO.pdf", "bytes": 12}]
            ),
        )
        leer_si_hay = constancias.leer_si_hay
        veces = []

        def ilegible_un_momento(ruta):
            # La de UPD2 no se deja leer la primera vez que la entrega la mira.
            if ruta.name == ".bot-entrega-UPD2.json" and not veces:
                veces.append(ruta)
                return None, True
            return leer_si_hay(ruta)

        monkeypatch.setattr(constancias, "leer_si_hay", ilegible_un_momento)
        run = _correr(_motor(ajustes, {"UPD1": ["RECURSO"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        assert veces
        # El de UPD2 nunca se apartó: la entrega volvió con su fallo y se rehízo.
        assert (nic / "02_RECLAMO.pdf").read_bytes() == b"%PDF de UPD2"
        assert _nombres(nic) == [INDICE, "01_RECURSO.pdf", "02_RECLAMO.pdf"]
        assert buscar_repetidos(destino) == []

    def test_un_origen_de_solo_digitos_no_aparta_pdf_de_otros_upd(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "2")
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        # El PDF de otro UPD cuyo RE acaba en «2»: no es de «2.pdf».
        ajeno = "01_RECLAMO-RE2311202207562.pdf"
        (nic / ajeno).write_bytes(b"%PDF de UPD9")
        constancias.escribir(
            nic / ".bot-entrega-UPD9.json",
            constancias.Constancia(
                origen="1000001/UPD9.pdf",
                tamano=1,
                modificado_ns=1,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=constancias.archivos_de(nic, [nic / ajeno]),
                job_id="trabajo-de-upd9",
            ),
        )
        run = _correr(_motor(ajustes, {"2": ["RESPUESTA"]}), origen, destino)
        assert run.state is RunState.DONE, run.error
        # Nada apartado: el de UPD9 sigue en la carpeta, numerado detrás de «2».
        assert not list((nic / REEMPLAZADOS_DIR).rglob("*.pdf"))
        assert _nombres(nic) == [INDICE, "01_RESPUESTA.pdf", "02_RECLAMO-RE2311202207562.pdf"]
        assert (nic / "02_RECLAMO-RE2311202207562.pdf").read_bytes() == b"%PDF de UPD9"
        assert buscar_repetidos(destino) == []

    def test_esperar_la_carpeta_de_otro_no_frena_las_demas_entregas(self, ajustes, tmp_path, monkeypatch):
        from resolutions.api.correccion_del_re import cerrojo_de_la_carpeta

        origen, destino = tmp_path / "origen", tmp_path / "destino"
        _caja(origen, "1000001", "UPD1")
        _caja(origen, "1000002", "UPD2")
        motor = _motor(replace(ajustes, entregas_a_la_vez=1), {"UPD1": ["RECLAMO"], "UPD2": ["RECLAMO"]})
        copiados: dict[str, float] = {}
        copiar = folders._copiar_directo

        def anotar(desde, carpeta, nombre, medir=None, *, encima_de=None):
            hecho = copiar(desde, carpeta, nombre, medir, encima_de=encima_de)
            copiados[carpeta.name] = time.monotonic()
            return hecho

        monkeypatch.setattr(folders, "_copiar_directo", anotar)
        ocupada = cerrojo_de_la_carpeta(destino / "1000001")
        tomada = threading.Event()
        suelta: list[float] = []

        def retener():
            # La carpeta del primer NIC, ocupada un rato (otro equipo entregando en ella).
            with ocupada:
                tomada.set()
                time.sleep(1.0)
                suelta.append(time.monotonic())

        hilo = threading.Thread(target=retener)
        hilo.start()
        tomada.wait(5)
        run = _correr(motor, origen, destino)
        hilo.join()
        assert run.state is RunState.DONE, run.error
        # Con un solo turno de entregas, el segundo NIC entregó mientras el
        # primero esperaba su carpeta: el turno se pide después de la carpeta.
        assert copiados["1000002"] < suelta[0] < copiados["1000001"]

    def test_lo_que_ya_esta_en_la_cola_no_se_vuelve_a_encolar(self, ajustes, tmp_path):
        origen = tmp_path / "origen"
        _caja(origen, "1000001", "UPD1", "UPD2")
        motor = _motor(ajustes, {})
        run = FolderRun(id="r1", source=origen, destination=tmp_path / "destino", task="segment")
        run.encolados.add(str(origen / "1000001" / "UPD1.pdf"))
        lotes = list(motor._lotes_del_origen(run))
        encontrados = [path.name for pendientes, _ in lotes for path in pendientes]
        assert encontrados == ["UPD2.pdf"]


class TestElExpedienteSinReleer:
    CITA = "Solicitud de Cumplimiento acorde a Derecho de Petición numerado según oficio 2311202201568. Quedamos atentos"

    def _expediente(self, carpeta: Path, *, metodo: str, con_citas: bool) -> None:
        from resolutions.domain.resolutor_del_re import citas_del_texto

        textos = {
            "01_DERECHO-DE-PETICION-RE2311202207568.pdf": "Señores AFINIA. Derecho de petición de 2022.",
            "02_DERECHO-DE-PETICION-RE2311202300704.pdf": self.CITA,
        }
        for nombre in textos:
            (carpeta / nombre).write_bytes(b"%PDF-1.4")
        for upd, ruta, hojas, evidencia in (
            (
                "UPD1",
                "01_DERECHO-DE-PETICION-RE2311202207568.pdf",
                [1, 2],
                {
                    "estado": "encontrado",
                    "valor": "RE2311202207568",
                    "metodo": metodo,
                    "candidatos": [{"valor": "RE2311202201568"}, {"valor": "RE2371202207568"}],
                },
            ),
            (
                "UPD2",
                "02_DERECHO-DE-PETICION-RE2311202300704.pdf",
                [1],
                {"estado": "encontrado", "valor": "RE2311202300704", "metodo": "etiqueta impresa"},
            ),
        ):
            archivo = {"ruta": ruta, "bytes": 8}
            if con_citas:
                archivo["citas"] = [list(cita) for cita in citas_del_texto(textos[ruta])]
            constancias.escribir(
                carpeta / f".bot-entrega-{upd}.json",
                constancias.Constancia(
                    origen=f"1111111/{upd}.pdf",
                    tamano=1,
                    modificado_ns=1,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=[archivo],
                    indice={"filas": [{"nombre": ruta[3:-4].replace("-", " ")}]},
                    evidencia={"re": {"1": evidencia}},
                    documentos=[{"hojas": hojas}],
                ),
            )

    @staticmethod
    def _contar_aperturas(monkeypatch) -> list[str]:
        from resolutions.adapters import pymupdf_source

        abiertos: list[str] = []
        original = pymupdf_source.PyMuPDFPageSource.__init__

        def contar(self, path, *args, **kwargs):
            abiertos.append(Path(path).name)
            original(self, path, *args, **kwargs)

        monkeypatch.setattr(pymupdf_source.PyMuPDFPageSource, "__init__", contar)
        return abiertos

    def test_sin_un_re_corregible_no_se_abre_ningun_pdf(self, tmp_path, monkeypatch):
        from resolutions.api.correccion_del_re import corregir_con_el_expediente

        self._expediente(tmp_path, metodo="etiqueta impresa", con_citas=False)
        abiertos = self._contar_aperturas(monkeypatch)
        assert corregir_con_el_expediente(tmp_path) == []
        assert abiertos == []

    def test_con_las_citas_guardadas_se_corrige_sin_abrirlos(self, tmp_path, monkeypatch):
        from resolutions.api.correccion_del_re import corregir_con_el_expediente

        self._expediente(
            tmp_path,
            metodo="decidido por el agente: el juez de la IA, mirando el sello, eligió entre lo leído",
            con_citas=True,
        )
        abiertos = self._contar_aperturas(monkeypatch)
        hechos = corregir_con_el_expediente(tmp_path)
        assert abiertos == []
        assert len(hechos) == 1 and "RE2311202201568" in hechos[0]
        assert (tmp_path / "01_DERECHO-DE-PETICION-RE2311202201568.pdf").exists()
        corregida = constancias.leer(tmp_path / ".bot-entrega-UPD1.json")
        assert corregida.archivos[0]["ruta"] == "01_DERECHO-DE-PETICION-RE2311202201568.pdf"
        # Sus citas siguen con su archivo renombrado.
        assert corregida.archivos[0]["citas"] == []

    def test_si_no_puede_guardar_la_constancia_todo_vuelve_a_como_estaba(self, tmp_path, monkeypatch):
        from resolutions.api import correccion_del_re

        self._expediente(
            tmp_path,
            metodo="decidido por el agente: el juez de la IA, mirando el sello, eligió entre lo leído",
            con_citas=True,
        )
        leidas = [
            (ruta, constancias.leer(ruta))
            for ruta in sorted(tmp_path.glob(".bot-entrega-*.json"))
        ]
        antes = [constancia.as_dict() for _, constancia in leidas]

        def sin_red(ruta, constancia, **_):
            raise OSError(errno.EHOSTDOWN, "Host is down")

        monkeypatch.setattr(correccion_del_re.constancias, "escribir", sin_red)
        hechos = correccion_del_re.corregir_con_el_expediente(tmp_path, leidas=leidas, en_el_orden=True)
        assert any("no se pudo actualizar" in hecho for hecho in hechos)
        # El PDF con su nombre de antes, y la constancia en memoria también:
        # quien ordena la carpeta sigue con ella.
        assert (tmp_path / "01_DERECHO-DE-PETICION-RE2311202207568.pdf").exists()
        assert [constancia.as_dict() for _, constancia in leidas] == antes

    def test_las_citas_dan_lo_mismo_que_el_texto(self):
        from resolutions.domain.resolutor_del_re import (
            citas_del_texto,
            re_citado_en_el_expediente,
            re_citado_entre_citas,
        )

        textos = {
            "02_DERECHO-DE-PETICION.pdf": self.CITA + " y otra vez 2311202201568, y el 2310202299463 de la etiqueta",
            "07_RECURSO-DE-REPOSICION-RE2310202299563.pdf": "AL CONTESTAR CITE ESTE NUMERORE2310202299463",
        }
        for actual, candidatos in (
            ("RE2311202207568", ["RE2311202201568"]),
            ("RE2310202299568", []),
            ("RE2311202201568", []),
        ):
            assert re_citado_entre_citas(
                actual, candidatos, {fuente: citas_del_texto(texto) for fuente, texto in textos.items()}
            ) == re_citado_en_el_expediente(actual, candidatos, textos)


class _CoordinacionDePrueba:
    """Lo que la corrida le pide a la coordinación, sin disco: para las decisiones de cada equipo."""

    def __init__(self, *, rol: bool, estados: dict[str, object] | None = None, vivos: int = 3) -> None:
        self.rol = rol
        self.estados = estados or {}
        self.retirado = False
        self.desplazado = False
        self.vivos = vivos
        self.roles_pedidos: list[str] = []

    def vigente(self) -> bool:
        return True

    def por_que_no_vale(self) -> str | None:
        return None

    def puede_entregar(self) -> bool:
        return True

    def equipos_vivos(self) -> list[str]:
        return [f"PC{n}" for n in range(self.vivos)]

    def tomar_rol(self, nombre: str) -> bool:
        self.roles_pedidos.append(nombre)
        return self.rol

    def cerrojo(self, nombre: str, **_):
        return contextlib.nullcontext()

    def estado_de(self, relativa: str):
        # Como ``clave_de``: la misma con «\» (Windows) o con «/».
        return self.estados.get(relativa.replace("\\", "/"))


class TestLosGeneralesDeUnoSolo:
    def _corrida(self, tmp_path: Path, coordinacion) -> FolderRun:
        run = FolderRun(id="r1", source=tmp_path / "origen", destination=tmp_path / "destino", task="segment")
        run.coordinacion = coordinacion
        return run

    def test_a_mitad_los_escribe_solo_el_del_rol_y_sin_el_indice_general(self, ajustes, tmp_path, monkeypatch):
        motor = _motor(ajustes, {})
        escritos: list[bool] = []
        monkeypatch.setattr(motor, "_escribir_generales", lambda run, con_indice=True: escritos.append(con_indice))
        monkeypatch.setattr(motor, "_escribir_control", lambda run: None)
        # Sin el rol: no escribe, ni pregunta por el turno, y no lo reintenta en el acto.
        run = self._corrida(tmp_path, _CoordinacionDePrueba(rol=False))
        motor._escribir_todo_lo_general(run, a_mitad=True)
        assert escritos == [] and run.generales_en > 0
        # Con el rol: escribe, sin el índice general.
        run = self._corrida(tmp_path, _CoordinacionDePrueba(rol=True))
        motor._escribir_todo_lo_general(run, a_mitad=True)
        assert escritos == [False]
        # Los definitivos (el que cierra): con todo.
        motor._escribir_todo_lo_general(run)
        assert escritos == [False, True]

    def test_un_equipo_solo_los_escribe_como_siempre(self, ajustes, tmp_path, monkeypatch):
        motor = _motor(ajustes, {})
        escritos: list[bool] = []
        monkeypatch.setattr(motor, "_escribir_generales", lambda run, con_indice=True: escritos.append(con_indice))
        monkeypatch.setattr(motor, "_escribir_control", lambda run: None)
        run = self._corrida(tmp_path, None)
        motor._escribir_todo_lo_general(run, a_mitad=True)
        assert escritos == [True]
        # Con la coordinación en «auto» pero solo en el destino: también con todo.
        run = self._corrida(tmp_path, _CoordinacionDePrueba(rol=True, vivos=1))
        motor._escribir_todo_lo_general(run, a_mitad=True)
        assert escritos == [True, True]


class TestLaSegundaPasada:
    def test_lo_de_los_demas_se_mira_antes_de_encolar(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        motor = _motor(ajustes, {})
        estados = {
            "1/HECHO.pdf": Ajeno(equipo="PC2", estado="hecho"),
            "1/EN-CURSO.pdf": Ajeno(equipo="PC3", estado="en curso"),
            "1/FALLO.pdf": Ajeno(equipo="PC4", estado="falló", error="Mistral no respondió"),
        }
        run = FolderRun(id="r1", source=origen, destination=destino, task="segment")
        run.coordinacion = _CoordinacionDePrueba(rol=False, estados=estados)
        segunda = [origen / "1" / nombre for nombre in ("HECHO.pdf", "EN-CURSO.pdf", "FALLO.pdf", "LIBRE.pdf")]
        quedan = motor._clasificar_la_segunda_pasada(run, segunda)
        assert [p.name for p in quedan] == ["LIBRE.pdf"]
        assert str(origen / "1" / "HECHO.pdf") in run.contados_sin_constancia
        assert run.ya_entregados == 1 and run.de_otros_equipos == 1
        assert run.ajenos == {str(origen / "1" / "EN-CURSO.pdf"): "PC3"}
        assert "1/FALLO.pdf" in {k.replace("\\", "/") for k in run.fallidos_en_otro}

    def test_el_que_cierra_lee_la_constancia_de_lo_contado(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        motor = _motor(ajustes, {})
        run = FolderRun(id="r1", source=origen, destination=destino, task="segment")
        path = origen / "1000001" / "UPD1.pdf"
        nic = destino / "1000001"
        nic.mkdir(parents=True)
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF")
        constancias.escribir(
            nic / ".bot-entrega-UPD1.json",
            constancias.Constancia(
                origen="1000001/UPD1.pdf",
                tamano=1,
                modificado_ns=1,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                archivos=constancias.archivos_de(nic, [nic / "01_RECLAMO.pdf"]),
                job_id="trabajo-del-otro",
            ),
        )
        assert motor._contar_como_de_otro(run, path, "PC2")
        assert not motor._contar_como_de_otro(run, path, "PC2")
        assert motor._completar_lo_de_los_otros(run)
        assert run.trabajos_de_otros == ["trabajo-del-otro"]
        assert not run.contados_sin_constancia
        assert "1000001/UPD1.pdf" in {k.replace("\\", "/") for k in run.procesos}

    def test_tambien_lee_la_constancia_de_unas_actas_en_su_espejo(self, ajustes, tmp_path):
        origen, destino = tmp_path / "origen", tmp_path / "destino"
        motor = _motor(ajustes, {})
        run = FolderRun(id="r1", source=origen, destination=destino, task="split")
        path = origen / "00C003284" / "LIBRO.pdf"
        ruta = motor._ruta_de_la_constancia(run, path, actas=True)
        constancias.escribir(
            ruta,
            constancias.Constancia(
                origen="00C003284/LIBRO.pdf",
                tamano=1,
                modificado_ns=1,
                estado=constancias.EstadoDeEntrega.COMPLETA,
                job_id="trabajo-de-las-actas",
            ),
        )
        assert motor._contar_como_de_otro(run, path, "PC2")
        assert motor._completar_lo_de_los_otros(run)
        assert run.trabajos_de_otros == ["trabajo-de-las-actas"]


class TestElArchivoRetenido:
    @pytest.mark.parametrize("numero", [errno.EAGAIN, errno.EBUSY])
    def test_eagain_y_ebusy_al_renombrar_se_reintentan(self, tmp_path, monkeypatch, numero):
        desde, hasta = tmp_path / "a.pdf", tmp_path / "b.pdf"
        desde.write_bytes(b"%PDF")
        intentos = []
        reemplazar = os.replace

        def retenido(origen, destino):
            intentos.append(1)
            if len(intentos) == 1:
                raise OSError(numero, os.strerror(numero))
            reemplazar(origen, destino)

        monkeypatch.setattr(folders.os, "replace", retenido)
        monkeypatch.setattr(folders.time, "sleep", lambda _segundos: None)
        folders._mover(desde, hasta)
        assert hasta.exists() and len(intentos) == 2

    def test_la_copia_directa_nunca_pisa_un_archivo(self, tmp_path):
        desde = tmp_path / "a.pdf"
        desde.write_bytes(b"%PDF nuevo")
        carpeta = tmp_path / "nic"
        carpeta.mkdir()
        (carpeta / "01_RECLAMO.pdf").write_bytes(b"%PDF del operador")
        hasta, copiados = folders._copiar_directo(desde, carpeta, "01_RECLAMO.pdf")
        assert hasta.name == "01_RECLAMO (2).pdf" and copiados == len(b"%PDF nuevo")
        assert (carpeta / "01_RECLAMO.pdf").read_bytes() == b"%PDF del operador"
