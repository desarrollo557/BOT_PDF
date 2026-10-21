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
    pistas_de_fecha,
    primera_fecha,
    ultima_fecha,
)


class TestTodasLasFormasDeEscribirUnaFecha:
    """«Que el bot cubra todas las excepciones posibles» (2026-10-21, UPD2465747)."""

    @pytest.mark.parametrize(
        ("texto", "esperada"),
        [
            ("Talaigua nuevo Bolívar, 07 octubre del 2022", date(2022, 10, 7)),
            ("Magangué, octubre 07 del 2022", date(2022, 10, 7)),
            ("Octubre 07, 2022", date(2022, 10, 7)),
            ("07 de octubre, 2022", date(2022, 10, 7)),
            ("07 de octubre del año 2022", date(2022, 10, 7)),
            ("07.10.2022", date(2022, 10, 7)),
            ("recibido 07/10/22", date(2022, 10, 7)),
            ("a los 7 días de octubre de 2.022", date(2022, 10, 7)),
            ("siete (7) de octubre de 2022", date(2022, 10, 7)),
            ("siete de octubre de dos mil veintidós", date(2022, 10, 7)),
            ("primero de mayo de 2021", date(2021, 5, 1)),
            ("treinta y uno de diciembre de dos mil veinte", date(2020, 12, 31)),
            ("veinte de enero de mil novecientos noventa y ocho", date(1998, 1, 20)),
            ("Fecha de emisión: 2022-10-07", date(2022, 10, 7)),
            ("O7/1O/2O22", date(2022, 10, 7)),
        ],
    )
    def test_se_lee(self, texto, esperada):
        assert fecha_de_la_pagina(texto) == esperada

    @pytest.mark.parametrize(
        "texto",
        [
            # Un código de guía con guiones no es una fecha.
            "GUIA 2022-10-07-5511",
            # Ni el número de una cifra con puntos de miles.
            "por valor de $ 1.500.000",
            # Ni un «o» de la prosa delante de un número.
            "uno o 2 documentos",
            # Ni una fecha futura escrita con año corto.
            "vence 07/10/99 de la prórroga",
        ],
    )
    def test_no_se_inventa(self, texto):
        fecha = fecha_de_la_pagina(texto)
        assert fecha is None or fecha.year == 1999


class TestLaFechaDeUnFormulario:
    """El CONTRATO DE TRANSACCIÓN de UPD2437820 salía «S.F.» con la fecha impresa (2026-10-20)."""

    @pytest.mark.parametrize(
        ("texto", "esperada"),
        [
            # El texto real de su última hoja.
            ("Ciudad: MAGANGUE, día:3 mes:5 del año2021.", date(2021, 5, 3)),
            ("Día __03__ Mes __05__ Año __2021__", date(2021, 5, 3)),
            ("dia 3 mes mayo año 2021", date(2021, 5, 3)),
            ("Fecha: DÍA MES AÑO\n03 05 2021", date(2021, 5, 3)),
        ],
    )
    def test_se_lee_la_fecha_del_formulario(self, texto, esperada):
        assert fecha_de_la_pagina(texto) == esperada

    @pytest.mark.parametrize(
        ("texto", "esperada"),
        [
            # El renglón manuscrito del ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO.
            ("26 , Nov de 2022\nACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO", date(2022, 11, 26)),
            ("03-dic-2021", date(2021, 12, 3)),
            ("5 Sept. 2020", date(2020, 9, 5)),
            # Lo que leyó la IA del renglón manuscrito de UPD2997962.
            ("El Banco 19/10 de 2021\n# ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO", date(2021, 10, 19)),
            ("Magangué, 19 de 10 de 2021", date(2021, 10, 19)),
            # El encabezado real de UPD2465747: sin «de» entre el día y el mes.
            ("‘^Talaigua nuevo Bolívar, 07 octubre del 2022\nSeñores,", date(2022, 10, 7)),
        ],
    )
    def test_el_mes_abreviado(self, texto, esperada):
        assert fecha_de_la_pagina(texto) == esperada

    @pytest.mark.parametrize(
        "texto",
        [
            # Las cédulas reales de UPD2973859 p5 y UPD3102728 p2.
            "09-SEP-1980\nFECHA DE NACIMIENTO\nLUGAR DE NACIMIENTO",
            "11-OCT-1995\nlugar de nacimiento",
            # Como la dejó la OCR en UPD3102762 p5.
            "fecha de NACÍMIEMTO 27-ENE-1995\nLUGAR DE NACiMíENTO\nBEOlSTRADOn NACIONAL",
            "ESTATURA 1.62 G.S. RH O+ SEXO F 18-AGO-1999 SOPLAVIENTO FECHA Y LUGAR DE EXPEDICION",
        ],
    )
    def test_la_fecha_de_una_cedula_no_fecha_el_documento(self, texto):
        assert fecha_de_la_pagina(texto) is None

    def test_una_palabra_que_empieza_como_un_mes_no_es_un_mes(self):
        # «mar» de «marca», «dic» de «dicho»: no son meses.
        assert fecha_de_la_pagina("12 marcas 2021") is None
        # Ni una palabra que no es un mes, sin «de» delante.
        assert fecha_de_la_pagina("consumo de 12 meses 2021") is None

    @pytest.mark.parametrize(
        ("texto", "esperada"),
        [
            # Lo que devolvió la IA del COMPROBANTE CUPON MANUAL de UPD2973860.
            (
                "Ortega* | FECHA  |   |   |\n|   |   |  DIA | MES | ANIO  |   |   |\n"
                "|  ID DE COBROS: **1 0 0 1 6 4 4 0 1** |   | **9 16 09 08 2022**  |   |",
                date(2022, 8, 9),
            ),
            ("FECHA DIA MES ANO 15 06 2021", date(2021, 6, 15)),
            ("dia 3 mes 5 anio 2021", date(2021, 5, 3)),
        ],
    )
    def test_las_casillas_de_un_formulario(self, texto, esperada):
        assert fecha_de_la_pagina(texto) == esperada

    def test_unas_casillas_sin_cifras_legibles_no_dan_fecha(self):
        # La capa de texto del mismo comprobante: rótulos y basura.
        assert fecha_de_la_pagina("NIC\nFECHA\nDIA\nMES *\nANIO\n¿é)2^\nID DE COBROS:") is None

    def test_una_casilla_imposible_no_es_una_fecha(self):
        assert fecha_de_la_pagina("día:31 mes:2 año:2021") is None

    def test_las_pistas_de_una_fecha_por_leer(self):
        assert pistas_de_fecha("Ciudad: MAGANGUE, día:__ mes:__ del año____") >= 3
        assert pistas_de_fecha("ACOMETIDA FRAUDULENTA") == 0


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
