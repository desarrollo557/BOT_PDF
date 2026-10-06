"""El orquestador de habilidades: quién elige la ruta cuando nadie reconoce el papel.

El operador lo pidió así: «cuando el bot no reconozca un documento, que llame a
todas las habilidades, y que el orquestador tome la decisión dependiendo de lo
que la OCR alimente al flujo». Estas pruebas fijan las tres preguntas en su
orden -- los marcadores, todas las habilidades, la página entera -- y las reglas
que las gobiernan: los marcadores que deciden se respetan, ninguna habilidad
gana por descarte, un dato suelto no decide, y una avería no es un veredicto.

Todo con textos sintéticos y motores falsos: ni red, ni Tesseract, ni IA.
"""

from __future__ import annotations

import pytest

from resolutions.application.orquestador import (
    MIN_SAMPLE_CHARS,
    DecididoPor,
    Orquestador,
    muestrear,
    paginas_de_muestra,
    repartidas,
)
from resolutions.application.ports import HEADER_BAND, OcrResult
from resolutions.domain.doctype import DocumentType, classify_pages
from resolutions.domain.validacion import (
    PUNTAJE_MINIMO,
    VALIDADORES,
    Validacion,
    ganadora,
    validar_todas,
)

# -----------------------------------------------------------------------------
#  Los textos
# -----------------------------------------------------------------------------
#  Cada uno se comprueba contra `classify_pages` en las pruebas que lo usan: si
#  mañana un marcador nuevo los reconociera, la prueba tiene que decirlo en vez
#  de seguir pasando por otro motivo.
# -----------------------------------------------------------------------------

NEUTRO = (
    "Texto corrido del expediente, sin ninguna frase que lo identifique, escrito "
    "para que la capa de texto alcance el largo minimo de la muestra."
)

#: Una resolución de un consejo: el encabezado oficial abre el renglón, pero el
#: cuerpo trae el vocabulario de un acta de sesión y los marcadores empatan.
RESOLUCION_DE_CONSEJO = (
    "RESOLUCIÓN No. 00086 de 2023\n"
    "El Consejo de Facultad, en cumplimiento del orden del dia de su sesion,\n"
    + NEUTRO
)

#: La ficha de un libro de diplomas antiguo: ninguna leyenda de las modernas,
#: pero la cédula rotulada y el título en la misma página.
FICHA_ANTIGUA = (
    "C.C. No. 7.882.907 Expedida en Arjona Bolivar\n"
    "DOCTOR EN MEDICINA Y CIRUGIA\n"
    + NEUTRO
)

PAGINA_DE_RESOLUCION = """
UNIVERSIDAD DE CARTAGENA
RESOLUCION No. 00072 de 2023
POR MEDIO DE LA CUAL SE HACE UN NOMBRAMIENTO PROVISIONAL EN UN CARGO
EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA
en uso de sus facultades legales y estatutarias
CONSIDERANDO
RESUELVE
COMUNIQUESE Y CUMPLASE
"""


# -----------------------------------------------------------------------------
#  Un PDF y un OCR de mentira
# -----------------------------------------------------------------------------


class FuenteFalsa:
    """Un documento hecho de textos.

    ``capas`` es la capa de texto de cada página; ``banda`` y ``entera``, lo que
    un OCR leería en la imagen de la banda superior o de la página entera. La
    imagen que se "rasteriza" dice qué es y de qué página, para que el OCR
    falso sepa qué contestar.
    """

    def __init__(self, capas, *, banda=None, entera=None):
        self._capas = list(capas)
        self.banda = dict(banda or {})
        self.entera = dict(entera or {})
        self.renders: list[tuple[int, object]] = []
        self.cerrada = False

    @property
    def page_count(self) -> int:
        return len(self._capas)

    def text_of(self, numero: int) -> str:
        return self._capas[numero - 1]

    def render(self, numero: int, band=None, dpi: int = 200) -> bytes:
        self.renders.append((numero, band))
        return f"{'banda' if band is not None else 'entera'}:{numero}".encode()

    def close(self) -> None:
        self.cerrada = True


class OcrFalso:
    def __init__(self, fuente: FuenteFalsa):
        self._fuente = fuente
        self.lecturas: list[tuple[str, int]] = []

    def read(self, image_png: bytes) -> OcrResult:
        clase, numero = image_png.decode().split(":")
        self.lecturas.append((clase, int(numero)))
        textos = self._fuente.banda if clase == "banda" else self._fuente.entera
        return OcrResult(text=textos.get(int(numero), ""))


def escaneo(paginas: int, *, banda=None, entera=None) -> FuenteFalsa:
    """Un escaneo sin capa de texto: todo lo que se sepa, lo dirá el OCR."""
    return FuenteFalsa([""] * paginas, banda=banda, entera=entera)


# -----------------------------------------------------------------------------
#  1. Los marcadores
# -----------------------------------------------------------------------------


class TestLosMarcadoresQueDecidenSeRespetan:
    def test_un_legajo_de_resoluciones_lo_deciden_los_marcadores(self):
        fuente = FuenteFalsa([PAGINA_DE_RESOLUCION] * 3)
        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.RESOLUCION
        assert eleccion.decidido_por is DecididoPor.MARCADORES
        # Y no se consultó a nadie más: es exactamente lo que se hacía antes.
        assert eleccion.validaciones == {}
        assert eleccion.segunda_mirada == ()

    def test_decidir_por_los_marcadores_no_gasta_ninguna_pagina_entera(self):
        fuente = escaneo(12, banda={n: PAGINA_DE_RESOLUCION for n in range(1, 13)})
        Orquestador(OcrFalso(fuente)).elegir(fuente)
        assert all(band is not None for _, band in fuente.renders)

    def test_la_primera_mirada_puede_hacerla_otro_camino(self):
        """El despachador la hace a través del inventario, como siempre."""
        from resolutions.application.inventory_document import InventoryDocument

        fuente = FuenteFalsa([PAGINA_DE_RESOLUCION] * 2)
        llamadas = []

        def primera(fuente_, motor):
            llamadas.append(1)
            return InventoryDocument(ocr=motor).identify(fuente_)

        eleccion = Orquestador(OcrFalso(fuente), primera_mirada=primera).elegir(fuente)
        assert llamadas == [1]
        assert eleccion.tipo is DocumentType.RESOLUCION


# -----------------------------------------------------------------------------
#  2. Todas las habilidades
# -----------------------------------------------------------------------------


class TestCuandoLosMarcadoresNoDecidenSeConsultaATodas:
    def test_una_resolucion_de_consejo_la_gana_la_habilidad_de_resoluciones(self):
        """Los marcadores empatan; el encabezado que abre el renglón no.

        El encabezado oficial suma lo mismo que el vocabulario de sesión del
        cuerpo ("orden del día", "consejo de facultad"), y `doctype` no zanja un
        empate. El lector del agrupador sí: el encabezado abre su renglón, y
        ninguna página trae el encabezado de un acta.
        """
        fuente = FuenteFalsa([RESOLUCION_DE_CONSEJO, NEUTRO])
        assert classify_pages([(1, RESOLUCION_DE_CONSEJO)]).document_type is (
            DocumentType.DESCONOCIDO
        )

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.RESOLUCION
        assert eleccion.decidido_por is DecididoPor.HABILIDAD
        resoluciones = eleccion.validaciones[DocumentType.RESOLUCION]
        assert resoluciones.paginas == (1,)
        assert "RESOLUCIÓN No. 00086" in resoluciones.evidencia[0]
        assert "abre el renglón" in resoluciones.evidencia[0]

    def test_un_libro_antiguo_sin_leyendas_lo_gana_la_de_diplomas(self):
        """Ningún marcador, pero cédula y título en la misma ficha."""
        paginas = [FICHA_ANTIGUA if n % 3 == 1 else NEUTRO for n in range(1, 13)]
        fuente = FuenteFalsa(paginas)
        assert classify_pages(list(enumerate(paginas, 1))).document_type is (
            DocumentType.DESCONOCIDO
        )

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.DIPLOMA
        assert eleccion.decidido_por is DecididoPor.HABILIDAD
        assert "cédula 7882907" in eleccion.motivo

    def test_se_consulta_a_todas_y_no_solo_a_la_primera_que_valida(self):
        fuente = FuenteFalsa([RESOLUCION_DE_CONSEJO, NEUTRO])
        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)
        assert set(eleccion.validaciones) == set(VALIDADORES)

    def test_dos_que_validan_sin_margen_no_deciden(self):
        """Una página dice resolución y otra dice diploma: no gana ninguna."""
        fuente = FuenteFalsa([RESOLUCION_DE_CONSEJO, FICHA_ANTIGUA])

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.DESCONOCIDO
        assert eleccion.decidido_por is DecididoPor.NADIE
        assert eleccion.validaciones[DocumentType.RESOLUCION].valida
        assert eleccion.validaciones[DocumentType.DIPLOMA].valida
        assert "sin ventaja clara" in eleccion.motivo

    def test_un_dato_suelto_a_media_caja_no_decide(self):
        """La caja de correspondencia con una resolución metida en medio."""
        paginas = [NEUTRO] * 12
        paginas[6] = FICHA_ANTIGUA
        fuente = FuenteFalsa(paginas)

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.DESCONOCIDO
        assert "un dato suelto no decide" in eleccion.motivo


class TestLasReglasDeLaGanadora:
    def _validacion(self, tipo, paginas, muestreadas=12):
        return Validacion(
            tipo=tipo,
            paginas=tuple(paginas),
            evidencia=tuple(f"p{n}: algo" for n in paginas),
            puntaje=len(paginas) / muestreadas,
            muestreadas=muestreadas,
        )

    def test_nadie_gana_por_descarte(self):
        """Tres sin evidencia y una sin evidencia: la última no queda en pie."""
        validaciones = {tipo: self._validacion(tipo, []) for tipo in VALIDADORES}
        tipo, motivo = ganadora(validaciones)
        assert tipo is None
        assert "ninguna habilidad" in motivo

    def test_gana_la_que_valida_con_ventaja(self):
        validaciones = {
            DocumentType.RESOLUCION: self._validacion(DocumentType.RESOLUCION, [1, 4, 7]),
            DocumentType.DIPLOMA: self._validacion(DocumentType.DIPLOMA, [10]),
        }
        tipo, _ = ganadora(validaciones)
        assert tipo is DocumentType.RESOLUCION

    def test_sin_ventaja_clara_no_gana_nadie(self):
        validaciones = {
            DocumentType.RESOLUCION: self._validacion(DocumentType.RESOLUCION, [1, 4, 7]),
            DocumentType.DIPLOMA: self._validacion(DocumentType.DIPLOMA, [2, 5]),
        }
        assert ganadora(validaciones)[0] is None

    def test_en_un_documento_corto_una_pagina_si_es_una_parte_grande(self):
        validacion = self._validacion(DocumentType.ACTA_CONSEJO, [3], muestreadas=5)
        assert validacion.puntaje >= PUNTAJE_MINIMO
        assert ganadora({DocumentType.ACTA_CONSEJO: validacion})[0] is (
            DocumentType.ACTA_CONSEJO
        )

    def test_las_actas_de_grado_no_son_candidatas(self):
        """Su lectura es un borrador; el orquestador no la propone por su cuenta."""
        assert DocumentType.ACTA not in VALIDADORES

    def test_una_pagina_en_blanco_no_es_evidencia_de_nada(self):
        validaciones = validar_todas([(1, ""), (2, "   ")])
        assert not any(validacion.valida for validacion in validaciones.values())


# -----------------------------------------------------------------------------
#  3. La página entera
# -----------------------------------------------------------------------------


class TestCuandoNadieValidaSeLeeLaPaginaEntera:
    def test_se_pide_la_pagina_entera_con_banda_none_y_el_mismo_ocr(self):
        fuente = escaneo(12, banda={n: "UNIVERSIDAD DE CARTAGENA" for n in range(1, 13)})
        ocr = OcrFalso(fuente)

        eleccion = Orquestador(ocr, paginas_segunda=4).elegir(fuente)

        enteras = [numero for numero, band in fuente.renders if band is None]
        assert len(enteras) == 4
        assert set(enteras) <= set(paginas_de_muestra(12))
        assert sorted(enteras) == list(eleccion.segunda_mirada)
        # El mismo motor: las cuatro páginas enteras las leyó el OCR que recibió.
        assert [n for clase, n in ocr.lecturas if clase == "entera"] == enteras
        # Y como tampoco dijeron nada, nadie validó.
        assert eleccion.tipo is DocumentType.DESCONOCIDO
        assert eleccion.decidido_por is DecididoPor.NADIE
        assert eleccion.motivo.startswith("nadie validó")

    def test_lo_que_dice_la_pagina_entera_puede_decidir_por_una_habilidad(self):
        """La banda superior no ve la ficha; la página entera sí."""
        fuente = escaneo(
            12,
            banda={n: "UNIVERSIDAD DE CARTAGENA" for n in range(1, 13)},
            entera={n: FICHA_ANTIGUA for n in range(1, 13)},
        )

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.DIPLOMA
        assert eleccion.decidido_por is DecididoPor.HABILIDAD
        assert len(eleccion.segunda_mirada) == 4
        assert "leídas enteras" in eleccion.motivo

    def test_o_por_los_marcadores_que_el_encabezado_no_mostraba(self):
        fuente = escaneo(
            4,
            banda={n: "UNIVERSIDAD DE CARTAGENA" for n in range(1, 5)},
            entera={n: PAGINA_DE_RESOLUCION for n in range(1, 5)},
        )

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert eleccion.tipo is DocumentType.RESOLUCION
        assert eleccion.decidido_por is DecididoPor.MARCADORES
        assert eleccion.segunda_mirada == (1, 2, 3, 4)

    def test_las_paginas_con_capa_de_texto_no_se_vuelven_a_leer(self):
        """Ya se leyeron enteras: un OCR encima daría un texto peor."""
        fuente = FuenteFalsa([NEUTRO] * 6)
        assert len(NEUTRO) >= MIN_SAMPLE_CHARS

        eleccion = Orquestador(OcrFalso(fuente)).elegir(fuente)

        assert fuente.renders == []
        assert eleccion.tipo is DocumentType.DESCONOCIDO
        assert eleccion.segunda_mirada == ()

    def test_sin_segunda_mirada_no_se_lee_ninguna_pagina_entera(self):
        fuente = escaneo(6, entera={n: FICHA_ANTIGUA for n in range(1, 7)})

        eleccion = Orquestador(OcrFalso(fuente), segunda_mirada=False).elegir(fuente)

        assert all(band is not None for _, band in fuente.renders)
        assert eleccion.tipo is DocumentType.DESCONOCIDO

    def test_sin_ocr_no_hay_segunda_mirada_ni_averia(self):
        eleccion = Orquestador(None).elegir(escaneo(3))
        assert eleccion.tipo is DocumentType.DESCONOCIDO


# -----------------------------------------------------------------------------
#  La muestra
# -----------------------------------------------------------------------------


class TestLaMuestraEsLaDeSiempre:
    def test_el_inventario_y_el_orquestador_miran_las_mismas_paginas(self):
        from resolutions.application.inventory_document import InventoryDocument

        fuente = escaneo(40, banda={n: f"banda {n}" for n in range(1, 41)})
        ocr = OcrFalso(fuente)

        assert InventoryDocument(ocr=ocr)._sample(fuente) == muestrear(fuente, ocr)
        assert [n for n, _ in muestrear(fuente, ocr)] == paginas_de_muestra(40)
        assert len(paginas_de_muestra(40)) == 12

    def test_por_omision_se_lee_solo_la_banda_superior(self):
        fuente = escaneo(2)
        muestrear(fuente, OcrFalso(fuente))
        assert {band for _, band in fuente.renders} == {HEADER_BAND}

    def test_la_capa_de_texto_suficiente_no_pasa_por_el_ocr(self):
        fuente = FuenteFalsa([NEUTRO, ""])
        ocr = OcrFalso(fuente)
        muestrear(fuente, ocr)
        assert ocr.lecturas == [("banda", 2)]

    def test_la_banda_no_se_lee_dos_veces_aunque_pregunten_dos(self):
        """La primera mirada del inventario y la consulta a las habilidades
        miran la misma muestra; el OCR la lee una sola vez."""
        from resolutions.application.inventory_document import InventoryDocument

        fuente = escaneo(12, banda={n: FICHA_ANTIGUA for n in range(1, 13)})
        ocr = OcrFalso(fuente)

        eleccion = Orquestador(
            ocr,
            primera_mirada=lambda f, motor: InventoryDocument(ocr=motor).identify(f),
        ).elegir(fuente)

        assert eleccion.tipo is DocumentType.DIPLOMA
        bandas = [n for clase, n in ocr.lecturas if clase == "banda"]
        assert sorted(bandas) == paginas_de_muestra(12)

    def test_repartidas_va_de_punta_a_punta(self):
        assert repartidas([1, 2, 3], 4) == [1, 2, 3]
        assert repartidas(list(range(1, 13)), 4) == [1, 4, 7, 10]
        assert repartidas([1, 2, 3], 0) == []


# -----------------------------------------------------------------------------
#  El despachador
# -----------------------------------------------------------------------------


@pytest.fixture
def documento(monkeypatch):
    """Sustituye el PDF y el Tesseract del despachador por los de mentira."""
    import resolutions.adapters.pymupdf_source as pymupdf_source
    import resolutions.adapters.tesseract_ocr as tesseract_ocr

    estado = {}

    def preparar(fuente: FuenteFalsa) -> FuenteFalsa:
        estado["fuente"] = fuente
        monkeypatch.setattr(pymupdf_source, "PyMuPDFPageSource", lambda *_a, **_k: fuente)
        monkeypatch.setattr(
            tesseract_ocr, "HeaderAndPageOcr", lambda *_a, **_k: OcrFalso(fuente)
        )
        return fuente

    return preparar


def _payload(task: str = "split") -> dict:
    return {
        "job_id": "t",
        "source": "x.pdf",
        "filename": "x.pdf",
        "task": task,
        "settings": {"ocr_language": "spa"},
    }


class TestElDespachadorUsaElOrquestador:
    def test_reconoce_con_el_orquestador_y_deja_la_eleccion_en_el_payload(
        self, documento, monkeypatch
    ):
        from resolutions.api import worker

        avisos = []
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: avisos.append(k))
        fuente = documento(FuenteFalsa([RESOLUCION_DE_CONSEJO, NEUTRO]))
        datos = _payload()

        assert worker._recognise(datos) is DocumentType.RESOLUCION
        assert datos["reconocimiento"]["tipo"] == "resolucion"
        assert datos["reconocimiento"]["decidido_por"] == "habilidad"
        assert fuente.cerrada
        # Una ruta que eligió una habilidad no se elige en silencio.
        assert any("orquestador" in (aviso.get("detail") or "") for aviso in avisos)

    def test_una_averia_sigue_siendo_none_y_no_deja_eleccion(
        self, documento, monkeypatch
    ):
        from resolutions.api import worker
        from resolutions.application import inventory_document

        class Averiado:
            def __init__(self, *_a, **_k):
                pass

            def identify(self, _source):
                raise RuntimeError("tesseract no está")

        monkeypatch.setattr(inventory_document, "InventoryDocument", Averiado)
        fuente = documento(FuenteFalsa([PAGINA_DE_RESOLUCION]))
        datos = _payload()

        assert worker._recognise(datos) is None
        assert "reconocimiento" not in datos
        assert fuente.cerrada

    def test_el_informe_de_la_ruta_lleva_el_reconocimiento(self, documento, monkeypatch):
        from resolutions.api import worker

        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        monkeypatch.setattr(
            worker, "_record_split_job", lambda payload, task, tipo=None: {"tipo": tipo}
        )
        documento(FuenteFalsa([FICHA_ANTIGUA if n % 3 == 1 else NEUTRO for n in range(1, 13)]))

        informe = worker.process_document_job(_payload())

        assert informe["tipo"] is DocumentType.DIPLOMA
        assert informe["reconocimiento"]["tipo"] == "diploma"
        assert informe["reconocimiento"]["validaciones"]

    def test_lo_desconocido_sigue_yendo_a_continuidad(self, documento, monkeypatch):
        """Si nadie valida, el despacho es el de siempre."""
        from resolutions.api import worker

        visitados = []
        monkeypatch.setattr(worker, "_anunciar", lambda *a, **k: None)
        monkeypatch.setattr(
            worker,
            "_segment_job",
            lambda payload, task, **_k: visitados.append("continuidad") or {},
        )
        documento(FuenteFalsa([NEUTRO] * 4))

        informe = worker.process_document_job(_payload())

        assert visitados == ["continuidad"]
        assert informe["reconocimiento"]["decidido_por"] == "nadie"
