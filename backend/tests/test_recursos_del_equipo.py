"""Los recursos de cada PC: núcleos, CPU, carga, memoria y disco (2026-11-27).

El operador: «obviamente el principal deberá tener más capacidad de recursos,
RAM, disco», y eligió ver la RAM, el disco y la CPU de cada PC de la corrida
compartida. Lo mide ``adapters.recursos_del_equipo`` para el latido de cada
equipo y para la pantalla de rendimiento. Lo que fija cada clase:

- ``TestLaCpu``: con un ``/proc/stat`` simulado, el uso entre dos medidas; la
  primera no dice nada; cada medidor con su propia muestra; lo raro, ``None``.
- ``TestLaMemoria``: MemTotal − MemAvailable de un ``/proc/meminfo`` simulado;
  sin él o sin sus dos líneas, ``None``.
- ``TestLaCargaYLosNucleos``: la carga de ``os.getloadavg``, que en Windows no
  existe (``None``), y los núcleos que ve el bot.
- ``TestElDisco``: ``shutil.disk_usage`` sobre una carpeta de verdad; el C: del
  equipo en Docker (``/equipo/c``) si existe, si no la carpeta de datos; y cómo
  se nombra el disco medido.
- ``TestTodoJunto``: ``medir`` da las claves del contrato, y en Windows sin
  Docker lo que no se puede medir va como ``None``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from resolutions.adapters import recursos_del_equipo
from resolutions.adapters.recursos_del_equipo import MedidorDeCpu
from resolutions.application.coordinacion import CLAVES_DE_LOS_RECURSOS

#: Un ``/proc/meminfo`` de una máquina virtual de Docker con 8 GB.
MEMINFO = """MemTotal:        8000000 kB
MemFree:          500000 kB
MemAvailable:    2000000 kB
Buffers:           10000 kB
"""


def _stat(carpeta: Path, usuario: int, sistema: int, ocioso: int, espera: int = 0) -> None:
    """La primera línea de ``/proc/stat``: user nice system idle iowait irq softirq steal."""
    (carpeta / "stat").write_text(
        f"cpu  {usuario} 0 {sistema} {ocioso} {espera} 0 0 0 0 0\ncpu0 1 0 1 1 0 0 0 0 0 0\n", encoding="ascii"
    )


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    """Un ``/proc`` simulado, vacío: cada prueba pone lo suyo."""
    carpeta = tmp_path / "proc"
    carpeta.mkdir()
    return carpeta


class TestLaCpu:
    def test_el_uso_entre_dos_medidas(self, proc):
        medidor = MedidorDeCpu(proc=proc)
        _stat(proc, 100, 100, 800)
        # La primera no tiene con qué comparar.
        assert medidor.medir() is None
        # 200 de tiempo más, 100 ocioso (con la espera de disco): la mitad.
        _stat(proc, 150, 150, 850, espera=50)
        assert medidor.medir() == 50.0
        # Sin tiempo nuevo -- dos medidas en el mismo instante --, nada.
        assert medidor.medir() is None

    def test_cada_medidor_con_su_muestra(self, proc):
        # El latido y la pantalla de rendimiento miden por su cuenta: ninguno le
        # roba al otro la muestra anterior (antes era una variable global).
        del_latido, de_la_pantalla = MedidorDeCpu(proc=proc), MedidorDeCpu(proc=proc)
        _stat(proc, 0, 0, 1000)
        assert del_latido.medir() is None
        _stat(proc, 300, 0, 1100)
        assert de_la_pantalla.medir() is None
        assert del_latido.medir() == 75.0
        _stat(proc, 300, 0, 1500)
        assert de_la_pantalla.medir() == 0.0

    def test_sin_proc_o_con_algo_raro_no_dice_nada(self, proc):
        medidor = MedidorDeCpu(proc=proc)
        assert medidor.medir() is None  # sin «stat»: el servicio en Windows sin Docker
        (proc / "stat").write_text("cpu  uno dos tres\n", encoding="ascii")
        assert medidor.medir() is None
        (proc / "stat").write_text("cpu  1 2\n", encoding="ascii")
        assert medidor.medir() is None
        (proc / "stat").write_text("", encoding="ascii")
        assert medidor.medir() is None

    def test_por_omision_lee_el_proc_del_modulo(self, proc, monkeypatch):
        monkeypatch.setattr(recursos_del_equipo, "PROC", proc)
        medidor = MedidorDeCpu()
        _stat(proc, 0, 0, 100)
        medidor.medir()
        _stat(proc, 10, 0, 190)
        assert medidor.medir() == 10.0


class TestLaMemoria:
    def test_usada_es_el_total_menos_lo_disponible(self, proc):
        (proc / "meminfo").write_text(MEMINFO, encoding="ascii")
        assert recursos_del_equipo.memoria(proc) == ((8_000_000 - 2_000_000) * 1024, 8_000_000 * 1024)

    def test_sin_el_archivo_o_sin_sus_dos_lineas_no_dice_nada(self, proc):
        assert recursos_del_equipo.memoria(proc) is None
        (proc / "meminfo").write_text("MemTotal: 8000000 kB\nMemFree: raro kB\n", encoding="ascii")
        assert recursos_del_equipo.memoria(proc) is None


class TestLaCargaYLosNucleos:
    def test_la_carga_del_ultimo_minuto(self, monkeypatch):
        monkeypatch.setattr(recursos_del_equipo.os, "getloadavg", lambda: (11.4512, 9.0, 8.0), raising=False)
        assert recursos_del_equipo.carga() == 11.45

    def test_en_windows_no_hay_carga(self, monkeypatch):
        monkeypatch.delattr(recursos_del_equipo.os, "getloadavg", raising=False)
        assert recursos_del_equipo.carga() is None

    def test_los_nucleos_que_ve_el_bot(self):
        assert recursos_del_equipo.nucleos() == os.cpu_count()


class TestElDisco:
    def test_lo_libre_y_lo_total_de_una_carpeta(self, tmp_path):
        libre, total = recursos_del_equipo.disco(tmp_path)
        uso = shutil.disk_usage(tmp_path)
        assert total == uso.total and 0 < libre <= total
        assert recursos_del_equipo.disco(tmp_path / "no-existe") is None

    def test_en_docker_el_c_del_equipo_y_si_no_la_carpeta_de_datos(self, tmp_path, monkeypatch):
        datos = tmp_path / "data"
        datos.mkdir()
        monkeypatch.setattr(recursos_del_equipo, "DISCO_DEL_EQUIPO", tmp_path / "no-montado")
        assert recursos_del_equipo.disco_a_medir(datos) == datos
        montado = tmp_path / "equipo-c"
        montado.mkdir()
        monkeypatch.setattr(recursos_del_equipo, "DISCO_DEL_EQUIPO", montado)
        assert recursos_del_equipo.disco_a_medir(datos) == montado

    def test_el_nombre_del_disco_medido(self):
        # En Docker, la carpeta montada; en Windows, la unidad.
        assert recursos_del_equipo._nombre_del_disco(PurePosixPath("/equipo/c")) == "/equipo/c"
        assert recursos_del_equipo._nombre_del_disco(PurePosixPath("/data")) == "/data"
        assert recursos_del_equipo._nombre_del_disco(PureWindowsPath("C:/Users/siar/BOT_PDF/data")) == "C:\\"


class TestTodoJunto:
    def test_medir_da_las_claves_del_contrato(self, tmp_path, proc, monkeypatch):
        (proc / "meminfo").write_text(MEMINFO, encoding="ascii")
        _stat(proc, 0, 0, 100)
        monkeypatch.setattr(recursos_del_equipo, "PROC", proc)
        monkeypatch.setattr(recursos_del_equipo, "DISCO_DEL_EQUIPO", tmp_path / "no-montado")
        cpu = MedidorDeCpu()
        primera = recursos_del_equipo.medir(tmp_path, cpu=cpu)
        assert tuple(primera) == CLAVES_DE_LOS_RECURSOS
        assert primera["cpu"] is None  # la primera medida no tiene con qué comparar
        _stat(proc, 50, 0, 150)
        segunda = recursos_del_equipo.medir(tmp_path, cpu=cpu)
        assert segunda["cpu"] == 50.0 and segunda["nucleos"] == os.cpu_count()
        assert segunda["memoria_usada"] == 6_000_000 * 1024 and segunda["memoria_total"] == 8_000_000 * 1024
        assert segunda["disco_total"] == shutil.disk_usage(tmp_path).total
        assert 0 < segunda["disco_libre"] <= segunda["disco_total"]
        assert segunda["disco"] == recursos_del_equipo._nombre_del_disco(tmp_path)
        # Sin medidor de CPU, la CPU no se mide; un disco que no se deja mirar, None.
        sin_disco = recursos_del_equipo.medir(tmp_path / "no-existe")
        assert sin_disco["cpu"] is None
        assert sin_disco["disco"] is None and sin_disco["disco_libre"] is None and sin_disco["disco_total"] is None

    @pytest.mark.skipif(sys.platform != "win32", reason="en Windows sin Docker no hay /proc")
    def test_en_windows_sin_docker_lo_que_no_se_mide_es_none(self, tmp_path):
        medido = recursos_del_equipo.medir(tmp_path, cpu=MedidorDeCpu())
        assert medido["cpu"] is None and medido["carga"] is None
        assert medido["memoria_usada"] is None and medido["memoria_total"] is None
        # El disco sí: el de la carpeta de datos, por su unidad.
        assert medido["disco_total"] > 0 and medido["disco"] == Path(tmp_path).anchor
