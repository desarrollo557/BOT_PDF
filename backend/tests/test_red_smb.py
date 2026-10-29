"""Carpetas de red con el cliente SMB propio, contra un servidor de mentira.

Lo pidió el operador el 2026-10-20 con
«\\\\200.100.20.97\\afinia\\REPOSITORIO\\AFINIA\\BOLIVAR SUR\\COMERCIAL\\MAGANGUE»:
cualquier ruta de red, sin credenciales escritas en ningún archivo, y que si el
servidor pide usuario y clave se le pidan a él. Aquí el servidor es un
diccionario: se prueba el comportamiento del bot, no la red.
"""

from __future__ import annotations

import asyncio
import errno
import io
import stat
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest
from smbprotocol.exceptions import SMBAuthenticationError

from resolutions.adapters import red_smb
from resolutions.api.folders import FolderError, FolderRunner, SourceDisposition
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings

SERVIDOR = "200.100.20.97"
RAIZ = rf"\\{SERVIDOR}\afinia"
CARPETA = rf"{RAIZ}\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MAGANGUE"
USUARIO, CLAVE = r"SIAR\desarrollo", "secreta"


class ServidorDeMentira:
    """Lo mínimo de ``smbclient`` que usa el bot, sobre un árbol en memoria."""

    def __init__(self, archivos: dict[str, bytes], prohibidas: tuple[str, ...] = ()) -> None:
        self.archivos = {self._clave(ruta): datos for ruta, datos in archivos.items()}
        self.prohibidas = {self._clave(ruta) for ruta in prohibidas}
        self.sesiones: set[str] = set()
        self.descargas = 0
        #: Las cuentas que el servidor acepta: (usuario, clave).
        self.cuentas = {(USUARIO, CLAVE)}
        self.reinicios = 0

    @staticmethod
    def _clave(ruta: str) -> str:
        return ruta.replace("/", "\\").rstrip("\\").lower()

    def _es_carpeta(self, clave: str) -> bool:
        return any(nombre.startswith(clave + "\\") for nombre in self.archivos)

    def _sesion(self, ruta: str, username=None, password=None) -> None:
        if (username, password) not in self.cuentas or SERVIDOR not in self.sesiones:
            raise SMBAuthenticationError("Failed to authenticate with server")

    # -- la API de smbclient ----------------------------------------------------------

    def register_session(self, server, username=None, password=None, **_):
        if (username, password) not in self.cuentas:
            raise SMBAuthenticationError("Failed to authenticate with server")
        self.sesiones.add(server)

    def reset_connection_cache(self, **_):
        self.reinicios += 1
        self.sesiones.clear()

    def stat(self, ruta, **cuenta):
        self._sesion(ruta, **cuenta)
        clave = self._clave(ruta)
        if clave in self.archivos:
            return types.SimpleNamespace(st_mode=stat.S_IFREG, st_size=len(self.archivos[clave]), st_mtime_ns=7)
        if self._es_carpeta(clave) or clave == self._clave(RAIZ):
            return types.SimpleNamespace(st_mode=stat.S_IFDIR, st_size=0, st_mtime_ns=0)
        raise FileNotFoundError(errno.ENOENT, "no existe", ruta)

    def scandir(self, ruta, **cuenta):
        self._sesion(ruta, **cuenta)
        clave = self._clave(ruta)
        if clave in self.prohibidas:
            raise PermissionError(errno.EACCES, "acceso denegado", ruta)
        vistos: dict[str, bool] = {}
        for nombre in self.archivos:
            if nombre.startswith(clave + "\\"):
                resto = nombre[len(clave) + 1 :].split("\\")
                vistos[resto[0]] = vistos.get(resto[0], False) or len(resto) > 1
        for nombre, es_carpeta in vistos.items():
            completo = f"{clave}\\{nombre}"
            datos = self.archivos.get(completo, b"")
            yield types.SimpleNamespace(
                name=nombre.upper() if nombre.endswith(".pdf") else nombre.upper(),
                is_dir=lambda c=es_carpeta: c,
                stat=lambda d=datos: types.SimpleNamespace(st_size=len(d), st_mtime_ns=7),
            )

    def open_file(self, ruta, mode="r", **cuenta):
        self._sesion(ruta, **cuenta)
        self.descargas += 1
        return io.BytesIO(self.archivos[self._clave(ruta)])


@pytest.fixture
def servidor(monkeypatch):
    falso = ServidorDeMentira(
        {
            rf"{CARPETA}\210847\UPD2998726.pdf": b"%PDF-1.4 caja 210847",
            rf"{CARPETA}\910349\UPD2998266.pdf": b"%PDF-1.4 caja 910349",
            rf"{CARPETA}\_procesados\910349\VIEJO.pdf": b"%PDF-1.4 ya apartado",
            rf"{CARPETA}\SIN PERMISO\UPD1.pdf": b"%PDF-1.4 no se deja",
        },
        prohibidas=(rf"{CARPETA}\SIN PERMISO",),
    )
    modulo = types.ModuleType("smbclient")
    for nombre in ("register_session", "reset_connection_cache", "stat", "scandir", "open_file"):
        setattr(modulo, nombre, getattr(falso, nombre))
    monkeypatch.setitem(sys.modules, "smbclient", modulo)
    # Como en el contenedor: Linux, la red por este cliente.
    monkeypatch.setattr(red_smb, "NATIVA", False)
    red_smb.olvidar()
    yield falso
    red_smb.olvidar()


class TestLaRuta:
    def test_partes_de_una_ruta_de_red(self):
        partes = red_smb.partes(CARPETA)
        assert (partes.servidor, partes.recurso) == (SERVIDOR, "afinia")
        assert partes.raiz == RAIZ
        assert partes.unc == CARPETA
        assert partes.del_servicio == (
            f"//{SERVIDOR}/afinia/REPOSITORIO/AFINIA/BOLIVAR SUR/COMERCIAL/MAGANGUE"
        )
        assert red_smb.partes(partes.del_servicio).unc == CARPETA

    def test_lo_que_no_es_de_red(self):
        assert red_smb.partes(r"C:\Users\ana") is None
        assert red_smb.partes("/equipo/c/Users") is None
        assert not red_smb.es_de_red("")


class TestLasCredenciales:
    def test_sin_credenciales_el_servidor_las_pide(self, servidor):
        with pytest.raises(red_smb.CredencialesDeRed) as pregunta:
            red_smb.asegurar(CARPETA)
        assert pregunta.value.recurso == RAIZ
        assert pregunta.value.motivo == "El servidor pide usuario y clave"

    def test_con_la_clave_mala_lo_dice(self, servidor):
        with pytest.raises(red_smb.CredencialesDeRed, match="no son correctos"):
            red_smb.conectar(CARPETA, USUARIO, "otra")
        assert red_smb.conectados() == []

    def test_con_la_buena_entra_y_lo_recuerda_en_memoria(self, servidor):
        assert red_smb.conectar(CARPETA, USUARIO, CLAVE) == RAIZ
        assert red_smb.conectados() == [RAIZ]
        red_smb.asegurar(CARPETA)  # ya no pregunta

    def test_olvidar_borra_la_memoria(self, servidor):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        red_smb.olvidar(SERVIDOR)
        assert red_smb.conectados() == []
        with pytest.raises(red_smb.CredencialesDeRed):
            red_smb.asegurar(CARPETA)

    def test_sin_dominio_se_le_pone_el_del_equipo(self, servidor, monkeypatch):
        # Así lo escribió el operador el 2026-10-20 y el servidor lo trató
        # como invitado: sin el dominio, la cuenta no existe.
        monkeypatch.setenv(red_smb.VARIABLE_DE_DOMINIO, "SIAR")
        assert red_smb.conectar(CARPETA, "desarrollo", CLAVE) == RAIZ
        assert red_smb.con_dominio("desarrollo@siar.local") == "desarrollo@siar.local"
        assert red_smb.con_dominio(r"OTRO\ana") == r"OTRO\ana"
        monkeypatch.delenv(red_smb.VARIABLE_DE_DOMINIO)
        assert red_smb.con_dominio("ana") == "ana"

    def test_sin_dominio_tambien_vale_una_cuenta_del_propio_servidor(self, servidor, monkeypatch):
        # 2026-10-28: «server2», cuenta del equipo que comparte Z: con el
        # contenedor, iba como «SIAR\server2» y el cuadro volvía una y otra vez.
        servidor.cuentas = {("server2", "clave")}
        monkeypatch.setenv(red_smb.VARIABLE_DE_DOMINIO, "SIAR")
        assert red_smb.conectar(CARPETA, "server2", "clave") == RAIZ
        red_smb.asegurar(CARPETA)  # y queda recordada así, sin dominio
        with pytest.raises(red_smb.CredencialesDeRed, match="no el PIN"):
            red_smb.conectar(CARPETA, "server2", "mala")

    def test_entrar_otra_vez_con_la_misma_cuenta_no_cierra_la_sesion(self, servidor):
        # Dos peticiones que llegan a la vez con la misma respuesta: la
        # segunda no puede cerrarle la conexión a la primera.
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        antes = servidor.reinicios
        assert red_smb.conectar(CARPETA, USUARIO, CLAVE) == RAIZ
        assert servidor.reinicios == antes
        assert red_smb.es_carpeta(CARPETA)

    def test_dos_entradas_a_la_vez_entran_las_dos(self, servidor):
        import threading

        resultados: list = []

        def entrar():
            try:
                resultados.append(red_smb.conectar(CARPETA, USUARIO, CLAVE))
            except Exception as error:  # noqa: BLE001 - la prueba lo cuenta
                resultados.append(error)

        antes = servidor.reinicios
        hilos = [threading.Thread(target=entrar) for _ in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        assert resultados == [RAIZ] * 8
        # Una sola entrada de verdad: las otras siete encontraron la sesión hecha.
        assert servidor.reinicios == antes + 1

    def test_si_el_servidor_lo_trata_como_invitado_se_pregunta_otra_vez(self, servidor, monkeypatch):
        from smbprotocol.exceptions import SMBException

        def como_invitado(*_, **__):
            raise SMBException(
                "SMB encryption or signing was required but session was authenticated as a "
                "guest which does not support encryption or signing"
            )

        monkeypatch.setattr(sys.modules["smbclient"], "register_session", como_invitado)
        with pytest.raises(red_smb.CredencialesDeRed, match="no reconoció ese usuario"):
            red_smb.conectar(CARPETA, "desarrollo", CLAVE)

    def test_otra_negativa_del_protocolo_no_es_un_fallo_del_servicio(self, servidor, monkeypatch):
        from smbprotocol.exceptions import SMBException

        def rara(*_, **__):
            raise SMBException("algo que el servidor no acepta")

        monkeypatch.setattr(sys.modules["smbclient"], "register_session", rara)
        with pytest.raises(red_smb.RedNoDisponible, match="no aceptó la conexión"):
            red_smb.conectar(CARPETA, USUARIO, CLAVE)

    def test_si_la_sesion_cae_se_reconecta_sola(self, servidor):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        servidor.sesiones.clear()  # el servidor se reinició
        assert red_smb.es_carpeta(CARPETA)


def _sin_error(hacer, *argumentos):
    try:
        hacer(*argumentos)
    except OSError:
        pass


class TestLeer:
    def test_recorre_las_cajas_sin_apartados_y_avisa_lo_que_no_se_deja(self, servidor):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        avisos = []
        archivos = red_smb.recorrer(
            CARPETA, saltar=frozenset({"_PROCESADOS", "_procesados"}), al_fallar=lambda c, e: avisos.append(c)
        )
        nombres = [a.ruta.rsplit("/", 2)[-2:] for a in archivos]
        assert nombres == [["210847", "UPD2998726.PDF"], ["910349", "UPD2998266.PDF"]]
        assert archivos[0].tamano == len(b"%PDF-1.4 caja 210847")
        assert len(avisos) == 1 and avisos[0].endswith("SIN PERMISO")

    def test_trae_una_copia_entera(self, servidor, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        copia = red_smb.traer(rf"{CARPETA}\210847\UPD2998726.pdf", tmp_path / "a" / "UPD.pdf")
        assert copia.read_bytes() == b"%PDF-1.4 caja 210847"
        assert not list(tmp_path.rglob("*.part"))

    def test_las_descargas_siempre_dejan_un_turno_para_listar(self, monkeypatch, tmp_path):
        """Con tantas descargas como turnos, el recorrido no listaba ni una carpeta
        hasta que terminara alguna: minutos sin descubrir nada (2026-10-28)."""
        import threading

        monkeypatch.setattr(red_smb, "A_LA_VEZ_POR_SERVIDOR", 2)
        monkeypatch.setattr(red_smb, "_turnos", {})
        monkeypatch.setattr(red_smb, "_descargas", {})
        soltar, dentro, a_la_vez = threading.Event(), [], []

        def bajar(ruta, copiar):
            def copiando():
                dentro.append(1)
                a_la_vez.append(len(dentro))
                soltar.wait(5)
                dentro.pop()
                raise OSError("se corta aquí: sólo importa cuántas bajaban a la vez")

            return red_smb._con_turno(red_smb.partes(ruta), copiando)

        monkeypatch.setattr(red_smb, "_llamar", bajar)
        hilos = [
            threading.Thread(target=lambda n=n: _sin_error(red_smb.traer, rf"\\srv\recurso\{n}.pdf", tmp_path / f"{n}.pdf"))
            for n in range(2)
        ]
        for hilo in hilos:
            hilo.start()
        while not dentro:
            soltar.wait(0.01)
        try:
            # Con dos descargas pedidas, el listado entra sin esperar a ninguna.
            assert red_smb._con_turno(red_smb.partes(r"\\srv\recurso"), lambda: "listado") == "listado"
        finally:
            soltar.set()
            for hilo in hilos:
                hilo.join()
        assert max(a_la_vez) == 1

    def test_lista_subcarpetas_y_sabe_si_existe(self, servidor):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        assert "210847" in red_smb.carpetas(CARPETA)
        assert red_smb.es_carpeta(CARPETA)
        assert not red_smb.es_carpeta(rf"{CARPETA}\NO EXISTE")


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


def _motor(ajustes, registro, leidos):
    async def run_job(job):
        # El trabajo recibe una copia local, con la ruta del servidor dentro.
        leidos.append((job.filename, Path(job.source).read_bytes(), str(job.source)))
        carpeta = ajustes.output_dir / job.id
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "01_DOCUMENTO.pdf").write_bytes(b"%PDF-1.4 out")
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

    return FolderRunner(registro, ajustes, run_job, watch_interval=0.01)


def _correr(motor, origen, destino, **opciones):
    async def ir():
        run = motor.start(origen, str(destino), **opciones)
        for _ in range(500):
            if not run.active:
                return run
            await asyncio.sleep(0.01)
        return run

    return asyncio.run(ir())


class TestUnaCorridaDesdeLaRed:
    def test_procesa_cada_caja_de_la_red_y_no_deja_copias(self, servidor, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        leidos: list = []
        run = _correr(_motor(ajustes, JobRegistry(), leidos), CARPETA, tmp_path / "destino")

        assert run.state == "done" and run.processed == 2
        assert sorted(contenido for _, contenido, _ in leidos) == [
            b"%PDF-1.4 caja 210847",
            b"%PDF-1.4 caja 910349",
        ]
        # La copia conserva la ruta del servidor: el índice lee de ella el
        # municipio (MAGANGUE) y el NIC (la carpeta de la caja).
        assert all("MAGANGUE" in ruta for _, _, ruta in leidos)
        # Lo entregado, en el destino del equipo, con la estructura de la caja.
        assert (tmp_path / "destino" / "210847" / "UPD2998726" / "01_DOCUMENTO.pdf").exists()
        # Ninguna copia de la red se queda ocupando disco.
        assert not list((ajustes.upload_dir / "red").rglob("*.pdf"))
        # Y la pantalla enseña la ruta de red como la escribió el operador.
        assert run.as_dict()["source"] == CARPETA

    def test_relanzarla_no_vuelve_a_bajar_lo_entregado(self, servidor, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        registro = JobRegistry()
        _correr(_motor(ajustes, registro, []), CARPETA, tmp_path / "destino")
        bajados = servidor.descargas

        leidos: list = []
        segunda = _correr(_motor(ajustes, registro, leidos), CARPETA, tmp_path / "destino")
        assert segunda.ya_entregados == 2 and segunda.processed == 0
        assert leidos == [] and servidor.descargas == bajados

    def test_sin_credenciales_la_corrida_las_pide_antes_de_empezar(self, servidor, ajustes, tmp_path):
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir():
            motor.start(CARPETA, str(tmp_path / "destino"))

        with pytest.raises(red_smb.CredencialesDeRed):
            asyncio.run(ir())

    def test_el_original_de_la_red_no_se_mueve_ni_se_borra(self, servidor, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir(disposicion):
            motor.start(CARPETA, str(tmp_path / "destino"), disposition=disposicion)

        for disposicion in (SourceDisposition.MOVE, SourceDisposition.DELETE):
            with pytest.raises(FolderError, match="Dejarlo"):
                asyncio.run(ir(disposicion))

    def test_el_destino_va_en_el_equipo(self, servidor, ajustes):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir():
            motor.start(CARPETA, rf"{RAIZ}\SALIDA")

        with pytest.raises(FolderError, match="destino tiene que estar en este equipo"):
            asyncio.run(ir())


class TestLaPantallaRecibeUnaPregunta:
    def test_el_401_dice_que_recurso_y_por_que(self):
        import json

        from resolutions.api.main import _credenciales_de_red

        respuesta = asyncio.run(
            _credenciales_de_red(None, red_smb.CredencialesDeRed(RAIZ, "El servidor pide usuario y clave"))
        )
        assert respuesta.status_code == 401
        assert json.loads(respuesta.body)["detail"] == {
            "codigo": "credenciales_de_red",
            "recurso": RAIZ,
            "mensaje": f"El servidor pide usuario y clave: {RAIZ}",
        }

    def test_conectar_desde_la_pantalla(self, servidor):
        from resolutions.api.routers import red

        respuesta = asyncio.run(red.conectar({"ruta": CARPETA, "usuario": USUARIO, "clave": CLAVE}))
        assert respuesta == {"recurso": RAIZ, "conectado": True}
        assert asyncio.run(red.abiertas()) == {"recursos": [RAIZ]}

    def test_el_explorador_entra_a_la_red(self, servidor):
        from types import SimpleNamespace

        from resolutions.api.routers.carpetas import browse

        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        listado = asyncio.run(browse(SimpleNamespace(), CARPETA))
        assert listado["path"] == CARPETA
        assert listado["parent"] == rf"{RAIZ}\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL"
        assert {"name": "210847", "path": rf"{CARPETA}\210847"} in listado["folders"]
        raiz = asyncio.run(browse(SimpleNamespace(), RAIZ + "\\"))
        assert raiz["parent"] is None


class TestSinCreditos:
    """\\\\200.100.20.97, 2026-10-22: «Request requires 1 credits but only 0 credits are available»."""

    def test_se_espera_y_se_reintenta(self, monkeypatch):
        from resolutions.adapters import red_smb

        monkeypatch.setattr(red_smb, "ESPERAS_SIN_CREDITOS", (0.0, 0.0))
        intentos = []

        def hacer():
            intentos.append(1)
            if len(intentos) < 3:
                raise RuntimeError("Request requires 1 credits but only 0 credits are available")
            return "ok"

        assert red_smb._con_turno(red_smb.partes(r"\\srv\recurso\a.pdf"), hacer) == "ok"
        assert len(intentos) == 3

    def test_otro_error_no_se_reintenta(self, monkeypatch):
        import pytest

        from resolutions.adapters import red_smb

        monkeypatch.setattr(red_smb, "ESPERAS_SIN_CREDITOS", (0.0, 0.0))
        intentos = []

        def hacer():
            intentos.append(1)
            raise RuntimeError("otra cosa")

        with pytest.raises(RuntimeError):
            red_smb._con_turno(red_smb.partes(r"\\srv\recurso\a.pdf"), hacer)
        assert len(intentos) == 1


class TestUnaUnidadQueSeLeePorLaRed:
    r"""2026-10-28: «Z:\Shared with Me\KINGSPAN» daba cero PDF dentro de Docker.

    Docker monta vacías las unidades de red mapeadas («Y:») y los discos
    virtuales como WorkDrive («Z:»). El instalador las declara con su ruta de
    red y el bot las lee por el cliente SMB, sin que el operador deje de
    escribir «Z:\…». Aquí «Z:» es el recurso entero, como el que comparte
    WorkDrive, e «Y:» una carpeta honda, como la de SIARNAS.
    """

    @pytest.fixture
    def unidades(self, monkeypatch):
        from resolutions.api import rutas_del_equipo

        monkeypatch.setenv(
            rutas_del_equipo.VARIABLE,
            rf"Z:=//{SERVIDOR}/afinia;Y:=\\{SERVIDOR}\afinia\REPOSITORIO\AFINIA",
        )

    def test_la_letra_va_por_la_red_y_vuelve_con_su_letra(self, servidor, unidades):
        from resolutions.api.rutas_del_equipo import al_operador, al_servicio, raices

        assert al_servicio(r"Y:\BOLIVAR SUR\COMERCIAL") == (
            f"//{SERVIDOR}/afinia/REPOSITORIO/AFINIA/BOLIVAR SUR/COMERCIAL"
        )
        # El servidor no distingue mayúsculas, y la vuelta tampoco.
        assert al_operador(rf"\\{SERVIDOR}\AFINIA\repositorio\afinia\X") == r"Y:\X"
        assert al_operador(CARPETA) == r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE"
        assert al_operador(f"//{SERVIDOR}/afinia") == "Z:\\"
        assert {"name": "Disco Z:", "path": "Z:\\"} in raices()

    def test_el_explorador_la_recorre_con_su_letra(self, servidor, unidades):
        from types import SimpleNamespace

        from resolutions.api.routers.carpetas import browse

        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        raiz = asyncio.run(browse(SimpleNamespace(), "Y:\\"))
        assert raiz["path"] == "Y:\\" and raiz["parent"] is None
        assert {"name": "BOLIVAR SUR", "path": r"Y:\BOLIVAR SUR"} in raiz["folders"]
        caja = asyncio.run(browse(SimpleNamespace(), r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE"))
        assert caja["parent"] == r"Y:\BOLIVAR SUR\COMERCIAL"
        assert {"name": "210847", "path": r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE\210847"} in caja["folders"]
        # El recurso ya es «Disco Z:»: no se repite como «Red \\servidor\recurso».
        assert not any(d["name"].startswith("Red ") for d in raiz["drives"])

    def test_una_corrida_desde_la_letra(self, servidor, unidades, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        leidos: list = []
        origen = r"Z:\REPOSITORIO\AFINIA\BOLIVAR SUR\COMERCIAL\MAGANGUE"
        run = _correr(_motor(ajustes, JobRegistry(), leidos), origen, tmp_path / "destino")

        assert run.state == "done" and run.processed == 2
        assert (tmp_path / "destino" / "210847" / "UPD2998726" / "01_DOCUMENTO.pdf").exists()
        # Esa carpeta también está bajo «Y:», que es más honda: se nombra con ella.
        assert run.as_dict()["source"] == r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE"

    def test_sin_credenciales_se_preguntan_por_la_letra(self, servidor, unidades):
        import json

        from resolutions.api.main import _credenciales_de_red

        with pytest.raises(red_smb.CredencialesDeRed) as pregunta:
            red_smb.asegurar(f"//{SERVIDOR}/afinia/REPOSITORIO")
        respuesta = asyncio.run(_credenciales_de_red(None, pregunta.value))
        assert json.loads(respuesta.body)["detail"]["recurso"] == "Z:\\"
        # Y la pantalla conecta con lo que se le dio.
        from resolutions.api.routers import red

        conectado = asyncio.run(red.conectar({"ruta": "Z:\\", "usuario": USUARIO, "clave": CLAVE}))
        assert conectado["conectado"] is True

    def test_el_original_se_deja_y_el_destino_va_en_el_equipo(self, servidor, unidades, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir(destino, disposicion=SourceDisposition.LEAVE):
            motor.start(r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE", destino, disposition=disposicion)

        with pytest.raises(FolderError, match="Dejarlo"):
            asyncio.run(ir(str(tmp_path / "destino"), SourceDisposition.MOVE))
        # Antes se colaba: «Z:\SALIDA» no parecía de red y se creaba dentro del contenedor.
        with pytest.raises(FolderError, match="destino tiene que estar en este equipo"):
            asyncio.run(ir(r"Z:\SALIDA"))


class TestRetomarNoBajaLoCompleto:
    def test_lo_ya_completo_no_se_baja_de_la_red(self, servidor, ajustes, tmp_path):
        # 2026-10-28: «Retomar lo que falta» bajaba entero cada libro de la red
        # y sólo después miraba su constancia.
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        _correr(_motor(ajustes, JobRegistry(), []), CARPETA, tmp_path / "destino", tipo="diploma")
        bajados = servidor.descargas

        run = _correr(
            _motor(ajustes, JobRegistry(), []),
            CARPETA,
            tmp_path / "destino",
            tipo="diploma",
            retomar="faltantes",
        )

        assert run.ya_entregados == 2
        assert servidor.descargas == bajados
