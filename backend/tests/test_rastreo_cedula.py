"""La segunda mirada local a la cédula, antes de pagar por ella.

El operador pidió que ningún documento quedara sin cédula y sin nombre, y que
antes de mandar una página a la IA se agotara lo que la OCR pudiera dar. Este
rastreo es ese intento: recorta la franja donde vive el número, se la pasa a
Tesseract atado a un renglón y a un juego de dígitos, y comprueba lo que sale.

Lo que más importa aquí **no es cuántas cédulas recupera sino que no invente
ninguna**, y hay un motivo medido: la primera versión barría la hoja a falta de
rótulo, y sobre el libro 7 de 1982 -- manuscrito, letra corrida -- devolvió una
cédula en las cuatro caras que se le probaron. Las cuatro falsas: 22212251,
515232, 6211552 y 213353, donde las de verdad eran 780064, 7882907, 30761 y
9091482.

No era un fallo de afinado. Atar Tesseract a dígitos no le enseña a leer
números: le prohíbe contestar otra cosa. Delante de un trazo de pluma contesta
dígitos igual, y como salen seis u ocho, pasan la prueba de credibilidad, entran
en el nombre del archivo y de paso impiden que esa página escale a la IA, que
era la única capaz de leerla.
"""

import pytest

from resolutions.adapters.rastreo_cedula import ANCLAS, RastreoDeCedula
from resolutions.application.ports import LineBox
from resolutions.domain.diploma import buscar_cedula


class FuenteFalsa:
    """Una página con el texto y las cajas que se le digan."""

    def __init__(self, texto: str, cajas: list[LineBox] | None = None):
        self._texto = texto
        self._cajas = cajas or []
        self.recortes: list[tuple] = []

    def text_of(self, page_number: int) -> str:
        return self._texto

    def boxes_of(self, page_number: int) -> list[LineBox]:
        return self._cajas

    def render(self, page_number, band=None, dpi=200) -> bytes:
        self.recortes.append((page_number, band, dpi))
        return b"recorte"


class MotorFalso:
    """Un Tesseract de mentira que contesta lo que se le indique."""

    def __init__(self, respuestas: list[str]):
        self._respuestas = list(respuestas)
        self.llamadas = 0

    def read(self, imagen: bytes):
        from resolutions.application.ports import OcrResult

        self.llamadas += 1
        texto = self._respuestas.pop(0) if self._respuestas else ""
        return OcrResult(text=texto, mean_confidence=0.0)


@pytest.fixture
def rastreo():
    return RastreoDeCedula()


def con_motores(rastreo, atado: list[str], libre: list[str]):
    """Le cambia los dos motores por dobles, para no llamar al binario."""
    rastreo._numerico = MotorFalso(atado)
    rastreo._libre = MotorFalso(libre)
    return rastreo


class TestNoSeMiraDondeNoHayNadaQueSeguir:
    """Sin el rótulo impreso no hay banda, y sin banda no se lee nada.

    Es la defensa de fondo contra la invención: el rastreo se orienta por lo
    que el formulario trae impreso, de modo que una página escaneada sin capa
    de texto -- que es donde el número está manuscrito -- no se toca.
    """

    def test_una_pagina_sin_capa_de_texto_no_se_rastrea(self, rastreo):
        fuente = FuenteFalsa(texto="")
        con_motores(rastreo, ["7882907"], ["C.C. No. 7.882.907"])
        assert rastreo.buscar(fuente, 1) is None
        assert fuente.recortes == [], "no se rasteriza ni una banda"

    def test_una_pagina_sin_el_rotulo_tampoco(self, rastreo):
        fuente = FuenteFalsa(texto="Folio 728\nJUAN PEREZ GOMEZ\nTitulo recibido: ABOGADO")
        con_motores(rastreo, ["7882907"], ["C.C. No. 7.882.907"])
        assert rastreo.buscar(fuente, 1) is None
        assert fuente.recortes == []

    def test_los_rotulos_que_se_reconocen(self):
        """Los que los dos formularios de la casa imprimen."""
        assert "C.C" in ANCLAS
        assert "IDENTIFICADO CON" in ANCLAS


class TestSoloSeCreeLoQueDosLecturasConfirman:
    """La corroboración es lo que separa un número leído de uno fabricado."""

    def caja(self):
        return [LineBox(text="identificado con CC. No.", center_x=0.5, top=0.4)]

    def test_cuando_las_dos_coinciden_se_entrega(self, rastreo):
        fuente = FuenteFalsa("identificado con CC. No. 1047375454", self.caja())
        con_motores(rastreo, ["1047375454"], ["CC. No. 1047375454"])
        assert rastreo.buscar(fuente, 1) == "1047375454"

    def test_cuando_discrepan_no_se_entrega_nada(self, rastreo):
        """El caso del manuscrito: la atada inventa, la libre ve garabatos."""
        fuente = FuenteFalsa("identificado con CC. No.", self.caja())
        con_motores(rastreo, ["22212251"], ["fis. / ??  Aur"])
        assert rastreo.buscar(fuente, 1) is None

    def test_si_la_libre_lee_otro_numero_tampoco(self, rastreo):
        fuente = FuenteFalsa("identificado con CC. No.", self.caja())
        con_motores(rastreo, ["1047375454"], ["CC. No. 1047375455"])
        assert rastreo.buscar(fuente, 1) is None

    def test_y_se_mira_la_banda_del_rotulo_y_no_la_pagina(self, rastreo):
        fuente = FuenteFalsa("identificado con CC. No. 1047375454", self.caja())
        con_motores(rastreo, ["1047375454"], ["CC. No. 1047375454"])
        rastreo.buscar(fuente, 1)
        _, banda, _ = fuente.recortes[0]
        assert banda.y0 < 0.4 < banda.y1, "la franja rodea al renglón anclado"
        assert banda.y1 - banda.y0 < 0.2, "y es una franja, no media página"


class TestLoQueSeEntregaSeSostiene:
    """Un número que no se sostiene como cédula no sale de aquí.

    Quien lo pide lo va a usar para nombrar un archivo y para decidir un corte,
    así que entregar uno dudoso sólo serviría para que alguien lo usara sin
    comprobarlo.
    """

    def test_el_folio_no_pasa_por_cedula(self):
        assert buscar_cedula("Folio 728") is None

    def test_ni_el_ano(self):
        assert buscar_cedula("de mil novecientos 1982") is None

    def test_un_numero_rotulado_si(self):
        assert buscar_cedula("identificado con CC. No. 1047375454") == "1047375454"

    def test_y_uno_suelto_con_forma_de_cedula_tambien(self):
        """Es lo que devuelve la lectura atada a dígitos, sin su rótulo."""
        assert buscar_cedula("7.882.907") == "7882907"

    def test_pero_uno_corto_no(self):
        assert buscar_cedula("30761") is None


class TestUnRotuloConUnNumeroRotoNoDaPasoAUnNumeroSuelto:
    """De "C.C. No. 4V.425.748" el número suelto es "425.748": seis dígitos que
    pasan por cédula y no lo son -- le falta el "45" que el OCR leyó como uve.
    Un trozo de cédula con aspecto de cédula nombra el archivo y nadie vuelve a
    mirarlo."""

    def test_una_letra_dentro_del_numero_lo_invalida_entero(self):
        from resolutions.domain.diploma import buscar_cedula

        assert buscar_cedula("C.C. No. 4V.425.748 Expedida en Ogeza") is None
        assert buscar_cedula("C.C. No. 33/23.201 Expedida") is None

    def test_pero_un_punto_de_menos_no_es_una_letra(self):
        """"9.081624" y "8673.721" son lecturas reales, y son la cédula entera."""
        from resolutions.domain.diploma import buscar_cedula

        assert buscar_cedula("C.C. No. 9.081624 Expedida en Cartagena") == "9081624"
        assert buscar_cedula("C.C. No. 8673.721 Expedida en B/guilla") == "8673721"
        assert buscar_cedula("C.C. No. 32625.076") == "32625076"

    def test_sin_rotulo_el_numero_suelto_sigue_valiendo(self):
        """Es lo que lee el rastreo atado a dígitos, que no ve ningún rótulo."""
        from resolutions.domain.diploma import buscar_cedula

        assert buscar_cedula("7.882.907") == "7882907"
