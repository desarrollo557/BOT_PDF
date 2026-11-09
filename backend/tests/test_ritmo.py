"""La velocidad real de la red y lo que le falta a una corrida (2026-11-05).

El operador: «que si es por red el bot me diga y estime en realidad cuánto es la
velocidad de la red y cuánto podría demorar, cuando es por red y cuando es por
local».
"""

from __future__ import annotations

import pytest

from resolutions.domain.ritmo import (
    MB,
    AvanceDeLaDescarga,
    Ritmo,
    duracion_legible,
    estimar,
    frase_de_la_descarga,
    tamano_legible,
    tiempo_ocupado,
    velocidad_legible,
)


class TestLaVelocidad:
    def test_una_copia_sola(self):
        ritmo = Ritmo()
        ritmo.sumar(10 * MB, 100.0, 105.0)
        assert ritmo.mb_por_segundo() == pytest.approx(2.0)

    def test_tres_a_la_vez_son_la_red_entera_y_no_un_tercio(self):
        """Tres descargas de 10 MB en los mismos 10 s: la red movió 3 MB/s, no 1."""
        ritmo = Ritmo()
        for _ in range(3):
            ritmo.sumar(10 * MB, 0.0, 10.0)
        assert ritmo.mb_por_segundo() == pytest.approx(3.0)

    def test_los_ratos_sin_copias_no_cuentan(self):
        """Entre una descarga y otra la corrida hace OCR: la red no estaba lenta, estaba quieta."""
        ritmo = Ritmo()
        ritmo.sumar(4 * MB, 0.0, 2.0)
        ritmo.sumar(4 * MB, 60.0, 62.0)
        assert ritmo.mb_por_segundo() == pytest.approx(2.0)

    def test_solo_cuenta_lo_reciente(self):
        ritmo = Ritmo(muestras=2)
        ritmo.sumar(100 * MB, 0.0, 1.0)  # una red rápida esta mañana
        ritmo.sumar(1 * MB, 10.0, 11.0)
        ritmo.sumar(1 * MB, 20.0, 21.0)
        assert ritmo.mb_por_segundo() == pytest.approx(1.0)

    def test_sin_medidas_no_hay_velocidad_y_lo_vacio_no_cuenta(self):
        ritmo = Ritmo()
        ritmo.sumar(0, 0.0, 1.0)
        ritmo.sumar(5, 3.0, 3.0)
        assert ritmo.mb_por_segundo() is None and ritmo.medidas == 0

    def test_el_tiempo_ocupado_cuenta_una_vez_lo_solapado(self):
        assert tiempo_ocupado([(0, 10), (5, 15), (20, 25)]) == pytest.approx(20.0)
        assert tiempo_ocupado([(0, 10), (2, 3)]) == pytest.approx(10.0)


class TestLoQueFalta:
    def _estimar(self, **cambios):
        datos = dict(
            pendientes=100,
            terminados_en=[0.0, 10.0, 20.0, 30.0, 40.0],
            ahora=40.0,
            bytes_pendientes=0,
            lectura_mb_s=None,
            escritura_mb_s=None,
            origen_de_red=False,
            destino_de_red=False,
            recorrido_terminado=True,
        )
        return estimar(**{**datos, **cambios})

    def test_del_ritmo_de_los_ultimos_terminados(self):
        """Un PDF cada 10 s y 100 en cola: 1000 s."""
        assert self._estimar().total == pytest.approx(1000.0)

    def test_si_se_atasca_lo_que_falta_sube(self):
        """El ritmo se mide hasta ahora: diez minutos sin terminar ninguno no es ir bien."""
        assert self._estimar(ahora=640.0).total > 10_000

    def test_con_pocos_terminados_no_se_inventa(self):
        assert self._estimar(terminados_en=[0.0, 10.0]).total is None

    def test_sin_pendientes_no_falta_nada(self):
        assert self._estimar(pendientes=0).total == 0.0

    def test_la_red_de_cada_lado_que_es_de_red(self):
        """800 MB por traer a 4 MB/s y por llevar a 2 MB/s: 200 s + 400 s."""
        local = self._estimar(bytes_pendientes=800 * MB, lectura_mb_s=4.0, escritura_mb_s=2.0)
        assert local.red is None
        de_red = self._estimar(
            bytes_pendientes=800 * MB,
            lectura_mb_s=4.0,
            escritura_mb_s=2.0,
            origen_de_red=True,
            destino_de_red=True,
        )
        assert de_red.red == pytest.approx(600.0)

    def test_la_red_no_tarda_mas_que_todo(self):
        estimacion = self._estimar(bytes_pendientes=100_000 * MB, lectura_mb_s=1.0, origen_de_red=True)
        assert estimacion.red == estimacion.total

    def test_mientras_se_recorre_el_origen_es_al_menos(self):
        assert self._estimar(recorrido_terminado=False).al_menos


class TestComoSeDice:
    @pytest.mark.parametrize(
        ("segundos", "texto"),
        [(None, "—"), (20, "menos de 1 min"), (720, "12 min"), (3600, "1 h"), (11_400, "3 h 10 min"), (190_000, "2 d 4 h")],
    )
    def test_la_duracion(self, segundos, texto):
        assert duracion_legible(segundos) == texto

    @pytest.mark.parametrize(("mb_s", "texto"), [(None, "—"), (0.5, "512 KB/s"), (4.25, "4,2 MB/s"), (112.4, "112 MB/s")])
    def test_la_velocidad_con_coma(self, mb_s, texto):
        assert velocidad_legible(mb_s) == texto


class TestElAvanceDeUnaDescarga:
    """El operador, 2026-11-09: «que se muestre el progreso de descarga, el tamaño del archivo, esos detallitos»."""

    def test_esperando_turno_dice_el_tamano(self):
        datos = AvanceDeLaDescarga(total=410 * MB).esperando()
        assert datos["estado"] == "esperando" and datos["bytes"] == 0 and datos["total"] == 410 * MB
        assert datos["mb_s"] is None and datos["falta_s"] is None

    def test_avisa_al_empezar_como_mucho_cuatro_veces_por_segundo_y_al_acabar(self):
        avance = AvanceDeLaDescarga(total=10 * MB)
        avisos = [avance.avanzar(mb * MB, 0.1 * mb) for mb in range(11)]
        # Al empezar, a los 0,3 s, a los 0,6 s, a los 0,9 s y al acabar, aunque no toque.
        dichos = [a["bytes"] // MB for a in avisos if a is not None]
        assert dichos == [0, 3, 6, 9, 10]

    def test_la_velocidad_y_lo_que_falta(self):
        avance = AvanceDeLaDescarga(total=410 * MB)
        avance.avanzar(0, 0.0)
        datos = avance.avanzar(14 * MB, 4.0)
        # La ventana es de dos segundos: los primeros, con la sesión abriéndose, no cuentan.
        assert datos["mb_s"] == pytest.approx(3.5, abs=0.01)
        assert datos["velocidad"] == "3,5 MB/s"
        assert datos["falta_s"] == pytest.approx((410 - 14) / 3.5, abs=0.2)

    def test_si_la_copia_vuelve_a_empezar_es_otro_intento(self):
        avance = AvanceDeLaDescarga(total=10 * MB)
        avance.avanzar(0, 0.0)
        avance.avanzar(6 * MB, 2.0)
        datos = avance.avanzar(0, 2.1)
        assert datos is not None and datos["intento"] == 2 and datos["bytes"] == 0

    def test_sin_tamano_no_hay_porcentaje_ni_lo_que_falta(self):
        avance = AvanceDeLaDescarga()
        avance.avanzar(0, 0.0)
        datos = avance.avanzar(5 * MB, 1.0)
        assert datos["total"] == 0 and datos["falta_s"] is None and datos["mb_s"] == pytest.approx(5.0)

    def test_el_tamano_que_trae_el_archivo_manda(self):
        avance = AvanceDeLaDescarga(total=0)
        assert avance.avanzar(0, 0.0, total=8 * MB)["total"] == 8 * MB

    @pytest.mark.parametrize(
        ("bytes_", "texto"),
        [(850 * 1024, "850 KB"), (int(2.4 * MB), "2,4 MB"), (410 * MB, "410 MB"), (int(1.6 * 1024 * MB), "1,6 GB"), (int(9.96 * MB), "10 MB"), (int(1023.9 * 1024), "1,0 MB")],
    )
    def test_el_tamano_con_coma(self, bytes_, texto):
        assert tamano_legible(bytes_) == texto

    def test_la_frase(self):
        avance = AvanceDeLaDescarga(total=410 * MB)
        assert frase_de_la_descarga(avance.esperando()) == "Esperando turno para bajar de la red · 410 MB"
        avance.avanzar(0, 0.0)
        datos = avance.avanzar(123 * MB, 35.0)
        assert frase_de_la_descarga(datos).startswith("Bajando de la red · 123 de 410 MB · ")
        assert frase_de_la_descarga(None) == ""

