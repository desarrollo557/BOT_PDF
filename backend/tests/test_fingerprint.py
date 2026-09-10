"""La huella de una página: lo poco que decide dónde empieza un documento.

Todos los textos vienen de "UPD2366126.pdf", un expediente real de Caribe Mar de
la Costa. Incluida la basura del OCR: el logo de la empresa sale como `ahnia`,
`aFinia` y `aPinia` en la misma caja, y la página 9 imprime `Página 1 de o`
porque el 6 salió como letra. Un caso inventado no habría mostrado que la
paginación —que es la señal más fuerte que hay— llega rota justo cuando más
falta hace.
"""

from resolutions.domain.fingerprint import (
    Heading,
    Pagination,
    fingerprint_page,
    read_pagination,
)
from resolutions.domain.segmentation import Verdict, decide_boundaries

#: Página 3: primera hoja de una respuesta a reclamación. Trae todo lo que un
#: documento nuevo suele traer, y por eso es el caso fácil.
PAGINA_3 = (
    "aFinia Grupo*epr9 Consecutivo No.202170183712 AGUSTIN CODAZZI, 08/07/2021 "
    "Señora: SULAY QUINTERO MOLINA CARRERA 19 No 12-31 Agustín Codazzi - Cesar "
    "Asunto: Reclamación No. RE3120202101650 Página 1 de 5"
)

#: Página 1: el aviso de publicación que abre cada trámite del expediente. Su
#: consecutivo lleva el prefijo "PA" y un espacio, que es la forma que el patrón
#: no admitía. Las siete publicaciones de la caja se imprimen así.
PAGINA_1 = (
    "ass afinia ^6 1^2 CO^?Í Al O) Grupo‘epr9 a> r^m% O) SI "
    "Consecutivo No. PA 202170210656 PUBLICACIÓN DEL AVISO "
    "Teniendo en cuenta que: a) El usuario SULAY QUINTERO MOLINA reportó como "
    "dirección de notificación para la respuesta a la petición presentada el día "
    "30/06/2021, radicada bajo el número RE3120202101650"
)

#: Página 2: la notificación por aviso que sigue a la publicación. Otro
#: documento, y su consecutivo lo dice: cambia y viene sin espacio.
PAGINA_2 = (
    "- \\M/ arinia Grupo-eprp Cartagena, 21-07-2021 "
    "Consecutivo No.A202170196624 Señor(a) SULAY QUINTERO MOLINA "
    "Asunto: Notificación por aviso NIC: 5826232 "
    "Radicado número: RE3120202101650"
)

#: Página 7: última hoja del mismo documento. Cierra con la fórmula de despedida
#: y con el cargo de quien firma.
PAGINA_7 = (
    "_ vJlí'/ arinia Grupo-epnQ No obstante, de conformidad con el artículo 155 "
    "de la ley 142 del 94, para presentar los recursos. Cordialmente, "
    "YUDIS PAREDES SARMIENTO Coordinadora Central de Escritos Página 5 de 5"
)

#: Página 9: el OCR convirtió el 6 del total en la letra o.
PAGINA_9 = (
    "ahnia Grupo*epfi3 Radicación # ;285762425826232 COD/^I, MARTES, 20 DE ABRIL "
    "DE 2021 rticular. gasta sai: /m Maéiwoo Página 1 de o"
)


class TestLaPaginacionQueElPapelDeclara:
    def test_lee_pagina_x_de_y(self):
        assert read_pagination("... Página 1 de 5") == Pagination(index=1, total=5)

    def test_tolera_la_forma_abreviada(self):
        assert read_pagination("Pag. 3 de 4") == Pagination(index=3, total=4)

    def test_tolera_la_barra(self):
        assert read_pagination("Página 2/3") == Pagination(index=2, total=3)

    def test_sin_paginacion_no_inventa(self):
        assert read_pagination("Cordialmente, YUDIS PAREDES") is None

    def test_el_total_roto_por_el_ocr_no_pasa_por_bueno(self):
        """`Página 1 de o` no es paginación: es una lectura fallada.

        Devolver `1 de 0` sería peor que devolver nada, porque una cadena con
        total cero encadena documentos que no existen.
        """
        assert read_pagination(PAGINA_9) is None

    def test_un_indice_mayor_que_el_total_se_descarta(self):
        assert read_pagination("Página 7 de 5") is None


class TestLaHuellaDeUnaPrimeraPagina:
    def test_recoge_las_senales_de_apertura(self):
        huella = fingerprint_page(3, PAGINA_3, headings=[])
        assert huella.page_number == 3
        assert huella.serial == "202170183712"
        assert huella.pagination == Pagination(index=1, total=5)
        assert huella.place_and_date is not None
        assert "08/07/2021" in huella.place_and_date
        assert huella.closes is False

    def test_el_codigo_de_caso_se_guarda_pero_no_es_del_documento(self):
        """RE31... identifica el expediente, no la hoja.

        Las 125 páginas de esta caja comparten el caso. Usarlo para decidir
        continuidad une el expediente entero en un solo documento, que es
        exactamente el error que hay que no cometer.
        """
        huella = fingerprint_page(3, PAGINA_3, headings=[])
        assert huella.case_code == "RE3120202101650"


class TestLaHuellaDeUnaUltimaPagina:
    def test_reconoce_la_formula_de_cierre(self):
        huella = fingerprint_page(7, PAGINA_7, headings=[])
        assert huella.closes is True
        assert huella.pagination == Pagination(index=5, total=5)

    def test_el_cierre_solo_cuenta_al_final_de_la_pagina(self):
        """"Cordialmente" citado a mitad de un recurso no cierra nada."""
        texto = "Cordialmente me dirijo a ustedes " + ("relleno " * 200)
        assert fingerprint_page(1, texto, headings=[]).closes is False


class TestElMembreteSeVeEnLaGeometria:
    def test_un_renglon_corto_y_centrado_arriba_es_membrete(self):
        headings = [Heading(text="Acta de Irregularidad", center_x=0.50, top=0.06)]
        assert fingerprint_page(12, "Acta de Irregularidad", headings).letterhead is True

    def test_un_renglon_al_pie_no_es_membrete(self):
        headings = [Heading(text="www.afinia.com", center_x=0.50, top=0.95)]
        assert fingerprint_page(12, "texto", headings).letterhead is False

    def test_un_renglon_pegado_al_margen_no_es_membrete(self):
        headings = [Heading(text="Sector Cesar Norte", center_x=0.08, top=0.05)]
        assert fingerprint_page(16, "texto", headings).letterhead is False

    def test_sin_geometria_la_huella_se_arma_igual(self):
        """Una fuente que no sabe dónde están sus renglones no rompe nada."""
        huella = fingerprint_page(3, PAGINA_3, headings=[])
        assert huella.letterhead is False
        assert huella.serial == "202170183712"


class TestLoQueViajaAlModelo:
    """Cada campo que sobra se paga 125 veces, una por página de la caja."""

    def test_lo_ausente_no_ocupa_lugar(self):
        compacta = fingerprint_page(50, "relleno sin ninguna señal").compact()
        assert "pg" not in compacta
        assert "cs" not in compacta
        assert "mb" not in compacta
        assert "fin" not in compacta

    def test_lo_presente_viaja_abreviado(self):
        compacta = fingerprint_page(3, PAGINA_3).compact()
        assert compacta["p"] == 3
        assert compacta["pg"] == "1/5"
        assert compacta["cs"] == "202170183712"

    def test_el_cierre_viaja_cuando_lo_hay(self):
        assert fingerprint_page(7, PAGINA_7).compact()["fin"] == 1

    def test_el_codigo_de_caso_no_viaja(self):
        """No decide nada y son veinte caracteres por página.

        Se guarda en la huella para el inventario; mandárselo al modelo solo
        lo invita a usarlo como continuidad, que es el error a evitar.
        """
        assert "re" not in fingerprint_page(3, PAGINA_3).compact()

    def test_una_pagina_cabe_en_poco(self):
        compacta = fingerprint_page(3, PAGINA_3).compact()
        assert len(str(compacta)) < 220


class TestElTituloNoEsLaMarcaDelPapel:
    """Lo que la hoja dice ser, no la empresa que la imprimió.

    Medido sobre el expediente de 125 páginas: el logo de Grupo EPM llegaba del
    OCR como 'Grupo*epr9', 'GrupO\'epo)', 'Grupo^epnQ' -- distinto en cada hoja --
    y era el título de 111 de las 125. Es el campo `t` de la huella: el único dato
    temático que viaja al modelo. Pedirle continuidad de tema mientras recibe el
    logo mal leído es pedirle que adivine.

    El discriminador sale del dato: todos los logos observados son un solo token
    y los nombres de documento son varias palabras.
    """

    def test_el_logo_no_le_gana_al_nombre_del_documento(self):
        headings = [
            Heading(text="Grupo*epr9", center_x=0.50, top=0.04),
            Heading(text="Acta de Irregularidad", center_x=0.50, top=0.11),
        ]
        assert fingerprint_page(1, "texto de la pagina", headings).title == "Acta de Irregularidad"

    def test_da_igual_como_el_ocr_haya_roto_el_logo(self):
        for logo in ("Grupo-eprp", "GrupO'epo)", "Grupo^epnQ", "Grupo*epfi3"):
            headings = [
                Heading(text=logo, center_x=0.50, top=0.04),
                Heading(text="Notificacion de cobro", center_x=0.50, top=0.12),
            ]
            titulo = fingerprint_page(1, "cuerpo", headings).title
            assert titulo == "Notificacion de cobro", f"con el logo {logo!r} salio {titulo!r}"

    def test_un_nombre_de_una_sola_palabra_se_conserva_si_es_lo_unico_que_hay(self):
        """Hay documentos que se llaman así. No se los descarta por ser cortos."""
        headings = [Heading(text="NOTIFICACION", center_x=0.50, top=0.05)]
        assert fingerprint_page(1, "cuerpo", headings).title == "NOTIFICACION"

    def test_sin_encabezados_utiles_habla_el_cuerpo(self):
        assert fingerprint_page(1, "el usuario reclama el consumo", []).title.startswith("el usuario")

    def test_un_encabezado_fuera_de_la_banda_no_es_el_titulo(self):
        headings = [Heading(text="pie de pagina con aviso legal", center_x=0.50, top=0.95)]
        assert fingerprint_page(1, "cuerpo de la hoja", headings).title.startswith("cuerpo")

    def test_el_primer_nombre_de_varias_palabras_es_el_que_manda(self):
        headings = [
            Heading(text="Grupo*epr9", center_x=0.50, top=0.03),
            Heading(text="Acta de Irregularidad", center_x=0.50, top=0.09),
            Heading(text="Señor Juan Perez Gomez", center_x=0.50, top=0.15),
        ]
        assert fingerprint_page(1, "cuerpo", headings).title == "Acta de Irregularidad"


class TestElConsecutivoConPrefijo:
    """El prefijo del consecutivo, que llega de tres formas distintas.

    Medido sobre "UPD2366126.pdf": de sus 125 páginas, 28 traían consecutivo
    legible y 7 más lo traían impreso sin que el patrón las viera. Esas 7 son
    todos los avisos de publicación de la caja, y cada una dejaba su costura sin
    decidir por un dato que estaba en la hoja.
    """

    def test_lee_el_prefijo_de_dos_letras_separado_por_un_espacio(self):
        assert fingerprint_page(1, PAGINA_1, headings=[]).serial == "PA202170210656"

    def test_sigue_leyendo_el_prefijo_de_una_letra_pegado(self):
        assert fingerprint_page(2, PAGINA_2, headings=[]).serial == "A202170196624"

    def test_sigue_leyendo_el_consecutivo_sin_prefijo(self):
        assert fingerprint_page(3, PAGINA_3, headings=[]).serial == "202170183712"

    def test_el_espacio_no_sobrevive_a_la_huella(self):
        """Porque la continuidad se decide comparando consecutivos por igualdad.

        Un espacio de más convierte dos lecturas del mismo número en dos números
        distintos, y con eso la regla corta donde debía continuar.
        """
        huella = fingerprint_page(1, PAGINA_1, headings=[])
        assert " " not in huella.serial

    def test_el_prefijo_se_guarda_en_mayusculas(self):
        """El OCR devuelve la caja que quiere; la comparación no puede depender de eso."""
        huella = fingerprint_page(1, "Consecutivo No. pa 202170210656", headings=[])
        assert huella.serial == "PA202170210656"

    def test_dos_avisos_seguidos_son_dos_documentos(self):
        """La costura que este arreglo saca de revisión, decidida como corresponde.

        La publicación del aviso y la notificación por aviso son dos documentos
        de una página cada uno. Sin el prefijo, la regla del consecutivo no tenía
        los dos datos que necesita y la costura caía en UNDECIDED.
        """
        huellas = [
            fingerprint_page(1, PAGINA_1, headings=[]),
            fingerprint_page(2, PAGINA_2, headings=[]),
        ]
        (costura,) = decide_boundaries(huellas)
        assert costura.verdict is Verdict.STARTS
        assert costura.reason == "cambia el consecutivo"


class TestElIdentificadorPartidoPorElEscaner:
    """"Nic:" en un renglón y "5826232" en otro, a la misma altura.

    Es como un formulario escaneado devuelve sus campos, y buscarlos pegados en
    el texto corrido no los encuentra nunca. La página 17 de "UPD2366126.pdf"
    tenía su NIC sólo así: la palabra aparecía en la hoja, el número también, y
    el texto plano los daba separados por media línea de otra columna.
    """

    def test_el_valor_a_la_derecha_del_rotulo_es_suyo(self):
        headings = [
            Heading(text="Nic:", center_x=0.76, top=0.096),
            Heading(text="5826232", center_x=0.89, top=0.094),
        ]
        huella = fingerprint_page(17, "cuerpo de la hoja", headings)
        assert ("nic", "5826232") in huella.identifiers

    def test_un_numero_de_otro_renglon_no_es_suyo(self):
        """Ocho milésimas de la altura de la página separan una línea de la siguiente."""
        headings = [
            Heading(text="Nic:", center_x=0.76, top=0.096),
            Heading(text="9999999", center_x=0.89, top=0.180),
        ]
        assert fingerprint_page(17, "cuerpo", headings).identifiers == frozenset()

    def test_un_numero_a_la_izquierda_del_rotulo_tampoco(self):
        headings = [
            Heading(text="Nic:", center_x=0.76, top=0.096),
            Heading(text="9999999", center_x=0.30, top=0.095),
        ]
        assert fingerprint_page(17, "cuerpo", headings).identifiers == frozenset()

    def test_entre_dos_valores_gana_el_mas_cercano(self):
        """En una fila de formulario, el valor de un rótulo es el que le sigue."""
        headings = [
            Heading(text="Nic:", center_x=0.40, top=0.096),
            Heading(text="5826232", center_x=0.52, top=0.096),
            Heading(text="140512", center_x=0.90, top=0.095),
        ]
        huella = fingerprint_page(17, "cuerpo", headings)
        assert ("nic", "5826232") in huella.identifiers
        assert ("nic", "140512") not in huella.identifiers

    def test_el_pegado_al_rotulo_se_sigue_leyendo(self):
        huella = fingerprint_page(18, "identificado con el NIC 5826232. 2. A lo anterior", [])
        assert ("nic", "5826232") in huella.identifiers

    def test_una_cifra_corta_no_es_un_identificador(self):
        headings = [
            Heading(text="Nic:", center_x=0.76, top=0.096),
            Heading(text="248", center_x=0.89, top=0.095),
        ]
        assert fingerprint_page(17, "cuerpo", headings).identifiers == frozenset()

    def test_sin_geometria_no_se_inventa_nada(self):
        assert fingerprint_page(17, "Nic: y en otra parte 5826232", []).identifiers == frozenset()


class TestElFolioEscritoAMano:
    """El número que pone quien arma el expediente, arriba de la hoja.

    No es la paginación impresa: ésa dice "3 de 5" y se basta sola. El folio
    sólo dice "3", y en la caja medida es la numeración que de verdad hay --
    cuarenta y ocho hojas la llevan y ninguna trae paginación.
    """

    def test_un_numero_solo_en_lo_alto_es_el_folio(self):
        headings = [Heading(text="4", center_x=0.88, top=0.04)]
        assert fingerprint_page(42, "cuerpo de la hoja", headings).folio == 4

    def test_un_numero_dentro_de_una_frase_no_lo_es(self):
        headings = [Heading(text="4 Elaborar una nueva factura", center_x=0.5, top=0.04)]
        assert fingerprint_page(42, "cuerpo", headings).folio is None

    def test_un_numero_de_mas_abajo_tampoco(self):
        """Bajo la banda alta ya no folia nadie: es una celda de tabla."""
        headings = [Heading(text="248", center_x=0.5, top=0.40)]
        assert fingerprint_page(42, "cuerpo", headings).folio is None

    def test_entre_varios_gana_el_de_mas_arriba(self):
        headings = [
            Heading(text="7", center_x=0.88, top=0.03),
            Heading(text="12", center_x=0.20, top=0.09),
        ]
        assert fingerprint_page(42, "cuerpo", headings).folio == 7

    def test_la_puntuacion_que_lo_rodea_no_estorba(self):
        headings = [Heading(text=".5.", center_x=0.88, top=0.04)]
        assert fingerprint_page(42, "cuerpo", headings).folio == 5

    def test_un_ano_no_es_un_folio(self):
        headings = [Heading(text="2020", center_x=0.88, top=0.04)]
        assert fingerprint_page(42, "cuerpo", headings).folio is None

    def test_sin_geometria_no_hay_folio(self):
        assert fingerprint_page(42, "4 el cuerpo de la hoja", []).folio is None


class TestLaCiudadYLaFechaPidenSuComa:
    """Sin coma, el patrón llamaba "ciudad y fecha" a media hoja.

    Medido sobre dos expedientes: de cada tres detecciones, dos eran cosas como
    "DEL 10/12/2021", "CARRERA 17 12-96" o "Transformador 26/08/2021". Cada una
    convertía una hoja de cuerpo en una que parecía abrir un documento.
    """

    def test_la_de_verdad_se_sigue_leyendo(self):
        huella = fingerprint_page(2, "arinia Grupo-eprp Cartagena, 21-07-2021 Señor(a)")
        assert huella.place_and_date is not None
        assert "21-07-2021" in huella.place_and_date

    def test_en_mayusculas_tambien(self):
        huella = fingerprint_page(3, "aFinia AGUSTIN CODAZZI, 08/07/2021 Señora:")
        assert huella.place_and_date is not None

    def test_una_preposicion_con_una_fecha_detras_no_lo_es(self):
        assert fingerprint_page(75, "REVISION No 29683385 DEL 24/11/2022. Ya, que no").place_and_date is None

    def test_una_direccion_tampoco(self):
        assert fingerprint_page(29, "CARRERA 17 12-96 ENTRADA 1 PISO 1").place_and_date is None

    def test_ni_una_pieza_de_la_red_con_su_fecha(self):
        assert fingerprint_page(38, "Transformador 26/08/2021 Sector Cesar").place_and_date is None


class TestElRotuloDeLaLiquidacion:
    def test_se_reconoce(self):
        texto = "armia Liquidación del Consumo No registrado Pendiente Por Facturar: C.N.R.P.F"
        assert fingerprint_page(33, texto).label == "liquidacion del consumo"
