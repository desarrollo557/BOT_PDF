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

#: Página 3: primera hoja de una respuesta a reclamación. Trae todo lo que un
#: documento nuevo suele traer, y por eso es el caso fácil.
PAGINA_3 = (
    "aFinia Grupo*epr9 Consecutivo No.202170183712 AGUSTIN CODAZZI, 08/07/2021 "
    "Señora: SULAY QUINTERO MOLINA CARRERA 19 No 12-31 Agustín Codazzi - Cesar "
    "Asunto: Reclamación No. RE3120202101650 Página 1 de 5"
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
