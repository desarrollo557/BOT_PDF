"""Ningún documento se entrega sin un nombre que lo referencie.

Lo pidió el operador el 2026-10-20 al abrir «01_DOCUMENTO.pdf» de la caja
UPD2998266, cuya hoja dice «ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO». Los
textos son los que la OCR de casa leyó de sus cajas reales.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from resolutions.domain.titulo_impreso import nombre_por_su_origen, titulo_impreso

#: UPD2998266 p1, Tesseract sobre la página entera.
ACTA_DE_PREDIO = """76 , Nov de 2022
ACTA DE VERIFICACIÓN DE PREDIO DESOCUPADO
El sr(a) Ua S Garáa. Identificado(a) con C.C.
, residente del barrio Wubi a currec:, del municipio de
San Selb ae, afirma que el predio ubicado en la _MulsiawW Caomwea 9
identificado con el código _ 441023449 se encontraba desocupado al momento de
Testigo 1 - Testigo 2
VoBo Representante Asociado Comercial VoBo Agente Comercial."""

#: UPD2998726 p1, la franja de arriba a 400 ppp: un formulario apaisado.
FORMATO_DE_SUMINISTROS = """REVISIÓN 1
FECHA: 17/01/2012
FORMATO DE NUEVOS,SUMINISTROS O SUMINISTROS MODIFICADOS A
A AAA y 0 Í CO0Ó0Ó A as 7
: afinia"""


class TestElTituloImpreso:
    def test_el_acta_se_llama_como_su_encabezado(self):
        assert titulo_impreso(ACTA_DE_PREDIO) == "ACTA DE VERIFICACION DE PREDIO DESOCUPADO"

    def test_el_formulario_sin_su_rotulo_ni_la_letra_suelta(self):
        assert titulo_impreso(FORMATO_DE_SUMINISTROS) == (
            "FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS"
        )

    def test_la_lectura_rota_no_es_un_titulo(self):
        # La misma hoja, leída entera: la OCR partió el título en pedazos.
        assert titulo_impreso("REVISIÓN 1\nFECHA: 17/01/2012\nFORMATO DE DAS DA Pe MA E MODIFICADOS") is None

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            # Una carta: el saludo y la prosa no son un título.
            "Valledupar, 02 de diciembre de 2020\nSeñores\nAFINIA\nCordial saludo, por medio de la presente",
            # El membrete y el número de cuenta tampoco.
            "afinia\nGrupo-epm\nCUENTA INTERNA 1012171",
            # Un nombre en mayúsculas en mitad de la hoja.
            "la vivienda\nque tiempo estuvo\nen mención\nnombre del testigo\nJOSE CHARRIS BORRERO",
        ],
    )
    def test_lo_que_no_es_titulo(self, texto):
        assert titulo_impreso(texto) is None

    def test_con_la_clase_de_papel_gana_aunque_vaya_mas_abajo(self):
        texto = "SAN SEBASTIAN BOLIVAR\nfecha de la visita\nCONSTANCIA DE VISITA REALIZADA EN EL INMUEBLE"
        assert titulo_impreso(texto) == "CONSTANCIA DE VISITA REALIZADA EN EL INMUEBLE"


class TestElNombrePorSuOrigen:
    def test_la_caja_y_sus_paginas(self):
        assert nombre_por_su_origen("210847/UPD2998726.pdf", [1, 2, 3]) == "UPD2998726 PAGINAS 1-3"
        assert nombre_por_su_origen(r"910349\UPD2998266.pdf", [4]) == "UPD2998266 PAGINA 4"

    def test_nunca_vacio(self):
        assert nombre_por_su_origen("", []) == "SIN TITULO"


class TestLaFranjaDelEncabezado:
    """La hoja cuya lectura entera se descartó se nombra por su franja de arriba."""

    def _pagina(self) -> bytes:
        salida = BytesIO()
        Image.new("L", (100, 200), 255).save(salida, format="PNG")
        return salida.getvalue()

    def test_lee_solo_la_franja_de_arriba(self):
        from resolutions.api.worker.correspondencia import (
            ALTO_DEL_ENCABEZADO,
            _titulo_del_encabezado,
        )

        vistas = []

        class Fuente:
            def render(self, pagina, banda, ppp):
                return TestLaFranjaDelEncabezado._pagina(None)

        class Lector:
            def read(self, png):
                vistas.append(Image.open(BytesIO(png)).size)
                return type("R", (), {"text": FORMATO_DE_SUMINISTROS})()

        titulo = _titulo_del_encabezado(Fuente(), 1, Lector())
        assert titulo == "FORMATO DE NUEVOS SUMINISTROS O SUMINISTROS MODIFICADOS"
        assert vistas == [(100, int(200 * ALTO_DEL_ENCABEZADO))]

    def test_si_falla_no_tumba_la_caja(self):
        from resolutions.api.worker.correspondencia import _titulo_del_encabezado

        class Rota:
            def render(self, *_):
                raise OSError("la hoja no se deja dibujar")

        assert _titulo_del_encabezado(Rota(), 1, None) is None
