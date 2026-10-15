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
from resolutions.application.consumo import Consumo
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
        assert available_readers({}) == {
            "local": True,
            "mistral": False,
            "mistral-nombres": False,
        }
        assert available_readers({"mistral_api_key": "x"}) == {
            "local": True,
            "mistral": True,
            "mistral-nombres": True,
        }


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


def _respuesta(paginas=1, markdown="135 70/1"):
    """Una respuesta del proveedor como la devuelve `urlopen`."""

    class RespuestaFalsa:
        def read(self):
            return json.dumps(
                {"pages": [{"markdown": markdown}], "usage_info": {"pages_processed": paginas}}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    return RespuestaFalsa()


class TestElTopeDeGastoDelTrabajo:
    """Ni una p\u00e1gina m\u00e1s de las que el operador autoriz\u00f3.

    Existe porque una caja son cientos de p\u00e1ginas y el motor remoto cobra por
    cada una: hasta ahora la \u00fanica se\u00f1al de que un trabajo se hab\u00eda comido el
    cr\u00e9dito llegaba cuando el proveedor contestaba "sin presupuesto" en mitad
    del libro siguiente.
    """

    def motor(self, monkeypatch, tope, llamadas):
        def urlopen_falso(peticion, timeout=None):
            llamadas.append(peticion)
            return _respuesta()

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))
        consumo = Consumo(tope_de_paginas=tope)
        return MistralOcr(api_key="llave", consumo=consumo), consumo

    def test_se_deja_de_pedir_al_alcanzarlo(self, monkeypatch):
        llamadas = []
        motor, consumo = self.motor(monkeypatch, tope=3, llamadas=llamadas)
        for _ in range(10):
            motor.read(b"imagen")
        assert len(llamadas) == 3
        assert consumo.as_dict()["paginas_facturadas"] == 3

    def test_sin_tope_no_se_limita_nada(self, monkeypatch):
        llamadas = []
        motor, _ = self.motor(monkeypatch, tope=None, llamadas=llamadas)
        for _ in range(5):
            motor.read(b"imagen")
        assert len(llamadas) == 5

    def test_pasado_el_tope_la_pagina_vuelve_sin_texto_y_no_falla(self, monkeypatch):
        """Alcanzar el tope no rompe el trabajo: el libro se sigue partiendo.

        El corte de un libro de diplomas sale de medir tinta y no necesita OCR,
        as\u00ed que pasado el tope los documentos salen igual, s\u00f3lo que nombrados
        por su folio o su orden en vez de por su c\u00e9dula.
        """
        motor, _ = self.motor(monkeypatch, tope=1, llamadas=[])
        motor.read(b"imagen")
        segunda = motor.read(b"imagen")
        assert segunda.text == ""
        assert segunda.mean_confidence == 0.0

    def test_el_tope_se_mira_antes_de_gastar(self, monkeypatch):
        """Un tope que se comprueba al volver ya pag\u00f3 la p\u00e1gina que sobraba."""
        llamadas = []
        motor, _ = self.motor(monkeypatch, tope=0, llamadas=llamadas)
        motor.read(b"imagen")
        assert llamadas == []


class TestLoQueViajaPesaLoMenosPosible:
    """Una p\u00e1gina a 300 dpi son 2,6 MB en PNG y 718 KB en JPEG.

    Con ocho lectores en vuelo esa diferencia es la que hay entre una
    conversaci\u00f3n normal con el proveedor y la r\u00e1faga de conexiones cortadas que
    este mismo adaptador tiene que reintentar. Se comprob\u00f3 sobre el caso dif\u00edcil
    -- la cara 3 del libro 7, manuscrita -- que la lectura no cambia.
    """

    def capturar(self, monkeypatch, imagen):
        capturado = {}

        def urlopen_falso(peticion, timeout=None):
            capturado["cuerpo"] = json.loads(peticion.data)
            return _respuesta()

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))
        MistralOcr(api_key="llave").read(imagen)
        return capturado["cuerpo"]["document"]["image_url"]

    def escaneo(self):
        """Un PNG con grano, que es lo que produce un escáner de verdad.

        Con ruido y no con texto vectorial limpio: un PNG de texto nítido se
        comprime tan bien que la JPEG sale más pesada, y una prueba montada así
        fijaría lo contrario de lo que pasa con el papel.
        """
        import random

        import pymupdf

        random.seed(7)
        ancho, alto = 900, 1200
        pixeles = bytes(random.randrange(120, 210) for _ in range(ancho * alto))
        return pymupdf.Pixmap(
            pymupdf.csGRAY, ancho, alto, pixeles, False
        ).tobytes("png")

    def test_un_escaneo_viaja_comprimido(self, monkeypatch):
        url = self.capturar(monkeypatch, self.escaneo())
        assert url.startswith("data:image/jpeg;base64,")

    def test_y_pesa_menos_que_el_original(self, monkeypatch):
        import base64

        original = self.escaneo()
        url = self.capturar(monkeypatch, original)
        enviado = base64.b64decode(url.split(",", 1)[1])
        assert len(enviado) < len(original)

    def test_lo_que_no_mejora_comprimido_se_manda_como_estaba(self, monkeypatch):
        """El caso contrario, y cuesta una prueba descubrirlo.

        Sobre una imagen sintética de texto nítido -- lo que sale de rasterizar
        un PDF nativo -- el PNG gana por bastante: 931 KB contra 1,7 MB de JPEG.
        Comprimir a ciegas habría hecho más pesadas las páginas que ya iban
        ligeras, así que se manda la más pequeña de las dos.
        """
        import pymupdf

        documento = pymupdf.open()
        pagina = documento.new_page(width=1700, height=2200)
        for indice in range(120):
            pagina.insert_text(
                (40, 30 + indice * 18),
                "C.C. No. 7.882.907 Expedida en Arizona Bolivar  ALBERTO FERNANDEZ",
                fontsize=11,
            )
        nitida = pagina.get_pixmap(
            matrix=pymupdf.Matrix(3, 3), colorspace=pymupdf.csGRAY, alpha=False
        ).tobytes("png")
        documento.close()

        url = self.capturar(monkeypatch, nitida)
        assert url.startswith("data:image/png;base64,")

    def test_una_esquina_pequena_se_manda_tal_cual(self, monkeypatch):
        """Recomprimir unos kilobytes costar\u00eda m\u00e1s tiempo del que ahorrar\u00eda."""
        url = self.capturar(monkeypatch, b"\x89PNG" + b"\x00" * 100)
        assert url.startswith("data:image/png;base64,")

    def test_una_imagen_que_no_se_deja_recomprimir_se_manda_igual(self, monkeypatch):
        """Abaratar jam\u00e1s puede costar una lectura."""
        rota = b"\x89PNG" + b"basura" * 50000
        url = self.capturar(monkeypatch, rota)
        assert url.startswith("data:image/png;base64,")


class TestLaLecturaDeAhorro:
    """La tercera forma de leer: pagar por la franja del nombre, no por la hoja.

    El proveedor cobra por **página procesada**, así que diez franjas apiladas
    en una imagen son una página. Medido sobre el libro de posgrados 3858080 --
    manuscrito y sin cédulas en el papel --: dieciséis caras leídas por dos
    páginas facturadas, los dieciséis nombres correctos.

    Lo que se deja de leer de esas caras es el folio, la fecha y el título. En un
    libro manuscrito eso no cuesta nada -- salen ilegibles igual y el FUID los
    escribe N/A con esta opción y sin ella -- y es justamente donde el ahorro
    hace falta, porque son los libros que obligan a pagar cada cara.
    """

    def test_es_una_eleccion_mas_del_operador(self):
        assert LecturaChoice.parse("mistral-nombres") is LecturaChoice.MISTRAL_NOMBRES

    def test_se_llama_por_lo_que_hace_y_no_por_el_proveedor(self):
        assert LecturaChoice.MISTRAL_NOMBRES.label == "OCR + IA (ahorro)"

    def test_necesita_la_misma_llave_que_la_otra(self):
        assert not LecturaChoice.MISTRAL_NOMBRES.is_available({})
        assert LecturaChoice.MISTRAL_NOMBRES.is_available({"mistral_api_key": "x"})

    def test_y_la_pantalla_la_recibe_con_las_demas(self):
        disponibles = available_readers({"mistral_api_key": "x"})
        assert disponibles == {
            "local": True,
            "mistral": True,
            "mistral-nombres": True,
        }


class TestElSobreDeLaTanda:
    """Las caras de una tanda viajan juntas, y cada una tan ligera como sola.

    Medido sobre doce caras del libro 7 a 300 ppp: el sobre pesaba doce megas
    -- treinta y uno en el peor de los casos -- y tardaba dos segundos y medio
    en armarse, porque cada cara entraba como PNG decodificado. En JPEG e
    incrustado tal cual pesa cinco y se arma en cuatro centésimas.
    """

    @staticmethod
    def jpeg(ancho: int, alto: int) -> bytes:
        from io import BytesIO

        from PIL import Image

        salida = BytesIO()
        Image.new("L", (ancho, alto), 220).save(salida, "JPEG", quality=85)
        return salida.getvalue()

    def test_cada_jpeg_entra_tal_cual_sin_recomprimir(self):
        import pymupdf

        from resolutions.adapters.mistral_ocr import _encuadernadas

        caras = [self.jpeg(300, 400), self.jpeg(320, 410)]
        sobre = _encuadernadas(caras)

        with pymupdf.open("pdf", sobre) as documento:
            assert documento.page_count == 2
            for pagina, original in zip(documento, caras, strict=True):
                xref = pagina.get_images(full=True)[0][0]
                assert documento.xref_get_key(xref, "Filter") == ("name", "/DCTDecode")
                assert documento.extract_image(xref)["image"] == original

    def test_cada_pagina_mide_lo_que_mide_su_imagen(self):
        import pymupdf

        from resolutions.adapters.mistral_ocr import _encuadernadas

        with pymupdf.open("pdf", _encuadernadas([self.jpeg(300, 400)])) as documento:
            assert (round(documento[0].rect.width), round(documento[0].rect.height)) == (300, 400)

    def test_lo_que_no_es_una_imagen_no_arma_sobre(self):
        from resolutions.adapters.mistral_ocr import _encuadernadas

        assert _encuadernadas([b"esto no es una imagen"]) is None
