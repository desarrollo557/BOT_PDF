"""El folio escrito a mano decide dónde empieza cada registro.

Un libro de registro se folia a mano en la esquina superior derecha de la cara
de delante, con una "v" al lado; la de atrás llega limpia porque nunca lo tuvo.
Lo que se fija aquí es que esa marca -- su presencia, no su número -- sea lo que
parte el libro, que la carpeta y el FUID cuenten lo mismo, y que donde nadie
pudo mirar la esquina el reparto siga siendo el de antes.

La regla la dictó el operador sobre el libro `UPD3859766`: la página 1 lleva
escrito "1/v", la 2 no lleva nada, la 3 lleva "2/v" y la 4 no lleva nada, de
modo que la 2 pertenece a la 1 y la 4 pertenece a la 3.
"""

import pymupdf
import pytest

from resolutions.adapters.pymupdf_source import PyMuPDFPageSource
from resolutions.application.diploma_fuid import filas_del_libro
from resolutions.application.diploma_split import group_by_record
from resolutions.application.ports import Band
from resolutions.domain.diploma import DiplomaRecord
from resolutions.domain.folio_manuscrito import (
    BANDA_DEL_FOLIO,
    TINTA_DE_FOLIO,
    MarcaDeFolio,
    TrazoEnEsquina,
    folio_de_la_esquina,
    folios_comprobados,
    libro_alterna,
    marca_de_folio,
    marcas_en_ritmo,
)


def registro(pagina, marca=None, folio=None, nombre=None, cedula=None):
    return DiplomaRecord(
        page_number=pagina,
        folio=folio,
        registered_folio=folio,
        name=nombre,
        identity_number=cedula,
        folio_mark=marca,
    )


class TestLaRegla:
    def test_la_tinta_de_un_folio_es_una_marca(self):
        """Las caras de delante del libro medido dan una mediana de 0.099."""
        assert marca_de_folio(TrazoEnEsquina(0.099, 0.0)) is MarcaDeFolio.PRESENTE

    def test_el_folio_de_un_solo_digito_cuenta_igual_que_el_de_tres(self):
        """El "1/v" de la página 1, que es el caso que dictó el operador.

        Da 0.032 contra los 0.148 de un folio largo, y aun así es la marca más
        floja de las 199 caras de delante: por debajo de ella no hay ninguna.
        Una medida en fracción de ancho lo perdía por corto.
        """
        assert marca_de_folio(TrazoEnEsquina(0.032, 0.0)) is MarcaDeFolio.PRESENTE

    def test_la_esquina_limpia_es_una_vuelta(self):
        """Las vueltas dan 0.001 de mediana, que es la otra población entera."""
        assert marca_de_folio(TrazoEnEsquina(0.001, 0.0)) is MarcaDeFolio.AUSENTE

    def test_media_banda_comida_por_el_canto_todavia_se_mide(self):
        """El máximo observado en el libro es 0.489 y el folio se ve igual."""
        assert marca_de_folio(TrazoEnEsquina(0.099, 0.489)) is MarcaDeFolio.PRESENTE

    def test_sin_banda_que_medir_no_se_afirma_nada(self):
        assert marca_de_folio(TrazoEnEsquina(0.099, 0.85)) is MarcaDeFolio.SIN_MEDIR

    def test_entre_las_dos_poblaciones_no_se_afirma_nada(self):
        """Ahí cae una sola página de las 398, y por eso la zona existe."""
        assert marca_de_folio(TrazoEnEsquina(0.018, 0.0)) is MarcaDeFolio.DUDOSA

    def test_no_haber_mirado_no_es_haber_visto_la_esquina_limpia(self):
        """Sin medida la respuesta es SIN_MEDIR, nunca AUSENTE ni DUDOSA.

        Tratarla como AUSENTE uniría el libro entero en un solo documento:
        ninguna página tendría marca y todas se pegarían a la primera. Y como
        DUDOSA, otro tanto, porque la duda también une.
        """
        assert marca_de_folio(None) is MarcaDeFolio.SIN_MEDIR


class TestElRepartoDelLibro:
    def test_la_vuelta_se_queda_con_su_recto(self):
        """El caso que dictó el operador: 1/v, nada, 2/v, nada."""
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1"),
            registro(2, MarcaDeFolio.AUSENTE),
            registro(3, MarcaDeFolio.PRESENTE, folio="2"),
            registro(4, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3, 4]]

    def test_la_marca_manda_sobre_lo_que_el_ocr_creyo_leer(self):
        """Una vuelta con ruido de OCR encima sigue siendo una vuelta.

        Es el caso real de estos libros: la plantilla impresa está en las dos
        caras, así que el OCR saca algo de la vuelta y esa basura bastaba para
        que se leyera como un registro nuevo.
        """
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1", nombre="ALIX MARIN"),
            registro(2, MarcaDeFolio.AUSENTE, nombre="LA REPUBLICA DE COLOMBIA"),
        ]
        grupos = group_by_record(registros).groups
        assert len(grupos) == 1
        assert grupos[0].page_numbers == [1, 2]

    def test_ninguna_pagina_se_pierde_ni_se_repite(self):
        registros = [
            registro(n, MarcaDeFolio.PRESENTE if n % 2 else MarcaDeFolio.AUSENTE)
            for n in range(1, 9)
        ]
        group_by_record(registros).verify_integrity(total_pages=8)

    def test_la_primera_pagina_abre_aunque_no_se_le_vea_la_marca(self):
        """No hay registro anterior al que pegarla, así que abre ella."""
        grupos = group_by_record([registro(1, MarcaDeFolio.AUSENTE)]).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1]]

    def test_dos_capturas_de_la_misma_cara_no_son_dos_registros(self):
        """Las dos llevan el folio escrito, así que la marca no las distingue.

        Lo que las delata es repetir folio y cédula a la vez, y esa regla tiene
        que sobrevivir a la marca en vez de quedar tapada por ella.
        """
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
            registro(2, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
        ]
        grupos = group_by_record(registros).groups
        assert len(grupos) == 1
        assert grupos[0].page_numbers == [1, 2]

    def test_el_mismo_folio_de_otra_persona_sigue_siendo_otro_registro(self):
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
            registro(2, MarcaDeFolio.PRESENTE, folio="51", cedula="22793650"),
        ]
        assert len(group_by_record(registros).groups) == 2

    def test_la_duda_une_en_vez_de_cortar(self):
        """La norma de la casa: sin evidencia de apertura, la hoja se queda.

        Medido sobre el libro, la diferencia son cuatro documentos: las cuatro
        hojas cuya esquina no se pudo juzgar abrían un archivo de media hoja en
        vez de quedarse con el registro al que pertenecen.
        """
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1"),
            registro(2, MarcaDeFolio.DUDOSA, nombre="LA REPUBLICA DE COLOMBIA"),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]

    def test_la_union_por_duda_queda_dicha(self):
        """Unir de más sólo es el lado seguro si deja rastro de que se unió."""
        from resolutions.domain.diploma import extract_diploma_warnings

        revisado = extract_diploma_warnings(
            registro(2, MarcaDeFolio.DUDOSA, nombre="ALIX MARIN")
        )
        assert any("esquina" in aviso for aviso in revisado.warnings)

    def test_sin_medida_el_reparto_es_el_de_antes(self):
        """Una fuente sin píxeles no cambia lo que el sistema ya hacía.

        Sin marca decide la regla de los identificadores leídos: la página que
        no trae ninguno se pega a la anterior, y la que trae folio abre.
        """
        registros = [
            registro(1, folio="330"),
            registro(2),
            registro(3, folio="331"),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3]]


class TestElFuidCuentaLoMismoQueLaCarpeta:
    def test_una_fila_por_registro_y_sus_folios(self):
        """Si no coincidieran, el inventario prometería diplomas que no existen."""
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1", nombre="ALIX MARIN"),
            registro(2, MarcaDeFolio.AUSENTE),
            registro(3, MarcaDeFolio.PRESENTE, folio="2", nombre="JOSE TORRES"),
            registro(4, MarcaDeFolio.AUSENTE),
        ]
        filas = filas_del_libro(registros, nombre_del_archivo="UPD3859766.pdf")
        grupos = group_by_record(registros).groups
        assert len(filas) == len(grupos) == 2
        assert [fila.folios for fila in filas] == [2, 2]


class TestLaMedidaSobrePapel:
    """Que el adaptador distinga de verdad una esquina escrita de una limpia."""

    @pytest.fixture
    def libro(self, tmp_path):
        documento = pymupdf.open()
        escrita = documento.new_page()
        ancho = escrita.rect.width
        # Donde va el folio: pegado al margen derecho y a la cabecera. En gris
        # y no en negro porque así llega un folio escaneado: la tinta o el lápiz
        # sobre papel dan gris medio, y el negro del todo en estos escaneos lo
        # pone el escáner -- el canto del libro, la sombra del alimentador --,
        # que es justo lo que la medida descarta.
        escrita.insert_text(
            (ancho * 0.80, 40), "126 v", fontsize=22, color=(0.45, 0.45, 0.45)
        )
        documento.new_page()  # la vuelta, que nunca llevó folio
        ruta = tmp_path / "libro.pdf"
        documento.save(ruta)
        documento.close()
        return ruta

    def test_la_cara_escrita_da_marca_y_la_vuelta_no(self, libro):
        fuente = PyMuPDFPageSource(libro)
        try:
            banda = Band(*BANDA_DEL_FOLIO)
            trazo_recto, vetado_recto = fuente.ink_of(1, banda)
            trazo_vuelto, _ = fuente.ink_of(2, banda)
        finally:
            fuente.close()

        assert trazo_recto >= TINTA_DE_FOLIO
        assert vetado_recto == 0.0
        assert trazo_vuelto == 0.0

    def test_el_canto_negro_del_escaner_no_es_un_folio(self, tmp_path):
        """Una franja negra en el borde entra en la banda y no es tinta de nadie.

        Le pasa a siete de las 398 hojas del libro medido. Contarla como folio
        parte por la mitad el registro al que pertenece esa vuelta.
        """
        documento = pymupdf.open()
        pagina = documento.new_page()
        rect = pagina.rect
        pagina.draw_rect(
            pymupdf.Rect(rect.width * 0.95, 0, rect.width, rect.height * 0.08),
            color=(0, 0, 0),
            fill=(0, 0, 0),
        )
        ruta = tmp_path / "con_canto.pdf"
        documento.save(ruta)
        documento.close()

        fuente = PyMuPDFPageSource(ruta)
        try:
            trazo, _ = fuente.ink_of(1, Band(*BANDA_DEL_FOLIO))
        finally:
            fuente.close()

        assert marca_de_folio(TrazoEnEsquina(trazo, 0.0)) is MarcaDeFolio.AUSENTE

    def test_la_lectura_del_libro_reparte_por_la_marca(self, libro):
        """De punta a punta: del PDF a los grupos, sin OCR de por medio."""
        from resolutions.application.read_diploma_book import ReadDiplomaBook

        fuente = PyMuPDFPageSource(libro)
        try:
            registros, _ = ReadDiplomaBook().execute(fuente)
        finally:
            fuente.close()

        assert registros[0].folio_mark is MarcaDeFolio.PRESENTE
        assert registros[1].folio_mark is MarcaDeFolio.AUSENTE
        grupos = group_by_record(registros).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]


class TestElRitmoDelLibro:
    """Un libro encuadernado va de dos en dos, y eso también es evidencia.

    Medido sobre `UPD3859766`: las 199 caras de delante se reconocen todas, y
    tres vueltas salen marcadas de más -- la franja negra del borde en la 140,
    la punta de la hoja levantada en la 354, y en la 224 la palabra "Anulada"
    escrita a mano. La tercera es la que obliga a esta regla: hay escritura de
    verdad en esa esquina, así que ninguna medida de tinta la va a descartar.
    """

    def marcas(self, presentes, total):
        return [
            MarcaDeFolio.PRESENTE if n in presentes else MarcaDeFolio.AUSENTE
            for n in range(total)
        ]

    def test_un_libro_escaneado_por_las_dos_caras_tiene_ritmo(self):
        assert libro_alterna(self.marcas(range(0, 40, 2), 40))

    def test_un_libro_de_cara_simple_no_lo_tiene(self):
        """Todas las hojas llevan folio, así que no hay compás que aplicar."""
        assert not libro_alterna(self.marcas(range(40), 40))

    def test_cuatro_hojas_no_hacen_un_compas(self):
        """Por debajo de la muestra mínima no se corrige nada."""
        assert not libro_alterna(self.marcas((0, 2, 4, 6), 8))

    def test_la_esquina_que_rompe_el_ritmo_se_une_a_la_anterior(self):
        """El caso de la página 224: "Anulada" escrito en la vuelta."""
        marcas = self.marcas(range(0, 40, 2), 40)
        marcas[23] = MarcaDeFolio.PRESENTE  # una vuelta con algo escrito

        ajustadas = marcas_en_ritmo(marcas)

        assert ajustadas[23] is MarcaDeFolio.DUDOSA
        assert ajustadas[22] is MarcaDeFolio.PRESENTE

    def test_y_no_se_lleva_por_delante_la_cara_siguiente(self):
        """La 141 lleva folio y abre registro, aunque la 140 se haya rebajado.

        Sin esto, cada esquina rebajada arrastraba al registro de después y lo
        soldaba al anterior: tres documentos de cuatro caras en el libro medido,
        que es exactamente el FALSE_MERGE que la regla venía a no cometer.
        """
        marcas = self.marcas(range(0, 40, 2), 40)
        marcas[23] = MarcaDeFolio.PRESENTE

        ajustadas = marcas_en_ritmo(marcas)

        assert ajustadas[24] is MarcaDeFolio.PRESENTE
        assert [i for i, m in enumerate(ajustadas) if m is MarcaDeFolio.DUDOSA] == [23]

    def test_un_libro_sin_ritmo_vuelve_intacto(self):
        """Sin compás demostrado no hay nada que contradiga a la tinta."""
        marcas = self.marcas(range(40), 40)
        assert marcas_en_ritmo(marcas) == marcas

    def test_el_reparto_queda_de_dos_en_dos(self):
        """De punta a punta: la costura rebajada une, y sólo esa."""
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1"),
            registro(2, MarcaDeFolio.AUSENTE),
            registro(3, MarcaDeFolio.PRESENTE, folio="2"),
            registro(4, MarcaDeFolio.DUDOSA),  # la vuelta con "Anulada" escrito
            registro(5, MarcaDeFolio.PRESENTE, folio="3"),
            registro(6, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3, 4], [5, 6]]


class TestElNumeroDelFolio:
    """Leer el folio es otra cosa que repartir el libro, y se comprueba aparte.

    Para repartir basta con saber si la esquina tiene algo escrito. Para nombrar
    el archivo hace falta el número, y entonces alguien tiene que leer
    manuscrito y lo que conteste hay que comprobarlo. Todas las cadenas de esta
    clase son lecturas reales del libro 7 con el OCR de Mistral.
    """

    def test_el_folio_es_el_que_lleva_la_v(self):
        """La esquina trae dos números: la página arriba y el folio debajo."""
        assert folio_de_la_esquina("135 70/1", 139) == "70"
        assert folio_de_la_esquina("396 200/V", 397) == "200"

    def test_la_v_llega_escrita_de_muchas_formas(self):
        """Lo que identifica al folio es la barra, no qué letra sobrevivió."""
        assert folio_de_la_esquina("15-8/v", 15) == "8"
        assert folio_de_la_esquina("#9-10/1", 19) == "10"
        assert folio_de_la_esquina("9 5/0", 9) == "5"

    def test_el_numero_de_pagina_pegado_al_folio_se_separa(self):
        """"2513/v" en la página 25 es el folio 13, no el folio 2513."""
        assert folio_de_la_esquina("2513/v", 25) == "13"

    def test_una_esquina_sin_numeros_no_inventa_ninguno(self):
        assert folio_de_la_esquina("N/A", 7) is None
        assert folio_de_la_esquina("Anulada", 224) is None
        assert folio_de_la_esquina("", 3) is None

    def test_la_progresion_del_libro_tumba_lo_que_no_encaja(self):
        """"No 44" en la sexta cara y "1974" en la séptima son lecturas reales.

        Las dos pasan por número y ninguna es un folio. Lo que las delata no es
        su forma sino su sitio: en ese punto del libro el folio va por seis.
        """
        lecturas = [
            (1, "1"), (3, "2"), (5, "3"), (7, None), (9, "5"),
            (11, "44"), (13, "1974"), (15, "8"), (17, "9"),
        ]
        confirmados = folios_comprobados(lecturas)

        assert confirmados == {1: "1", 3: "2", 5: "3", 9: "5", 15: "8", 17: "9"}
        assert 11 not in confirmados
        assert 13 not in confirmados

    def test_la_foliacion_puede_saltarse_un_numero(self):
        """En el libro 7 la cara 111 lleva el folio 111 y la 199 lleva el 200.

        El foliador se dejó un número en algún punto, y una comprobación que
        exigiera coincidencia exacta tiraría la mitad del libro por eso.
        """
        lecturas = [(1, "1"), (3, "2"), (5, "3"), (7, "5"), (9, "6")]
        assert len(folios_comprobados(lecturas)) == 5

    def test_sin_ninguna_lectura_no_se_devuelve_nada(self):
        """Y en particular no se rellena contando caras.

        La cara 199 de este libro lleva el folio 200: nombrar por el ordinal
        equivocaría la última mitad del libro sin que nadie pudiera notarlo.
        """
        assert folios_comprobados([(1, None), (3, None)]) == {}

    def test_el_folio_de_la_esquina_nombra_el_archivo_cuando_no_hay_otro(self):
        """En estos libros el formulario no trae ningún folio impreso."""
        registros = [
            DiplomaRecord(
                page_number=1,
                folio_mark=MarcaDeFolio.PRESENTE,
                folio_manuscrito="1",
            ),
            DiplomaRecord(page_number=2, folio_mark=MarcaDeFolio.AUSENTE),
            DiplomaRecord(
                page_number=3,
                folio_mark=MarcaDeFolio.PRESENTE,
                folio_manuscrito="2",
            ),
            DiplomaRecord(page_number=4, folio_mark=MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.code.value for grupo in grupos] == ["1", "2"]
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3, 4]]


class TestLaCarpetaYElInventarioCuentanIgual:
    """Una fila del FUID por archivo en la carpeta, sin excepción.

    Es el invariante que más caro sale romper: si el inventario cuenta una fila
    donde la carpeta escribe media, promete diplomas que no existen y nadie lo
    nota hasta que alguien va a buscar uno. Se rompió de verdad -- 203 filas
    contra 199 archivos en el libro 7 -- porque el separador y el FUID tenían
    la regla escrita cada uno por su lado y habían divergido.
    """

    def test_la_hoja_fotografiada_dos_veces_cuenta_una_sola_vez(self):
        """El caso que las separó: mismo folio y misma cédula, dos capturas."""
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
            registro(2, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
            registro(3, MarcaDeFolio.PRESENTE, folio="52", cedula="22793650"),
        ]
        grupos = group_by_record(registros).groups
        filas = filas_del_libro(registros, nombre_del_archivo="UPD3859766.pdf")

        assert len(grupos) == len(filas) == 2
        assert grupos[0].page_numbers == [1, 2]
        assert filas[0].folios == 2

    def test_y_dos_graduados_distintos_con_el_mismo_folio_cuentan_dos(self):
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="51", cedula="45437535"),
            registro(2, MarcaDeFolio.PRESENTE, folio="51", cedula="22793650"),
        ]
        assert len(group_by_record(registros).groups) == 2
        assert len(filas_del_libro(registros, nombre_del_archivo="x.pdf")) == 2

    def test_la_vuelta_sin_folio_suma_a_la_fila_de_arriba(self):
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, folio="1", cedula="45437535"),
            registro(2, MarcaDeFolio.AUSENTE),
            registro(3, MarcaDeFolio.PRESENTE, folio="2", cedula="22793650"),
            registro(4, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros).groups
        filas = filas_del_libro(registros, nombre_del_archivo="x.pdf")

        assert len(grupos) == len(filas) == 2
        assert [fila.folios for fila in filas] == [2, 2]
        assert [grupo.size for grupo in grupos] == [2, 2]


class TestUnLibroSeParteSinPagarLectura:
    """El corte no necesita OCR, así que sin él se pierden nombres, no documentos.

    Es la capacidad que pidió el operador: procesar un libro de diplomas con lo
    que hay en casa y dejar la ayuda de pago como algo que se enciende cuando
    hace falta. El folio de la esquina se detecta contando tinta -- 199 de 199
    caras en el libro medido -- y eso ocurre antes de que nadie lea una palabra.
    """

    def test_los_documentos_salen_numerados_en_secuencia(self):
        """Sin cédula ni folio leídos, cada documento lleva su orden en el libro."""
        registros = []
        for pagina in range(1, 13):
            marca = MarcaDeFolio.PRESENTE if pagina % 2 else MarcaDeFolio.AUSENTE
            registros.append(registro(pagina, marca))

        grupos = group_by_record(registros).groups

        assert [grupo.code.value for grupo in grupos] == [
            "001", "002", "003", "004", "005", "006"
        ]
        assert [grupo.page_numbers for grupo in grupos] == [
            [1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12]
        ]

    def test_tres_digitos_para_que_la_carpeta_se_ordene(self):
        """Listada por nombre, "010" va detrás de "009" y "10" iría detrás de "1"."""
        registros = [
            registro(pagina, MarcaDeFolio.PRESENTE if pagina % 2 else MarcaDeFolio.AUSENTE)
            for pagina in range(1, 21)
        ]
        codigos = [grupo.code.value for grupo in group_by_record(registros).groups]
        assert codigos[-1] == "010"
        assert codigos == sorted(codigos)

    def test_y_la_cedula_manda_en_cuanto_se_lee(self):
        """Encender la ayuda de pago cambia el nombre, no el corte."""
        registros = [
            registro(1, MarcaDeFolio.PRESENTE, cedula="7882907"),
            registro(2, MarcaDeFolio.AUSENTE),
            registro(3, MarcaDeFolio.PRESENTE),
            registro(4, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros).groups
        assert [grupo.code.value for grupo in grupos] == ["7882907", "002"]
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3, 4]]

class TestLaProgresionExigeMayoria:
    def test_un_folio_suelto_entre_muchos_sin_leer_no_se_cree(self):
        """Sin mayoría no hay progresión contra la que comprobar, sólo números.

        Pasó en el libro 7 leído sólo con el motor local: de sus 199 registros
        se sacaron cuatro folios dispares, y el primero se daba por bueno. En la
        carpeta aparecía un `7_DIPLOMA.pdf` entre el 004 y el 006 -- que parece
        un dato del papel y no lo es.
        """
        lecturas = [(1, "7"), (3, None), (5, None), (7, "91"), (9, None), (11, "3")]
        assert folios_comprobados(lecturas) == {}

    def test_pero_un_libro_de_un_solo_registro_conserva_su_folio(self):
        """Ahí ese folio es todo lo que hay, y la mayoría se cumple sola."""
        assert folios_comprobados([(1, "336")]) == {1: "336"}
