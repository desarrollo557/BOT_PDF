"""Varios equipos sobre la misma fuente y el mismo destino, sin pisarse (2026-11-25).

El operador: «correr 4 PC al mismo tiempo sin que ninguno se pise los procesos,
consumiendo de la misma fuente y llevando al mismo destino», «no quiero en la
carpeta ningún archivo repetido, absolutamente ninguno», y «el destino debe ser
sólo uno: un solo FUID general, un solo Excel de métricas».

Lo que fija cada clase:

- ``TestLaClaveYElReparto``: la clave de un PDF es la misma se lea por unidad o
  por SMB, y cada carpeta NIC tiene un solo equipo preferido.
- ``TestLaVida``: un equipo está caído cuando su contador deja de cambiar 90 s
  medidos por quien mira, y nunca si quien mira no pudo mirar de seguido.
- ``TestLosReclamos``: un PDF lo toma un solo equipo; «hecho» lo cierra para
  todos; un fallo no lo paga otro; lo de un caído se toma; el que vuelve no
  entrega (la ficha).
- ``TestLaCorrida``: el segundo se une a la corrida del primero; con otras
  opciones o con otra versión del bot, no.
- ``TestLosCerrojos``: el turno de una carpeta es de uno a la vez entre equipos,
  reentrante en el mismo, y el de un caído se quita.
- ``TestCuatroEquiposALaVez``: cuatro equipos compitiendo por 300 PDF: cada uno
  sale una sola vez.
- ``TestRepetidos``: el control del cierre encuentra «(2)», contenidos iguales y
  carpetas «- copia».
- ``TestDosCorridasDeVerdad``: dos ``FolderRunner`` sobre el mismo origen y
  destino: cada PDF se procesa una vez, todos se entregan, nada repetido, y uno
  solo cierra.

El monitoreo de equipos (2026-11-26, «un monitoreo para ver los que están
conectados y poder desconectarlos»):

- ``TestElResumenDeLosEquipos``: la parte pura -- ``Vida.quieto_hace`` no
  apunta a nadie, «ya» manda sobre «calma», el ritmo con el reloj del propio
  equipo y la lista en su orden, con a quién se puede parar y por qué no;
  «en curso» cuenta todos aunque los nombres vayan cortados en veinte, y el
  que se está uniendo (sin corrida todavía) va con los de esta corrida.
- ``TestLasOrdenesDeParar``: el latido lleva ``unido``, ``orden`` y
  ``en_curso_n``; la orden llega una sola vez y «ya» manda sobre «calma»;
  ``latidos`` no lee el disco ni cambia los vivos, y retirado no da por vivo a
  nadie; quien se retira o cae se lleva su orden, y al que ya se retiró no se
  le deja ninguna; al que se está uniendo se le ordena parar y la guarda.
- ``TestPararUnEquipoDesdeElMonitoreo``: tres ``FolderRunner`` reales. Con
  calma, el ordenado entrega lo que tenía en curso, no toma nada más y queda
  STOPPED; «ya» lo para enseguida; al propio equipo, sin archivo; y lo que no
  se puede parar se dice en palabras.
- ``TestLosHuecosDelMonitoreo``: lo que encontró la revisión. «Detener» en
  plena unión retira la coordinación al volver de ella; la orden recibida
  mientras se une se cumple al unirse («calma» y «ya»); una orden a una
  corrida ya parada retira la coordinación que seguía latiendo; el que está
  cerrando no se detiene al vaciarse; el trabajador que esperaba ranura
  devuelve su PDF a la cola, en los dos bucles; y con la orden puesta la
  segunda pasada no se clasifica.
- ``TestDetenerAMitadDeUnaEntrega``: «Detener» o «Parar ya» con la entrega en
  su hilo -- que no se para -- espera a que acabe antes de soltar el reclamo:
  otro equipo no la entrega encima («(2)») y el PDF se cuenta una vez; si ya
  dejó su constancia completa, queda «hecho»; y la espera tiene tope.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolutions.adapters.coordinacion_en_disco import (
    AREA,
    Ajeno,
    CerrojoOcupado,
    Coordinacion,
    CoordinacionRechazada,
    Reclamo,
    ReclamoPerdido,
)
from resolutions.api.folders import FolderRun, FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.repetidos import buscar_repetidos
from resolutions.api.settings import Settings
from resolutions.application.coordinacion import (
    CORRIDA_TERMINADA,
    NO_ESTA_EN_LA_CORRIDA,
    OrdenNoPermitida,
    Vida,
    carpeta_de,
    clave_de,
    equipo_preferido,
    la_orden_que_manda,
    opciones_distintas,
    pdf_por_hora,
    resumen_de_los_equipos,
)

OPCIONES = {"task": "segment", "tipo": "auto", "lectura": "mistral", "agrupar": "documento"}
#: Un latido corto: las pruebas no esperan diez segundos por equipo.
LATIDO = 0.05


class Reloj:
    """Un reloj monótono que avanza cuando la prueba lo dice."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


def equipo(destino: Path, nombre: str, *, version: str = "v1", reloj=None, opciones=OPCIONES) -> Coordinacion:
    coordinacion = Coordinacion(
        destino, equipo=nombre, version=version, latido=LATIDO, **({"reloj": reloj} if reloj else {})
    )
    coordinacion.unirse(opciones, origen="MAGANGUE")
    return coordinacion


def caer(coordinacion: Coordinacion) -> None:
    """El equipo se cae: deja de latir y de mirar sin retirarse (su latido queda en el disco)."""
    coordinacion._parar.set()
    for hilo in (coordinacion._hilo, coordinacion._hilo_de_la_mirada):
        if hilo is not None:
            hilo.join()


def dar_por_caido(observador: Coordinacion, reloj: Reloj) -> None:
    """El observador mira los latidos de seguido durante más de 90 s de su reloj (y late)."""
    for _ in range(4):
        observador._mirar_a_los_demas()
        reloj.ahora += 40
    observador._latir()


class TestLaClaveYElReparto:
    def test_la_clave_no_distingue_mayusculas_ni_barras(self):
        assert clave_de("4133182\\UPD3119467.PDF") == clave_de("4133182/upd3119467.pdf")
        assert clave_de(" 4133182 / UPD3119467.pdf ") == clave_de("4133182/UPD3119467.pdf")

    def test_la_carpeta_es_la_del_nic(self):
        assert carpeta_de("4133182\\UPD3119467.pdf") == "4133182"
        assert carpeta_de("UPD3119467.pdf") == "upd3119467.pdf"

    def test_cada_carpeta_tiene_un_solo_preferido_y_el_reparto_es_parejo(self):
        equipos = ["PC1-a", "PC2-b", "PC3-c", "PC4-d"]
        cuentas = dict.fromkeys(equipos, 0)
        for nic in range(2000):
            preferido = equipo_preferido(str(nic), equipos)
            assert preferido == equipo_preferido(str(nic), list(reversed(equipos)))
            cuentas[preferido] += 1
        # Cada uno con su cuarta parte, más o menos.
        assert all(400 < cuenta < 600 for cuenta in cuentas.values()), cuentas

    def test_si_sale_un_equipo_solo_cambian_sus_carpetas(self):
        antes = ["PC1", "PC2", "PC3", "PC4"]
        despues = ["PC1", "PC2", "PC3"]
        for nic in range(500):
            uno, otro = equipo_preferido(str(nic), antes), equipo_preferido(str(nic), despues)
            if uno != "PC4":
                assert uno == otro

    def test_las_opciones_distintas_se_dicen_en_palabras(self):
        distintas = opciones_distintas({**OPCIONES, "lectura": "local"}, OPCIONES)
        assert len(distintas) == 1 and "lectura" in distintas[0] and "local" in distintas[0]


class TestLaFechaDelOrigenEntreEquipos:
    def test_la_misma_fecha_leida_en_segundos_enteros_es_la_misma(self):
        from resolutions.api.constancia import misma_fecha

        por_smb = 1_732_550_400_123_456_700
        montada = 1_732_550_400_000_000_000
        assert misma_fecha(por_smb, montada)
        assert misma_fecha(montada, por_smb)

    def test_cualquier_otra_diferencia_se_comprueba(self):
        from resolutions.api.constancia import misma_fecha

        assert not misma_fecha(1_732_550_400_123_456_700, 1_732_550_400_123_456_701)
        assert not misma_fecha(1_732_550_400_000_000_000, 1_732_550_401_500_000_000)


class TestLaVida:
    @staticmethod
    def _mirando(vida: Vida, desde: float, hasta: float) -> None:
        """Quien mira, mira de seguido cada diez segundos."""
        t = desde
        while t <= hasta:
            vida.mirada(t, bien=True)
            t += 10

    def test_nunca_visto_esta_vivo_hasta_que_pase_el_plazo(self):
        vida = Vida(caido=90)
        vida.mirada(0, bien=True)
        assert vida.vivo("PC2", 10)
        self._mirando(vida, 10, 95)
        assert vida.vivo("PC2", 95)
        self._mirando(vida, 100, 101)
        assert not vida.vivo("PC2", 101)

    def test_el_contador_que_cambia_lo_mantiene_vivo(self):
        vida = Vida(caido=90)
        vida.mirada(0, bien=True)
        for t in range(0, 300, 10):
            vida.mirada(float(t), bien=True)
            vida.observar("PC2", t, float(t))
        assert vida.vivo("PC2", 300)

    def test_sin_mirar_de_seguido_nadie_cae(self):
        # La red propia cortada: al volver, los demás no parecen muertos.
        vida = Vida(caido=90)
        vida.mirada(0, bien=True)
        vida.observar("PC2", 1, 0)
        vida.mirada(50, bien=False)
        self._mirando(vida, 200, 250)
        assert vida.vivo("PC2", 250)
        self._mirando(vida, 260, 291)
        assert not vida.vivo("PC2", 291)

    def test_con_la_mirada_propia_atrasada_nadie_cae(self):
        # El hilo que mira, colgado esperando a la red (una lectura de 467 s el
        # 2026-11-25): sin mirar no se sabe nada de los demás, y nadie cae.
        vida = Vida(caido=90)
        self._mirando(vida, 0, 100)
        vida.observar("PC2", 1, 0)
        assert not vida.vivo("PC2", 100)
        vida.observar("PC3", 1, 95)
        # Lleva 200 s sin poder mirar: ni PC3, que latía, ni PC2 se dan por caídos.
        assert vida.vivo("PC2", 300)
        assert vida.vivo("PC3", 300)
        # Al volver a mirar, el que de verdad no latió sigue caído.
        vida.mirada(305, bien=True)
        assert not vida.vivo("PC3", 305)
        assert vida.muerto_hace("PC3", 305) == pytest.approx(210)


class TestLosReclamos:
    def test_un_pdf_lo_toma_uno_solo(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            tomado = uno.reclamar("4133182/UPD1.pdf")
            assert isinstance(tomado, Reclamo)
            visto = otro.reclamar("4133182/upd1.PDF")
            assert isinstance(visto, Ajeno) and visto.estado == "en curso" and visto.equipo == "PC1"
            uno.terminar(tomado, trabajo="job-1")
            hecho = otro.reclamar("4133182/UPD1.pdf")
            assert isinstance(hecho, Ajeno) and hecho.estado == "hecho"
            assert uno.lo_hecho_en_la_corrida()[0] == ["job-1"]
        finally:
            uno.parar()
            otro.parar()

    def test_lo_que_fallo_en_uno_no_lo_paga_otro(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            uno.soltar(tomado, error="Mistral no respondió", reintentable=True)
            fallo = otro.fallo_de("NIC/UPD.pdf")
            assert fallo is not None and fallo.estado == "falló" and "Mistral" in fallo.error
            assert otro.estado_de("NIC/UPD.pdf").estado == "falló"
            # El suyo lo reintenta y, al entregarlo, el fallo se borra.
            otra_vez = uno.reclamar("NIC/UPD.pdf")
            uno.terminar(otra_vez, trabajo="job-2")
            assert otro.fallo_de("NIC/UPD.pdf") is None
        finally:
            uno.parar()
            otro.parar()

    def test_lo_de_un_equipo_caido_se_toma_y_el_que_vuelve_no_entrega(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1")
        otro = equipo(tmp_path, "PC2", reloj=reloj)
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            assert isinstance(otro.reclamar("NIC/UPD.pdf"), Ajeno)
            caer(uno)
            dar_por_caido(otro, reloj)
            nuevo = otro.reclamar("NIC/UPD.pdf")
            assert isinstance(nuevo, Reclamo)
            # El caído vuelve: su ficha ya no está, no entrega.
            with pytest.raises(ReclamoPerdido):
                uno.confirmar(tomado)
            otro.confirmar(nuevo)
        finally:
            otro.parar()

    def test_el_que_no_pudo_latir_no_entrega(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            caer(uno)
            reloj.ahora += 60
            with pytest.raises(ReclamoPerdido, match="demasiado sin poder escribir"):
                uno.confirmar(tomado)
        finally:
            pass


class TestLaCorrida:
    def test_el_segundo_se_une_a_la_corrida_del_primero(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        otro = equipo(tmp_path, "PC2")
        try:
            assert otro.corrida["id"] == uno.corrida["id"]
            assert len(otro.equipos_vivos()) >= 1
        finally:
            uno.parar()
            otro.parar()

    def test_con_otra_lectura_no_se_une(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        try:
            with pytest.raises(CoordinacionRechazada, match="lectura"):
                equipo(tmp_path, "PC2", opciones={**OPCIONES, "lectura": "local"})
        finally:
            uno.parar()

    def test_con_otra_version_del_bot_no_se_une(self, tmp_path):
        uno = equipo(tmp_path, "PC1", version="v1")
        try:
            with pytest.raises(CoordinacionRechazada, match="versión del bot"):
                equipo(tmp_path, "PC2", version="v2")
        finally:
            uno.parar()

    def test_sin_nadie_vivo_la_corrida_es_nueva(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        vieja = uno.corrida["id"]
        tomado = uno.reclamar("NIC/UPD.pdf")
        uno.terminar(tomado)
        uno.parar()
        nuevo = equipo(tmp_path, "PC2")
        try:
            assert nuevo.corrida["id"] != vieja
            # Lo de la corrida vieja no cuenta en la nueva.
            assert isinstance(nuevo.reclamar("NIC/UPD.pdf"), Reclamo)
        finally:
            nuevo.parar()

    def test_retirarse_borra_su_latido(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        uno.parar()
        assert not list((tmp_path / AREA / "equipos").glob("*.json"))


class TestLosCerrojos:
    def test_de_uno_a_la_vez_entre_equipos_y_reentrante(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        orden: list[str] = []
        dentro = threading.Event()
        try:

            def primero():
                # Dos veces el mismo: es reentrante.
                with uno.cerrojo("carpeta:4133182"), uno.cerrojo("carpeta:4133182"):
                    orden.append("uno entra")
                    dentro.set()
                    time.sleep(0.3)
                    orden.append("uno sale")

            hilo = threading.Thread(target=primero)
            hilo.start()
            dentro.wait(5)
            with otro.cerrojo("carpeta:4133182"):
                orden.append("otro entra")
            hilo.join()
            assert orden == ["uno entra", "uno sale", "otro entra"]
        finally:
            uno.parar()
            otro.parar()

    def test_el_de_un_caido_se_quita(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1")
        otro = equipo(tmp_path, "PC2", reloj=reloj)
        try:
            gestor = uno.cerrojo("carpeta:X")
            gestor.__enter__()  # lo toma y se cae con él
            caer(uno)
            dar_por_caido(otro, reloj)
            with otro.cerrojo("carpeta:X", espera_maxima=5):
                pass
        finally:
            otro.parar()

    def test_con_el_dueno_vivo_se_espera_y_se_rinde_al_plazo(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            with uno.cerrojo("carpeta:X"), pytest.raises(CerrojoOcupado), otro.cerrojo("carpeta:X", espera_maxima=0.3):
                pass
        finally:
            uno.parar()
            otro.parar()


class TestCuatroEquiposALaVez:
    def test_cada_pdf_sale_una_sola_vez(self, tmp_path):
        equipos = [equipo(tmp_path, f"PC{n}") for n in range(1, 5)]
        pdfs = [f"NIC{n // 3}/UPD{n}.pdf" for n in range(300)]
        hechos: list[tuple[str, str]] = []
        cerrojo = threading.Lock()
        try:

            def trabajar(coordinacion: Coordinacion) -> None:
                for relativa in pdfs:
                    tomado = coordinacion.reclamar(relativa)
                    if isinstance(tomado, Reclamo):
                        coordinacion.confirmar(tomado)
                        with cerrojo:
                            hechos.append((relativa, coordinacion.id))
                        coordinacion.terminar(tomado)

            hilos = [threading.Thread(target=trabajar, args=(c,)) for c in equipos]
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join()
            assert sorted(r for r, _ in hechos) == sorted(pdfs)
            assert len({r for r, _ in hechos}) == len(hechos)
        finally:
            for coordinacion in equipos:
                coordinacion.parar()


class TestLaCoordinacionContraUnServidorLento:
    """Lo que el 2026-11-25 se midió contra el Escritorio de un Windows compartido por
    siete PC: FLUSH de 1,06 s, renombres de 0,94 s, una lectura de 467 s y «Host is down»."""

    def test_crear_en_exclusiva_no_pide_fsync(self, tmp_path, monkeypatch):
        from resolutions.adapters import coordinacion_en_disco

        def prohibido(_fd):
            raise AssertionError("fsync no da exclusividad y costaba un segundo por archivo")

        monkeypatch.setattr(coordinacion_en_disco.os, "fsync", prohibido)
        ruta = tmp_path / "reclamo.json"
        assert coordinacion_en_disco._crear_en_exclusiva(ruta, {"ficha": "a"})
        assert not coordinacion_en_disco._crear_en_exclusiva(ruta, {"ficha": "b"})
        assert coordinacion_en_disco._leer(ruta) == {"ficha": "a"}

    def test_el_propio_en_curso_no_se_devuelve_otra_vez(self, tmp_path):
        from resolutions.adapters.coordinacion_en_disco import AQUI

        uno = equipo(tmp_path, "PC1")
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            assert isinstance(tomado, Reclamo)
            # Otro hilo del mismo equipo con el mismo PDF (entró dos veces en la cola).
            otra_vez = uno.reclamar("NIC/UPD.pdf")
            assert isinstance(otra_vez, Ajeno) and otra_vez.estado == AQUI
            # Suelto, se puede volver a tomar (la vuelta de reintento).
            uno.soltar(tomado)
            assert isinstance(uno.reclamar("NIC/UPD.pdf"), Reclamo)
        finally:
            uno.parar()

    def test_un_reclamo_propio_que_no_lleva_nadie_esta_libre(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        try:
            uno.reclamar("NIC/UPD.pdf")
            assert uno.estado_de("NIC/UPD.pdf").estado == "en curso"
            # No se pudo soltar (el destino caído) y ningún hilo lo lleva ya:
            # antes se esperaba a sí mismo para siempre y la corrida no cerraba.
            uno.en_curso.clear()
            assert uno.estado_de("NIC/UPD.pdf") is None
            assert isinstance(uno.reclamar("NIC/UPD.pdf"), Reclamo)
        finally:
            uno.parar()

    def test_la_barrera_espera_a_que_vuelva_el_latido_propio(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            # Un minuto sin poder escribir su latido (el destino sin contestar)...
            uno._latir = lambda: None
            time.sleep(0.1)
            reloj.ahora += 60
            assert not uno.puede_entregar()

            def vuelve():
                time.sleep(0.1)
                uno._ultimo_latido = reloj()

            hilo = threading.Thread(target=vuelve)
            hilo.start()
            # ...y vuelve: el PDF sigue siendo suyo y se entrega, sin tirar lo leído.
            uno.confirmar(tomado)
            hilo.join()
        finally:
            uno.parar()

    def test_el_latido_propio_no_espera_a_la_mirada(self, tmp_path, monkeypatch):
        uno = equipo(tmp_path, "PC1")
        try:
            mirar = uno._latidos_de_otros

            def lenta():
                time.sleep(1.0)
                return mirar()

            monkeypatch.setattr(uno, "_latidos_de_otros", lenta)
            antes = uno._contador
            time.sleep(0.6)
            # Con la mirada colgada en una lectura lenta, el latido sigue a su ritmo.
            assert uno._contador - antes >= 5
            assert uno.puede_entregar()
        finally:
            uno.parar()

    def test_unirse_no_desplaza_a_quien_late_tarde(self, tmp_path):
        uno = equipo(tmp_path, "PC1")
        pausado = threading.Event()
        pausado.set()
        latir = uno._latir
        uno._latir = lambda: None if pausado.is_set() else latir()
        try:

            def vuelve():
                # Su latido tarda más de lo que miraba antes quien se unía (≈2,5 latidos).
                time.sleep(0.6)
                pausado.clear()

            hilo = threading.Thread(target=vuelve)
            hilo.start()
            otro = Coordinacion(tmp_path, equipo="PC2", version="v1", latido=LATIDO, caido=3.0)
            otro.unirse(OPCIONES, origen="MAGANGUE")
            hilo.join()
            try:
                assert otro.corrida["id"] == uno.corrida["id"]
                assert uno.por_que_no_vale() is None
            finally:
                otro.parar()
        finally:
            uno.parar()

    def test_lo_hecho_sale_de_los_diarios_y_de_los_reclamos_que_faltan(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            for numero in range(3):
                uno.terminar(uno.reclamar(f"NIC/UPD{numero}.pdf"), trabajo=f"job-uno-{numero}")
                otro.terminar(otro.reclamar(f"NIC/UPDB{numero}.pdf"), trabajo=f"job-otro-{numero}")
            otro._volcar_el_diario()
            esperados = sorted([f"job-uno-{n}" for n in range(3)] + [f"job-otro-{n}" for n in range(3)])
            assert sorted(uno.lo_hecho_en_la_corrida()[0]) == esperados
            # Un equipo que cayó sin volcar su diario: lo suyo sale de sus reclamos.
            for diario in (tmp_path / AREA / "diario").glob(f"{otro.id}.jsonl"):
                diario.unlink()
            assert sorted(uno.lo_hecho_en_la_corrida()[0]) == esperados
        finally:
            uno.parar()
            otro.parar()

    def test_el_turno_espera_a_que_vuelva_el_destino(self, tmp_path, monkeypatch):
        import errno

        from resolutions.adapters import coordinacion_en_disco

        uno = equipo(tmp_path, "PC1")
        try:
            uno._dormir = lambda _segundos: None
            crear = coordinacion_en_disco._crear_en_exclusiva
            fallos = []

            def sin_red(ruta, datos):
                if ruta.suffix == ".lock" and len(fallos) < 2:
                    fallos.append(ruta)
                    raise OSError(errno.EHOSTDOWN, "Host is down")
                return crear(ruta, datos)

            monkeypatch.setattr(coordinacion_en_disco, "_crear_en_exclusiva", sin_red)
            # Los 36 «Host is down» del 2026-11-25: con el PDF ya leído y pagado.
            with uno.cerrojo("carpeta:4133182"):
                pass
            assert len(fallos) == 2
        finally:
            uno.parar()

    def test_la_barrera_no_espera_mas_alla_del_plazo_de_caido(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            uno._latir = lambda: None
            time.sleep(0.1)
            # Un hueco de latido tan largo que los demás pudieron darlo por caído
            # y quitarle el turno de la carpeta: aunque el reclamo siga siendo
            # suyo, no escribe.
            reloj.ahora += 100
            with pytest.raises(ReclamoPerdido, match="demasiado sin poder escribir"):
                uno.confirmar(tomado)

            # Y si el latido vuelve mientras espera, pero tras un hueco de esa
            # medida, tampoco.
            uno._ultimo_latido = reloj.ahora = 2000.0
            reloj.ahora += 60

            def vuelve_tarde():
                time.sleep(0.1)
                reloj.ahora += 35
                uno._ultimo_latido = reloj()

            hilo = threading.Thread(target=vuelve_tarde)
            hilo.start()
            with pytest.raises(ReclamoPerdido):
                uno.confirmar(tomado)
            hilo.join()
        finally:
            uno.parar()

    def test_una_mirada_lenta_no_da_por_caido_a_nadie(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        otro = equipo(tmp_path, "PC2")
        try:
            caer(uno)
            for _ in range(4):
                uno._mirar_a_los_demas()
                reloj.ahora += 20
            assert uno.vivo(otro.id)
            leer = uno._latidos_de_otros

            def lenta():
                # La lectura tarda 467 s (medido el 2026-11-25).
                reloj.ahora += 467
                return leer()

            uno._latidos_de_otros = lenta
            uno._mirar_a_los_demas()
            uno._latidos_de_otros = leer
            reloj.ahora += 10
            uno._mirar_a_los_demas()
            # Lo leído se fecha al terminar la lectura, y una mirada tan lenta no
            # cuenta como mirar de seguido: el que latía sigue vivo.
            assert uno.vivo(otro.id)
        finally:
            otro.parar()

    def test_el_que_cierra_no_cierra_si_no_pudo_mirar(self, tmp_path, monkeypatch):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            uno._mirar_a_los_demas()
            assert not uno.los_demas_terminaron()

            def sin_red():
                raise OSError("Host is down")

            monkeypatch.setattr(uno, "_latidos_de_otros", sin_red)
            assert not uno.los_demas_terminaron()
            # Un vivo cuyo latido está en la carpeta pero no se dejó leer sigue contando.
            monkeypatch.undo()

            def ilegible():
                uno._ilegibles = {otro.id}
                return {}

            monkeypatch.setattr(uno, "_latidos_de_otros", ilegible)
            assert not uno.los_demas_terminaron()
        finally:
            uno.parar()
            otro.parar()

    def test_el_hecho_que_no_se_pudo_escribir_se_reintenta(self, tmp_path, monkeypatch):
        from resolutions.adapters import coordinacion_en_disco

        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            tomado = uno.reclamar("NIC/UPD.pdf")
            # Sin sus hilos: sólo lo que hace la prueba.
            caer(uno)
            escribir = coordinacion_en_disco._escribir_entero
            monkeypatch.setattr(
                coordinacion_en_disco, "_escribir_entero", lambda ruta, datos: (_ for _ in ()).throw(OSError("Host is down"))
            )
            uno.terminar(tomado, trabajo="job-1")
            assert otro.estado_de("NIC/UPD.pdf").estado == "en curso"
            # Vuelve la red: la mirada lo deja «hecho».
            monkeypatch.setattr(coordinacion_en_disco, "_escribir_entero", escribir)
            uno._marcar_lo_pendiente()
            assert otro.estado_de("NIC/UPD.pdf").estado == "hecho"
            assert not uno._hechos_pendientes
        finally:
            uno.parar()
            otro.parar()

    def test_lo_pendiente_de_borrar_no_se_lleva_el_turno_vuelto_a_tomar(self, tmp_path):
        from resolutions.adapters.coordinacion_en_disco import clave_de

        uno = equipo(tmp_path, "PC1")
        try:
            ruta = tmp_path / AREA / "cerrojos" / f"{clave_de('carpeta:X')}.lock"
            with uno.cerrojo("carpeta:X"):
                # Un borrado que quedó pendiente de una vez anterior.
                uno._por_borrar.append(ruta)
                uno._borrar_lo_pendiente()
                assert ruta.exists()
            assert not ruta.exists()
        finally:
            uno.parar()

    def test_el_latido_viejo_de_un_arranque_caido_se_borra(self, tmp_path):
        import json

        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        try:
            caer(uno)
            viejo = tmp_path / AREA / "equipos" / "PC9-viejo.json"
            viejo.write_text(json.dumps({"id": "PC9-viejo", "corrida": "otra", "contador": 7}), encoding="utf-8")
            for _ in range(7):
                uno._mirar_a_los_demas()
                reloj.ahora += 40
            assert not viejo.exists()
        finally:
            uno._parar.set()


class TestRepetidos:
    def test_encuentra_nombres_contenidos_y_carpetas_repetidas(self, tmp_path):
        nic = tmp_path / "4133182"
        nic.mkdir()
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF uno")
        (nic / "01_RECLAMO (2).pdf").write_bytes(b"%PDF dos")
        (nic / "02_RECURSO.pdf").write_bytes(b"%PDF igual")
        (nic / "03_RECURSO.pdf").write_bytes(b"%PDF igual")
        (tmp_path / "4133182 - copia").mkdir()
        (tmp_path / "_reemplazados").mkdir()
        (tmp_path / "_reemplazados" / "01_RECLAMO (2).pdf").write_bytes(b"x")
        (tmp_path / AREA).mkdir()
        motivos = [r.en_palabras() for r in buscar_repetidos(tmp_path)]
        assert any("01_RECLAMO (2).pdf" in m and "nombre repetido" in m for m in motivos)
        assert any("02_RECURSO.pdf" in m and "03_RECURSO.pdf" in m and "mismo contenido" in m for m in motivos)
        assert any("4133182 - copia" in m and "carpeta repetida" in m for m in motivos)
        assert len(motivos) == 3

    def test_la_carpeta_que_trae_asi_la_fuente_no_cuenta(self, tmp_path):
        (tmp_path / "4133182 - copia").mkdir()
        assert buscar_repetidos(tmp_path, en_la_fuente=lambda relativa: True) == []

    def test_un_destino_limpio_no_tiene_repetidos(self, tmp_path):
        nic = tmp_path / "4133182"
        nic.mkdir()
        (nic / "01_RECLAMO.pdf").write_bytes(b"%PDF uno")
        (nic / "02_RECURSO.pdf").write_bytes(b"%PDF dos")
        assert buscar_repetidos(tmp_path) == []


# -- dos corridas de verdad --------------------------------------------------------


def _ajustes(tmp_path: Path, nombre: str) -> Settings:
    ajustes = replace(
        Settings(),
        upload_dir=tmp_path / nombre / "uploads",
        output_dir=tmp_path / nombre / "outputs",
        ledger_path=tmp_path / nombre / "inventory.jsonl",
        pausa_tras_fallos=0.01,
    )
    ajustes.ensure_directories()
    return ajustes


def _motor(
    ajustes: Settings, procesados: list[str], cerrojo: threading.Lock, *, tarda: float = 0.15
) -> FolderRunner:
    registro = JobRegistry()

    async def run_job(job):
        with cerrojo:
            procesados.append(job.filename)
        # Lo que tarda leer un PDF: así los equipos trabajan a la vez.
        await asyncio.sleep(tarda)
        if job.state.value == "cancelled":
            return
        carpeta = ajustes.output_dir / job.id
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"01_{Path(job.filename).stem}.pdf").write_bytes(f"%PDF {job.filename}".encode())
        registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

    motor = FolderRunner(registro, ajustes, run_job, watch_interval=0.01)
    motor.SEGUNDOS_DEL_LATIDO = LATIDO
    motor.ESPERA_DE_LOS_OTROS = 0.05
    return motor


def _todos_retirados(destino: Path) -> bool:
    """Ningún equipo sigue latiendo: o borró su latido, o lo dejó diciendo «terminado»."""
    import json

    return all(
        json.loads(ruta.read_text(encoding="utf-8")).get("estado") == "terminado"
        for ruta in (destino / AREA / "equipos").glob("*.json")
    )


class TestDosCorridasDeVerdad:
    def test_dos_equipos_procesan_cada_pdf_una_vez_y_entregan_todo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
        for nic in range(6):
            (origen / f"10000{nic}").mkdir(parents=True)
            for upd in range(3):
                (origen / f"10000{nic}" / f"UPD{nic}{upd}.pdf").write_bytes(f"%PDF-1.4 {nic}{upd}".encode())
        destino.mkdir()
        procesados: list[str] = []
        cerrojo = threading.Lock()
        uno = _motor(_ajustes(tmp_path, "pc1"), procesados, cerrojo)
        otro = _motor(_ajustes(tmp_path, "pc2"), procesados, cerrojo)

        async def correr():
            primera = uno.start(str(origen), str(destino))
            await asyncio.sleep(0.2)
            segunda = otro.start(str(origen), str(destino))
            for _ in range(1200):
                if not primera.active and not segunda.active:
                    break
                await asyncio.sleep(0.05)
            # Que se retiren del todo (el latido borrado).
            await asyncio.sleep(0.3)
            return primera, segunda

        primera, segunda = asyncio.run(correr())
        assert primera.state is RunState.DONE, primera.error
        assert segunda.state is RunState.DONE, segunda.error
        # Cada PDF una sola vez entre los dos equipos.
        assert sorted(procesados) == sorted({p for p in procesados})
        assert len(procesados) == 18
        # Los dos trabajaron.
        assert primera.processed > 0 and segunda.processed > 0
        assert primera.processed + segunda.processed == 18
        # Todo entregado, una vez, sin nada repetido.
        entregados = sorted(p.name for p in destino.rglob("*.pdf") if "_reemplazados" not in p.parts)
        assert len(entregados) == 18, entregados
        assert buscar_repetidos(destino) == []
        # Uno solo cerró, con lo de los dos contado.
        cerraron = [r for r in (primera, segunda) if not any("los cierra otro equipo" in a for a in r.avisos)]
        assert len(cerraron) == 1
        # Lo suyo procesado, y lo de los demás contado como ya entregado: los
        # Excel generales del que cierra llevan los 18.
        assert cerraron[0].processed + cerraron[0].ya_entregados == 18
        # Y la auditoría de la corrida, una sola, con los trabajos de los dos.
        trabajos, fallidos = cerraron[0].coordinacion.lo_hecho_en_la_corrida()
        assert len(set(trabajos)) == 18 and not fallidos

    def test_un_equipo_se_cuelga_los_demas_toman_lo_suyo_y_al_volver_no_entrega(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
        for nic in range(6):
            (origen / f"30000{nic}").mkdir(parents=True)
            for upd in range(2):
                (origen / f"30000{nic}" / f"UPD{nic}{upd}.pdf").write_bytes(f"%PDF-1.4 {nic}{upd}".encode())
        destino.mkdir()
        procesados: list[str] = []
        cerrojo = threading.Lock()
        sanos = [_motor(_ajustes(tmp_path, f"pc{n}"), procesados, cerrojo, tarda=0.2) for n in range(2)]
        for motor in sanos:
            motor.SEGUNDOS_PARA_DARLO_POR_CAIDO = 1.0
        # El que se cuelga: sus PDF no terminan de leerse hasta que «vuelve».
        ajustes_colgado = _ajustes(tmp_path, "colgado")
        registro = JobRegistry()
        vuelve = asyncio.Event()
        tomados: list[str] = []

        async def run_job_colgado(job):
            tomados.append(job.filename)
            await vuelve.wait()
            carpeta = ajustes_colgado.output_dir / job.id
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / f"01_{Path(job.filename).stem}.pdf").write_bytes(f"%PDF {job.filename}".encode())
            registro.mark_done(job, {"groups": [{"code": "01"}], "review_queue": []})

        colgado = FolderRunner(registro, ajustes_colgado, run_job_colgado, watch_interval=0.01)
        colgado.SEGUNDOS_DEL_LATIDO = LATIDO
        colgado.ESPERA_DE_LOS_OTROS = 0.05

        async def correr():
            del_colgado = colgado.start(str(origen), str(destino))
            for _ in range(200):
                if tomados:
                    break
                await asyncio.sleep(0.05)
            # Se cuelga: deja de latir con sus PDF reclamados.
            await asyncio.to_thread(caer, del_colgado.coordinacion)
            corridas = []
            for motor in sanos:
                corridas.append(motor.start(str(origen), str(destino)))
            for _ in range(1200):
                if not any(c.active for c in corridas):
                    break
                await asyncio.sleep(0.05)
            # Vuelve: termina de leer lo que tenía, pero ya no es suyo.
            vuelve.set()
            await asyncio.sleep(1.0)
            colgado.stop(del_colgado.id)
            await asyncio.sleep(0.3)
            return del_colgado, corridas

        del_colgado, corridas = asyncio.run(correr())
        for corrida in corridas:
            assert corrida.state is RunState.DONE, corrida.error
        assert tomados, "el colgado llegó a tomar algún PDF"
        # Todo entregado una vez por los sanos; lo del colgado, también.
        entregados = sorted(p.name for p in destino.rglob("*.pdf") if "_reemplazados" not in p.parts)
        assert len(entregados) == 12 and len(set(entregados)) == 12, entregados
        assert buscar_repetidos(destino) == []
        # El colgado no entregó nada: al volver, su ficha ya no estaba.
        assert del_colgado.delivered == 0
        assert any("Lo entrega el otro equipo" in a or "ya no tiene" in a for a in del_colgado.avisos)

    def test_cuatro_equipos_y_uno_se_detiene_a_la_mitad(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
        for nic in range(12):
            (origen / f"20000{nic:02d}").mkdir(parents=True)
            for upd in range(3):
                (origen / f"20000{nic:02d}" / f"UPD{nic:02d}{upd}.pdf").write_bytes(f"%PDF-1.4 {nic}{upd}".encode())
        destino.mkdir()
        procesados: list[str] = []
        cerrojo = threading.Lock()
        motores = [_motor(_ajustes(tmp_path, f"pc{n}"), procesados, cerrojo, tarda=0.3) for n in range(4)]

        async def correr():
            corridas = []
            for motor in motores:
                corridas.append(motor.start(str(origen), str(destino)))
                await asyncio.sleep(0.1)
            # Al rato, el operador detiene el segundo equipo.
            for _ in range(200):
                if corridas[1].processed >= 1:
                    break
                await asyncio.sleep(0.05)
            motores[1].stop(corridas[1].id)
            for _ in range(2400):
                if not any(c.active for c in corridas):
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
            return corridas

        corridas = asyncio.run(correr())
        assert corridas[1].state is RunState.STOPPED
        for n in (0, 2, 3):
            assert corridas[n].state is RunState.DONE, corridas[n].error
        # Todo entregado una vez: lo del detenido lo terminaron los demás.
        entregados = sorted(p.name for p in destino.rglob("*.pdf") if "_reemplazados" not in p.parts)
        assert len(entregados) == 36 and len(set(entregados)) == 36, entregados
        assert buscar_repetidos(destino) == []
        # Uno solo cerró, con los 36 contados y los 36 trabajos de la corrida.
        cerraron = [
            c for c in corridas if c.state is RunState.DONE and not any("los cierra otro equipo" in a for a in c.avisos)
        ]
        assert len(cerraron) == 1
        assert cerraron[0].processed + cerraron[0].ya_entregados == 36
        trabajos, _ = cerraron[0].coordinacion.lo_hecho_en_la_corrida()
        assert len(set(trabajos)) == 36
        assert _todos_retirados(destino)
        assert _todos_retirados(destino)


# -- el monitoreo de equipos (2026-11-26) ---------------------------------------


def _leido(ruta: Path) -> dict | None:
    """Un archivo de coordinación, como lo lee la coordinación: con reintentos si otro lo reemplaza."""
    from resolutions.adapters.coordinacion_en_disco import _leer

    return _leer(ruta)


def _esperar(condicion, segundos: float = 5.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return bool(condicion())


class TestElResumenDeLosEquipos:
    CORRIDA = "20261126-094756-d1057b"

    def test_quieto_hace_no_apunta_a_nadie(self):
        # ``Vida.vivo`` cuenta como visto al que no conoce: preguntar desde la
        # pantalla cambiaba ``equipos_vivos`` y el reparto. ``quieto_hace`` no.
        vida = Vida(caido=90)
        vida.mirada(0, bien=True)
        assert vida.quieto_hace("PC2", 10) is None
        assert vida.vivos(10) == []
        vida.observar("PC2", 1, 5)
        assert vida.quieto_hace("PC2", 12.5) == pytest.approx(7.5)

    def test_ya_manda_sobre_calma_y_entre_iguales_la_primera(self):
        calma, ya = {"modo": "calma", "por": "A"}, {"modo": "ya", "por": "B"}
        assert la_orden_que_manda(calma, ya) == ya
        assert la_orden_que_manda(ya, calma) == ya
        assert la_orden_que_manda(None, calma) == calma
        assert la_orden_que_manda(calma, {"modo": "calma", "por": "C"})["por"] == "A"
        assert la_orden_que_manda({"modo": "otra"}, None) is None

    def test_el_ritmo_sale_del_reloj_del_propio_equipo(self):
        assert pdf_por_hora(88, "2026-11-26T09:00:00-05:00", "2026-11-26T10:00:00-05:00") == 88.0
        assert pdf_por_hora(399, "2026-11-26T09:00:00-05:00", "2026-11-26T09:30:00-05:00") == 798.0
        # Menos de cinco minutos unido -- el arranque dentro --: todavía no dice nada.
        assert pdf_por_hora(10, "2026-11-26T09:00:00-05:00", "2026-11-26T09:04:59-05:00") is None
        assert pdf_por_hora(10, None, "2026-11-26T10:00:00-05:00") is None
        assert pdf_por_hora(10, "ayer", "hoy") is None

    def _latido(self, equipo: str, id_: str, **datos) -> dict:
        return {
            "id": id_,
            "equipo": equipo,
            "version": "v1",
            "corrida": self.CORRIDA,
            "estado": "procesando",
            "vivo": True,
            "hechos": 10,
            "en_curso": ["NIC/UPD1.pdf"],
            "unido": "2026-11-26T09:00:00-05:00",
            "escrito": "2026-11-26T10:00:00-05:00",
            "quieto_hace": 4.24,
            "orden": None,
            **datos,
        }

    def test_la_lista_va_en_su_orden_y_dice_a_quien_se_puede_parar(self):
        calma = {"para": "COORDINADORTIC-1e52b0", "modo": "calma", "por": "SIAR-ad21be", "equipo_que_ordena": "SIAR",
                 "operador": "siar", "cuando": "2026-11-26T10:00:00-05:00"}
        latidos = {
            "VISUALIZADOR-ff0e6a": self._latido("VISUALIZADOR", "VISUALIZADOR-ff0e6a", vivo=False),
            "ANALISSIG-000000": self._latido("ANALISSIG", "ANALISSIG-000000", corrida="otra", version="v0"),
            "DESKTOP-UMCOEU8-abc": self._latido("DESKTOP-UMCOEU8", "DESKTOP-UMCOEU8-abc", orden={**calma, "modo": "ya"}),
            "DESARROLLADOR-fa12b8": self._latido("DESARROLLADOR", "DESARROLLADOR-fa12b8", estado="cerrando"),
            "COORDINADORTIC-1e52b0": self._latido("COORDINADORTIC", "COORDINADORTIC-1e52b0", orden=calma),
            "SIAR-ad21be": self._latido("SIAR", "SIAR-ad21be", hechos=399, en_curso=[f"N/U{n}.pdf" for n in range(8)]),
        }
        resumen = resumen_de_los_equipos(latidos, este="SIAR-ad21be", corrida=self.CORRIDA, version="v1", activa=True)
        assert {k: resumen[k] for k in ("compartida", "corrida", "version", "este", "activa")} == {
            "compartida": True, "corrida": self.CORRIDA, "version": "v1", "este": "SIAR-ad21be", "activa": True,
        }
        # Los de esta corrida primero, luego los vivos, luego el propio, y por nombre.
        assert [e["id"] for e in resumen["equipos"]] == [
            "SIAR-ad21be",
            "COORDINADORTIC-1e52b0",
            "DESARROLLADOR-fa12b8",
            "DESKTOP-UMCOEU8-abc",
            "VISUALIZADOR-ff0e6a",
            "ANALISSIG-000000",
        ]
        fila = {e["id"]: e for e in resumen["equipos"]}
        propio = fila["SIAR-ad21be"]
        assert propio["este"] and propio["en_curso"] == 8 and propio["pdf_por_hora"] == 399.0
        assert propio["quieto_hace"] == 4.2 and propio["se_puede_parar"] and propio["por_que_no"] is None
        # Con «calma» todavía se le puede dar «ya»; con «ya», nada más.
        assert fila["COORDINADORTIC-1e52b0"]["se_puede_parar"]
        assert fila["COORDINADORTIC-1e52b0"]["orden"] == {k: v for k, v in calma.items() if k != "para"}
        assert not fila["DESKTOP-UMCOEU8-abc"]["se_puede_parar"]
        assert "Parar ya" in fila["DESKTOP-UMCOEU8-abc"]["por_que_no"]
        assert fila["VISUALIZADOR-ff0e6a"]["por_que_no"] == (
            "«VISUALIZADOR-ff0e6a» ya no late: sus PDF los toman los demás solos y su latido se borra a los 3 minutos."
        )
        assert fila["DESARROLLADOR-fa12b8"]["por_que_no"] == (
            "«DESARROLLADOR-fa12b8» está cerrando la corrida: termina solo en unos minutos."
        )
        otra = fila["ANALISSIG-000000"]
        assert not otra["de_esta_corrida"] and not otra["misma_version"] and otra["por_que_no"] == NO_ESTA_EN_LA_CORRIDA
        # Con la corrida de este equipo ya terminada, no se le ordena nada a nadie.
        terminada = resumen_de_los_equipos(latidos, este="SIAR-ad21be", corrida=self.CORRIDA, version="v1", activa=False)
        assert {e["por_que_no"] for e in terminada["equipos"]} == {CORRIDA_TERMINADA}

    def test_en_curso_cuenta_todos_aunque_los_nombres_vayan_cortados(self):
        # El latido lleva hasta veinte nombres: con 25 a la vez la pantalla decía 20.
        nombres = [f"N/U{n}.pdf" for n in range(20)]
        latidos = {
            "PC1-a": self._latido("PC1", "PC1-a", en_curso=nombres, en_curso_n=25),
            # El latido de una versión sin ``en_curso_n``: por sus nombres.
            "PC2-b": self._latido("PC2", "PC2-b", en_curso=nombres[:3]),
            "PC3-c": self._latido("PC3", "PC3-c", en_curso=nombres, en_curso_n="muchos"),
            "PC4-d": self._latido("PC4", "PC4-d", en_curso=nombres, en_curso_n=True),
        }
        resumen = resumen_de_los_equipos(latidos, este="PC1-a", corrida=self.CORRIDA, version="v1", activa=True)
        assert {e["id"]: e["en_curso"] for e in resumen["equipos"]} == {
            "PC1-a": 25, "PC2-b": 3, "PC3-c": 20, "PC4-d": 20,
        }

    def test_el_que_se_esta_uniendo_va_con_los_de_esta_corrida(self):
        # Mientras se une late sin corrida: salía aparte, como de otra corrida,
        # sin botones, y «Parar todos con calma» no lo alcanzaba.
        latidos = {
            "SIAR-ad21be": self._latido("SIAR", "SIAR-ad21be"),
            "ENTRANTE-123456": self._latido(
                "ENTRANTE", "ENTRANTE-123456", corrida=None, estado="uniéndose", hechos=0, en_curso=[], unido=None,
            ),
            # Sin corrida y sin estar uniéndose, o uniéndose cuando ya lleva otra: aparte.
            "RARO-000000": self._latido("RARO", "RARO-000000", corrida=None),
            "ANALISSIG-000000": self._latido("ANALISSIG", "ANALISSIG-000000", corrida="otra", estado="uniéndose"),
        }
        resumen = resumen_de_los_equipos(latidos, este="SIAR-ad21be", corrida=self.CORRIDA, version="v1", activa=True)
        assert [e["id"] for e in resumen["equipos"]] == [
            "SIAR-ad21be", "ENTRANTE-123456", "ANALISSIG-000000", "RARO-000000",
        ]
        fila = {e["id"]: e for e in resumen["equipos"]}
        entrante = fila["ENTRANTE-123456"]
        assert entrante["de_esta_corrida"] and entrante["corrida"] is None and entrante["estado"] == "uniéndose"
        assert entrante["se_puede_parar"] and entrante["por_que_no"] is None
        assert not fila["RARO-000000"]["de_esta_corrida"] and not fila["ANALISSIG-000000"]["de_esta_corrida"]
        # Una lista sin corrida propia no tiene a nadie «de esta corrida».
        sin_corrida = resumen_de_los_equipos(latidos, este="SIAR-ad21be", corrida=None, version="v1", activa=True)
        assert not any(e["de_esta_corrida"] for e in sin_corrida["equipos"])


class TestLasOrdenesDeParar:
    def test_el_latido_lleva_unido_y_orden(self, tmp_path):
        from datetime import datetime

        uno = equipo(tmp_path, "PC1")
        ruta = tmp_path / AREA / "equipos" / f"{uno.id}.json"
        try:
            latido = _leido(ruta)
            assert latido["unido"] == uno.unido and datetime.fromisoformat(latido["unido"]).tzinfo is not None
            assert latido["orden"] is None
            uno.ordenar_parar(uno.id, "calma", "prueba")
            assert _esperar(lambda: ((_leido(ruta) or {}).get("orden") or {}).get("modo") == "calma")
        finally:
            uno.parar()

    def test_la_orden_llega_una_sola_vez_y_ya_manda_sobre_calma(self, tmp_path, monkeypatch):
        from resolutions.adapters import coordinacion_en_disco

        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        recibidas: list[dict] = []
        otro.al_recibir_orden = recibidas.append
        ruta = tmp_path / AREA / "ordenes" / f"{otro.id}.json"
        escribir = coordinacion_en_disco._escribir_entero
        escritas: list[dict] = []

        def escribir_contando(destino, datos):
            if destino == ruta:
                escritas.append(dict(datos))
            escribir(destino, datos)

        monkeypatch.setattr(coordinacion_en_disco, "_escribir_entero", escribir_contando)
        try:
            dada = uno.ordenar_parar(otro.id, "calma", "operador de prueba")
            assert _leido(ruta) == dada
            assert dada["para"] == otro.id and dada["por"] == uno.id and dada["equipo_que_ordena"] == "PC1"
            assert dada["modo"] == "calma" and dada["operador"] == "operador de prueba" and dada["cuando"]
            # La mirada del otro la lee en su vuelta, y una sola vez aunque el archivo siga ahí.
            assert _esperar(lambda: recibidas)
            time.sleep(10 * LATIDO)
            assert [r["modo"] for r in recibidas] == ["calma"] and otro.orden["modo"] == "calma"
            # La misma otra vez no hace nada: ni se reescribe.
            assert uno.ordenar_parar(otro.id, "calma") == dada
            assert len(escritas) == 1
            # «ya» manda sobre «calma»: se escribe y llega otra vez.
            uno.ordenar_parar(otro.id, "ya")
            assert _esperar(lambda: len(recibidas) == 2)
            assert recibidas[1]["modo"] == "ya" and len(escritas) == 2
            # Y una «calma» después de «ya» se ignora: ni se escribe ni se recibe.
            assert uno.ordenar_parar(otro.id, "calma")["modo"] == "ya"
            assert len(escritas) == 2 and _leido(ruta)["modo"] == "ya"
            assert not otro.recibir_orden(dada)
            time.sleep(10 * LATIDO)
            assert len(recibidas) == 2 and otro.orden["modo"] == "ya"
            # Su latido lleva la orden que cumple, y quien la dio la ve en su foto.
            latido = tmp_path / AREA / "equipos" / f"{otro.id}.json"
            assert _esperar(lambda: (((_leido(latido) or {}).get("orden")) or {}).get("modo") == "ya")
            assert uno.latidos()[otro.id]["orden"]["modo"] == "ya"
        finally:
            monkeypatch.undo()
            uno.parar()
            otro.parar()

    def test_un_aviso_que_falla_no_tumba_la_mirada(self, tmp_path):
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")

        def roto(_orden):
            raise RuntimeError("la corrida no contesta")

        otro.al_recibir_orden = roto
        try:
            uno.ordenar_parar(otro.id, "calma")
            assert _esperar(lambda: otro.orden is not None)
            # La mirada sigue: el «ya» de después también llega.
            uno.ordenar_parar(otro.id, "ya")
            assert _esperar(lambda: otro.orden["modo"] == "ya")
            assert otro._hilo_de_la_mirada.is_alive()
        finally:
            uno.parar()
            otro.parar()

    def test_latidos_no_lee_el_disco_ni_cambia_los_vivos(self, tmp_path, monkeypatch):
        from resolutions.adapters import coordinacion_en_disco

        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        try:
            assert _esperar(lambda: otro.id in uno.latidos())
            # Sin sus hilos: sólo lo que hace la prueba. Pero sin dejar a «uno»
            # retirado: retirado, ya no da por vivo a nadie.
            caer(uno)
            uno._parar.clear()
            caer(otro)
            vivos = uno.equipos_vivos()
            # Uno que la mirada nunca observó: ``Vida.vivo`` lo habría contado entre los vivos.
            uno._foto["PC9-nuevo"] = {
                "id": "PC9-nuevo", "equipo": "PC9", "corrida": uno.corrida["id"], "contador": 1, "estado": "procesando",
            }

            def prohibido(*_args, **_kwargs):
                raise AssertionError("latidos() no lee el destino")

            monkeypatch.setattr(coordinacion_en_disco, "_leer", prohibido)
            monkeypatch.setattr(coordinacion_en_disco.Path, "glob", prohibido)
            monkeypatch.setattr(coordinacion_en_disco.Path, "read_text", prohibido)
            monkeypatch.setattr(uno, "_latidos_de_otros", prohibido)
            latidos = uno.latidos()
            assert set(latidos) == {uno.id, otro.id, "PC9-nuevo"}
            assert latidos[otro.id]["vivo"] and latidos[otro.id]["quieto_hace"] is not None
            assert latidos["PC9-nuevo"]["vivo"] and latidos["PC9-nuevo"]["quieto_hace"] is None
            assert latidos[uno.id]["unido"] == uno.unido and latidos[uno.id]["quieto_hace"] >= 0
            assert uno.equipos_vivos() == vivos
        finally:
            monkeypatch.undo()

    def test_quien_se_retira_o_cae_se_lleva_su_orden(self, tmp_path):
        reloj = Reloj()
        uno = equipo(tmp_path, "PC1", reloj=reloj)
        otro, tercero = equipo(tmp_path, "PC2"), equipo(tmp_path, "PC3")
        ordenes = tmp_path / AREA / "ordenes"
        try:
            uno.ordenar_parar(otro.id, "calma")
            uno.ordenar_parar(tercero.id, "calma")
            assert (ordenes / f"{otro.id}.json").exists() and (ordenes / f"{tercero.id}.json").exists()
            # El que se retira borra la suya.
            otro.parar()
            assert not (ordenes / f"{otro.id}.json").exists()
            # La del que cae la borra, con su latido, quien lo ve caído hace rato.
            caer(tercero)
            caer(uno)
            for _ in range(7):
                uno._mirar_a_los_demas()
                reloj.ahora += 40
            assert not (ordenes / f"{tercero.id}.json").exists()
            assert not (tmp_path / AREA / "equipos" / f"{tercero.id}.json").exists()
            assert tercero.id not in uno.latidos()
        finally:
            uno._parar.set()

    def test_a_un_equipo_que_ya_se_retiro_no_se_le_deja_orden(self, tmp_path):
        # Se retiró después de la última mirada: la orden quedaba en ``ordenes/``
        # para siempre -- nadie la iba a leer ni a borrar -- y se daba por puesta.
        from resolutions.adapters.coordinacion_en_disco import _escribir_entero

        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        equipos, ordenes = tmp_path / AREA / "equipos", tmp_path / AREA / "ordenes"
        try:
            assert _esperar(lambda: otro.id in uno.latidos())
            otro.parar()
            with pytest.raises(OrdenNoPermitida, match="ya se retiró"):
                uno.ordenar_parar(otro.id, "calma", "prueba")
            # El que se retiró sin poder borrar su latido: lo deja diciendo «terminado».
            _escribir_entero(equipos / f"{otro.id}.json", {"id": otro.id, "estado": "terminado", "contador": 99})
            with pytest.raises(OrdenNoPermitida, match="ya se retiró"):
                uno.ordenar_parar(otro.id, "ya")
            assert not list(ordenes.glob("*.json"))
            # Un latido que está y no se deja leer no dice nada: se reintenta, sin dejar la orden.
            (equipos / "PC3-ilegible.json").write_text("{", encoding="utf-8")
            with pytest.raises(OSError, match="no se deja leer"):
                uno.ordenar_parar("PC3-ilegible", "calma")
            assert not list(ordenes.glob("*.json"))
        finally:
            uno.parar()

    def test_el_latido_cuenta_todos_los_en_curso(self, tmp_path):
        # Los nombres van cortados en veinte; ``en_curso_n``, todos.
        uno, otro = equipo(tmp_path, "PC1"), equipo(tmp_path, "PC2")
        ruta = tmp_path / AREA / "equipos" / f"{uno.id}.json"
        try:
            uno.en_curso = {f"clave{n}": f"7000{n:02d}/UPD{n}.pdf" for n in range(25)}
            uno._latir()
            latido = _leido(ruta)
            assert len(latido["en_curso"]) == 20 and latido["en_curso_n"] == 25
            assert uno.latidos()[uno.id]["en_curso_n"] == 25
            # Quien lo mira cuenta los veinticinco, no los veinte nombres.
            assert _esperar(lambda: (otro.latidos().get(uno.id) or {}).get("en_curso_n") == 25)
            resumen = resumen_de_los_equipos(
                otro.latidos(), este=otro.id, corrida=otro.corrida["id"], version="v1", activa=True
            )
            assert next(e for e in resumen["equipos"] if e["id"] == uno.id)["en_curso"] == 25
        finally:
            uno.en_curso = {}
            uno.parar()
            otro.parar()

    def test_retirado_no_da_por_vivo_a_nadie(self, tmp_path):
        # Con la corrida terminada, ``parar`` congela la foto y la mirada, y la
        # mirada «atrasada» daba vivos a todos: la tarjeta terminada decía
        # «5 vivos · 980 PDF/h» con los puntos latiendo horas después.
        reloj = Reloj()
        uno, otro = equipo(tmp_path, "PC1", reloj=reloj), equipo(tmp_path, "PC2")
        try:
            assert _esperar(lambda: (uno.latidos().get(otro.id) or {}).get("estado") == "procesando")
            assert uno.latidos()[otro.id]["vivo"]
            uno.parar()
            reloj.ahora += 3 * 3600
            latidos = uno.latidos()
            assert latidos[otro.id]["vivo"] is False and latidos[otro.id]["estado"] == "procesando"
            assert latidos[uno.id]["vivo"] is False and latidos[uno.id]["estado"] == "terminado"
            resumen = resumen_de_los_equipos(
                latidos, este=uno.id, corrida=uno.corrida["id"], version="v1", activa=False
            )
            assert not any(e["vivo"] for e in resumen["equipos"])
            assert {e["por_que_no"] for e in resumen["equipos"]} == {CORRIDA_TERMINADA}
        finally:
            uno.parar()
            otro.parar()

    def test_al_que_se_esta_uniendo_se_le_ordena_parar_y_la_guarda(self, tmp_path):
        # Mientras espera para unirse late sin corrida y «uniéndose». Su mirada
        # ya corre -- el latido arranca al empezar ``unirse`` -- y guarda la
        # orden aunque la corrida todavía no le haya dicho a quién avisar.
        uno = equipo(tmp_path, "PC1")
        entrante = Coordinacion(tmp_path, equipo="PC2", version="v1", latido=LATIDO)
        latido = tmp_path / AREA / "equipos" / f"{entrante.id}.json"
        hilo = threading.Thread(target=entrante.unirse, args=(OPCIONES,), kwargs={"origen": "MAGANGUE"}, daemon=True)
        try:
            # El turno de la corrida, tomado: el que llega espera dentro de ``unirse``.
            with uno.cerrojo("corrida"):
                hilo.start()
                assert _esperar(lambda: (uno.latidos().get(entrante.id) or {}).get("estado") == "uniéndose")
                resumen = resumen_de_los_equipos(
                    uno.latidos(), este=uno.id, corrida=uno.corrida["id"], version="v1", activa=True
                )
                fila = next(e for e in resumen["equipos"] if e["id"] == entrante.id)
                assert fila["corrida"] is None and fila["de_esta_corrida"] and fila["vivo"]
                assert fila["se_puede_parar"] and fila["por_que_no"] is None
                assert entrante.al_recibir_orden is None
                uno.ordenar_parar(entrante.id, "calma", "prueba")
                assert _esperar(lambda: (entrante.orden or {}).get("modo") == "calma")
                assert entrante.corrida is None, "todavía se estaba uniendo"
            hilo.join(timeout=30)
            assert not hilo.is_alive()
            # Ya unido, la orden sigue en pie y su latido la lleva.
            assert entrante.corrida["id"] == uno.corrida["id"] and entrante.orden["modo"] == "calma"
            assert _esperar(lambda: (((_leido(latido) or {}).get("orden")) or {}).get("modo") == "calma")
        finally:
            uno.parar()
            entrante.parar()


def _vigilar(motor: FolderRunner) -> dict:
    """Lo que hace la corrida de ``motor`` con la orden de parar: lo que tenía en curso y lo que tomó después."""
    vigilado: dict = {"en_curso_al_ordenar": {}, "tomados_tras_la_orden": [], "ordenes": []}
    consumir, obedecer = motor._consume, motor._obedecer

    async def consumir_vigilado(run, path):
        if run.parando is not None:
            vigilado["tomados_tras_la_orden"].append(str(path))
        await consumir(run, path)

    def obedecer_vigilado(run_id, orden):
        run = motor.get(run_id)
        if run is not None and not vigilado["ordenes"]:
            vigilado["en_curso_al_ordenar"] = dict(run.en_curso)
        vigilado["ordenes"].append(dict(orden))
        obedecer(run_id, orden)

    motor._consume = consumir_vigilado
    motor._obedecer = obedecer_vigilado
    return vigilado


def _origen_y_destino(tmp_path: Path, base: int, *, nics: int = 12, upds: int = 3) -> tuple[Path, Path]:
    origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
    for nic in range(nics):
        carpeta = origen / f"{base}{nic:02d}"
        carpeta.mkdir(parents=True)
        for upd in range(upds):
            (carpeta / f"UPD{base}{nic:02d}{upd}.pdf").write_bytes(f"%PDF-1.4 {base} {nic} {upd}".encode())
    destino.mkdir()
    return origen, destino


def _entregados(destino: Path) -> list[str]:
    return sorted(p.name for p in destino.rglob("*.pdf") if "_reemplazados" not in p.parts)


def _cerraron(corridas) -> list:
    return [c for c in corridas if c.state is RunState.DONE and not any("los cierra otro equipo" in a for a in c.avisos)]


class TestPararUnEquipoDesdeElMonitoreo:
    @staticmethod
    def _motores(tmp_path: Path, cuantos: int, *, tarda: float = 0.3) -> list[FolderRunner]:
        procesados: list[str] = []
        cerrojo = threading.Lock()
        motores = [_motor(_ajustes(tmp_path, f"pc{n}"), procesados, cerrojo, tarda=tarda) for n in range(cuantos)]
        for motor in motores:
            motor.ESPERA_AL_VACIARSE = 0.05
        return motores

    @staticmethod
    async def _hasta_que_lea(corrida, segundos: float = 10.0) -> None:
        """Hasta que el equipo haya entregado alguno y tenga otro leyéndose."""
        limite = time.monotonic() + segundos
        while time.monotonic() < limite and not (corrida.processed >= 1 and corrida.en_curso):
            await asyncio.sleep(0.02)
        assert corrida.processed >= 1 and corrida.en_curso, "el equipo no llegó a leer nada"

    @staticmethod
    async def _hasta_que_terminen(corridas) -> None:
        for _ in range(2400):
            if not any(c.active for c in corridas):
                break
            await asyncio.sleep(0.05)
        # Que se retiren del todo (el latido borrado).
        await asyncio.sleep(0.3)

    def test_con_calma_entrega_lo_suyo_no_toma_nada_y_los_demas_acaban(self, tmp_path, monkeypatch):
        from resolutions.api.jobs import JobState

        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 4000)
        motores = self._motores(tmp_path, 3)
        vigilado = _vigilar(motores[1])

        async def correr():
            corridas = []
            for motor in motores:
                corridas.append(motor.start(str(origen), str(destino), paralelo=2))
                await asyncio.sleep(0.1)
            await self._hasta_que_lea(corridas[1])
            # Desde la pantalla del primero: «Parar con calma» al segundo.
            respuesta = await asyncio.to_thread(
                motores[0].ordenar_parar, corridas[0].id, corridas[1].coordinacion.id, "calma", "prueba"
            )
            await self._hasta_que_terminen(corridas)
            return corridas, respuesta

        corridas, respuesta = asyncio.run(correr())
        ordenada = corridas[1]
        # La respuesta ya trae la orden en su fila, aunque el otro todavía no la hubiera leído.
        fila = next(e for e in respuesta["equipos"] if e["id"] == ordenada.coordinacion.id)
        assert fila["orden"]["modo"] == "calma" and fila["orden"]["por"] == corridas[0].coordinacion.id
        # Se detuvo por la orden, y lo dice.
        assert ordenada.state is RunState.STOPPED, ordenada.error
        assert ordenada.parando["modo"] == "calma"
        assert "Parar con calma" in ordenada.detenido_por and "prueba" in ordenada.detenido_por
        assert any("ordenó «Parar con calma»" in aviso for aviso in ordenada.avisos)
        # Lo que tenía en curso se entregó: nada se canceló.
        assert vigilado["en_curso_al_ordenar"], "tenía PDF leyéndose al recibir la orden"
        registro = motores[1]._registry
        for job_id in vigilado["en_curso_al_ordenar"]:
            assert registro.get(job_id).state is JobState.DONE
        assert not [job.filename for job in registro.list() if job.state is JobState.CANCELLED]
        # Y después de la orden no tomó nada nuevo.
        assert vigilado["tomados_tras_la_orden"] == []
        # Los demás terminan, con todo entregado una vez y uno solo cerrando.
        for n in (0, 2):
            assert corridas[n].state is RunState.DONE, corridas[n].error
        entregados = _entregados(destino)
        assert len(entregados) == 36 and len(set(entregados)) == 36, entregados
        assert buscar_repetidos(destino) == []
        cerraron = _cerraron(corridas)
        assert len(cerraron) == 1
        assert cerraron[0].processed + cerraron[0].ya_entregados == 36
        assert _todos_retirados(destino)
        assert not list((destino / AREA / "ordenes").glob("*.json"))

    def test_ya_lo_para_enseguida_y_lo_suyo_lo_terminan_los_demas(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 5000)
        motores = self._motores(tmp_path, 3)

        async def correr():
            corridas = []
            for motor in motores:
                corridas.append(motor.start(str(origen), str(destino), paralelo=2))
                await asyncio.sleep(0.1)
            await self._hasta_que_lea(corridas[1])
            antes = time.monotonic()
            await asyncio.to_thread(
                motores[2].ordenar_parar, corridas[2].id, corridas[1].coordinacion.id, "ya", "prueba"
            )
            while corridas[1].active and time.monotonic() - antes < 10:
                await asyncio.sleep(0.02)
            tardo = time.monotonic() - antes
            await self._hasta_que_terminen(corridas)
            return corridas, tardo

        corridas, tardo = asyncio.run(correr())
        ordenada = corridas[1]
        assert ordenada.state is RunState.STOPPED
        assert tardo < 2.0, f"«Parar ya» tardó {tardo:.1f} s"
        assert "Parar ya" in ordenada.detenido_por and "prueba" in ordenada.detenido_por
        for n in (0, 2):
            assert corridas[n].state is RunState.DONE, corridas[n].error
        # Lo que estaba leyendo lo terminaron los demás: todo entregado una vez.
        entregados = _entregados(destino)
        assert len(entregados) == 36 and len(set(entregados)) == 36, entregados
        assert buscar_repetidos(destino) == []
        assert len(_cerraron(corridas)) == 1
        assert _todos_retirados(destino)
        assert not list((destino / AREA / "ordenes").glob("*.json"))

    def test_con_calma_al_propio_equipo_sin_archivo(self, tmp_path, monkeypatch):
        from resolutions.api.jobs import JobState

        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 6000, nics=4)
        (motor,) = self._motores(tmp_path, 1)
        vigilado = _vigilar(motor)

        async def correr():
            corrida = motor.start(str(origen), str(destino), paralelo=2)
            await self._hasta_que_lea(corrida)
            # Desde su propia pantalla: directo, sin pasar por el destino.
            respuesta = motor.ordenar_parar(corrida.id, corrida.coordinacion.id, "calma", "prueba")
            sin_archivo = not list((destino / AREA / "ordenes").glob("*.json"))
            await self._hasta_que_terminen([corrida])
            return corrida, respuesta, sin_archivo

        corrida, respuesta, sin_archivo = asyncio.run(correr())
        assert sin_archivo
        propio = next(e for e in respuesta["equipos"] if e["este"])
        assert propio["orden"]["modo"] == "calma" and propio["se_puede_parar"]
        assert corrida.state is RunState.STOPPED and "Parar con calma" in corrida.detenido_por
        assert vigilado["en_curso_al_ordenar"]
        for job_id in vigilado["en_curso_al_ordenar"]:
            assert motor._registry.get(job_id).state is JobState.DONE
        assert vigilado["tomados_tras_la_orden"] == []
        # Lo que quedaba en la cola no se tomó.
        assert corrida.processed < 12
        assert _todos_retirados(destino)

    def test_lo_que_no_se_puede_parar_se_dice_en_palabras(self, tmp_path):
        import json

        from resolutions.api.folders import (
            EquipoNoEncontrado,
            FolderRun,
            OrdenNoPermitida,
        )

        destino = tmp_path / "destino"
        destino.mkdir()
        reloj = Reloj()
        uno = equipo(destino, "PC1", reloj=reloj)
        cae, cierra, vivo = equipo(destino, "PC2"), equipo(destino, "PC3"), equipo(destino, "PC4")
        (motor,) = self._motores(tmp_path, 1)
        corridas = {
            "compartida": FolderRun(id="compartida", source=tmp_path, destination=destino, state=RunState.PROCESSING),
            "sola": FolderRun(id="sola", source=tmp_path, destination=destino, state=RunState.PROCESSING),
            "terminada": FolderRun(id="terminada", source=tmp_path, destination=destino, state=RunState.DONE),
        }
        corridas["compartida"].coordinacion = corridas["terminada"].coordinacion = uno
        motor._runs.update(corridas)
        # El latido que dejó un equipo de otra corrida sobre este destino.
        (destino / AREA / "equipos" / "PC9-viejo.json").write_text(
            json.dumps({"id": "PC9-viejo", "equipo": "PC9", "corrida": "otra", "contador": 7, "estado": "procesando"}),
            encoding="utf-8",
        )
        try:
            cierra.estado = "cerrando"
            cierra._latir()
            caer(cae)
            dar_por_caido(uno, reloj)
            time.sleep(5 * LATIDO)
            uno._mirar_a_los_demas()
            with pytest.raises(EquipoNoEncontrado, match="no existe"):
                motor.ordenar_parar("no-existe", vivo.id, "calma")
            with pytest.raises(OrdenNoPermitida, match="ya había terminado"):
                motor.ordenar_parar("terminada", vivo.id, "calma")
            with pytest.raises(OrdenNoPermitida, match="no es compartida"):
                motor.ordenar_parar("sola", vivo.id, "calma")
            with pytest.raises(EquipoNoEncontrado, match="no está en esta corrida"):
                motor.ordenar_parar("compartida", "PC7-desconocido", "calma")
            with pytest.raises(EquipoNoEncontrado, match="no está en esta corrida"):
                motor.ordenar_parar("compartida", "PC9-viejo", "calma")
            with pytest.raises(OrdenNoPermitida, match="ya no late"):
                motor.ordenar_parar("compartida", cae.id, "calma")
            with pytest.raises(OrdenNoPermitida, match="está cerrando la corrida"):
                motor.ordenar_parar("compartida", cierra.id, "ya")
            # Ninguna de ésas dejó nada en el destino. A uno vivo, sí, y la respuesta la trae.
            assert not list((destino / AREA / "ordenes").glob("*.json"))
            respuesta = motor.ordenar_parar("compartida", vivo.id, "calma", "prueba")
            fila = next(e for e in respuesta["equipos"] if e["id"] == vivo.id)
            assert fila["orden"]["modo"] == "calma" and fila["se_puede_parar"]
            assert (destino / AREA / "ordenes" / f"{vivo.id}.json").exists()
        finally:
            for coordinacion in (uno, cierra, vivo):
                coordinacion.parar()


# -- los huecos que encontró la revisión del monitoreo (2026-11-26) ------------------


def _registrar_las_coordinaciones(monkeypatch) -> list[Coordinacion]:
    """Las ``Coordinacion`` que crea ``_unirse_a_la_corrida``, para mirarlas desde la prueba."""
    from resolutions.adapters import coordinacion_en_disco

    creadas: list[Coordinacion] = []

    class Registrada(Coordinacion):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            creadas.append(self)

    monkeypatch.setattr(coordinacion_en_disco, "Coordinacion", Registrada)
    return creadas


@contextlib.contextmanager
def _union_retenida(destino: Path):
    """El turno de la corrida, tomado por un equipo que no late: quien se une espera dentro de ``unirse``.

    Con su latido «uniéndose» ya escrito y su mirada en marcha, como quien
    espera el turno en un destino lento: unirse tarda de segundos a minutos.
    """
    (destino / AREA / "cerrojos").mkdir(parents=True, exist_ok=True)
    portero = Coordinacion(destino, equipo="PC9", version="v1", latido=LATIDO)
    with portero.cerrojo("corrida"):
        yield portero


async def _hasta(condicion, segundos: float = 10.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.02)
    return bool(condicion())


def _un_motor(tmp_path: Path) -> FolderRunner:
    (motor,) = TestPararUnEquipoDesdeElMonitoreo._motores(tmp_path, 1)
    return motor


#: Una orden de «Parar con calma» de otro equipo, ya recibida.
CALMA = {"modo": "calma", "por": "PC2-abc", "equipo_que_ordena": "PC2", "operador": "prueba"}


class TestLosHuecosDelMonitoreo:
    def test_detenida_mientras_se_une_se_retira_al_volver_de_la_union(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 7100, nics=2)
        motor = _un_motor(tmp_path)
        creadas = _registrar_las_coordinaciones(monkeypatch)
        equipos = destino / AREA / "equipos"

        async def correr():
            with _union_retenida(destino):
                corrida = motor.start(str(origen), str(destino))
                # Dentro de ``unirse``: su latido «uniéndose» ya está en el destino.
                assert await _hasta(lambda: bool(creadas) and (equipos / f"{creadas[0].id}.json").exists())
                assert motor.stop(corrida.id) is corrida
            # Suelto el turno, la unión acaba con la corrida ya detenida.
            await _hasta(lambda: creadas[0].retirado)
            return corrida

        try:
            corrida = asyncio.run(correr())
            (creada,) = creadas
            assert corrida.state is RunState.STOPPED
            # Antes se quedaba latiendo «procesando» sin nadie que la parara, y el
            # que cierra la esperaba para siempre.
            assert creada.retirado
            assert not (equipos / f"{creada.id}.json").exists()
            assert corrida.coordinacion is None
        finally:
            for creada in creadas:
                creada.parar()

    @pytest.mark.parametrize("modo", ["calma", "ya"])
    def test_la_orden_recibida_durante_la_union_se_cumple_al_unirse(self, tmp_path, monkeypatch, modo):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 7200, nics=4)
        motor = _un_motor(tmp_path)
        creadas = _registrar_las_coordinaciones(monkeypatch)
        equipos = destino / AREA / "equipos"

        async def correr():
            with _union_retenida(destino) as portero:
                corrida = motor.start(str(origen), str(destino), paralelo=2)
                assert await _hasta(lambda: bool(creadas) and (equipos / f"{creadas[0].id}.json").exists())
                # Su mirada la recibe antes de que ``unirse`` vuelva: sin corrida a
                # la que avisar todavía, sólo se guarda.
                assert creadas[0].recibir_orden(portero.orden_para(creadas[0].id, modo, "prueba"))
                assert creadas[0].corrida is None and creadas[0].al_recibir_orden is None
            assert await _hasta(lambda: not corrida.active)
            await _hasta(lambda: creadas[0].retirado)
            return corrida

        try:
            corrida = asyncio.run(correr())
        finally:
            for creada in creadas:
                creada.parar()
        assert corrida.state is RunState.STOPPED, corrida.error
        boton = "Parar con calma" if modo == "calma" else "Parar ya"
        assert boton in corrida.detenido_por and "PC9" in corrida.detenido_por and "prueba" in corrida.detenido_por
        assert (corrida.parando or {}).get("modo") == ("calma" if modo == "calma" else None)
        # Se cumplió al unirse, antes de tomar ningún PDF.
        assert corrida.processed == 0 and not motor._registry.list()
        assert _todos_retirados(destino)

    def test_una_orden_a_una_corrida_ya_parada_retira_su_coordinacion(self, tmp_path):
        destino = tmp_path / "destino"
        destino.mkdir()
        coordinacion = equipo(destino, "PC1")
        motor = _un_motor(tmp_path)
        # Se detuvo en un mal momento y su coordinación sigue latiendo.
        corrida = FolderRun(id="parada", source=tmp_path, destination=destino, state=RunState.STOPPED)
        corrida.coordinacion = coordinacion
        motor._runs[corrida.id] = corrida
        latido = destino / AREA / "equipos" / f"{coordinacion.id}.json"

        async def correr():
            motor._obedecer(corrida.id, coordinacion.orden_para(coordinacion.id, "calma", "prueba"))
            await _hasta(lambda: coordinacion.retirado and not latido.exists())

        try:
            assert latido.exists() and not coordinacion.retirado
            asyncio.run(correr())
            assert coordinacion.retirado and not latido.exists()
            # No la «cumple»: la corrida ya no estaba activa.
            assert corrida.parando is None and corrida.detenido_por is None and not corrida.avisos
        finally:
            coordinacion.parar()

    def test_el_que_esta_cerrando_no_se_detiene_al_vaciarse(self, tmp_path):
        motor = _un_motor(tmp_path)
        corrida = FolderRun(id="cerrando", source=tmp_path, destination=tmp_path, state=RunState.PROCESSING)
        corrida.parando = dict(CALMA)
        corrida.coordinacion = SimpleNamespace(id="PC1-abc", estado="cerrando", equipos_vivos=lambda: ["PC1-abc"])
        motor._runs[corrida.id] = corrida
        # Nada en curso ni bajando, pero cerrando la corrida -- la auditoría, los
        # generales finales --: no se interrumpe, termina sola.
        assert not corrida.tomados and not corrida.bajando
        assert not motor._parar_si_se_vacio(corrida)
        assert corrida.active and corrida.detenido_por is None
        # El mismo equipo sin estar cerrando, sí: es esa guarda la que lo sostiene.
        corrida.coordinacion.estado = "procesando"
        assert motor._parar_si_se_vacio(corrida)
        assert corrida.state is RunState.STOPPED and "Parar con calma" in corrida.detenido_por

    @pytest.mark.parametrize("bucle", ["por_lotes", "en_paralelo"])
    def test_el_que_esperaba_ranura_devuelve_su_pdf_a_la_cola(self, tmp_path, bucle):
        origen, destino = _origen_y_destino(tmp_path, 7300, nics=1, upds=2)
        pdfs = sorted(origen.rglob("*.pdf"))
        motor = _un_motor(tmp_path)
        corrida = FolderRun(id="ranura", source=origen, destination=destino, state=RunState.PROCESSING, paralelo=1)
        motor._runs[corrida.id] = corrida
        consumidos: list[str] = []

        async def consumir(run, path):
            consumidos.append(path.name)

        motor._consume = consumir

        async def correr():
            motor._loop = asyncio.get_running_loop()
            ranuras = motor._planificador.ranuras
            # Las ranuras del planificador, todas ocupadas (por otras carpetas).
            cuantas = motor._planificador.documentos_de_carpeta
            for _ in range(cuantas):
                await ranuras.acquire()
            if bucle == "por_lotes":
                trabajo = asyncio.create_task(motor._procesar_por_lotes(corrida))
            else:
                trabajo = asyncio.create_task(motor._consumir_en_paralelo(corrida, list(pdfs)))
            # Un trabajador sacó el primero de la cola y espera ranura.
            assert await _hasta(lambda: len(getattr(ranuras, "_waiters", None) or ()) == 1)
            # Llega «Parar con calma», y se libera una ranura.
            corrida.parando = dict(CALMA)
            ranuras.release()
            await asyncio.sleep(0.5)
            con_la_orden = list(consumidos)
            # Sin la orden -- sólo para ver la cola --, sigue por donde iba.
            corrida.parando = None
            for _ in range(cuantas - 1):
                ranuras.release()
            await asyncio.wait_for(trabajo, 10)
            return con_la_orden

        con_la_orden = asyncio.run(correr())
        assert con_la_orden == [], "tomó un PDF con la orden de parar"
        # El que esperaba ranura volvió a la cola, y en su sitio: el primero.
        assert consumidos == [pdf.name for pdf in pdfs]

    @pytest.mark.parametrize("con_la_orden", [False, True])
    def test_con_la_orden_de_parar_la_segunda_pasada_no_empieza(self, tmp_path, con_la_orden):
        origen, destino = tmp_path / "MAGANGUE", tmp_path / "destino"
        origen.mkdir()
        destino.mkdir()
        motor = _un_motor(tmp_path)
        coordinacion = equipo(destino, "PC1")
        corrida = FolderRun(id="segunda", source=origen, destination=destino, state=RunState.PROCESSING)
        corrida.coordinacion = coordinacion
        # Lo de las carpetas de los otros equipos, para el final.
        diferidos = [origen / "7400000" / f"UPD74000{n}.pdf" for n in range(2)]
        corrida.diferidos = list(diferidos)
        if con_la_orden:
            corrida.parando = dict(CALMA)
        motor._runs[corrida.id] = corrida
        clasificadas: list[list[Path]] = []

        def clasificar(run, segunda):
            clasificadas.append(list(segunda))
            return []

        motor._clasificar_la_segunda_pasada = clasificar
        motor._pedir_generales = lambda run: None

        async def correr():
            motor._loop = asyncio.get_running_loop()
            await asyncio.wait_for(motor._procesar_por_lotes(corrida), 10)

        try:
            asyncio.run(correr())
        finally:
            coordinacion.parar()
        if con_la_orden:
            # Lo de los demás lo hacen ellos: ni se mira.
            assert clasificadas == [] and corrida.diferidos == diferidos
        else:
            assert clasificadas == [list(reversed(diferidos))] and corrida.diferidos == []


class TestDetenerAMitadDeUnaEntrega:
    """«Detener» (o «Parar ya») con la entrega de un PDF a medias en su hilo (2026-11-26).

    Cancelar la corrida no para el hilo que entrega. El «finally» soltaba el
    reclamo con la entrega en marcha; otro equipo lo tomaba sin ver todavía su
    constancia «entregando» y lo entregaba encima: «01_UPD022 (2).pdf», igual
    al original, que vio un revisor bajo carga en
    ``test_cuatro_equipos_y_uno_se_detiene_a_la_mitad``. Ahora se espera a
    que acabe -- con tope -- antes de soltarlo.
    """

    @staticmethod
    def _entrega_retenida(motor: FolderRunner) -> tuple[threading.Event, threading.Event, threading.Event]:
        """La entrega de ``motor``, lenta: pasa la barrera y espera a que la prueba la deje seguir.

        Devuelve (entró, sigue, salió): «entró» con la barrera pasada y nada
        escrito todavía en el destino; «salió» cuando ``_deliver`` acabó.
        """
        entro, sigue, salio = threading.Event(), threading.Event(), threading.Event()
        confirmar, entregar = motor._confirmar, motor._deliver

        def confirmar_y_esperar(run, origin):
            confirmar(run, origin)
            if not entro.is_set():
                entro.set()
                sigue.wait(30)

        def entregar_y_avisar(run, job, origin, huella=(0, 0)):
            try:
                return entregar(run, job, origin, huella)
            finally:
                salio.set()

        motor._confirmar = confirmar_y_esperar
        motor._deliver = entregar_y_avisar
        return entro, sigue, salio

    @pytest.mark.parametrize("como", ["detener", "parar_ya"])
    def test_a_mitad_de_la_entrega_otro_equipo_no_la_entrega_encima(self, tmp_path, monkeypatch, como):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 7500, nics=1, upds=1)
        procesados: list[str] = []
        cerrojo = threading.Lock()
        detenido = _motor(_ajustes(tmp_path, "pc1"), procesados, cerrojo, tarda=0.05)
        otro = _motor(_ajustes(tmp_path, "pc2"), procesados, cerrojo, tarda=0.05)
        entro, sigue, salio = self._entrega_retenida(detenido)
        leer = otro._run_job

        async def leer_cuando_acabe(job):
            # Si «otro» llega a leerlo, la entrega de «detenido» sigue y acaba mientras tanto.
            sigue.set()
            await asyncio.to_thread(salio.wait, 30)
            await leer(job)

        otro._run_job = leer_cuando_acabe

        async def correr():
            primera = detenido.start(str(origen), str(destino))
            try:
                assert await asyncio.to_thread(entro.wait, 30), "no llegó a entregar"
                if como == "detener":
                    detenido.stop(primera.id)
                else:
                    detenido._obedecer(primera.id, {**CALMA, "modo": "ya"})
                assert not primera.active
                segunda = otro.start(str(origen), str(destino))
                # «otro» lo toma ya -- lo que pasaba: el reclamo suelto con la entrega
                # en marcha -- o lo ve en curso en «detenido», que lo tiene hasta que
                # acaba de entregarlo.
                await _hasta(lambda: sigue.is_set() or bool(segunda.ajenos), segundos=30)
            finally:
                sigue.set()
            await _hasta(lambda: not segunda.active, segundos=60)
            await asyncio.wait({detenido._tasks[primera.id]}, timeout=30)
            await asyncio.sleep(0.3)
            return primera, segunda

        primera, segunda = asyncio.run(correr())
        assert primera.state is RunState.STOPPED
        assert segunda.state is RunState.DONE, segunda.error
        # Ningún «(2)»: lo que dejó «detenido» lo apartó «otro» al rehacerlo.
        assert _entregados(destino) == ["01_UPD7500000.pdf"]
        assert buscar_repetidos(destino) == []
        # Y se cuenta una vez: lo entregó «otro», y «detenido» no lo da por suyo.
        assert segunda.processed == 1 and primera.processed == 0
        trabajos, _ = segunda.coordinacion.lo_hecho_en_la_corrida()
        assert len(trabajos) == 1
        assert _todos_retirados(destino)

    def test_si_ya_dejo_su_constancia_completa_queda_hecho_y_nadie_lo_rehace(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 7600, nics=1, upds=1)
        procesados: list[str] = []
        cerrojo = threading.Lock()
        detenido = _motor(_ajustes(tmp_path, "pc1"), procesados, cerrojo, tarda=0.05)
        otro = _motor(_ajustes(tmp_path, "pc2"), procesados, cerrojo, tarda=0.05)
        entro, sigue = threading.Event(), threading.Event()
        dejar = detenido._dejar_constancia

        def dejar_y_esperar(run, job, origin, huella, entrega):
            cerrada = dejar(run, job, origin, huella, entrega)
            # La constancia «completa», ya en el destino; lo que queda va lento.
            entro.set()
            sigue.wait(30)
            return cerrada

        detenido._dejar_constancia = dejar_y_esperar

        async def correr():
            primera = detenido.start(str(origen), str(destino))
            try:
                assert await asyncio.to_thread(entro.wait, 30), "no llegó a dejar su constancia"
                detenido.stop(primera.id)
                segunda = otro.start(str(origen), str(destino))
                await _hasta(lambda: bool(segunda.ajenos or segunda.ya_entregados or procesados[1:]), segundos=30)
            finally:
                sigue.set()
            await _hasta(lambda: not segunda.active, segundos=60)
            await asyncio.wait({detenido._tasks[primera.id]}, timeout=30)
            await asyncio.sleep(0.3)
            return primera, segunda

        primera, segunda = asyncio.run(correr())
        assert primera.state is RunState.STOPPED
        assert segunda.state is RunState.DONE, segunda.error
        # Entregado entero por «detenido»: «hecho» con su trabajo, y «otro» sólo lo cuenta.
        assert len(procesados) == 1 and primera.processed == 1
        assert segunda.processed == 0 and segunda.ya_entregados == 1
        trabajos, _ = segunda.coordinacion.lo_hecho_en_la_corrida()
        assert trabajos == primera.job_ids
        assert _entregados(destino) == ["01_UPD7600000.pdf"]
        assert _todos_retirados(destino)

    def test_detener_no_espera_a_la_entrega_mas_que_el_tope(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOTPDF_COORDINACION", "si")
        origen, destino = _origen_y_destino(tmp_path, 7700, nics=1, upds=1)
        detenido = _motor(_ajustes(tmp_path, "pc1"), [], threading.Lock(), tarda=0.05)
        detenido.ESPERA_DE_LA_ENTREGA_AL_DETENER = 0.5
        entro, sigue, _salio = self._entrega_retenida(detenido)

        async def correr():
            primera = detenido.start(str(origen), str(destino))
            try:
                assert await asyncio.to_thread(entro.wait, 30), "no llegó a entregar"
                antes = time.monotonic()
                # Un destino que no contesta: la entrega no acaba.
                detenido.stop(primera.id)
                retirada = await _hasta(lambda: primera.coordinacion.retirado, segundos=20)
                return retirada, time.monotonic() - antes
            finally:
                sigue.set()

        retirada, tardo = asyncio.run(correr())
        # Esperó la entrega hasta el tope, y no más: soltó el reclamo y se retiró.
        assert retirada, "«Detener» se quedó colgado de una entrega que no acababa"
        assert 0.4 <= tardo < 10, f"se retiró a los {tardo:.1f} s"
