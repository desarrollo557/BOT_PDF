"""Ningún documento debería salir sin cédula y sin nombre.

Lo pidió el operador después de ver una carpeta entera de archivos llamados
`001_DIPLOMA.pdf`, `002_DIPLOMA.pdf`, con el inventario en N/A: «ningún
documento debería [quedar] sin nombre, y tampoco sin cédula».

No siempre se puede cumplir, y conviene decirlo con el papel delante: el libro
de posgrados `3858080` es de los años setenta y su fórmula —«en atención a que
el Señor [nombre] ha completado todos los Estudios Clásicos»— **no lleva cédula
en ninguna parte**. Ahí el nombre es la identidad, y sólo aparece leyendo con
ayuda de pago porque está manuscrito.

De modo que lo que se fija aquí son las tres cosas que sí están en nuestra mano:

1. que la cédula, cuando falta, deje paso al nombre y no al consecutivo;
2. que un título que no nombra ninguna especialidad no pase por título;
3. que lo que aun así quede sin identidad se **cuente y se declare**, para que
   el operador pueda decidir si vuelve a pasar ese libro con IA.
"""

from resolutions.application.diploma_split import group_by_record
from resolutions.application.read_diploma_book import ReadDiplomaBook
from resolutions.domain.diploma import (
    CriterioDeCorte,
    DiplomaRecord,
    extract_diploma,
    lines_from_text,
)
from resolutions.domain.folio_manuscrito import MarcaDeFolio
from resolutions.domain.naming import output_filename
from resolutions.domain.validation import validate_diplomas

#: Estas pruebas describen un libro foliado hoja a hoja -- las impares abren y
#: las pares son su vuelta --, así que se cortan por folio. Con el criterio por
#: omisión, que es cara a cara, no hay vueltas y cada página cuenta.
POR_FOLIO = CriterioDeCorte.FOLIO


def archivo(record):
    grupo = group_by_record([record]).groups[0]
    return output_filename(grupo.code, grupo.title, prefix=None, kind=grupo.kind)


class TestLaCedulaDejaPasoAlNombre:
    """Entre `001_DIPLOMA.pdf` y `manuel-ruiz-yepes_DIPLOMA.pdf` no hay color.

    Los dos nombres salen del mismo libro sin cédulas. Al segundo lo encuentra
    quien busque a esa persona; al primero no lo encuentra nadie.
    """

    def test_sin_cedula_manda_el_nombre(self):
        record = DiplomaRecord(
            page_number=1,
            name="MANUEL RUIZ YEPES",
            folio_mark=MarcaDeFolio.PRESENTE,
        )
        assert archivo(record) == "manuel-ruiz-yepes_DIPLOMA.pdf"

    def test_con_cedula_sigue_mandando_la_cedula(self):
        """Es única, y un nombre no. Dos homónimos existen."""
        record = DiplomaRecord(
            page_number=1,
            identity_number="1047375454",
            name="MANUEL RUIZ YEPES",
            folio_mark=MarcaDeFolio.PRESENTE,
        )
        assert archivo(record) == "1047375454_DIPLOMA.pdf"

    def test_sin_ninguno_de_los_dos_queda_el_orden(self):
        record = DiplomaRecord(page_number=1, folio_mark=MarcaDeFolio.PRESENTE)
        assert archivo(record) == "001_DIPLOMA.pdf"


class TestUnTituloTieneQueNombrarUnaEspecialidad:
    """"DOCTOR EN //" no es un título: es la fórmula impresa y nada más.

    Es traicionero porque no parece un hueco. La fórmula está impresa y el OCR
    la lee perfectamente, así que llega con aspecto de dato leído; lo que falta
    es justamente lo único que importaba, que va manuscrito detrás. Medido sobre
    el libro de posgrados `3858080`, la mayoría de sus 224 unidades se archivó
    bajo "DOCTOR EN //", "DOCTOR EN )" o "DOCTOR EN ^".
    """

    def titulo(self, texto):
        return extract_diploma(lines_from_text(texto), 1).degree

    def test_la_formula_sola_no_pasa(self):
        for basura in ("//", ")", "^", "T", "y7iji'dc..y'zA^ t!"):
            assert self.titulo(f"DOCTOR EN {basura}") is None, basura

    def test_pero_con_su_especialidad_si(self):
        assert self.titulo("DOCTOR EN MEDICINA Y CIRUGIA") == "DOCTOR EN MEDICINA Y CIRUGIA"

    def test_y_llega_en_un_solo_renglon(self):
        """La fórmula y lo manuscrito están en renglones distintos del papel.

        Sin juntarlos, el título llega con un salto de línea dentro y parte en
        dos la fila del FUID.
        """
        assert self.titulo("DOCTOR EN\nMedicina y Cirugia") == "DOCTOR EN Medicina y Cirugia"

    def test_los_titulos_rotulados_no_cambian(self):
        assert self.titulo("Titulo recibido: ESPECIALISTA EN GERENCIA EN SALUD") == (
            "ESPECIALISTA EN GERENCIA EN SALUD"
        )


class TestLoQueQuedaSinIdentidadSeDeclara:
    """No se puede impedir siempre, pero sí se puede contar.

    Es la diferencia entre una entrega revisable y una que hay que creerse: el
    operador mira el número, ve que su libro salió entero sin identidad y sabe
    que tiene que volver a pasarlo con ayuda de pago.
    """

    class FuenteMuda:
        """Un libro cuya capa de texto no dice nada, como un escaneo crudo."""

        def __init__(self, caras: int) -> None:
            self._caras = caras

        @property
        def page_count(self) -> int:
            return self._caras

        def lines_of(self, page_number):
            return []

        def render(self, page_number, band=None, dpi=200) -> bytes:
            return b""

        def ink_of(self, page_number, band):
            return (0.09, 0.0) if page_number % 2 else (0.0, 0.0)

    def test_se_cuentan_las_unidades_sin_cedula_y_sin_nombre(self):
        _, stats = ReadDiplomaBook(ocr=None, criterio=POR_FOLIO).execute(self.FuenteMuda(6))
        # Tres caras abren documento -- las impares, que llevan folio -- y las
        # tres se quedan sin nada con que nombrarse.
        assert stats.sin_identidad == [1, 3, 5]

    def test_y_viajan_al_informe(self):
        _, stats = ReadDiplomaBook(ocr=None, criterio=POR_FOLIO).execute(self.FuenteMuda(4))
        assert stats.as_dict()["sin_identidad"] == [1, 3]

    def test_las_vueltas_no_cuentan(self):
        """Una vuelta no es una unidad documental: sus datos son los de la cara
        que la abre, y pedirle identidad propia inflaría la cuenta al doble."""
        _, stats = ReadDiplomaBook(ocr=None, criterio=POR_FOLIO).execute(self.FuenteMuda(6))
        assert 2 not in stats.sin_identidad
        assert 4 not in stats.sin_identidad

    def test_la_validacion_lo_dice_con_su_pagina(self):
        issues = validate_diplomas(
            [DiplomaRecord(page_number=7, folio_mark=MarcaDeFolio.PRESENTE)]
        )
        identidad = [issue for issue in issues if issue.field == "identidad"]
        assert len(identidad) == 1
        assert identidad[0].page_number == 7
        assert "sin cédula y sin nombre" in identidad[0].reason

    def test_un_documento_con_nombre_no_se_declara(self):
        issues = validate_diplomas(
            [
                DiplomaRecord(
                    page_number=7,
                    name="MANUEL RUIZ YEPES",
                    folio_mark=MarcaDeFolio.PRESENTE,
                )
            ]
        )
        assert [issue for issue in issues if issue.field == "identidad"] == []
