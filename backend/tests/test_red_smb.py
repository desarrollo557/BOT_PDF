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
import threading
import time
import types
from dataclasses import replace
from pathlib import Path

import pytest
from smbprotocol.exceptions import SMBAuthenticationError, SMBConnectionClosed

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

    def open_file(self, ruta, mode="r", share_access=None, **cuenta):
        self._sesion(ruta, **cuenta)
        self.descargas += 1
        #: Cómo se abrió: «rwd» deja a los demás programas usarlo a la vez.
        self.compartido = share_access
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

    def test_se_lee_compartiendo_con_los_demas_programas(self, servidor, tmp_path):
        """2026-10-29: «está abierto en otro programa» en Z:. Se abría en
        exclusiva (permiso compartido 0): WorkDrive sincronizándolo, un visor o
        el propio bot sugiriendo el tipo bastaban para que fallara, y mientras
        se copiaba nadie más podía abrirlo."""
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        red_smb.traer(rf"{CARPETA}\210847\UPD2998726.pdf", tmp_path / "UPD.pdf")
        assert servidor.compartido == "rwd"
        servidor.compartido = None
        assert len(red_smb.firma(rf"{CARPETA}\210847\UPD2998726.pdf")) == 64
        assert servidor.compartido == "rwd"

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
    def test_un_acta_tal_cual_se_entrega_desde_la_copia_local(self, servidor, ajustes, tmp_path):
        """2026-10-29, Z:: «No se encontró «1RESOLUCIONES DE RECTORIA 03272-03275.pdf»:
        se movió, se renombró o se borró». Un PDF que ya era un acta se entrega
        tal cual, y se copiaba por su ruta de la red, que no es de este equipo."""
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        registro = JobRegistry()

        async def un_acta(job):
            registro.mark_done(job, {"inventario_actas": [{"acta": "001", "folios": "1-2"}]})

        motor = FolderRunner(registro, ajustes, un_acta, watch_interval=0.01)
        run = _correr(motor, rf"{CARPETA}\210847", tmp_path / "destino", task="both")

        assert run.state == "done" and run.processed == 1 and run.failed == 0
        entregado = tmp_path / "destino" / "210847" / "UPD2998726.PDF"
        assert entregado.read_bytes() == b"%PDF-1.4 caja 210847"

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

    def test_el_destino_de_red_sin_montar_dice_como_montarlo(self, servidor, ajustes):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir():
            motor.start(CARPETA, rf"{RAIZ}\SALIDA")

        with pytest.raises(FolderError, match="tiene que tenerla montada") as error:
            asyncio.run(ir())
        assert "montar-unidad-de-red.ps1" in str(error.value)

    def test_el_destino_de_red_montado_se_entrega_alli(self, servidor, ajustes, tmp_path, monkeypatch):
        """El operador, 2026-11-25: «la idea es colocar como ruta destino rutas en red»."""
        from resolutions.adapters import acceso

        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        montada = tmp_path / "montada"
        montada.mkdir()
        vistas: list[str] = []

        def montaje(ruta, montajes=None):
            vistas.append(ruta)
            return str(montada / "SALIDA")

        monkeypatch.setattr(acceso, "montaje_de_la_red", montaje)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir():
            corrida = motor.start(CARPETA, rf"{RAIZ}\SALIDA")
            motor.stop(corrida.id)
            return corrida

        corrida = asyncio.run(ir())
        assert corrida.destination == montada / "SALIDA"
        assert vistas and vistas[0].replace("\\", "/").lower().endswith("/salida")


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


class TestUnaCuentaQueSambaNoConoce:
    def test_se_pregunta_otra_vez_y_no_es_un_fallo_de_red(self, servidor, monkeypatch):
        # Samba la deja entrar como invitado y le borra la sesión:
        # «STATUS_USER_SESSION_DELETED», que salía como un 503 de red.
        class SesionBorrada(Exception):
            status = 0xC0000203

            def __init__(self):
                super().__init__("The remote user session has been deleted")

        def borrada(*_, **__):
            raise SesionBorrada()

        monkeypatch.setattr(sys.modules["smbclient"], "register_session", borrada)
        with pytest.raises(red_smb.CredencialesDeRed, match="no son correctos"):
            red_smb.conectar(CARPETA, "otra", "clave")


class TestSugerirElTipoSinBajarLoGrande:
    def test_un_pdf_grande_no_se_baja_solo_para_sugerir(self, servidor, monkeypatch):
        """2026-10-29: sugerir el tipo en WorkDrive tardó 24 min bajando PDF de 200 MB."""
        from resolutions.api.routers import reconocer

        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        ruta = red_smb.partes(rf"{CARPETA}\210847").del_servicio
        monkeypatch.setattr(reconocer, "TOPE_DE_LA_MUESTRA_EN_RED", 5)
        respuesta = reconocer._reconocer_en_la_red(ruta)
        assert respuesta["total"] == 1
        assert servidor.descargas == 0
        assert "no se bajó para sugerir el tipo" in respuesta["archivos"][0]["motivo"]


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

    def test_sin_recursos_en_el_servidor_tambien_se_espera(self, monkeypatch):
        """2026-10-29: el Windows que comparte Z: (WorkDrive) con diez PDF de 200 MB a la vez."""
        from resolutions.adapters import red_smb

        monkeypatch.setattr(red_smb, "ESPERAS_SIN_CREDITOS", (0.0, 0.0))
        intentos = []

        def hacer():
            intentos.append(1)
            if len(intentos) < 3:
                raise RuntimeError(
                    "[Error 0] [NtStatus 0xc000009a] Unknown NtStatus error returned "
                    "'STATUS_INSUFFICIENT_RESOURCES': '\\\\host.docker.internal\\BOTPDF-Z\\a.pdf'"
                )
            return "ok"

        assert red_smb._con_turno(red_smb.partes(r"\\srv\recurso\a.pdf"), hacer) == "ok"
        assert len(intentos) == 3
        assert red_smb._sin_creditos(
            RuntimeError("Insufficient system resources exist to complete the API. (3221225626)")
        )

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

    def test_la_pregunta_dice_que_cuenta_tiene_permiso(self, servidor, unidades, monkeypatch):
        r"""2026-10-29: en el otro equipo se escribía «server2» y el recurso de
        «Z:» sólo dejaba entrar a «SIAR1», la cuenta que instaló: el cuadro
        volvía una y otra vez sin decir cuál era la buena."""
        import json

        from resolutions.api import rutas_del_equipo
        from resolutions.api.main import _credenciales_de_red

        monkeypatch.setenv(rutas_del_equipo.VARIABLE_DE_CUENTAS, r"Z:=SERVER2\SIAR1,SIAR\otra;Y:=")
        with pytest.raises(red_smb.CredencialesDeRed) as pregunta:
            red_smb.conectar(f"//{SERVIDOR}/afinia", "server2", "mala")
        detalle = json.loads(asyncio.run(_credenciales_de_red(None, pregunta.value)).body)["detail"]
        assert detalle["usuario"] == r"SERVER2\SIAR1"
        assert r"sólo para SERVER2\SIAR1, SIAR\otra" in detalle["mensaje"]
        assert detalle["mensaje"].startswith("El usuario o la clave no son correctos")
        # Una unidad sin cuentas anotadas pregunta como siempre.
        assert rutas_del_equipo.cuentas_de(f"//{SERVIDOR}/afinia/REPOSITORIO/AFINIA") == []

    def test_el_original_se_deja_y_el_destino_va_en_el_equipo(self, servidor, unidades, ajustes, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        motor = _motor(ajustes, JobRegistry(), [])

        async def ir(destino, disposicion=SourceDisposition.LEAVE):
            motor.start(r"Y:\BOLIVAR SUR\COMERCIAL\MAGANGUE", destino, disposition=disposicion)

        with pytest.raises(FolderError, match="Dejarlo"):
            asyncio.run(ir(str(tmp_path / "destino"), SourceDisposition.MOVE))
        # Antes se colaba: «Z:\SALIDA» no parecía de red y se creaba dentro del contenedor.
        with pytest.raises(FolderError, match="tiene que tenerla montada"):
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


class _Lenta(io.BytesIO):
    """Un archivo de la red que tarda en cada bloque, como uno de 400 MB a 4 MB/s."""

    def read(self, n=-1):
        import time

        time.sleep(0.12)
        return super().read(n)


def _con_red_lenta(servidor, monkeypatch, ruta: str, tamano: int) -> bytes:
    datos = b"%PDF-1.4 " + b"x" * tamano
    servidor.archivos = {servidor._clave(ruta): datos}
    abrir = servidor.open_file

    def lento(ruta, mode="r", share_access=None, **cuenta):
        return _Lenta(abrir(ruta, mode, share_access, **cuenta).getvalue())

    monkeypatch.setattr(sys.modules["smbclient"], "open_file", lento)
    return datos


def _correr_mirando(motor, registro, origen, destino, **opciones):
    """Como ``_correr``, y con lo que la pantalla recibe: las tramas publicadas, cuatro veces por segundo."""

    async def ir():
        cola = registro.subscribe()
        run = motor.start(origen, str(destino), **opciones)
        tramas = []
        for _ in range(800):
            registro.flush()
            while not cola.empty():
                tramas.append(cola.get_nowait())
            if not run.active:
                break
            await asyncio.sleep(0.02)
        while not cola.empty():
            tramas.append(cola.get_nowait())
        return run, tramas

    return asyncio.run(ir())


class TestLaDescargaEnVivo:
    """El operador, 2026-11-09: «cuando esté un archivo o un PDF a procesar en la red y se esté
    bajando, que se muestre el progreso de descarga, el tamaño del archivo, esos detallitos»."""

    def test_traer_dice_cuanto_lleva_bajado(self, servidor, tmp_path):
        ruta = rf"{CARPETA}\GRANDE.pdf"
        datos = b"%PDF-1.4 " + b"x" * (3 * red_smb.BLOQUE + 1000)
        servidor.archivos[servidor._clave(ruta)] = datos
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        avisos = []
        red_smb.traer(ruta, tmp_path / "G.pdf", al_avanzar=lambda copiados, total: avisos.append((copiados, total)))
        total = len(datos)
        # En cuanto se abre, con su tamaño; después, bloque a bloque hasta el final.
        assert avisos == [(0, total), *[(n * red_smb.BLOQUE, total) for n in (1, 2, 3)], (total, total)]
        assert (tmp_path / "G.pdf").read_bytes() == datos

    def test_un_aviso_que_falla_no_corta_la_descarga(self, servidor, tmp_path):
        red_smb.conectar(CARPETA, USUARIO, CLAVE)

        def roto(_copiados, _total):
            raise RuntimeError("la pantalla no contesta")

        copia = red_smb.traer(rf"{CARPETA}\210847\UPD2998726.pdf", tmp_path / "a.pdf", al_avanzar=roto)
        assert copia.read_bytes() == b"%PDF-1.4 caja 210847"

    def test_el_registro_lo_lleva_en_el_trabajo_y_lo_quita_al_terminar(self, tmp_path):
        registro = JobRegistry()
        origen = tmp_path / "a.pdf"
        origen.write_bytes(b"%PDF-1.4")
        job = registro.create(filename="a.pdf", source=origen, size=410 * 1024 * 1024)
        registro.anotar_descarga(job.id, {"estado": "bajando", "bytes": 123 * 1024 * 1024, "total": 410 * 1024 * 1024, "velocidad": "3,5 MB/s"})
        trama = job.as_dict()["progress"]
        assert trama["descarga"]["bytes"] == 123 * 1024 * 1024
        assert trama["detail"] == "Bajando de la red · 123 de 410 MB · 3,5 MB/s"
        assert [cambiado.id for cambiado in registro.flush()] == [job.id]
        registro.anotar_descarga(job.id, None)
        assert job.as_dict()["progress"]["descarga"] is None and not job.as_dict()["progress"]["detail"]
        # Un trabajo que ya no está en curso no se toca.
        registro.mark_failed(job, "se detuvo")
        registro.anotar_descarga(job.id, {"estado": "bajando", "bytes": 1, "total": 2})
        assert job.progress.descarga is None

    def test_cancelado_a_media_descarga_no_se_queda_congelado(self, tmp_path):
        """Revisión, 2026-11-09: cancelar el PDF mientras baja dejaba «Bajando de la red · …» para siempre."""
        registro = JobRegistry()
        origen = tmp_path / "a.pdf"
        origen.write_bytes(b"%PDF-1.4")
        job = registro.create(filename="a.pdf", source=origen, size=10)
        registro.anotar_descarga(job.id, {"estado": "bajando", "bytes": 5, "total": 10, "velocidad": "1,0 MB/s"})
        registro.mark_cancelled(job)
        # Un aviso tardío del hilo no la vuelve a poner; el final la quita.
        registro.anotar_descarga(job.id, {"estado": "bajando", "bytes": 9, "total": 10, "velocidad": "1,0 MB/s"})
        assert job.progress.descarga["bytes"] == 5
        registro.anotar_descarga(job.id, None)
        assert job.progress.descarga is None and not job.progress.detail

    def test_la_pantalla_ve_bajar_el_pdf(self, servidor, ajustes, tmp_path, monkeypatch):
        datos = _con_red_lenta(servidor, monkeypatch, rf"{CARPETA}\210847\GRANDE.pdf", 4 * red_smb.BLOQUE)
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        registro = JobRegistry()
        run, tramas = _correr_mirando(_motor(ajustes, registro, []), registro, rf"{CARPETA}\210847", tmp_path / "destino")
        assert run.state == "done" and run.processed == 1

        de_trabajos = [t for t in tramas if t.get("kind") == "job"]
        descargas = [t["progress"]["descarga"] for t in de_trabajos if t["progress"].get("descarga")]
        # Primero, esperando su turno, con el tamaño del archivo.
        assert descargas[0]["estado"] == "esperando" and descargas[0]["total"] == len(datos)
        bajando = [d for d in descargas if d["estado"] == "bajando"]
        # Después lo bajado, subiendo hasta el total, con la velocidad.
        copiados = [d["bytes"] for d in bajando]
        assert len(copiados) >= 3 and copiados == sorted(copiados) and copiados[-1] == len(datos)
        assert any(d["velocidad"].endswith(("MB/s", "KB/s")) for d in bajando)
        assert any(t["progress"]["detail"].startswith("Bajando de la red") for t in de_trabajos if t["progress"].get("descarga"))
        # Y al terminar, nada: la tarjeta sigue con el proceso.
        ultima = de_trabajos[-1]["progress"]
        assert ultima["descarga"] is None

    def test_al_retomar_se_ve_en_la_corrida(self, servidor, ajustes, tmp_path, monkeypatch):
        """Al retomar, el PDF se baja antes de tener trabajo: su avance va en la corrida, una vez por segundo."""
        datos = _con_red_lenta(servidor, monkeypatch, rf"{CARPETA}\210847\GRANDE.pdf", 12 * red_smb.BLOQUE)
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        registro = JobRegistry()
        run, tramas = _correr_mirando(
            _motor(ajustes, registro, []), registro, rf"{CARPETA}\210847", tmp_path / "destino",
            tipo="diploma", retomar="revisar",
        )
        de_la_corrida = [t for t in tramas if t.get("kind") == "folder_run"]
        bajando = [b["descarga"] for t in de_la_corrida for b in t.get("bajando") or []]
        assert bajando and bajando[0]["estado"] == "esperando" and bajando[0]["total"] == len(datos)
        assert any(d["estado"] == "bajando" and d["bytes"] > 0 for d in bajando)
        # Al terminar de bajarlo, ya no está.
        assert de_la_corrida[-1]["bajando"] == []
        assert run.as_dict()["bajando"] == []


# -- el arranque rápido: la raíz de una vez y las carpetas pedidas por delante --------
#
# 2026-11-26: cada equipo tardaba de 3 a 28 min desde que se unía a la corrida hasta
# tomar su primer PDF. El origen de Magangué (~32.000 carpetas NIC, 21 ms cada listado)
# se recorría de a una carpeta: unos 10 min en serie antes de llegar a lo pendiente.

SERVICIO = red_smb.partes(CARPETA).del_servicio


def _plantar(servidor, *rutas: str, prohibidas: tuple[str, ...] = ()) -> None:
    """Cambia el árbol del servidor de mentira por éste, bajo CARPETA; cada archivo lleva su ruta dentro."""
    servidor.archivos = {
        servidor._clave(rf"{CARPETA}\{ruta}"): f"%PDF-1.4 {ruta}".encode() for ruta in rutas
    }
    servidor.prohibidas = {servidor._clave(rf"{CARPETA}\{ruta}") for ruta in prohibidas}


def _relativas(archivos) -> list[str]:
    return [archivo.ruta.removeprefix(SERVICIO + "/") for archivo in archivos]


def _esperar(condicion, segundos: float = 5.0) -> None:
    limite = time.monotonic() + segundos
    while not condicion():
        assert time.monotonic() < limite, "no llegó a tiempo"
        time.sleep(0.01)


class _Espia:
    """El ``scandir`` del servidor de mentira, mirado: qué se listó y cuántos a la vez.

    Además, puede hacer que unas carpetas tarden (``retrasos``), se queden
    colgadas hasta ``soltar`` (``esperan``) o fallen (``fallan``). Las carpetas,
    relativas a CARPETA.
    """

    def __init__(
        self,
        servidor,
        monkeypatch,
        *,
        retraso: float = 0.0,
        retrasos: dict[str, float] | None = None,
        esperan=(),
        soltar: threading.Event | None = None,
        fallan: dict[str, Exception] | None = None,
    ) -> None:
        self._original = servidor.scandir
        self._clave = servidor._clave
        self._retraso = retraso
        self._retrasos = {self._de(ruta): segundos for ruta, segundos in (retrasos or {}).items()}
        self._esperan = {self._de(ruta) for ruta in esperan}
        self._soltar = soltar
        self._fallan = {self._de(ruta): error for ruta, error in (fallan or {}).items()}
        self._cerrojo = threading.Lock()
        self.listadas: list[str] = []
        self.dentro = 0
        self.maximo = 0
        monkeypatch.setattr(sys.modules["smbclient"], "scandir", self.scandir)

    def _de(self, relativa: str) -> str:
        return self._clave(rf"{CARPETA}\{relativa}")

    def scandir(self, ruta, **cuenta):
        clave = self._clave(ruta)
        with self._cerrojo:
            self.listadas.append(clave.removeprefix(self._clave(CARPETA)).lstrip("\\"))
            self.dentro += 1
            self.maximo = max(self.maximo, self.dentro)
        try:
            time.sleep(self._retrasos.get(clave, self._retraso))
            if clave in self._esperan:
                self._soltar.wait(10)
            if clave in self._fallan:
                raise self._fallan[clave]
            yield from self._original(ruta, **cuenta)
        finally:
            with self._cerrojo:
                self.dentro -= 1


@pytest.fixture
def turnos(monkeypatch):
    """Cuatro turnos por servidor, como en el contenedor, sin los semáforos de otras pruebas."""
    monkeypatch.setattr(red_smb, "A_LA_VEZ_POR_SERVIDOR", 4)
    for nombre in ("_turnos", "_descargas", "_adelantos"):
        monkeypatch.setattr(red_smb, nombre, {})


#: Raíz con un PDF suelto y carpetas NIC con sus PDF, desordenados en el servidor.
DOS_NIVELES = (
    r"300\UPD3.pdf",
    r"100\UPD2.pdf",
    r"100\upd1.pdf",
    r"200\nota.txt",
    r"050\UPD9.pdf",
    r"200\UPD5.pdf",
    r"400\nota.txt",
    "SUELTO.pdf",
)
#: Con subcarpetas dentro de las carpetas, archivos entre ellas y un «_procesados».
TRES_NIVELES = (
    r"300\X\Y\UPD7.pdf",
    r"100\c.pdf",
    r"100\b\UPD4.pdf",
    r"100\a.pdf",
    r"100\_procesados\VIEJO.pdf",
    r"100\b\nota.txt",
    r"200\UPD5.pdf",
    r"200\d\e\UPD6.pdf",
    r"200\d\UPD8.pdf",
    "SUELTO.pdf",
)


class TestListarUnNivel:
    def test_archivos_y_subcarpetas_por_nombre_sin_entrar_ni_apartados(self, servidor, turnos, monkeypatch):
        _plantar(servidor, "b.pdf", "A.pdf", "nota.txt", r"Z\UPD1.pdf", r"m\UPD2.pdf", r"_procesados\VIEJO.pdf")
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        espia = _Espia(servidor, monkeypatch)

        archivos, carpetas = red_smb.listar_nivel(CARPETA, saltar=frozenset({"_Procesados"}))

        assert [archivo.ruta for archivo in archivos] == [f"{SERVICIO}/A.PDF", f"{SERVICIO}/B.PDF"]
        # El tamaño y la fecha, del mismo listado.
        assert (archivos[0].tamano, archivos[0].modificado_ns) == (len(b"%PDF-1.4 A.pdf"), 7)
        # «_PROCESADOS» se salta aunque se pidiera «_Procesados».
        assert carpetas == [f"{SERVICIO}/M", f"{SERVICIO}/Z"]
        # Un solo listado: las subcarpetas no se abren.
        assert espia.listadas == [""]

    def test_la_raiz_que_no_se_deja_leer_es_un_error_y_la_sesion_caida_se_olvida(self, servidor, turnos, monkeypatch):
        _plantar(servidor, r"100\UPD1.pdf", prohibidas=("",))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        with pytest.raises(PermissionError):
            red_smb.listar_nivel(CARPETA)
        assert red_smb.conectados() == [RAIZ]

        servidor.prohibidas = set()
        _Espia(servidor, monkeypatch, fallan={"": SMBConnectionClosed("la conexión se cerró")})
        with pytest.raises(red_smb.RedNoDisponible):
            red_smb.listar_nivel(CARPETA)
        # La próxima vez se vuelve a entrar con lo que ya se dio.
        assert red_smb.conectados() == []


class TestIterarCarpetas:
    @pytest.mark.parametrize(
        ("arbol", "orden"),
        [
            (DOS_NIVELES, ["050/UPD9.PDF", "100/UPD1.PDF", "100/UPD2.PDF", "200/UPD5.PDF", "300/UPD3.PDF"]),
            (
                TRES_NIVELES,
                [
                    "100/A.PDF",
                    "100/B/UPD4.PDF",
                    "100/C.PDF",
                    "200/D/E/UPD6.PDF",
                    "200/D/UPD8.PDF",
                    "200/UPD5.PDF",
                    "300/X/Y/UPD7.PDF",
                ],
            ),
        ],
        ids=["dos-niveles", "tres-niveles"],
    )
    def test_el_mismo_orden_que_iterar(self, servidor, turnos, monkeypatch, arbol, orden):
        _plantar(servidor, *arbol)
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        # Las primeras son las que más tardan en listarse: se entregan en el
        # orden dado, no en el que terminan sus listados.
        _Espia(servidor, monkeypatch, retrasos={"050": 0.15, "100": 0.15, "200": 0.08})
        saltar = frozenset({"_PROCESADOS"})
        sueltos, carpetas = red_smb.listar_nivel(CARPETA, saltar=saltar)

        obtenido = list(red_smb.iterar_carpetas(carpetas, saltar=saltar, adelantadas=4))

        assert _relativas(obtenido) == orden
        assert obtenido == [archivo for carpeta in carpetas for archivo in red_smb.iterar(carpeta, saltar=saltar)]
        # Con los sueltos de la raíz es el recorrido entero de antes: nada se pierde ni se repite.
        assert _relativas(sueltos) == ["SUELTO.PDF"]
        assert obtenido == [archivo for archivo in red_smb.iterar(CARPETA, saltar=saltar) if archivo not in sueltos]

    def test_una_carpeta_que_acaba_en_espacio_no_lo_pierde(self, servidor, turnos, monkeypatch):
        # «1000265 »: NTFS admite el espacio final si la creó un cliente SMB.
        # Pasada por ``partes``, que recorta la ruta entera, perdía su espacio y
        # se listaba otra que no existe: sus PDF no entraban en la corrida y,
        # con una hermana «1000265», ésa se leía dos veces (2026-11-26).
        _plantar(servidor, "100 \\UPD1.pdf", r"100\UPD2.pdf", r"200\UPD3.pdf")
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        fallos: list[str] = []

        sueltos, carpetas = red_smb.listar_nivel(CARPETA)
        obtenido = list(red_smb.iterar_carpetas(carpetas, al_fallar=lambda carpeta, _error: fallos.append(carpeta)))

        assert sueltos == [] and fallos == []
        assert obtenido == list(red_smb.iterar(CARPETA))
        assert sorted(_relativas(obtenido)) == ["100 /UPD1.PDF", "100/UPD2.PDF", "200/UPD3.PDF"]

    def test_varias_a_la_vez_y_nunca_mas_que_los_turnos(self, servidor, turnos, monkeypatch):
        nics = [f"{n:03d}" for n in range(12)]
        _plantar(servidor, *(rf"{nic}\UPD{nic}.pdf" for nic in nics))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        espia = _Espia(servidor, monkeypatch, retraso=0.05)

        obtenido = list(red_smb.iterar_carpetas([f"{SERVICIO}/{nic}" for nic in nics], adelantadas=4))

        assert _relativas(obtenido) == [f"{nic}/UPD{nic}.PDF" for nic in nics]
        assert espia.maximo > 1
        # Nunca más que los turnos del servidor, y ni siquiera todos: uno queda para bajar.
        assert espia.maximo <= red_smb.A_LA_VEZ_POR_SERVIDOR - 1

    @pytest.mark.parametrize("adelantadas", [1, 4, 10])
    def test_solo_se_adelantan_las_que_se_piden(self, servidor, turnos, monkeypatch, adelantadas):
        nics = [f"{n:03d}" for n in range(20)]
        _plantar(servidor, *(rf"{nic}\UPD{nic}.pdf" for nic in nics))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        espia = _Espia(servidor, monkeypatch)
        recorrido = red_smb.iterar_carpetas([f"{SERVICIO}/{nic}" for nic in nics], adelantadas=adelantadas)
        try:
            assert _relativas([next(recorrido)]) == ["000/UPD000.PDF"]
            # La que se lee y las «adelantadas» siguientes; más de los turnos, nunca.
            listadas = min(adelantadas, red_smb.A_LA_VEZ_POR_SERVIDOR) + 1
            _esperar(lambda: len(espia.listadas) >= listadas)
            time.sleep(0.1)  # y ninguna más mientras nadie lee
            assert sorted(espia.listadas) == nics[:listadas]
        finally:
            recorrido.close()

    def test_una_carpeta_que_no_se_deja_leer_va_a_al_fallar_y_se_sigue(self, servidor, turnos):
        _plantar(
            servidor,
            r"100\UPD1.pdf",
            r"200\UPD2.pdf",
            r"300\a.pdf",
            r"300\SUB\UPD3.pdf",
            r"400\UPD4.pdf",
            prohibidas=("200", r"300\SUB"),
        )
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        carpetas = [f"{SERVICIO}/{nic}" for nic in ("100", "200", "300", "400")]
        avisos: list = []

        obtenido = list(
            red_smb.iterar_carpetas(carpetas, al_fallar=lambda carpeta, error: avisos.append((carpeta, type(error))))
        )

        assert _relativas(obtenido) == ["100/UPD1.PDF", "300/A.PDF", "400/UPD4.PDF"]
        # Una de las dadas y una de sus subcarpetas, en orden.
        assert avisos == [(f"{SERVICIO}/200", PermissionError), (f"{SERVICIO}/300/SUB", PermissionError)]
        # Sin a quién avisar, se lanza.
        with pytest.raises(PermissionError):
            list(red_smb.iterar_carpetas(carpetas))

    @pytest.mark.parametrize(
        ("caida", "traducida"),
        [
            (SMBConnectionClosed("la conexión se cerró"), red_smb.RedNoDisponible),
            (SMBAuthenticationError("la sesión caducó"), red_smb.CredencialesDeRed),
        ],
        ids=["conexion-cerrada", "sesion-caducada"],
    )
    def test_una_sesion_caida_se_lanza_y_se_olvida(self, servidor, turnos, monkeypatch, caida, traducida):
        nics = ["100", "200", "300", "400"]
        _plantar(servidor, *(rf"{nic}\UPD{nic}.pdf" for nic in nics))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        _Espia(servidor, monkeypatch, fallan={"300": caida})
        avisos: list = []
        vistos: list = []

        with pytest.raises(traducida):
            for archivo in red_smb.iterar_carpetas(
                [f"{SERVICIO}/{nic}" for nic in nics], al_fallar=lambda carpeta, error: avisos.append(carpeta)
            ):
                vistos.append(archivo)

        # Lo de antes llegó, en orden; la sesión caída no es «una carpeta que no se deja leer».
        assert _relativas(vistos) == ["100/UPD100.PDF", "200/UPD200.PDF"]
        assert avisos == []
        # La próxima vez se vuelve a entrar con lo que ya se dio.
        assert red_smb.conectados() == []

    def test_cerrar_a_medias_no_espera_ni_deja_hilos(self, servidor, turnos, monkeypatch):
        nics = [f"{n:03d}" for n in range(12)]
        _plantar(servidor, *(rf"{nic}\UPD{nic}.pdf" for nic in nics))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        soltar = threading.Event()
        # Desde la tercera, cada listado se queda colgado, como un servidor que no contesta.
        espia = _Espia(servidor, monkeypatch, esperan=nics[2:], soltar=soltar)
        recorrido = red_smb.iterar_carpetas([f"{SERVICIO}/{nic}" for nic in nics], adelantadas=4)
        try:
            assert _relativas([next(recorrido)]) == ["000/UPD000.PDF"]
            _esperar(lambda: espia.dentro == 3)  # 002, 003 y 004, colgados con su turno
            inicio = time.monotonic()
            recorrido.close()
            # No espera a los listados colgados: nadie los va a leer.
            assert time.monotonic() - inicio < 1.0
        finally:
            soltar.set()
        for hilo in [h for h in threading.enumerate() if h.name.startswith("red-adelanto")]:
            hilo.join(5)
            assert not hilo.is_alive()
        # Lo que no había empezado no se pidió al servidor.
        assert not set(espia.listadas) & set(nics[5:])

    def test_el_adelanto_deja_siempre_un_turno_para_bajar(self, servidor, turnos, monkeypatch, tmp_path):
        """La reserva de las descargas al revés: con los listados por delante colgados, un PDF se baja igual."""
        monkeypatch.setattr(red_smb, "A_LA_VEZ_POR_SERVIDOR", 2)
        nics = ["100", "200", "300"]
        _plantar(servidor, *(rf"{nic}\UPD{nic}.pdf" for nic in nics))
        red_smb.conectar(CARPETA, USUARIO, CLAVE)
        soltar = threading.Event()
        espia = _Espia(servidor, monkeypatch, esperan=nics, soltar=soltar)
        vistos: list = []
        recorrido = threading.Thread(
            target=lambda: vistos.extend(
                red_smb.iterar_carpetas([f"{SERVICIO}/{nic}" for nic in nics], adelantadas=2)
            )
        )
        recorrido.start()
        try:
            _esperar(lambda: espia.dentro == 1)
            bajada = threading.Thread(
                target=red_smb.traer, args=(rf"{CARPETA}\200\UPD200.pdf", tmp_path / "UPD200.pdf")
            )
            bajada.start()
            bajada.join(3)
            assert not bajada.is_alive()
            assert (tmp_path / "UPD200.pdf").read_bytes() == servidor.archivos[servidor._clave(rf"{CARPETA}\200\UPD200.pdf")]
            # Con dos turnos, el adelanto lista de a uno: el otro era el de la descarga.
            assert espia.maximo == 1
        finally:
            soltar.set()
            recorrido.join(5)
        assert _relativas(vistos) == [f"{nic}/UPD{nic}.PDF" for nic in nics]

