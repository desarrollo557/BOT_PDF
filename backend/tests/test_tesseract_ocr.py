"""El OCR le habla al binario por stdin y stdout, sin archivos temporales.

Se hacía a través de pytesseract, que guardaba cada imagen en la carpeta
temporal del sistema y al terminar la buscaba con un glob: con trece mil
archivos en esa carpeta, cada lectura pasaba más tiempo listándola que
leyendo. Estas pruebas fijan que el adaptador construye la llamada correcta,
entiende el TSV que devuelve Tesseract y explica un fallo del binario; y una
de ellas, sólo donde Tesseract está instalado, lee de verdad.

Y desde el 2026-11-26, los turnos: como mucho N Tesseract a la vez en todo el
equipo, entre hilos y entre procesos, sin perder el turno de un proceso que
muere y sin que el turno pueda dejar parado el OCR.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from io import BytesIO
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from resolutions.adapters import tesseract_ocr  # noqa: E402
from resolutions.adapters.tesseract_ocr import (  # noqa: E402
    TESSERACT_A_LA_VEZ,
    TESSERACT_CMD,
    TURNOS,
    TesseractConfig,
    TesseractError,
    TesseractOcr,
    TurnosDeTesseract,
    _tesseract_a_la_vez,
    en_columnas,
)

#: Donde está el paquete, para los procesos aparte que importan el módulo.
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def _turnos_de_la_prueba(tmp_path, monkeypatch):
    """Cada prueba con su carpeta de turnos.

    La del sistema la comparten todas las pruebas que corran a la vez en el
    equipo, y una prueba no puede quedarse esperando turno por otra.
    """
    monkeypatch.setattr(tesseract_ocr, "TURNOS", TurnosDeTesseract(2, tmp_path / "turnos"))

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t800\t200\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t10\t10\t400\t30\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t10\t10\t120\t30\t96.5\tRESOLUCION\n"
    "5\t1\t1\t1\t1\t2\t140\t10\t60\t30\t91.0\tNo.\n"
    "5\t1\t1\t1\t1\t3\t210\t10\t80\t30\t88.25\t00412\n"
    "5\t1\t1\t1\t2\t1\t10\t50\t200\t30\t70.0\tPor\n"
    "5\t1\t1\t1\t2\t2\t220\t50\t200\t30\t75.0\tla cual\n"
)


def _png(texto: str = "", ancho: int = 200, alto: int = 60) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), "white")
    if texto:
        ImageDraw.Draw(imagen).text((10, 10), texto, fill="black")
    buffer = BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


class TestElTsvSeLeeComoColumnas:
    def test_cada_columna_con_su_tipo(self):
        columnas = en_columnas(TSV)
        assert columnas["text"][2:5] == ["RESOLUCION", "No.", "00412"]
        assert columnas["conf"][2] == 96.5
        assert columnas["conf"][0] == -1.0
        assert columnas["line_num"][5] == 2
        assert all(isinstance(valor, int) for valor in columnas["block_num"])

    def test_una_fila_sin_texto_no_descuadra(self):
        """Los renglones de estructura no llevan palabra, y a veces ni la celda."""
        columnas = en_columnas("level\tconf\ttext\n1\t-1\n5\t90\thola\n")
        assert columnas["text"] == ["", "hola"]
        assert columnas["conf"] == [-1.0, 90.0]

    def test_vacio_es_vacio(self):
        assert en_columnas("")["text"] == []


class TestLaLlamadaAlBinario:
    @staticmethod
    def _con_respuesta(monkeypatch, stdout: str = TSV, returncode: int = 0, stderr: str = ""):
        llamadas: list[dict] = []

        def run(args, **kwargs):
            llamadas.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(
                args, returncode, stdout=stdout.encode(), stderr=stderr.encode()
            )

        monkeypatch.setattr(subprocess, "run", run)
        return llamadas

    def test_la_imagen_entra_por_stdin_y_el_tsv_sale_por_stdout(self, monkeypatch):
        llamadas = self._con_respuesta(monkeypatch)
        TesseractOcr(TesseractConfig(language="spa", psm=6), command="tess").read(_png())

        [llamada] = llamadas
        assert llamada["args"][:3] == ["tess", "stdin", "stdout"]
        assert llamada["args"][3:] == ["-l", "spa", "--psm", "6", "tsv"]
        assert llamada["input"][:8] == b"\x89PNG\r\n\x1a\n", "va como PNG"
        assert llamada["capture_output"] is True

    def test_cada_llamada_usa_un_solo_hilo(self, monkeypatch):
        """Con OpenMP cada llamada abría un hilo por núcleo y varias a la vez se
        ahogaban: cuatro PDF a la vez, 41 s; con un hilo, 20 s (2026-10-28)."""
        llamadas = self._con_respuesta(monkeypatch)
        TesseractOcr().read(_png())

        [llamada] = llamadas
        assert llamada["env"]["OMP_THREAD_LIMIT"] == "1"

    def test_lo_leido_conserva_los_renglones(self, monkeypatch):
        self._con_respuesta(monkeypatch)
        resultado = TesseractOcr().read(_png())
        assert resultado.text == "RESOLUCION No. 00412\nPor la cual"
        assert round(resultado.mean_confidence, 3) == round((96.5 + 91 + 88.25 + 70 + 75) / 500, 3)

    def test_una_lectura_floja_vuelve_vacia(self, monkeypatch):
        """Un texto inventado con poca confianza mueve páginas al archivo equivocado."""
        flojo = TSV.replace("96.5", "20").replace("91.0", "20").replace("88.25", "20")
        flojo = flojo.replace("70.0", "20").replace("75.0", "20")
        self._con_respuesta(monkeypatch, stdout=flojo)
        resultado = TesseractOcr().read(_png())
        assert resultado.text == ""
        assert 0 < resultado.mean_confidence < 0.4

    def test_un_fallo_del_binario_dice_lo_que_dijo(self, monkeypatch):
        self._con_respuesta(monkeypatch, returncode=1, stderr="Error opening data file spa.traineddata")
        with pytest.raises(TesseractError, match="spa.traineddata"):
            TesseractOcr().read(_png())

    def test_sin_binario_falla_como_cualquier_programa_que_no_esta(self):
        with pytest.raises(FileNotFoundError):
            TesseractOcr(command="no-existe-tesseract-xyz").read(_png())


@pytest.mark.skipif(shutil.which(TESSERACT_CMD) is None, reason="sin Tesseract instalado")
class TestConElBinarioDeVerdad:
    def test_lee_un_encabezado_impreso(self):
        imagen = Image.new("RGB", (900, 160), "white")
        try:
            fuente = ImageFont.load_default(size=48)
        except TypeError:  # Pillow viejo: la fuente por defecto no admite tamaño
            fuente = ImageFont.load_default()
        ImageDraw.Draw(imagen).text((30, 40), "RESOLUCION No. 00412", fill="black", font=fuente)
        buffer = BytesIO()
        imagen.save(buffer, format="PNG")

        resultado = TesseractOcr(TesseractConfig(language="spa", psm=6)).read(buffer.getvalue())
        assert "00412" in resultado.text
        assert resultado.mean_confidence > 0.5


# -----------------------------------------------------------------------------
#  Los turnos de Tesseract (2026-11-26)
# -----------------------------------------------------------------------------


def _a_la_vez(intervalos: list[tuple[float, float]]) -> int:
    """Cuántos intervalos llegaron a estar abiertos a la vez.

    Uno que termina en el mismo instante en que otro empieza no se solapa: el
    turno se soltó antes de que el otro lo tomara.
    """
    eventos = sorted([(fin, -1) for _, fin in intervalos] + [(inicio, 1) for inicio, _ in intervalos])
    maximo = abiertos = 0
    for _, cambio in eventos:
        abiertos += cambio
        maximo = max(maximo, abiertos)
    return maximo


def _entorno() -> dict[str, str]:
    """El entorno de un proceso aparte que tiene que importar ``resolutions``."""
    rutas = [str(SRC), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(ruta for ruta in rutas if ruta)}


def _esperar_archivo(ruta: Path, proceso: subprocess.Popen, segundos: float = 20.0) -> None:
    limite = time.monotonic() + segundos
    while not ruta.exists():
        assert proceso.poll() is None, f"el proceso aparte terminó con {proceso.returncode}"
        assert time.monotonic() < limite, f"el proceso aparte no escribió {ruta.name}"
        time.sleep(0.02)


#: Un proceso aparte con tres hilos que toman cuatro turnos cada uno y anotan
#: cuándo los tuvieron. Empieza a la par del otro proceso, cuando los dos
#: están listos, para que se disputen los mismos turnos.
_PROCESO_QUE_LEE = textwrap.dedent(
    """
    import os, sys, threading, time
    from resolutions.adapters.tesseract_ocr import TurnosDeTesseract

    carpeta, marcas, listo, el_otro = sys.argv[1:5]
    turnos = TurnosDeTesseract(2, carpeta)
    open(listo, "w").close()
    limite = time.time() + 15
    while not os.path.exists(el_otro) and time.time() < limite:
        time.sleep(0.01)

    anotadas = []
    candado = threading.Lock()

    def leer():
        for _ in range(4):
            with turnos.turno() as tomado:
                inicio = time.time()
                time.sleep(0.05)
                fin = time.time()
            with candado:
                anotadas.append((inicio, fin, tomado))

    hilos = [threading.Thread(target=leer) for _ in range(3)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    with open(marcas, "w") as archivo:
        for inicio, fin, tomado in anotadas:
            archivo.write(f"{inicio!r} {fin!r} {tomado}\\n")
    """
)

#: Un proceso aparte que toma el único turno y se queda con él.
_PROCESO_QUE_RETIENE = textwrap.dedent(
    """
    import sys, time
    from resolutions.adapters.tesseract_ocr import TurnosDeTesseract

    carpeta, tomado = sys.argv[1:3]
    with TurnosDeTesseract(1, carpeta).turno():
        open(tomado, "w").close()
        time.sleep(120)
    """
)


class TestLosTurnosDeTesseract:
    """Como mucho N Tesseract a la vez en todo el equipo.

    En otro PC de la corrida compartida Tesseract pasaba de 90 s por página
    con 8 PDF a la vez y 31 procesos, y cada página que se pasaba de tiempo se
    pagaba a Mistral. El Planificador sólo reparte los hilos de página; la
    fecha, la franja, el sello, el rastreo y las tandas no tenían tope.
    """

    @staticmethod
    def _contando(monkeypatch, segundos: float) -> dict[str, int]:
        """Un ``subprocess.run`` que tarda ``segundos`` y cuenta cuántos van a la vez."""
        candado = threading.Lock()
        cuenta = {"ahora": 0, "maximo": 0, "llamadas": 0}

        def run(args, **kwargs):
            with candado:
                cuenta["ahora"] += 1
                cuenta["llamadas"] += 1
                cuenta["maximo"] = max(cuenta["maximo"], cuenta["ahora"])
            time.sleep(segundos)
            with candado:
                cuenta["ahora"] -= 1
            return subprocess.CompletedProcess(args, 0, stdout=TSV.encode(), stderr=b"")

        monkeypatch.setattr(subprocess, "run", run)
        return cuenta

    def test_entre_hilos_nunca_corren_mas_que_los_turnos(self, monkeypatch, tmp_path):
        carpeta = tmp_path / "dos-turnos"
        monkeypatch.setattr(tesseract_ocr, "TURNOS", TurnosDeTesseract(2, carpeta))
        cuenta = self._contando(monkeypatch, 0.15)
        errores: list[Exception] = []

        def leer():
            try:
                TesseractOcr().read(_png())
            except Exception as error:  # noqa: BLE001 - se mira abajo
                errores.append(error)

        hilos = [threading.Thread(target=leer) for _ in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        assert errores == []
        assert cuenta["llamadas"] == 8
        assert cuenta["maximo"] == 2
        # Ningún descriptor quedó abierto, tampoco los de esperar: en Windows
        # un archivo abierto no se deja borrar.
        for archivo in carpeta.iterdir():
            archivo.unlink()

    def test_entre_procesos_tampoco(self, tmp_path):
        """Dos procesos de tres hilos sobre la misma carpeta: nunca más de 2 a la vez."""
        carpeta = tmp_path / "turnos-del-equipo"
        procesos = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _PROCESO_QUE_LEE,
                    str(carpeta),
                    str(tmp_path / f"marcas-{i}.txt"),
                    str(tmp_path / f"listo-{i}"),
                    str(tmp_path / f"listo-{1 - i}"),
                ],
                env=_entorno(),
            )
            for i in range(2)
        ]
        try:
            for proceso in procesos:
                assert proceso.wait(timeout=30) == 0
        finally:
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                    proceso.wait(timeout=10)

        marcas = []
        for i in range(2):
            for linea in (tmp_path / f"marcas-{i}.txt").read_text().splitlines():
                inicio, fin, tomado = linea.split()
                marcas.append((float(inicio), float(fin), tomado))
        assert len(marcas) == 24
        assert {tomado for *_, tomado in marcas} == {"True"}
        assert _a_la_vez([(inicio, fin) for inicio, fin, _ in marcas]) == 2

    def test_un_proceso_que_muere_con_el_turno_lo_devuelve(self, tmp_path):
        """El pool mata procesos congelados; su turno lo suelta el sistema, no se pierde."""
        carpeta, tomado = tmp_path / "un-turno", tmp_path / "tomado"
        proceso = subprocess.Popen(
            [sys.executable, "-c", _PROCESO_QUE_RETIENE, str(carpeta), str(tomado)], env=_entorno()
        )
        try:
            _esperar_archivo(tomado, proceso)
            dentro = threading.Event()

            def esperar_turno():
                with TurnosDeTesseract(1, carpeta).turno():
                    dentro.set()

            # En un hilo aparte: un turno que no vuelve es una prueba que falla,
            # no una que se queda colgada.
            threading.Thread(target=esperar_turno, daemon=True).start()
            assert not dentro.wait(0.3), "el turno era del otro proceso"

            proceso.kill()
            proceso.wait(timeout=10)
            assert dentro.wait(2.0), "el turno del proceso muerto no volvió en 2 s"
        finally:
            if proceso.poll() is None:
                proceso.kill()
                proceso.wait(timeout=10)

    def test_el_plazo_cuenta_desde_que_arranca_tesseract(self, monkeypatch, tmp_path):
        """Esperar turno no es pasarse de tiempo: 1 s de espera con un plazo de 0,5 s."""
        turnos = TurnosDeTesseract(1, tmp_path / "un-turno")
        monkeypatch.setattr(tesseract_ocr, "TURNOS", turnos)
        tomado, soltando = threading.Event(), []

        def ocupar():
            with turnos.turno():
                tomado.set()
                time.sleep(1.0)
                soltando.append(time.monotonic())

        llamadas: list[tuple[float, float]] = []

        def run(args, **kwargs):
            llamadas.append((time.monotonic(), kwargs["timeout"]))
            return subprocess.CompletedProcess(args, 0, stdout=TSV.encode(), stderr=b"")

        monkeypatch.setattr(subprocess, "run", run)
        otro = threading.Thread(target=ocupar)
        otro.start()
        assert tomado.wait(5)

        resultado = TesseractOcr(TesseractConfig(timeout_seconds=0.5)).read(_png())
        otro.join()

        assert resultado.text == "RESOLUCION No. 00412\nPor la cual"
        [(cuando, plazo)] = llamadas
        assert plazo == 0.5, "el plazo de Tesseract no cambia"
        assert cuando >= soltando[0], "Tesseract arrancó con el turno del otro"

    def test_un_tesseract_que_se_pasa_de_tiempo_devuelve_el_turno(self, monkeypatch, tmp_path):
        turnos = TurnosDeTesseract(1, tmp_path / "un-turno")
        monkeypatch.setattr(tesseract_ocr, "TURNOS", turnos)

        def run(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(TesseractError, match="superó"):
            TesseractOcr().read(_png())

        dentro = threading.Event()

        def tomar():
            with turnos.turno():
                dentro.set()

        threading.Thread(target=tomar, daemon=True).start()
        assert dentro.wait(2.0), "el turno se quedó tomado"

    def test_sin_carpeta_de_turnos_lee_igual_y_avisa_una_vez(self, monkeypatch, tmp_path, caplog):
        """El turno ordena el OCR, nunca lo para."""
        archivo = tmp_path / "no-es-una-carpeta"
        archivo.write_text("x")
        monkeypatch.setattr(tesseract_ocr, "TURNOS", TurnosDeTesseract(2, archivo / "turnos"))
        llamadas = TestLaLlamadaAlBinario._con_respuesta(monkeypatch)

        with caplog.at_level(logging.WARNING, logger="resolutions.adapters.tesseract_ocr"):
            for _ in range(3):
                assert TesseractOcr().read(_png()).text == "RESOLUCION No. 00412\nPor la cual"

        assert len(llamadas) == 3
        avisos = [r.getMessage() for r in caplog.records if "sin turnos" in r.getMessage()]
        assert len(avisos) == 1
        assert "no-es-una-carpeta" in avisos[0]

    def test_por_omision_todos_los_procesos_comparten_la_carpeta_temporal(self):
        assert TURNOS.carpeta == os.path.join(tempfile.gettempdir(), "botpdf-turnos-de-tesseract")
        assert TURNOS.cuantos == TESSERACT_A_LA_VEZ


class TestCuantosTesseractALaVez:
    def test_la_variable_manda(self, monkeypatch):
        monkeypatch.setenv("RESOLUTIONS_TESSERACT_A_LA_VEZ", "3")
        monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(12)), raising=False)
        assert _tesseract_a_la_vez() == 3

    @pytest.mark.parametrize("valor", ["", "  ", "cuatro", "2.5", "0", "-1"])
    def test_vacia_o_ilegible_es_automatico(self, monkeypatch, valor):
        """Automático: los núcleos que ve el proceso -- los de Docker -- menos uno."""
        monkeypatch.setenv("RESOLUTIONS_TESSERACT_A_LA_VEZ", valor)
        monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(12)), raising=False)
        assert _tesseract_a_la_vez() == 11

    def test_sin_afinidad_cuenta_los_nucleos_y_deja_al_menos_uno(self, monkeypatch):
        monkeypatch.delenv("RESOLUTIONS_TESSERACT_A_LA_VEZ", raising=False)
        monkeypatch.delattr(os, "sched_getaffinity", raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 4)
        assert _tesseract_a_la_vez() == 3
        monkeypatch.setattr(os, "cpu_count", lambda: 1)
        assert _tesseract_a_la_vez() == 1
        monkeypatch.setattr(os, "cpu_count", lambda: None)
        assert _tesseract_a_la_vez() == 1
