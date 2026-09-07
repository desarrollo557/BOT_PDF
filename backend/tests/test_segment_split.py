"""Del corte a los archivos: cómo se llama cada documento de una caja.

La segmentación ya decidió dónde termina un papel y empieza el siguiente. Falta
lo mismo que resuelven los otros partidores: cómo se llama cada archivo. Con una
diferencia -- aquí no hay número que leer. Una caja de correspondencia no trae
folio ni resolución, así que lo único cierto sobre un documento recién cortado es
el puesto que ocupa en la caja y de qué páginas del origen salió.

Nombrar por el puesto no es una respuesta provisional a la espera de la
clasificación: es lo que permite mirar los PDF de una vez, que es lo que hace
falta para saber si los cortes están bien.
"""

from resolutions.application.segment_split import group_by_segment
from resolutions.domain.naming import DOCUMENT_PREFIX, output_filename
from resolutions.domain.segmentation import Segment


def segmento(*paginas: int, reason: str = "inicio") -> Segment:
    return Segment(page_numbers=list(paginas), reason=reason)


class TestUnGrupoPorSegmento:
    def test_cada_segmento_produce_su_grupo(self):
        resultado = group_by_segment([segmento(1, 2), segmento(3), segmento(4, 5, 6)])
        assert [grupo.page_numbers for grupo in resultado.groups] == [
            [1, 2],
            [3],
            [4, 5, 6],
        ]

    def test_una_caja_vacia_no_produce_nada(self):
        assert group_by_segment([]).groups == []

    def test_nada_va_a_cuarentena(self):
        """No existe la página huérfana: la segmentación cubre la caja entera."""
        assert group_by_segment([segmento(1)]).quarantine == []

    def test_el_cuadre_de_paginas_se_sostiene(self):
        group_by_segment([segmento(1, 2), segmento(3)]).verify_integrity(total_pages=3)

    def test_un_segmento_sin_paginas_no_produce_archivo(self):
        """Un grupo vacío escribiría un PDF sin hojas, que no es un documento.

        ``assemble`` no los produce, pero el escritor no tiene cómo defenderse de
        uno si llega, y un archivo vacío en la entrega parece una página perdida.
        """
        resultado = group_by_segment([segmento(1), segmento()])
        assert [grupo.page_numbers for grupo in resultado.groups] == [[1]]

    def test_el_segmento_vacio_tampoco_gasta_un_numero(self):
        resultado = group_by_segment([segmento(), segmento(1)])
        assert [grupo.code.value for grupo in resultado.groups] == ["01"]


class TestElNombre:
    def test_numera_desde_uno_en_el_orden_de_la_caja(self):
        resultado = group_by_segment([segmento(1), segmento(2), segmento(3)])
        assert [grupo.code.value for grupo in resultado.groups] == ["01", "02", "03"]

    def test_dos_documentos_nunca_comparten_nombre(self):
        resultado = group_by_segment([segmento(n) for n in range(1, 6)])
        nombres = {grupo.code.value for grupo in resultado.groups}
        assert len(nombres) == 5

    def test_una_caja_de_cien_documentos_usa_tres_digitos(self):
        """El relleno sigue al total para que el listado ordene como la caja.

        Con dos dígitos, "100" se ordenaría delante de "99" y el operador vería
        la caja desordenada justo cuando más archivos tiene que revisar.
        """
        resultado = group_by_segment([segmento(n) for n in range(1, 101)])
        codigos = [grupo.code.value for grupo in resultado.groups]
        assert codigos[0] == "001"
        assert codigos[-1] == "100"
        assert codigos == sorted(codigos)

    def test_el_archivo_se_llama_por_lo_que_es_y_por_su_puesto(self):
        grupo = group_by_segment([segmento(1, 2)]).groups[0]
        nombre = output_filename(grupo.code, grupo.title, prefix=DOCUMENT_PREFIX)
        assert nombre == "DOCUMENTO_01.pdf"


class TestElAsunto:
    def test_dice_de_que_paginas_del_origen_salio(self):
        """Lo único que se sabe del documento antes de clasificarlo, y es un hecho."""
        grupo = group_by_segment([segmento(4, 5, 6)]).groups[0]
        assert grupo.title == "páginas 4-6"

    def test_un_documento_de_una_hoja_lo_dice_en_singular(self):
        grupo = group_by_segment([segmento(7)]).groups[0]
        assert grupo.title == "página 7"
