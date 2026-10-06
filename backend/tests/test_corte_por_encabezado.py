"""Cortar por el membrete impreso, sin pagarle una página a nadie.

Los libros de registro mecanografiados -- los de 2011 en adelante -- no se
parecen en nada a los manuscritos de 1982. Cada diploma ocupa su propia cara,
el formulario va impreso encima y el PDF **ya trae capa de texto**: medido sobre
los libros 8 de 2013 y de 2012-2013, las primeras dieciséis caras de cada uno
traen membrete, nombre, cédula, título, fecha y folio, todo leído sin una sola
petición a ningún proveedor.

De ahí este criterio: la señal que reparte el libro está **impresa**, así que la
lee el motor de casa y la IA no hace falta. Y no se pide: pedirla sería pagar
por leer lo que ya estaba leído.
"""

from resolutions.application.diploma_split import group_by_record
from resolutions.domain.diploma import (
    CriterioDeCorte,
    DiplomaRecord,
    abre_formulario,
    extract_diploma,
    lines_from_text,
)

POR_ENCABEZADO = CriterioDeCorte.ENCABEZADO

#: Una cara del libro 8 tal como la devuelve su capa de texto, erratas incluidas.
CARA = """UMiVERSSDAD DE CARTAGENA
LIBRO DE REGISTRO DE DIPLOlVlAS DE POSTGRADOS
LA REPUBLICA DE COLOMBIA, Ministerio de Educación Macional
por intermedio de la UNIVERSiDAD DE CARTAGENA
Folio 728
ANGELICA MARIA CUELLO SALCEDO
Nombres y apellidos del graduando
identificado con CC. No. 1047375454
expedida en CARTAGENA
Titulo recibido: ESPECIALISTA EN GERENCIA EN SALUD
Fecha de graduación: 21/06/2013"""


def cara(pagina, texto=CARA):
    return extract_diploma(lines_from_text(texto), pagina)


def hoja(pagina, membrete=False, nombre=None):
    """Una cara armada a mano, para aislar cada señal."""
    return DiplomaRecord(page_number=pagina, encabezado=membrete, name=nombre)


def paginas(grupos):
    return [grupo.page_numbers for grupo in grupos]


class TestReconocerElMembrete:
    """La cabecera llega con erratas, así que se compara con holgura."""

    def test_se_reconoce_tal_como_lo_devuelve_el_escaner(self):
        """"UMiVERSSDAD DE CARTAGENA", literal del libro 8 de 2013."""
        assert abre_formulario(lines_from_text(CARA))

    def test_y_con_la_otra_errata_del_mismo_libro(self):
        assert abre_formulario(lines_from_text("UNiVERSiDAD DE CARTAGEMA\nFolio 730"))

    def test_una_cara_sin_membrete_no_lo_inventa(self):
        texto = "Folio 729\nJUAN PEREZ GOMEZ\nNombres y apellidos del graduando"
        assert not abre_formulario(lines_from_text(texto))

    def test_la_formula_del_cuerpo_no_cuenta_como_membrete(self):
        """El renglón "por intermedio de la UNIVERSIDAD DE CARTAGENA" va a media
        hoja. Contarlo haría que toda cara abriera documento y el criterio no
        diría nada."""
        cuerpo = "\n".join(
            ["Folio 729", "JUAN PEREZ GOMEZ"]
            + [f"renglón de relleno {n}" for n in range(8)]
            + ["por intermedio de la UNIVERSIDAD DE CARTAGENA"]
        )
        assert not abre_formulario(lines_from_text(cuerpo))


class TestUnaCaraDelLibroSeLeeEntera:
    """Lo que el criterio necesita sale de la capa de texto, y sale limpio."""

    def test_trae_membrete_nombre_cedula_titulo_y_fecha(self):
        registro = cara(1)
        assert registro.encabezado
        assert registro.name == "ANGELICA MARIA CUELLO SALCEDO"
        assert registro.identity_number == "1047375454"
        assert registro.identity_creible
        assert registro.folio == "728"
        assert registro.degree == "ESPECIALISTA EN GERENCIA EN SALUD"
        assert registro.graduation_date == "21/06/2013"


class TestElMembreteAbreDocumento:
    def test_cada_cara_con_membrete_es_un_diploma(self):
        libro = [hoja(n, membrete=True, nombre=f"GRADUADO NUMERO {n}") for n in range(1, 5)]
        assert paginas(group_by_record(libro, POR_ENCABEZADO).groups) == [[1], [2], [3], [4]]

    def test_una_cara_sin_membrete_ni_nombre_se_une(self):
        """El anexo que el archivo intercala: una fotocopia, un acta suelta."""
        libro = [
            hoja(1, membrete=True, nombre="ANGELICA CUELLO SALCEDO"),
            hoja(2),
            hoja(3),
        ]
        assert paginas(group_by_record(libro, POR_ENCABEZADO).groups) == [[1, 2, 3]]

    def test_otro_nombre_abre_aunque_falte_el_membrete(self):
        """La señal que salva las caras mal escaneadas, que es para lo que está.

        Si el escáner se comió la cabecera pero el nombre se leyó y es otro, eso
        ya prueba que es otro diploma.
        """
        libro = [
            hoja(1, membrete=True, nombre="ANGELICA CUELLO SALCEDO"),
            hoja(2, membrete=False, nombre="CATALINA GIL RODRIGUEZ"),
        ]
        assert paginas(group_by_record(libro, POR_ENCABEZADO).groups) == [[1], [2]]

    def test_el_mismo_nombre_sin_membrete_se_queda(self):
        """Dos caras del mismo graduando: la segunda continúa a la primera."""
        libro = [
            hoja(1, membrete=True, nombre="ANGELICA CUELLO SALCEDO"),
            hoja(2, membrete=False, nombre="ANGELICA CUELLO SALCEDO"),
        ]
        assert paginas(group_by_record(libro, POR_ENCABEZADO).groups) == [[1, 2]]


class TestEsteCriterioNoPagaNunca:
    """Y eso es parte de lo que es, no un detalle de implementación.

    La señal que usa está impresa. Si el motor de casa no la ve, tampoco la
    arregla la IA: lo que hay que hacer entonces es mirar la hoja. Pedirla
    sería gastar por costumbre.
    """

    def test_lo_declara(self):
        assert not CriterioDeCorte.ENCABEZADO.paga_lectura

    def test_y_los_otros_tres_si_pueden(self):
        assert CriterioDeCorte.FOLIO.paga_lectura
        assert CriterioDeCorte.CEDULA.paga_lectura
        assert CriterioDeCorte.NOMBRE_Y_CEDULA.paga_lectura

    def test_llega_por_la_api_con_su_nombre(self):
        assert CriterioDeCorte.parse("encabezado") is POR_ENCABEZADO

    def test_y_la_pantalla_dice_que_es_solo_ocr(self):
        assert "OCR" in POR_ENCABEZADO.label
