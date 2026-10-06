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

from resolutions.domain.fechas import (
    fecha_de_la_pagina,
    fechas_de,
    primera_fecha,
    ultima_fecha,
)


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


class TestLaFechaDeUnaPagina:
    """La fecha de una página suelta, para agrupar una caja por mes.

    Los casos salen de un expediente escaneado real (UPD2532400), leído con la
    OCR de casa. Cada uno es una página que la regla de «la más reciente»
    fechaba mal o no fechaba.
    """

    def test_manda_el_encabezado_ciudad_fecha_sobre_una_fecha_posterior(self):
        """Por la más reciente, esta carta de diciembre se iba a febrero."""
        pagina = (
            "Grupo-epm Cartagena, 21/12/2021 Señor Usuario Ref: respuesta. "
            "Cuenta con plazo hasta el 01/02/2022 para interponer el recurso."
        )
        assert fecha_de_la_pagina(pagina) == date(2021, 12, 21)

    def test_el_encabezado_tambien_se_reconoce_escrito_en_letra(self):
        assert fecha_de_la_pagina("Sahagun, 07 de Diciembre de 2021 Señor Usuario") == date(
            2021, 12, 7
        )

    def test_el_mes_delante_del_dia(self):
        """«Mayo 20 de 2021»: así encabezan algunos oficios."""
        assert fecha_de_la_pagina("Sahagún, Mayo 20 de 2021 CARIBEMAR") == date(2021, 5, 20)

    def test_los_espacios_que_la_ocr_mete_entre_las_barras(self):
        assert fecha_de_la_pagina("Consecutivo No.2021 SAHAGUN, 25/ 05/ 2021 Señor") == date(
            2021, 5, 25
        )

    def test_la_formula_de_firma_de_un_pagare(self):
        pagina = "Firmado en la ciudad de SAHAGUN alos 26 días del mes de — Abril del 2021"
        assert fecha_de_la_pagina(pagina) == date(2021, 4, 26)

    def test_sin_encabezado_manda_la_mas_reciente(self):
        """La publicación de un aviso lleva la fecha del día en que se publica."""
        pagina = (
            "respuesta a la petición presentada el día 20/05/2021, se notifica el "
            "aviso de 04-06-2021. El presente aviso se publica el día 18/06/2021."
        )
        assert fecha_de_la_pagina(pagina) == date(2021, 6, 18)

    def test_una_pagina_sin_fechas(self):
        assert fecha_de_la_pagina("REPUBLICA DE COLOMBIA IDENTIFICACION PERSONAL") is None

    def test_no_cambia_lo_que_leen_las_otras_rutas(self):
        """«Mayo 20 de 2021» no la reconoce fechas_de, y así sigue: sólo esto la lee."""
        assert fechas_de("Sahagún, Mayo 20 de 2021") == []
