"""Leer con ayuda de pago: cuándo se pide, cuándo no, y qué pasa si falla.

Lo que se fija acá es que activar el motor de pago no cambie ninguna decisión
del sistema salvo una: cuánto se lee. El reparto del libro, las costuras y el
inventario siguen saliendo de lo mismo; lo único que cambia es que las páginas
escritas a mano dejan de volver vacías.

Y que la ayuda sea ayuda: si el proveedor se cae, se agota o no tiene llave, el
trabajo sale igual con lo que leyó Tesseract. Un motor de lectura que puede
tumbar una caja de cuatrocientas páginas no es una mejora, es una dependencia.
"""

import json

import pytest

from resolutions.adapters.mistral_ocr import MistralOcr, MistralOcrConfig
from resolutions.adapters.ocr_cascada import MINIMO_UTIL, OcrEnCascada
from resolutions.application.lectura import LecturaChoice, available_readers
from resolutions.application.ports import OcrResult


class OcrFalso:
    """Un motor que contesta lo que se le diga, y cuenta cuántas veces se le pidió."""

    def __init__(self, texto: str = "", falla: bool = False) -> None:
        self.texto = texto
        self.falla = falla
        self.llamadas = 0

    def read(self, image_png: bytes) -> OcrResult:
        self.llamadas += 1
        if self.falla:
            raise RuntimeError("el proveedor se cayó")
        return OcrResult(text=self.texto, mean_confidence=0.0)


class TestLaCascada:
    def test_lo_que_el_local_leyo_bien_no_se_vuelve_a_pagar(self):
        """Una banda de encabezado que Tesseract leyó entera no se escala.

        Es la mitad del argumento para tener cascada y no un motor único: en un
        expediente mecanografiado el remoto no aportaría nada y se cobraría por
        cada página igual.
        """
        local = OcrFalso("RESOLUCION NUMERO 00412 DE 2024")
        remoto = OcrFalso("no debería llamarse")

        resultado = OcrEnCascada(local, remoto).read(b"imagen")

        assert resultado.text == "RESOLUCION NUMERO 00412 DE 2024"
        assert remoto.llamadas == 0

    def test_una_esquina_que_el_local_no_supo_leer_se_escala(self):
        """`', "'` es lo que Tesseract devuelve de un folio manuscrito."""
        local = OcrFalso("', “'")
        remoto = OcrFalso("135 70/1")

        resultado = OcrEnCascada(local, remoto).read(b"imagen")

        assert resultado.text == "135 70/1"
        assert remoto.llamadas == 1

    def test_la_puntuacion_no_cuenta_como_lectura(self):
        """Medir la longitud a secas haría pasar por texto el ruido del escaneo."""
        local = OcrFalso("-" * (MINIMO_UTIL * 3))
        remoto = OcrFalso("200/V")

        assert OcrEnCascada(local, remoto).read(b"imagen").text == "200/V"

    def test_si_el_remoto_se_cae_queda_la_lectura_local(self):
        local = OcrFalso("algo poco")
        remoto = OcrFalso(falla=True)

        assert OcrEnCascada(local, remoto).read(b"imagen").text == "algo poco"

    def test_y_si_el_remoto_tampoco_lee_no_se_empeora_lo_que_habia(self):
        """Gastar una llamada no es motivo para quedarse con la peor de las dos."""
        local = OcrFalso("70/v")
        remoto = OcrFalso("")

        assert OcrEnCascada(local, remoto).read(b"imagen").text == "70/v"

    def test_si_el_local_se_cae_se_pregunta_igual(self):
        local = OcrFalso(falla=True)
        remoto = OcrFalso("200/V")

        assert OcrEnCascada(local, remoto).read(b"imagen").text == "200/V"


class TestElAdaptadorDeMistral:
    def test_sin_llave_devuelve_vacio_en_vez_de_fallar(self):
        """No tener llave es una respuesta, no una avería del documento."""
        assert MistralOcr(api_key="").read(b"imagen").text == ""

    def test_arma_la_peticion_que_el_proveedor_espera(self, monkeypatch):
        capturado = {}

        class RespuestaFalsa:
            def read(self):
                return json.dumps({"pages": [{"markdown": "135 70/1"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def urlopen_falso(peticion, timeout=None):
            capturado["url"] = peticion.full_url
            capturado["auth"] = peticion.get_header("Authorization")
            capturado["cuerpo"] = json.loads(peticion.data)
            return RespuestaFalsa()

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))

        resultado = MistralOcr(api_key="llave-de-prueba").read(b"imagen")

        assert resultado.text == "135 70/1"
        assert capturado["url"].endswith("/v1/ocr")
        assert capturado["auth"] == "Bearer llave-de-prueba"
        assert capturado["cuerpo"]["document"]["image_url"].startswith("data:image/png;base64,")

    def test_un_error_del_proveedor_deja_la_pagina_sin_texto(self, monkeypatch):
        """Y no levanta: una página ilegible no puede tumbar cuatrocientas."""
        import urllib.error

        def urlopen_falso(peticion, timeout=None):
            raise urllib.error.HTTPError(peticion.full_url, 500, "boom", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)

        motor = MistralOcr(api_key="x", config=MistralOcrConfig(reintentos=1))
        assert motor.read(b"imagen").text == ""

    def test_un_rechazo_por_ritmo_se_reintenta(self, monkeypatch):
        """Un 429 es "más despacio", no "no se puede"."""
        import urllib.error

        intentos = {"n": 0}

        class RespuestaFalsa:
            def read(self):
                return json.dumps({"pages": [{"markdown": "200/V"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise urllib.error.HTTPError(peticion.full_url, 429, "slow", {}, None)
            return RespuestaFalsa()

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))
        monkeypatch.setattr("time.sleep", lambda _segundos: None)

        motor = MistralOcr(api_key="x", config=MistralOcrConfig(espera_inicial=0.0))
        assert motor.read(b"imagen").text == "200/V"
        assert intentos["n"] == 2


class TestLaEleccionDelOperador:
    def test_el_local_siempre_se_puede_pedir(self):
        assert LecturaChoice.LOCAL.is_available({})

    def test_el_de_pago_necesita_su_llave(self):
        assert not LecturaChoice.MISTRAL.is_available({})
        assert LecturaChoice.MISTRAL.is_available({"mistral_api_key": "x"})

    def test_por_omision_se_lee_como_siempre(self):
        """Quien no pida nada sigue trabajando igual que antes, y gratis."""
        assert LecturaChoice.parse(None) is LecturaChoice.LOCAL
        assert LecturaChoice.parse("") is LecturaChoice.LOCAL

    def test_un_motor_desconocido_no_se_adivina(self):
        with pytest.raises(ValueError):
            LecturaChoice.parse("el-que-sea")

    def test_la_pantalla_recibe_que_hay_y_que_no(self):
        assert available_readers({}) == {"local": True, "mistral": False}
        assert available_readers({"mistral_api_key": "x"}) == {"local": True, "mistral": True}


class TestUnCorteDeConexionNoEsUnaRespuesta:
    """Leyendo ocho páginas a la vez, el proveedor corta conexiones.

    Llegan `RemoteDisconnected` e `IncompleteRead` en mitad de una respuesta, y
    eso no es un "no": es una llamada que hay que repetir. Darlas por
    definitivas hacía que un libro entero se diera por leído en trece segundos,
    con sus 398 páginas vacías y sin una sola cédula -- cada corte volvía al
    instante, así que el trabajo terminaba a la velocidad de los fallos.
    """

    def test_una_conexion_cortada_se_repite(self, monkeypatch):
        import json as _json

        intentos = {"n": 0}

        class RespuestaFalsa:
            def read(self):
                return _json.dumps({"pages": [{"markdown": "7882907"}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            if intentos["n"] < 3:
                raise ConnectionResetError("el proveedor cerró la conexión")
            return RespuestaFalsa()

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: _json.loads(conexion.read()))
        monkeypatch.setattr("time.sleep", lambda _s: None)

        motor = MistralOcr(api_key="x", config=MistralOcrConfig(espera_inicial=0.0))
        assert motor.read(b"imagen").text == "7882907"
        assert intentos["n"] == 3

    def test_un_proveedor_caido_se_reintenta_y_luego_se_deja(self, monkeypatch):
        """Y no para siempre: agotados los intentos, la página vuelve vacía."""
        intentos = {"n": 0}

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            raise ConnectionResetError("sigue cerrando")

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("time.sleep", lambda _s: None)

        motor = MistralOcr(
            api_key="x", config=MistralOcrConfig(reintentos=4, espera_inicial=0.0)
        )
        assert motor.read(b"imagen").text == ""
        assert intentos["n"] == 4

    def test_una_llave_mala_no_se_repite(self, monkeypatch):
        """Un 401 no mejora por insistir: se contesta a la primera."""
        import urllib.error

        intentos = {"n": 0}

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            raise urllib.error.HTTPError(peticion.full_url, 401, "no", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("time.sleep", lambda _s: None)

        assert MistralOcr(api_key="x").read(b"imagen").text == ""
        assert intentos["n"] == 1


class TestCuandoSeAcabaElCredito:
    """Un 402 es de la cuenta, no de la página.

    Pasó en mitad de un libro de 398 hojas: el proveedor empezó a contestar
    "API budget exhausted" y el sistema se lo preguntó cuatrocientas veces. El
    registro se llenó de líneas idénticas que tapaban cualquier otro problema, y
    cada página gastaba una ida y vuelta a la red para oír lo mismo.
    """

    def _urlopen_sin_credito(self, intentos):
        import urllib.error

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            raise urllib.error.HTTPError(
                peticion.full_url, 402, "budget", {}, None
            )

        return urlopen_falso

    def test_no_se_vuelve_a_preguntar(self, monkeypatch):
        intentos = {"n": 0}
        monkeypatch.setattr("urllib.request.urlopen", self._urlopen_sin_credito(intentos))
        monkeypatch.setattr("time.sleep", lambda _s: None)

        motor = MistralOcr(api_key="x")
        for _ in range(5):
            assert motor.read(b"imagen").text == ""

        assert intentos["n"] == 1
        assert motor.sin_presupuesto

    def test_y_el_trabajo_sigue_con_lo_que_lea_el_local(self, monkeypatch):
        """Quedarse sin crédito degrada la lectura; no tumba el documento."""
        intentos = {"n": 0}
        monkeypatch.setattr("urllib.request.urlopen", self._urlopen_sin_credito(intentos))
        monkeypatch.setattr("time.sleep", lambda _s: None)

        local = OcrFalso("RESOLUCION NUMERO 00412 DE 2024")
        cascada = OcrEnCascada(local=local, remoto=MistralOcr(api_key="x"))

        assert cascada.read(b"imagen").text == "RESOLUCION NUMERO 00412 DE 2024"
