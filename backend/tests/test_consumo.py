"""Lo que un trabajo le pidió a los proveedores de pago, contado.

Se fija que se cuente en las unidades en que cobra cada uno -- páginas el OCR,
tokens los modelos --, que las cuentas viajen con el progreso para que la
pantalla las enseñe en vivo, y que sin gasto no se enseñe nada: una carga leída
con el motor local no tiene por qué anunciar un cero.
"""

import json
import urllib.error

from resolutions.adapters.mistral_ocr import MistralOcr, MistralOcrConfig
from resolutions.application.consumo import Consumo, anotar_uso_anthropic, anotar_uso_json
from resolutions.application.ports import OcrResult
from resolutions.application.progress import ProgressEvent, Stage
from resolutions.application.read_diploma_book import ReadDiplomaBook
from resolutions.domain.diploma import TextLine


class TestElContador:
    def test_cada_proveedor_en_sus_unidades(self):
        consumo = Consumo()
        consumo.peticion("mistral-ocr", paginas=3)
        consumo.peticion("mistral-ocr", paginas=1)
        consumo.peticion("claude-bordes", tokens_entrada=1200, tokens_salida=80, tokens_cache=900)

        cuentas = consumo.as_dict()
        assert cuentas["proveedores"]["mistral-ocr"]["paginas_facturadas"] == 4
        assert cuentas["proveedores"]["mistral-ocr"]["peticiones"] == 2
        assert cuentas["proveedores"]["claude-bordes"]["tokens_entrada"] == 1200
        assert cuentas["tokens"] == 1280
        assert cuentas["paginas_facturadas"] == 4
        assert cuentas["peticiones"] == 3

    def test_sin_precio_no_se_inventa_dinero(self):
        consumo = Consumo()
        consumo.peticion("mistral-ocr", paginas=10)
        assert consumo.as_dict()["coste_estimado"] is None

    def test_con_precio_se_estima(self):
        consumo = Consumo(precio_por_pagina=0.001, moneda="USD")
        consumo.peticion("mistral-ocr", paginas=398)
        assert consumo.as_dict()["coste_estimado"] == 0.398

    def test_vacio_mientras_nadie_gasto(self):
        consumo = Consumo()
        assert consumo.vacio
        consumo.rechazo("mistral-ocr")
        assert not consumo.vacio

    def test_es_seguro_entre_hilos(self):
        """Ocho lectores anotando a la vez no pueden perder cuentas."""
        from concurrent.futures import ThreadPoolExecutor

        consumo = Consumo()
        with ThreadPoolExecutor(max_workers=8) as pool:
            for _ in range(800):
                pool.submit(consumo.peticion, "mistral-ocr", paginas=1)
        assert consumo.as_dict()["paginas_facturadas"] == 800

    def test_lee_lo_que_dice_el_sdk_de_anthropic(self):
        class Uso:
            input_tokens = 10
            output_tokens = 4
            cache_read_input_tokens = 6

        class Mensaje:
            usage = Uso()

        consumo = Consumo()
        anotar_uso_anthropic(consumo, "claude-vision", Mensaje())
        cuenta = consumo.as_dict()["proveedores"]["claude-vision"]
        assert (cuenta["tokens_entrada"], cuenta["tokens_salida"], cuenta["tokens_cache"]) == (10, 4, 6)

    def test_lee_las_dos_formas_del_json(self):
        consumo = Consumo()
        anotar_uso_json(consumo, "mistral-bordes", {"usage": {"prompt_tokens": 7, "completion_tokens": 2}})
        anotar_uso_json(consumo, "gemini-bordes", {"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}})
        cuentas = consumo.as_dict()
        assert cuentas["proveedores"]["mistral-bordes"]["tokens_entrada"] == 7
        assert cuentas["proveedores"]["gemini-bordes"]["tokens_salida"] == 1


class TestElOcrDeMistralAnota:
    class Respuesta:
        def __init__(self, cuerpo):
            self._cuerpo = json.dumps(cuerpo).encode()

        def read(self):
            return self._cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def test_anota_las_paginas_que_el_proveedor_dice_haber_cobrado(self, monkeypatch):
        respuesta = self.Respuesta({"pages": [{"markdown": "70/v"}], "usage_info": {"pages_processed": 1}})
        monkeypatch.setattr("urllib.request.urlopen", lambda peticion, timeout=None: respuesta)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))

        consumo = Consumo()
        MistralOcr(api_key="x", consumo=consumo).read(b"imagen")
        MistralOcr(api_key="x", consumo=consumo).read(b"imagen")

        cuenta = consumo.as_dict()["proveedores"]["mistral-ocr"]
        assert cuenta["peticiones"] == 2
        assert cuenta["paginas_facturadas"] == 2

    def test_un_429_cuenta_como_espera_y_no_como_pagina(self, monkeypatch):
        intentos = {"n": 0}
        respuesta = self.Respuesta({"pages": [{"markdown": "x"}], "usage_info": {"pages_processed": 1}})

        def urlopen_falso(peticion, timeout=None):
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise urllib.error.HTTPError(peticion.full_url, 429, "slow", {}, None)
            return respuesta

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        monkeypatch.setattr("json.load", lambda conexion: json.loads(conexion.read()))
        monkeypatch.setattr("time.sleep", lambda _s: None)

        consumo = Consumo()
        MistralOcr(api_key="x", consumo=consumo, config=MistralOcrConfig(espera_inicial=0.0)).read(b"i")
        cuenta = consumo.as_dict()["proveedores"]["mistral-ocr"]
        assert (cuenta["rechazos"], cuenta["peticiones"], cuenta["paginas_facturadas"]) == (1, 1, 1)

    def test_quedarse_sin_credito_es_un_fallo_y_no_una_pagina(self, monkeypatch):
        def urlopen_falso(peticion, timeout=None):
            raise urllib.error.HTTPError(peticion.full_url, 402, "budget", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", urlopen_falso)
        consumo = Consumo()
        MistralOcr(api_key="x", consumo=consumo).read(b"i")
        cuenta = consumo.as_dict()["proveedores"]["mistral-ocr"]
        assert (cuenta["fallos"], cuenta["paginas_facturadas"]) == (1, 0)


class TestElConsumoViajaConElProgreso:
    class Fuente:
        def __init__(self, paginas):
            self._paginas = paginas

        @property
        def page_count(self):
            return len(self._paginas)

        def lines_of(self, n):
            return [TextLine(text=t, y=float(i)) for i, t in enumerate(self._paginas[n - 1])]

        def render(self, n, band=None, dpi=200):
            return f"p{n}".encode()

    class OcrQueCobra:
        """Un motor de pago de mentira: cada lectura cuesta una página."""

        def __init__(self):
            self.consumo = Consumo()

        def read(self, image_png):
            self.consumo.peticion("mistral-ocr", paginas=1)
            return OcrResult(text="", mean_confidence=0.0)

    def test_cada_aviso_lleva_lo_gastado_hasta_entonces(self):
        recibidos = []

        class Reportero:
            def emit(self, event):
                recibidos.append(event)

        ReadDiplomaBook(ocr=self.OcrQueCobra(), progress=Reportero(), workers=2).execute(
            self.Fuente([("",)] * 4)
        )
        con_cuentas = [e for e in recibidos if e.consumo]
        assert con_cuentas, "ningún aviso trajo el consumo"
        assert con_cuentas[-1].consumo["paginas_facturadas"] >= 4
        # Y lo gastado sólo crece: la foto de cada aviso es la cuenta acumulada.
        facturadas = [e.consumo["paginas_facturadas"] for e in con_cuentas]
        assert facturadas == sorted(facturadas)

    def test_sin_motor_de_pago_no_se_anuncia_ningun_gasto(self):
        recibidos = []

        class Reportero:
            def emit(self, event):
                recibidos.append(event)

        ReadDiplomaBook(progress=Reportero()).execute(self.Fuente([("",)] * 2))
        assert all(e.consumo is None for e in recibidos)

    def test_el_evento_lo_serializa(self):
        evento = ProgressEvent(stage=Stage.PAGE, page_number=1, consumo={"paginas_facturadas": 3})
        assert evento.as_dict()["consumo"] == {"paginas_facturadas": 3}


class TestElRegistroDelTrabajoLoGuarda:
    def test_la_ultima_foto_manda(self):
        from resolutions.api.jobs import JobProgress

        progreso = JobProgress()
        progreso.apply({"stage": "opened", "page_count": 2})
        progreso.apply({"stage": "page", "page_number": 1, "consumo": {"paginas_facturadas": 1}})
        progreso.apply({"stage": "page", "page_number": 2, "consumo": {"paginas_facturadas": 2}})
        assert progreso.as_dict()["consumo"] == {"paginas_facturadas": 2}

    def test_sin_gasto_queda_vacio(self):
        from resolutions.api.jobs import JobProgress

        progreso = JobProgress()
        progreso.apply({"stage": "opened", "page_count": 1})
        progreso.apply({"stage": "page", "page_number": 1})
        assert progreso.as_dict()["consumo"] is None
