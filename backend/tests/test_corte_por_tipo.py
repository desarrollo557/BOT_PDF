"""Lo que decide dónde se corta cuando el papel dice qué es.

Sale de un expediente real, UPD2365925, de 97 páginas. El software lo partió en
31 documentos y su primer archivo juntaba las páginas 1 a 10, que son tres
cosas: un derecho de petición de ocho hojas, el acta que lo notifica y la
cédula de la persona. El operador lo revisó hoja por hoja y de ahí salen estas
reglas.
"""

from __future__ import annotations

from resolutions.domain.fingerprint import fingerprint_page
from resolutions.domain.segmentation import Verdict, decide_boundaries
from resolutions.domain.tipo_documental import identificar_asunto, identificar_documento


def veredicto(izquierda, derecha):
    return decide_boundaries([izquierda, derecha])[0]


class TestElNumeroDeCedulaNoEsUnImporte:
    """La cédula de la persona del expediente sale en casi todas sus hojas.

    Tiene separadores de miles, así que el patrón de importe la reconocía como
    una cantidad de dinero, y la regla de "las dos hojas llevan el mismo
    importe" soldaba el escrito que la persona firmó, el acta que la notifica y
    la copia de su cédula: tres documentos en uno.
    """

    def test_una_cedula_no_se_lee_como_dinero(self):
        huella = fingerprint_page(1, "INIRIDA ZARATE C.C. No 42.491.816 de Valledupar")
        assert not [valor for clase, valor in huella.identifiers if clase == "importe"]

    def test_una_cantidad_anunciada_como_dinero_si(self):
        huella = fingerprint_page(1, "por un valor de $526.980.00 facturado el 10/12/2021")
        assert ("importe", "526.980") in huella.identifiers

    def test_un_numero_de_ley_tampoco_es_dinero(self):
        """La ley 142,143 y la ley 142 de 1,994 salían como importes."""
        huella = fingerprint_page(1, "conocemos las leyes 142,143 y la ley 142 de 1,994")
        assert not [valor for clase, valor in huella.identifiers if clase == "importe"]

    def test_la_cedula_se_lee_aparte_y_normalizada(self):
        """Sin puntos: la misma cédula se imprime de las dos formas y hay que
        poder compararlas."""
        assert fingerprint_page(1, "CC: 42.491.816 DE: VALLEDUPAR").cedula == "42491816"
        assert fingerprint_page(1, "cedula 42491816").cedula == "42491816"


class TestElRotuloTieneQueSerUnTitulo:
    """Una frase del catálogo mencionada en la prosa no abre un documento.

    La primera hoja de un recurso dice en su cuarto punto "4. Constancia de
    Visita asociada al Acta de Revisión con Orden de Servicio...", y eso partía
    el recurso en dos por una frase de su propio cuerpo.
    """

    def test_un_titulo_en_su_renglon_abre_documento(self):
        cuerpo = "\n".join(
            [
                "ARINIA",
                "GRUPO EPF",
                "NOTIFICACION PERSONAL",
                "En la fecha 18/02/2022 comparecio a las oficinas",
            ]
        )
        assert fingerprint_page(9, cuerpo).label == "notificacion personal"

    def test_la_misma_frase_dentro_de_la_prosa_no(self):
        cuerpo = (
            "ARINIA\nGRUPO EPFT\n"
            "4 Constancia de Visita asociada al Acta de Revision con Orden de "
            "Servicio Dentro del expediente se encuentra como prueba documental"
        )
        assert fingerprint_page(70, cuerpo).label is None

    def test_el_logo_pegado_delante_no_esconde_el_titulo(self):
        """El escáner pega el logo al título más veces de las que lo separa."""
        huella = fingerprint_page(
            33, "armia Liquidación del Consumo No registrado Pendiente Por Facturar"
        )
        assert huella.label == "liquidacion del consumo"


class TestDosHojasQueSeTitulanIgualSonElMismoDocumento:
    """Lo pidió el operador: no quiere ver dos archivos seguidos del mismo tipo.

    Un acta de cuatro hojas repite su rótulo en las cuatro, y cortar por él la
    convertía en cuatro actas de una hoja. Dos documentos distintos del mismo
    tipo se separan por el consecutivo, que se mira mucho antes que el rótulo.
    """

    @staticmethod
    def _con_rotulo(numero, rotulo):
        return fingerprint_page(numero, rotulo + "\ncuerpo del documento")

    def test_un_rotulo_nuevo_abre(self):
        izquierda = self._con_rotulo(1, "DERECHO DE PETICION")
        derecha = self._con_rotulo(2, "NOTIFICACION PERSONAL")
        assert veredicto(izquierda, derecha).verdict is Verdict.STARTS

    def test_el_mismo_rotulo_repetido_no_abre(self):
        izquierda = self._con_rotulo(1, "ACTA DE IRREGULARIDAD")
        derecha = self._con_rotulo(2, "ACTA DE IRREGULARIDAD")
        assert veredicto(izquierda, derecha).verdict is not Verdict.STARTS

    def test_pero_un_consecutivo_distinto_sigue_separando(self):
        """Dos avisos seguidos son dos documentos, y lo dice el consecutivo:
        esa regla se aplica mucho antes que la del rótulo."""
        izquierda = fingerprint_page(
            17, "PUBLICACION DEL AVISO\nConsecutivo No. PA 202270053788"
        )
        derecha = fingerprint_page(
            18, "PUBLICACION DEL AVISO\nConsecutivo No. A202270041023"
        )
        assert veredicto(izquierda, derecha).verdict is Verdict.STARTS


class TestLaCedulaSueltaSeComprueba:
    """Y no se supone. Lo pidió el operador: validar el número y el nombre.

    Una cédula detrás de un escrito es su soporte cuando es la cédula de quien
    lo firmó. Si es la de otra persona pertenece a otra cosa, y unirla
    escondería un documento dentro de otro.
    """

    ESCRITO = (
        "NOTIFICACION PERSONAL\n"
        "El notificado INIRIDA BEATRIZ ZARATE GARIZABAL CC: 42.491.816"
    )
    CEDULA = (
        "REPUBLICA DE COLOMBIA\n"
        "CEDULA DE CIUDADANIA NUMERO {} ZARATE GARIZABAL INIRIDA BEATRIZ"
    )

    def test_la_cedula_de_quien_firmo_es_su_anexo(self):
        izquierda = fingerprint_page(9, self.ESCRITO)
        derecha = fingerprint_page(10, self.CEDULA.format("42.491.816"))
        borde = veredicto(izquierda, derecha)
        assert borde.verdict is Verdict.ATTACHMENT
        assert "42491816" in borde.reason

    def test_la_cedula_de_otra_persona_no(self):
        izquierda = fingerprint_page(9, self.ESCRITO)
        derecha = fingerprint_page(10, self.CEDULA.format("13.579.246"))
        borde = veredicto(izquierda, derecha)
        assert borde.verdict is Verdict.STARTS
        assert "no es la de la hoja anterior" in borde.reason

    def test_sin_numero_legible_se_cae_a_los_nombres(self):
        izquierda = fingerprint_page(9, self.ESCRITO)
        derecha = fingerprint_page(
            10,
            "REPUBLICA DE COLOMBIA\n"
            "CEDULA DE CIUDADANIA ZARATE GARIZABAL INIRIDA BEATRIZ",
        )
        borde = veredicto(izquierda, derecha)
        assert borde.verdict is Verdict.ATTACHMENT
        assert "como la hoja anterior" in borde.reason

    def test_y_sin_nada_que_comparar_se_une_igual(self):
        """La copia de una cédula no es una unidad documental que nadie vaya a
        buscar por sí misma: el error de unirla deja un anexo donde debía."""
        izquierda = fingerprint_page(9, "ACTA DE IRREGULARIDAD\ncuerpo del acta")
        derecha = fingerprint_page(10, "REPUBLICA DE COLOMBIA\nCEDULA DE CIUDADANIA")
        assert veredicto(izquierda, derecha).verdict is Verdict.ATTACHMENT


class TestLaCortesiaNoEsUnaCabecera:
    """Una fórmula de cortesía a media página no abre un documento.

    Partía por la mitad un derecho de petición de ocho hojas: su sexta hoja
    empieza con "Respetados señores:" y la marca de destinatario se buscaba en
    el texto corrido. La cabecera de verdad, en la primera hoja, dice
    "Señores:" y nada más en su renglón.
    """

    def test_la_cabecera_en_su_renglon_si_abre(self):
        huella = fingerprint_page(1, "Señores:\nAFINIA GRUPO EPM\nS. D. E.")
        assert "destinatario" in huella.opening

    def test_la_formula_de_cortesia_en_mitad_del_cuerpo_no(self):
        huella = fingerprint_page(
            6,
            "Respetados señores: Representante Legal o quien haga sus veces de la "
            "empresa AFINIA Grupo EPM, y al Superintendente de Servicios Publicos",
        )
        assert "destinatario" not in huella.opening

class TestElAsuntoDiceDeQueEsElPapel:
    """La tercera fuente del tipo, y la pidió el operador.

    Un rótulo hay que reconocerlo por su sitio en la página y una mención
    puede ser cualquier cosa; el asunto es el documento diciendo de qué trata,
    en el renglón donde el papel oficial lo declara. Va detrás del título y
    delante de la mención.
    """

    def test_el_asunto_declara_el_tipo(self):
        assert identificar_asunto("Asunto: Notificación por aviso").nombre == (
            "NOTIFICACION POR AVISO"
        )

    def test_la_referencia_tambien(self):
        """Un derecho de petición se encabeza con REF y no lleva otro título."""
        hallazgo = identificar_asunto(
            "REF: Derecho de Petición según el Artículo 23 de nuestra Carta Magna"
        )
        assert hallazgo.nombre == "DERECHO DE PETICION"

    def test_y_reconoce_la_frase_larga_dentro_del_asunto(self):
        hallazgo = identificar_asunto(
            "Asunto: Reconocimiento de deuda y propuesta de acuerdo de pago."
        )
        assert hallazgo.nombre == "RECONOCIMIENTO DE DEUDA Y PROPUESTA DE ACUERDO DE PAGO"

    def test_un_radicado_citado_en_el_asunto_no_es_un_tipo(self):
        """El caso que obligó a medirlo.

        La respuesta a una reclamación se encabeza "Asunto: Reclamación No.
        RE3120202200134". Ese número es el del expediente, no el del papel, y
        leer "Reclamación" como tipo bautizaba RECLAMO a los tres oficios que
        la contestan. Es el mismo modo de fallo que el código de caso.
        """
        assert identificar_asunto("ASUNTO: Reclamación No. RE3120202200134") is None

    def test_una_direccion_en_el_asunto_no_es_un_tipo(self):
        assert identificar_asunto("Asunto: Dir.: CARRERA 22 No 18 - 1") is None

    def test_el_asunto_manda_sobre_el_encabezado(self):
        """El orden lo fijó el operador, y es el de lo más directo primero.

        El asunto es el documento diciendo de qué trata; el encabezado hay
        que interpretarlo por su sitio en la página. Cuando los dos hablan,
        gana el asunto.
        """
        pagina = "\n".join(
            ["NOTIFICACION PERSONAL", "Asunto: Notificación por aviso", "cuerpo"]
        )
        assert identificar_documento([pagina]).nombre == "NOTIFICACION POR AVISO"

    def test_un_asunto_de_formulario_no_le_gana_al_encabezado(self):
        """Y aquí está el límite de la regla anterior, medido en el papel.

        Un acta de notificación personal lleva dentro un formulario con el
        renglón "Tipo de PQR o Asunto: RECLAMO". Ese asunto es el de la PQR
        que se está notificando, no el del acta, y leído como propio hacía
        que dos actas del expediente pasaran a llamarse RECLAMO. El asunto
        de un documento abre su renglón; éste no.
        """
        pagina = "\n".join(
            [
                "NOTIFICACION PERSONAL",
                "En la fecha 18/02/2022 comparecio a las oficinas",
                "Tipo de PQR o Asunto:RECLAMO",
            ]
        )
        assert identificar_documento([pagina]).nombre == "NOTIFICACION PERSONAL"

    def test_y_el_encabezado_manda_sobre_una_mencion_del_cuerpo(self):
        """La mención es la última fuente: puede ser cualquier cosa."""
        pagina = "\n".join(
            [
                "ACTA DE IRREGULARIDAD",
                "En el expediente obra la constancia de visita realizada en el "
                "inmueble que acompana a la presente",
            ]
        )
        assert identificar_documento([pagina]).nombre == "ACTA DE IRREGULARIDAD"
