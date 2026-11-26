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
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

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
from resolutions.api.folders import FolderRunner, RunState
from resolutions.api.jobs import JobRegistry
from resolutions.api.repetidos import buscar_repetidos
from resolutions.api.settings import Settings
from resolutions.application.coordinacion import (
    Vida,
    carpeta_de,
    clave_de,
    equipo_preferido,
    opciones_distintas,
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
