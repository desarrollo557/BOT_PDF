"""Qué tipo documental se le pone a un papel, y cuándo no se le pone ninguno.

Las frases de estas pruebas están tomadas de la caja real de correspondencia de
servicios públicos, incluidas las erratas: son las que el escáner devuelve.
"""

from __future__ import annotations

import pytest

from resolutions.domain.catalogo import CATALOGO, POR_NOMBRE
from resolutions.domain.naming import DOCUMENT_PREFIX, kind_fragment, output_filename
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.tipo_documental import identificar, identificar_documento


def _codigo(valor: str) -> ResolutionCode:
    return ResolutionCode(value=valor, raw=valor)


class TestElCatalogo:
    def test_todos_los_nombres_son_distintos(self):
        """Dos entradas con el mismo nombre serían dos carpetas para lo mismo."""
        nombres = [tipo.nombre for tipo in CATALOGO]
        assert len(nombres) == len(set(nombres))

    def test_ninguna_frase_se_reparte_entre_dos_tipos(self):
        """Una frase que delata a dos tipos no delata a ninguno.

        El desempate del clasificador es el largo de la frase; si la misma frase
        estuviera en dos tipos, cuál gana dependería del orden en que se
        escribieron en el catálogo, que no es una razón.
        """
        vistas: dict[str, str] = {}
        repetidas = []
        for tipo in CATALOGO:
            for frase in tipo.frases:
                if frase in vistas and vistas[frase] != tipo.nombre:
                    repetidas.append((frase, vistas[frase], tipo.nombre))
                vistas[frase] = tipo.nombre
        assert repetidas == []

    def test_las_variantes_del_listado_no_se_perdieron(self):
        """El listado del cliente trae el mismo tipo escrito de varias maneras.

        Se eligió una como nombre y las demás se quedaron como frases. Si
        alguien las borra por parecer duplicados, el papel que use esa forma deja
        de reconocerse y nadie se entera hasta que aparecen los archivos sin
        tipo.
        """
        assert "PAGOS NO APLICADOS" in POR_NOMBRE["PAGO NO APLICADO"].frases
        assert "RECURSOS DE QUEJAS" in POR_NOMBRE["RECURSO DE QUEJA"].frases
        assert "TRASLADO DE COMPETENCIA" in POR_NOMBRE["TRASLADO POR COMPETENCIA"].frases
        assert (
            "PROYECCION O AUTORIZACION PARA REFATURACCION DE COMSUMOS"
            in POR_NOMBRE["PROYECCION Y AUTORIZACION PARA REFACTURACCION DE COMSUMOS"].frases
        )


class TestLoQueDiceElPapel:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("NOTIFICACION POR AVISO\nSeñor usuario", "NOTIFICACION POR AVISO"),
            ("CITACIÓN PARA NOTIFICACIÓN PERSONAL", "CITACION PARA NOTIFICACION PERSONAL"),
            (
                "ACTA DE SUSPENSIÓN, CORTE Y RECONEXIÓN\nDirección del inmueble",
                "ACTA DE SUSPENSION CORTE Y RECONEXION",
            ),
            ("CERTIFICADO DE TRADICION Y LIBERTAD", "CERTIFICADO DE TRADICION"),
            ("Constancia del contenido de la reclamación", "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION"),
        ],
    )
    def test_reconoce_el_rotulo_impreso(self, texto, esperado):
        encontrado = identificar(texto)
        assert encontrado is not None
        assert encontrado.nombre == esperado

    def test_perdona_las_erratas_del_escaner(self):
        """"NOTIFICACIQN P0R AVIS0" es lo que devuelve el OCR de estas cajas."""
        encontrado = identificar("NOTIFICACIQN P0R AVIS0")
        assert encontrado is not None
        assert encontrado.nombre == "NOTIFICACION POR AVISO"
        assert encontrado.distancia > 0

    def test_gana_la_frase_mas_larga(self):
        """La que distingue un recurso del otro, no la que comparten.

        Un recurso de reposición en subsidio de apelación dice las dos cosas. Si
        ganara la corta, el archivo se llamaría como el recurso simple y el
        subsidio de apelación desaparecería del nombre.
        """
        encontrado = identificar("RECURSO DE REPOSICION Y SUBSIDIARIAMENTE EL DE APELACION")
        assert encontrado is not None
        assert encontrado.nombre == "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION"


class TestLoQueNoSeLlamaComoSuena:
    def test_una_palabra_corriente_en_el_cuerpo_no_nombra_el_documento(self):
        """La mitad de esta correspondencia menciona una factura sin serlo.

        Ésta es la regla que separa un título del cuerpo: "factura" dentro de una
        frase es prosa. Sin ella, media caja de notificaciones sale llamándose
        factura y nadie lo nota hasta buscar una factura de verdad.
        """
        texto = (
            "Señor usuario:\n"
            "Le informamos que la factura del mes de mayo presenta un saldo "
            "pendiente y que su reclamo fue radicado.\n"
        )
        assert identificar(texto) is None

    def test_la_misma_palabra_sola_en_su_renglon_si_lo_nombra(self):
        """Porque así es como se imprime un título."""
        encontrado = identificar("EMPRESA DE SERVICIOS PUBLICOS\nFACTURA\nPeriodo facturado")
        assert encontrado is not None
        assert encontrado.nombre == "FACTURA"

    def test_un_papel_que_no_dice_que_es_se_queda_sin_tipo(self):
        """Sin tipo, no con el más parecido. Es la política de la casa.

        Un nombre inventado convierte una duda en un dato: el archivo pasa a
        decir que es una cosa que nadie comprobó, y el que lo recibe no tiene
        forma de saber que ahí hubo una duda.
        """
        assert identificar("Cordial saludo,\n\nAtentamente,\n\nJuan Pérez") is None

    def test_tmp_nunca_se_reconoce_solo(self):
        """Está en el catálogo porque el listado lo trae, pero no es un rótulo.

        Con tres letras, cualquier tolerancia lo encontraría dentro de una
        palabra corriente.
        """
        assert POR_NOMBRE["TMP"].frases == ()
        assert identificar("TMP") is None


class TestElDocumentoEntero:
    def test_mira_las_primeras_paginas_hasta_encontrar_el_rotulo(self):
        paginas = ["", "PAGARE\nNo 4500123456", "por valor de un millón de pesos"]
        encontrado = identificar_documento(paginas)
        assert encontrado is not None
        assert encontrado.nombre == "PAGARE"
        assert encontrado.pagina == 2

    def test_el_anexo_de_atras_no_le_cambia_el_nombre_al_documento(self):
        """Un acta que adjunta una factura sigue siendo un acta.

        Por eso las páginas se miran de una en una y se para en la primera que
        contesta, en vez de buscar en todas a la vez: lo que va detrás es lo que
        el documento adjunta, no lo que el documento es.
        """
        paginas = [
            "ACTA DE INSPECCION ELECTRICA\nSe practicó visita al inmueble",
            "continúa el acta",
            "FACTURA\nPeriodo facturado",
        ]
        encontrado = identificar_documento(paginas)
        assert encontrado is not None
        assert encontrado.nombre == "ACTA DE INSPECCION ELECTRICA"


class TestComoSeLlamaElArchivo:
    """Tres formas, una por clase de unidad, y cada ruta elige la suya.

    Se piden explícitamente y no se deducen de la combinación de parámetros:
    deducirlas fue el error que puso "00086_ACTA-DE-IRREGULARIDAD.pdf" donde el
    operador había pedido "RESOLUCION_00086.pdf".
    """

    def test_una_resolucion_lleva_su_palabra_y_su_numero(self):
        """Y el tipo documental no entra: el asunto vive en el inventario."""
        assert (
            output_filename(_codigo("00086"), "por la cual", kind="ACTA DE IRREGULARIDAD")
            == "RESOLUCION_00086.pdf"
        )

    def test_el_numero_delante_y_el_tipo_detras(self):
        assert (
            output_filename(
                _codigo("01"), None, prefix=None, kind="NOTIFICACION POR AVISO"
            )
            == "01_NOTIFICACION-POR-AVISO.pdf"
        )

    def test_un_folio_dice_ademas_de_quien_es(self):
        """Lo pidió el operador viendo "1128047041_DOCUMENTO-DE-IDENTIDAD.pdf":
        el número y el tipo estaban, y el nombre de la persona se había
        perdido."""
        assert output_filename(
            _codigo("1128047041"),
            "JUAN PEREZ GOMEZ",
            prefix=None,
            kind="DOCUMENTO DE IDENTIDAD",
            con_titulo=True,
        ) == "1128047041_juan-perez-gomez_DOCUMENTO-DE-IDENTIDAD.pdf"

    def test_la_procedencia_no_entra_en_el_nombre_de_una_caja(self):
        """En una caja el título es de qué páginas salió, y eso ya está en el
        inventario: en el nombre sólo estorba."""
        assert (
            output_filename(_codigo("01"), "páginas 1-8", prefix=None, kind="FACTURA")
            == "01_FACTURA.pdf"
        )

    def test_el_que_nadie_reconocio_sale_generico(self):
        assert (
            output_filename(_codigo("04"), None, prefix=None, kind=DOCUMENT_PREFIX)
            == "04_DOCUMENTO.pdf"
        )

    def test_lo_que_windows_no_admite_no_llega_al_nombre(self):
        """El catálogo tiene un tipo con una barra, y una barra abre carpetas."""
        assert kind_fragment("CAMBIO Y/O ACTUALIZACION DE DATOS BASICOS") == (
            "CAMBIO-Y-O-ACTUALIZACION-DE-DATOS-BASICOS"
        )

    def test_si_no_cabe_se_recorta_el_tipo_y_nunca_el_numero(self):
        """Un archivo nombrado sólo con su número se encuentra igual.

        Uno que no se llegó a escribir porque la ruta pasaba de 260 caracteres,
        no: se pierde entero y el fallo aparece al final del trabajo.
        """
        largo = "MATERIALES INCLUIDOS EN CADA ITEM DE INSTALACION Y CENSO DE CARGA"
        nombre = output_filename(_codigo("07"), None, prefix=None, budget=30, kind=largo)
        assert nombre.startswith("07_MATERIALES")
        assert len(nombre) <= 30
        assert (
            output_filename(_codigo("07"), None, prefix=None, budget=12, kind=largo)
            == "07.pdf"
        )

    def test_se_aprieta_el_nombre_de_la_persona_antes_que_el_tipo(self):
        """El archivo se busca por el tipo; el nombre es lo largo."""
        nombre = output_filename(
            _codigo("1128047041"),
            "JUAN SEBASTIAN PEREZ GOMEZ DE LA TORRE",
            prefix=None,
            kind="DOCUMENTO DE IDENTIDAD",
            con_titulo=True,
            budget=45,
        )
        assert len(nombre) <= 45
        assert "DOCUMENTO-DE-IDENTIDAD" in nombre
        assert nombre.startswith("1128047041")
