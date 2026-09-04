"""Partir un libro de folios: un archivo por registro.

Un documento de resoluciones se parte por herencia y una resolución puede ocupar
cuarenta páginas. Un libro de folios no: cada cara es un registro terminado. Lo
que se fija aquí es que la división sea uno a uno, que ningún archivo pise a
otro cuando el libro repite un folio, y que una página ilegible siga saliendo.
"""

from resolutions.application.diploma_split import group_by_record
from resolutions.domain.diploma import DiplomaRecord
from resolutions.domain.naming import output_filename


def registro(pagina, folio=None, nombre=None, titulo=None, cedula=None):
    return DiplomaRecord(
        page_number=pagina,
        folio=folio,
        registered_folio=folio,
        name=nombre,
        identity_number=cedula,
        degree=titulo,
    )



class TestUnoAUno:
    def test_cada_pagina_produce_su_propio_grupo(self):
        registros = [registro(n, folio=str(330 + n)) for n in range(1, 5)]
        resultado = group_by_record(registros)
        assert len(resultado.groups) == 4
        assert all(group.size == 1 for group in resultado.groups)

    def test_conserva_el_orden_del_pdf(self):
        """El orden es el del documento y no el del folio: los libros alternan."""
        registros = [registro(1, folio="337BIS"), registro(2, folio="337")]
        paginas = [group.page_numbers[0] for group in group_by_record(registros).groups]
        assert paginas == [1, 2]

    def test_nada_va_a_cuarentena(self):
        """En un libro de folios no existe la página huérfana: ninguna hereda."""
        assert group_by_record([registro(1)]).quarantine == []

    def test_el_cuadre_de_paginas_se_sostiene(self):
        registros = [registro(n, folio=str(n)) for n in range(1, 6)]
        group_by_record(registros).verify_integrity(total_pages=5)


class TestNombres:
    def test_el_archivo_se_llama_por_la_cedula_y_el_graduando(self):
        grupo = group_by_record(
            [
                registro(
                    1,
                    folio="336BIS",
                    nombre="ALIX JOSEFINA MARIN",
                    titulo="ESPECIALISTA EN GESTION DE LA CALIDAD",
                    cedula="22793650",
                )
            ]
        ).groups[0]
        nombre = output_filename(grupo.code, grupo.title, prefix=None)
        assert nombre.startswith("22793650__")
        assert "alix-josefina-marin" in nombre
        assert "especialista-en-gestion-de-la-calidad" in nombre

    def test_el_archivo_se_llama_por_el_folio_cuando_no_hay_cedula(self):
        grupo = group_by_record(
            [registro(1, folio="336BIS", nombre="ALIX JOSEFINA MARIN", titulo="ESPECIALISTA")]
        ).groups[0]
        nombre = output_filename(grupo.code, grupo.title, prefix=None)
        assert nombre.startswith("336bis__")
        assert "alix-josefina-marin" in nombre

    def test_un_folio_repetido_con_la_misma_cedula_se_agrupa(self):
        """Un mismo folio puede repetir la misma persona, y entonces es la misma
        unidad documental y no debe partirse en dos archivos.
        """
        registros = [
            registro(18, folio="348", nombre="ANA", cedula="CEDULA-1"),
            registro(20, folio="348", nombre="ANA", cedula="CEDULA-1"),
        ]
        grupos = group_by_record(registros).groups
        assert len(grupos) == 1
        assert grupos[0].page_numbers == [18, 20]
        assert grupos[0].code.value == "CEDULA-1"

    def test_un_folio_repetido_con_cedula_distinta_no_se_agrupa(self):
        """Si el folio repite pero la persona no coincide, no hay excepción."""
        registros = [
            registro(18, folio="348", nombre="ANA", cedula="CEDULA-1"),
            registro(20, folio="348", nombre="LUIS", cedula="CEDULA-2"),
        ]
        codigos = [group.code.value for group in group_by_record(registros).groups]
        assert len(set(codigos)) == 2
        assert codigos[0] == "CEDULA-1"
        assert codigos[1] == "CEDULA-2"

    def test_sin_folio_legible_se_usa_el_numero_de_pagina(self):
        grupo = group_by_record([registro(152)]).groups[0]
        assert "152" in grupo.code.value

    def test_una_pagina_ilegible_sigue_saliendo_como_archivo(self):
        """Para que alguien pueda mirarla, en vez de perderse en un montón común."""
        resultado = group_by_record([registro(152)])
        assert len(resultado.groups) == 1
        assert resultado.groups[0].title is None


class TestLaVueltaDeUnFolio:
    """La cara de atrás de una hoja no es un diploma más.

    El archivo de la Universidad escanea las hojas por las dos caras cuando
    llevan algo escrito detrás, y lo anota poniendo una "v" junto al folio que
    escribe a mano en la esquina superior derecha. La cara de atrás llega sin
    folio y sin nada más, porque nunca lo tuvo. Lo mismo vale para lo que
    alguien anexa al expediente: la fotografía de una cédula no lleva folio ni
    encabezado.

    Antes cada una de esas páginas salía como archivo propio, con un nombre
    inventado a partir del número de página, así que la cuenta de diplomas del
    libro salía de más. Es la misma regla que ya regía en los expedientes de
    resoluciones -- una página sin identificador pertenece a la unidad que venía
    abierta -- y el usuario confirmó que vale para todos los tipos de documento.
    """

    def vacia(self, pagina):
        """Una página que no trajo absolutamente ningún identificador."""
        return DiplomaRecord(page_number=pagina)

    def test_a_page_with_nothing_on_it_joins_the_record_above(self):
        registros = [registro(1, folio="331", nombre="ANA"), self.vacia(2)]
        grupos = group_by_record(registros).groups
        assert len(grupos) == 1
        assert grupos[0].page_numbers == [1, 2]
        assert grupos[0].code.value == "331"

    def test_several_backs_in_a_row_all_join_the_same_record(self):
        registros = [
            registro(1, folio="331", nombre="ANA"),
            self.vacia(2),
            self.vacia(3),
            registro(4, folio="332", nombre="LUIS"),
        ]
        grupos = group_by_record(registros).groups
        assert [(g.code.value, g.page_numbers) for g in grupos] == [
            ("331", [1, 2, 3]),
            ("332", [4]),
        ]

    def test_a_page_that_read_badly_is_still_its_own_record(self):
        # La diferencia que sostiene todo esto: "no se pudo leer bien" no es
        # "no había nada". Una página que trae un nombre y ningún folio es un
        # registro que hay que revisar, no la vuelta de la anterior.
        registros = [registro(1, folio="331", nombre="ANA"), registro(2, nombre="LUIS")]
        grupos = group_by_record(registros).groups
        assert len(grupos) == 2
        assert grupos[1].page_numbers == [2]

    def test_a_first_page_with_nothing_still_ships_as_its_own_file(self):
        # No hay registro anterior al que unirla. Antes que perderla, sale sola.
        grupos = group_by_record([self.vacia(1), registro(2, folio="331")]).groups
        assert [g.page_numbers for g in grupos] == [[1], [2]]

    def test_every_page_is_still_accounted_for(self):
        registros = [
            registro(1, folio="331"),
            self.vacia(2),
            registro(3, folio="332"),
            self.vacia(4),
            self.vacia(5),
        ]
        group_by_record(registros).verify_integrity(total_pages=5)
