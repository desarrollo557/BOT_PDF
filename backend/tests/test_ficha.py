"""Lo que un archivo entero declara de sí mismo para su única fila del FUID.

Los textos de estas pruebas están copiados de un PDF real -- la estructura
documental de Kingspan, doce tipos de documento emitidos por el mismo sistema --
y no inventados. Lo que se comprueba aquí es lo que el operador pidió: que de un
PDF salga su tipo, sus fechas extremas y sus folios, sin partirlo.
"""

from __future__ import annotations

from datetime import date

from resolutions.domain.fechas import fechas_de
from resolutions.domain.ficha import (
    Ficha,
    asunto_impreso,
    consecutivos,
    es_legible,
    fichar,
)

NOTA_DE_AJUSTE = """NOTA DE AJUSTE
KINGSPAN PANELES AISLADOS S.A.S          Numero:  001-NA-00001204
NIT 900447906-1                          Fecha:   30/08/2022
PRINCIPAL
Tercero: 890903938 BANCOLOMBIA S.A.
Notas: COMPTAS TC-8816 AGOSTO 2022
"""

RECLASIFICACIONES = """NOTAS Y RECLASIFICACIONES CARTERA
KINGSPAN PANELES AISLADOS S.A.S          Numero:  001-NR-00000917
NIT 900447906-1                          Fecha:   30/12/2022
Tercero: 800096464 PUERTO DE MAMONAL S.A.
RECLASIFICACION NCE COMO SALDO A FAVOR
"""


class TestUnaSolaFila:
    """Inventariar es anotar el archivo, no repartirlo en filas."""

    def test_el_asunto_sale_del_titulo_impreso(self):
        ficha = fichar([NOTA_DE_AJUSTE])
        assert ficha.asunto == "NOTA DE AJUSTE"

    def test_las_fechas_extremas_de_una_sola_hoja_son_la_misma(self):
        # Un documento de un día abre y cierra el mismo día. Dejar "hasta"
        # vacío haría pensar en un expediente todavía abierto.
        ficha = fichar([NOTA_DE_AJUSTE])
        assert ficha.fecha_inicial == date(2022, 8, 30)
        assert ficha.fecha_final == date(2022, 8, 30)

    def test_las_fechas_extremas_van_de_punta_a_punta_del_archivo(self):
        ficha = fichar([NOTA_DE_AJUSTE, RECLASIFICACIONES])
        assert ficha.fecha_inicial == date(2022, 8, 30)
        assert ficha.fecha_final == date(2022, 12, 30)

    def test_los_folios_son_las_paginas_del_pdf_y_no_las_que_traen_texto(self):
        # Una hoja que salió en blanco del escáner sigue siendo un folio.
        ficha = fichar([NOTA_DE_AJUSTE, "", ""], folios=3)
        assert ficha.folios == 3


class TestConsecutivos:
    """Las columnas "No. Documento: Desde / Hasta" del formato."""

    def test_el_numero_impreso_abre_y_cierra_cuando_hay_uno_solo(self):
        assert consecutivos([NOTA_DE_AJUSTE]) == (
            "001-NA-00001204",
            "001-NA-00001204",
        )

    def test_se_conserva_el_orden_de_aparicion_y_no_el_alfabetico(self):
        # "NR" va después de "NA" en el alfabeto y también en el papel, pero lo
        # que manda es el papel: el "desde" es el que encabeza la primera hoja.
        desde, hasta = consecutivos([RECLASIFICACIONES, NOTA_DE_AJUSTE])
        assert desde == "001-NR-00000917"
        assert hasta == "001-NA-00001204"

    def test_un_archivo_sin_numero_impreso_no_se_lo_inventa(self):
        assert consecutivos(["una hoja suelta sin encabezado"]) == (None, None)


class TestLoQueNoSeLee:
    """Un campo que no está no se rellena con algo verosímil."""

    def test_sin_fechas_legibles_la_ficha_lo_dice(self):
        ficha = fichar(["KINGSPAN COMERCIAL SAS"], folios=1)
        assert ficha.fecha_inicial is None
        assert ficha.fecha_final is None
        assert not ficha.esta_fechada

    def test_sin_titulo_impreso_el_asunto_queda_vacio(self):
        assert asunto_impreso(["   ", ""]) is None

    def test_una_ficha_vacia_conserva_los_folios(self):
        # Los folios son lo único que no depende de saber leer el papel.
        ficha = Ficha(folios=12)
        assert ficha.folios == 12
        assert ficha.asunto is None


class TestElRuidoDelOcrNoEsUnAsunto:
    """Un encabezado ilegible se declara, no se rellena con lo que salga.

    Los dos primeros textos están copiados literalmente de lo que Tesseract
    devolvió sobre este PDF. Pasaban todos los filtros de forma del extractor de
    títulos -- tres palabras, sin pinta de fecha -- y acababan en la columna de
    asuntos del inventario como si alguien los hubiera escrito.
    """

    def test_la_basura_del_ocr_no_pasa_por_titulo(self):
        assert not es_legible("r a $ Fechas extremas")

    def test_una_linea_de_simbolos_tampoco(self):
        assert not es_legible("E — ——]]]6)¡—]—]]]]——————————É.——]_—];—;__")

    def test_un_titulo_con_numeros_si_es_un_titulo(self):
        # El filtro descarta ruido, no cifras: un acta se numera y se fecha en
        # su propio encabezado.
        assert es_legible("ACTA 004 DE 2022")

    def test_los_titulos_reales_del_corpus_pasan(self):
        for titulo in (
            "NOTA DE AJUSTE",
            "NOTAS Y RECLASIFICACIONES CARTERA",
            "COMPROBANTE DE EGRESO",
        ):
            assert es_legible(titulo), titulo

    def test_un_numero_de_documento_no_es_un_asunto(self):
        assert not es_legible("001-NA-00001204")

    def test_una_hoja_ilegible_deja_paso_a_la_siguiente(self):
        # La primera página de este PDF es una carta escaneada de mala calidad y
        # su encabezado no se lee; la segunda sí.
        assert asunto_impreso(["r a $ Fechas extremas", NOTA_DE_AJUSTE]) == "NOTA DE AJUSTE"


class TestUnaFechaFuturaEsUnaErrata:
    """La fecha extrema final no puede estar por venir.

    Sobre este PDF el OCR leyó "19/02/2024" como "19/02/2074" -- el 2 y el 7 se
    confunden en un escaneo malo -- y como la fecha final es la más reciente que
    aparezca, esa errata se convertía en la fecha de cierre del expediente.
    """

    def test_una_fecha_posterior_a_hoy_se_descarta(self):
        linea = "264 152,225 y.meza 19/02/2074 Clientes 31017072407-001"
        assert fechas_de(linea, hoy=date(2026, 9, 15)) == []

    def test_la_misma_fecha_bien_leida_se_conserva(self):
        linea = "264 152,225 y.meza 19/02/2024 Clientes 31017072407-001"
        assert fechas_de(linea, hoy=date(2026, 9, 15)) == [date(2024, 2, 19)]

    def test_la_errata_no_se_lleva_la_fecha_final_del_archivo(self):
        paginas = [NOTA_DE_AJUSTE, "movimiento del 19/02/2074 por el usuario"]
        ficha = fichar(paginas)
        assert ficha.fecha_final == date(2022, 8, 30)
