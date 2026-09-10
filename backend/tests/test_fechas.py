"""La fecha que lleva escrita un documento, y cuál de todas lo fecha.

El archivo necesita fechar cada unidad: es lo que el FUID llama fechas extremas
y lo que permite ordenar una caja en el tiempo sin abrirla. Estos papeles son
escaneos y no traen metadatos, así que se lee del texto.

Lo difícil no es reconocer una fecha sino distinguir la del documento de las que
sólo se citan dentro de él. Medido sobre un expediente real de 97 páginas: de
214 fechas reconocibles, 49 eran citas de leyes y sentencias.
"""

from __future__ import annotations

from datetime import date

import pytest

from resolutions.domain.fechas import fechas_de, primera_fecha, ultima_fecha


class TestLosTresFormatosDelCorpus:
    """Contados sobre el expediente: 157 con barras, 49 en letra, 8 con guiones."""

    @pytest.mark.parametrize(
        ("texto", "esperada"),
        [
            ("AGUSTIN CODAZZI, 28/01/2022 Señora INIRIDA", date(2022, 1, 28)),
            ("En la fecha 18-02-2022 compareció a las oficinas", date(2022, 2, 18)),
            ("el día 27 de enero del 2022, radicada bajo", date(2022, 1, 27)),
            ("firmado el 9 DE DICIEMBRE DE 2021 por el operador", date(2021, 12, 9)),
        ],
        ids=["barras", "guiones", "en-letra", "en-letra-mayusculas"],
    )
    def test_se_lee_la_fecha(self, texto, esperada):
        assert fechas_de(texto) == [esperada]


class TestLoQueSeCitaNoFechaNada:
    """Un escrito jurídico nombra docenas de normas y todas llevan año.

    Ninguna dice cuándo se escribió el papel que las cita, y sin este filtro
    un recurso de reposición de 2022 quedaba fechado en 1991.
    """

    @pytest.mark.parametrize(
        "texto",
        [
            "con fundamento en la Ley 142 de 1994",
            "las Sentencias T-1204 de 2001 y T-558 de 2006",
            "el Decreto 2591 de 1991 y su reglamento",
            "el Artículo 29 de la Constitución de 1991",
            "Sentencia SU-1010 de Octubre del 2008",
        ],
        ids=["ley", "sentencias", "decreto", "articulo", "providencia"],
    )
    def test_una_cita_no_es_una_fecha(self, texto):
        assert fechas_de(texto) == []

    def test_pero_la_fecha_del_papel_sobrevive_al_lado_de_una_cita(self):
        texto = (
            "Cartagena, 08-02-2022. Con fundamento en la Ley 142 de 1994 "
            "y la Sentencia T-1204 de 2001 se resuelve"
        )
        assert fechas_de(texto) == [date(2022, 2, 8)]


class TestLoQueNoEsUnaFecha:
    def test_una_fecha_imposible_no_es_una_fecha(self):
        """El OCR produce "31/02/2022" más veces de lo que parece."""
        assert fechas_de("revisión del 31/02/2022") == []

    def test_un_mes_que_no_existe_tampoco(self):
        assert fechas_de("el 12/25/2021 se notificó") == []

    def test_ni_un_ano_de_archivo_historico(self):
        """Estos expedientes son correspondencia viva: un año así es ruido."""
        assert fechas_de("radicado el 10/12/1850") == []


class TestLaQueFechaLaUnidad:
    PAGINAS = [
        "Cartagena, 28/01/2022 Señora INIRIDA, en atención a su escrito",
        "anexo sin ninguna fecha legible",
        "En la fecha 18-02-2022 compareció a notificarse",
    ]

    def test_la_ultima_es_la_mas_reciente_del_documento_entero(self):
        """Se lee el documento completo, no su primera página: un acta puede
        llevar la fecha de la visita arriba y la del acuse detrás."""
        assert ultima_fecha(self.PAGINAS) == date(2022, 2, 18)

    def test_y_la_primera_es_la_mas_antigua(self):
        assert primera_fecha(self.PAGINAS) == date(2022, 1, 28)

    def test_un_documento_sin_fechas_no_tiene_fecha(self):
        assert ultima_fecha(["una hoja de firmas y nada más"]) is None

    def test_un_documento_vacio_tampoco(self):
        assert ultima_fecha([]) is None
