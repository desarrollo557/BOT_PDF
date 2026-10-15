"""Partir un libro de folios: un archivo por registro.

Un documento de resoluciones se parte por herencia y una resolución puede ocupar
cuarenta páginas. Un libro de folios no: cada cara es un registro terminado. Lo
que se fija aquí es que la división sea uno a uno, que ningún archivo pise a
otro cuando el libro repite un folio, y que una página ilegible siga saliendo.
"""

from resolutions.application.diploma_split import group_by_record
from resolutions.domain.diploma import CriterioDeCorte, DiplomaRecord
from resolutions.domain.folio_manuscrito import MarcaDeFolio
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
        # En el disco el guión bajo sale como guión: lo normaliza el nombrador
        # del proyecto, que reserva "__" para separar el código del asunto.
        # La cedula delante, sin prefijo: de que es el archivo lo dice el
        # tipo documental, que va al final del nombre.
        assert nombre.startswith("22793650__")
        assert "alix-josefina-marin" in nombre
        assert "especialista-en-gestion-de-la-calidad" in nombre

    def test_el_nombre_de_la_persona_tambien_queda_en_el_archivo(self):
        grupo = group_by_record(
            [registro(1, folio="336BIS", nombre="ALIX JOSEFINA MARIN", cedula="22793650")]
        ).groups[0]
        nombre = output_filename(
            grupo.code, grupo.title, prefix=None, kind=grupo.kind, con_titulo=True
        )
        assert nombre == "22793650_alix-josefina-marin_DIPLOMA.pdf"

    def test_sin_cedula_el_archivo_se_llama_por_el_graduando(self):
        """Lo pidió el operador: ningún documento sin nombre ni sin cédula.

        Antes caía al folio, y el folio identifica el asiento dentro del
        empaste pero no a la persona: entre `336bis_DIPLOMA.pdf` y
        `alix-josefina-marin_DIPLOMA.pdf`, al segundo lo encuentra cualquiera
        que busque a esa graduada y al primero sólo quien tenga el libro
        delante. El folio no se pierde: sigue en las notas del FUID.
        """
        grupo = group_by_record(
            [registro(1, folio="336BIS", nombre="ALIX JOSEFINA MARIN", titulo="ESPECIALISTA")]
        ).groups[0]
        nombre = output_filename(grupo.code, grupo.title, prefix=None)
        assert nombre.startswith("alix-josefina-marin")

    def test_y_por_el_folio_cuando_tampoco_hay_nombre(self):
        """La cola de alternativas entera: cédula, nombre, folio, orden."""
        grupo = group_by_record(
            [registro(1, folio="336BIS", titulo="ESPECIALISTA")]
        ).groups[0]
        assert output_filename(grupo.code, grupo.title, prefix=None).startswith("336bis")

    def test_un_nombre_de_una_sola_palabra_no_nombra(self):
        """"ANA" no es el nombre de la graduada: es lo que quedó de él cuando el
        escáner se comió el resto del renglón."""
        grupo = group_by_record(
            [registro(1, folio="336BIS", nombre="ANA")]
        ).groups[0]
        assert grupo.code.value == "336BIS"

    def test_un_nombre_con_danos_tampoco(self):
        """`ELI2ABETH-SM1TH_DIPLOMA.pdf` no lo busca nadie."""
        grupo = group_by_record(
            [registro(1, folio="336BIS", nombre="ELI2ABETH SM1TH")]
        ).groups[0]
        assert grupo.code.value == "336BIS"

    def test_un_folio_repetido_con_la_misma_cedula_se_agrupa(self):
        """Un mismo folio puede repetir la misma persona, y entonces es la misma
        unidad documental y no debe partirse en dos archivos (criterio FOLIO).

        Las cédulas son números de verdad y no rótulos: sólo una cédula que se
        sostiene nombra el archivo, de modo que un "CEDULA-1" de mentira haría
        pasar esta prueba por el camino equivocado -- el del folio -- sin probar
        nada de lo que dice probar.
        """
        registros = [
            registro(18, folio="348", nombre="ANA", cedula="7882907"),
            registro(20, folio="348", nombre="ANA", cedula="7882907"),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert len(grupos) == 1
        assert grupos[0].page_numbers == [18, 20]
        assert grupos[0].code.value == "7882907"

    def test_un_folio_repetido_con_cedula_distinta_no_se_agrupa(self):
        """Si el folio repite pero la persona no coincide, no hay excepción (criterio FOLIO)."""
        registros = [
            registro(18, folio="348", nombre="ANA", cedula="7882907"),
            registro(20, folio="348", nombre="LUIS", cedula="45437535"),
        ]
        codigos = [group.code.value for group in group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups]
        assert len(set(codigos)) == 2
        assert codigos[0] == "7882907"
        assert codigos[1] == "45437535"

    def test_sin_folio_legible_se_usa_el_orden_del_documento(self):
        """El consecutivo dentro del libro, que es lo que hay en la carpeta.

        Antes se usaba el número de página, y contaba otra cosa: "pagina-152"
        obliga a dividir mentalmente para saber por dónde va, mientras que el
        documento 76 es el archivo 76 de 199. Es además lo que permite partir un
        libro entero sin pagar una sola lectura -- el corte sale de la tinta de
        la esquina, no del OCR.
        """
        grupo = group_by_record([registro(152)]).groups[0]
        assert grupo.code.value == "001"

    def test_una_pagina_ilegible_sigue_saliendo_como_archivo(self):
        """Para que alguien pueda mirarla, en vez de perderse en un montón común."""
        resultado = group_by_record([registro(152)])
        assert len(resultado.groups) == 1
        assert resultado.groups[0].title is None


class TestLaVueltaDeUnFolio:
    """La cara de atrás de una hoja no es un diploma más (criterio FOLIO).

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
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
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
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [(g.code.value, g.page_numbers) for g in grupos] == [
            ("331", [1, 2, 3]),
            ("332", [4]),
        ]

    def test_a_page_that_read_badly_is_still_its_own_record(self):
        # La diferencia que sostiene todo esto: "no se pudo leer bien" no es
        # "no había nada". Una página que trae un nombre y ningún folio es un
        # registro que hay que revisar, no la vuelta de la anterior.
        registros = [registro(1, folio="331", nombre="ANA"), registro(2, nombre="LUIS")]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert len(grupos) == 2
        assert grupos[1].page_numbers == [2]

    def test_a_first_page_with_nothing_still_ships_as_its_own_file(self):
        # No hay registro anterior al que unirla. Antes que perderla, sale sola.
        grupos = group_by_record([self.vacia(1), registro(2, folio="331")], criterio=CriterioDeCorte.FOLIO).groups
        assert [g.page_numbers for g in grupos] == [[1], [2]]

    def test_every_page_is_still_accounted_for(self):
        registros = [
            registro(1, folio="331"),
            self.vacia(2),
            registro(3, folio="332"),
            self.vacia(4),
            self.vacia(5),
        ]
        group_by_record(registros, criterio=CriterioDeCorte.FOLIO).verify_integrity(total_pages=5)


class TestLaUnionEsPorElFolio:
    """Unir dos hojas depende del folio, salvo que el papel diga otra cosa (criterio FOLIO).

    Aquí hubo una segunda condición -- que las cédulas de las dos hojas no se
    contradijeran -- que el operador quitó después de verla correr: la cédula es
    manuscrita, el OCR la leía con errores, y "cédulas distintas" salía cierto
    en costuras que no lo eran. El libro volvía partido de más.

    Se volvió a proponer -- esta vez junto al folio de registro del pie, y con la
    cédula comprobada antes de compararla -- enseñándole el papel: sobre las
    dieciséis primeras caras reales del libro 7 el reparto por tinta sola da
    **ocho** archivos en vez de dieciséis, y las caras de esquina limpia traen
    nombre, cédula y número de asiento propios. **El operador lo rechazó otra
    vez**: en su archivo la unidad documental es la hoja, y la esquina limpia
    dice que esa cara es la vuelta de la anterior.

    De modo que lo que se fija aquí es que **la condición sea el folio y sólo el
    folio**, y que ningún dato leído separe dos caras. La cédula se sigue leyendo
    y sigue nombrando el archivo, con la de la cara que lo abre.
    """

    def hoja(self, pagina, marca, cedula=None, folio_registro=None):
        return DiplomaRecord(
            page_number=pagina,
            folio_mark=marca,
            identity_number=cedula,
            registered_folio=folio_registro,
        )

    def test_la_vuelta_sin_cedula_se_une_igual(self):
        """El caso corriente: el padre trae cédula y la vuelta llega en blanco."""
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]

    def test_la_vuelta_que_repite_la_cedula_se_une(self):
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE, "7882907"),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]

    def test_una_hoja_con_otra_cedula_se_une_igual(self):
        """Lo que decide es el folio, no de quién sea la cédula que lleve.

        Fija el criterio del operador para que no se revierta sin querer: aquí
        se comprobó la cédula y se cortó cuando no coincidía, dos veces, y las
        dos se deshizo.
        """
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE, "45437535"),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]

    def test_otro_folio_de_registro_al_pie_tampoco_corta(self):
        """Ni el número de asiento impreso, que es la otra señal que se propuso.

        "Registrado al folio No. 2 del libro No. 7" avanza de uno en uno por
        cara, de modo que en el libro 7 discrepa en todas las caras pares. El
        operador decidió que aun así la hoja no se parte: la unidad documental
        de su archivo es la hoja de papel.
        """
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, folio_registro="1"),
            self.hoja(2, MarcaDeFolio.AUSENTE, folio_registro="2"),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]

    def test_la_secuencia_de_hojas_se_conserva(self):
        """Folio, vuelta, folio, vuelta: dos hojas, dos documentos de dos caras.

        Es la secuencia que dictó el operador -- "la 1 tiene folio y la 2 no; la
        3 tiene folio y la 4 no" -- y es el caso corriente de estos empastes.
        """
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE, "9089958"),
            self.hoja(3, MarcaDeFolio.PRESENTE, "45437535"),
            self.hoja(4, MarcaDeFolio.AUSENTE, "73078931"),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2], [3, 4]]
        assert [grupo.code.value for grupo in grupos] == ["7882907", "45437535"]

    def test_el_documento_lleva_la_cedula_de_la_hoja_que_lo_abre(self):
        """La del primer documento, que es como lo pidió el operador.

        La hoja que abre lleva el folio escrito y es la que trae los datos del
        graduado; la que le sigue, cuando de verdad le pertenece, no cambia el
        nombre del archivo.
        """
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert [grupo.page_numbers for grupo in grupos] == [[1, 2]]
        assert grupos[0].code.value == "7882907"

    def test_el_archivo_lleva_la_cedula_y_el_tipo(self):
        """El nombre que pidió el operador: la cédula y que es un diploma.

        El tipo no se le pregunta al catálogo del archivo, que es de
        correspondencia de servicios públicos y contestaba DOCUMENTO DE
        IDENTIDAD a las 199 unidades del libro medido -- el diploma empieza por
        "LA REPUBLICA DE COLOMBIA", que es también como empieza una cédula.
        """
        registros = [
            self.hoja(1, MarcaDeFolio.PRESENTE, "7882907"),
            self.hoja(2, MarcaDeFolio.AUSENTE),
        ]
        grupos = group_by_record(registros, criterio=CriterioDeCorte.FOLIO).groups
        assert grupos[0].code.value == "7882907"
        assert grupos[0].kind == "DIPLOMA"
        assert output_filename(
            grupos[0].code, grupos[0].title, prefix=None, kind=grupos[0].kind
        ) == "7882907_DIPLOMA.pdf"
