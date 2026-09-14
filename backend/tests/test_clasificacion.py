"""El tipo documental, con las mismas reglas para todas las rutas.

El orden de las fuentes lo fijó el operador y es el de lo más directo primero:
el asunto, el encabezado, una mención del cuerpo, y el contexto sólo cuando la
hoja no dice nada de sí misma.

Vive en la aplicación y no dentro del partidor de cajas porque la pregunta es
la misma se haya cortado como se haya cortado. Una resolución, un folio de
diplomas, un expediente de matrícula y un documento de una caja revuelta son
cuatro unidades delimitadas de cuatro maneras distintas, y las cuatro son un
papel del que el archivo quiere saber qué es.
"""

from __future__ import annotations

from resolutions.application.clasificacion import MAX_HOJAS_HEREDADAS, clasificar
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode

FIRMA = "MAYDA GOMEZ CABALLERO\nCOORDINADORA CENTRAL DE ESCRITOS"


def grupo(code: str, pages: list[int]) -> PageGroup:
    return PageGroup(code=ResolutionCode(value=code, raw=code), page_numbers=list(pages))


def fuente(textos: dict[int, str]):
    def texto_de(page_number: int) -> str:
        return textos.get(page_number, "")

    return texto_de


class TestElOrdenDeLasFuentes:
    def test_el_asunto_va_primero(self):
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1])]),
            fuente({1: "Asunto: Notificación por aviso\ncuerpo del oficio"}),
        )
        assert resultado.groups[0].kind == "NOTIFICACION POR AVISO"

    def test_sin_asunto_manda_el_encabezado(self):
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1])]),
            fuente({1: "ACTA DE IRREGULARIDAD\ncuerpo del acta sin asunto"}),
        )
        assert resultado.groups[0].kind == "ACTA DE IRREGULARIDAD"

    def test_sin_ninguno_de_los_dos_vale_una_mencion(self):
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1])]),
            fuente(
                {
                    1: "En atencion a lo anterior se adjunta el certificado de "
                    "tradicion y libertad del inmueble objeto de la revision"
                }
            ),
        )
        assert resultado.groups[0].kind == "CERTIFICADO DE TRADICION"


class TestElContextoNombraLoQueNoDiceNada:
    """La cuarta fuente, y la pidió el operador.

    Las hojas que sólo llevan una firma -- "MAYDA GOMEZ CABALLERO,
    COORDINADORA CENTRAL DE ESCRITOS" y nada más -- son la última cara del
    escrito que las precede, y en la carpeta se leen mejor con el nombre de
    aquél que con uno genérico.
    """

    def test_una_hoja_muda_hereda_del_documento_anterior(self):
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1]), grupo("02", [2])]),
            fuente({1: "Asunto: Notificación por aviso\ncuerpo", 2: FIRMA}),
        )
        assert [g.kind for g in resultado.groups] == [
            "NOTIFICACION POR AVISO",
            "NOTIFICACION POR AVISO",
        ]

    def test_pero_no_hereda_un_documento_largo(self):
        """Heredar es suponer, y sólo se supone de lo que tiene forma de cola.

        Varias hojas seguidas que no dicen nada de sí mismas ya no son el final
        de nada: son un documento del que no se sabe qué es, y llamarlo como su
        vecino sería inventarlo.
        """
        largo = list(range(2, 2 + MAX_HOJAS_HEREDADAS + 1))
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1]), grupo("02", largo)]),
            fuente({1: "Asunto: Notificación por aviso\ncuerpo"}),
        )
        assert resultado.groups[1].kind is None

    def test_la_primera_unidad_no_tiene_de_quien_heredar(self):
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1])]), fuente({1: FIRMA})
        )
        assert resultado.groups[0].kind is None

    def test_hereda_del_ultimo_que_dijo_algo_y_no_del_heredado(self):
        """Tres seguidas: una que habla y dos mudas. Las dos heredan de aquélla."""
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1]), grupo("02", [2]), grupo("03", [3])]),
            fuente({1: "ACTA DE IRREGULARIDAD\ncuerpo del acta", 2: FIRMA, 3: FIRMA}),
        )
        assert [g.kind for g in resultado.groups] == ["ACTA DE IRREGULARIDAD"] * 3

    def test_se_puede_apagar_la_herencia(self):
        """Un libro de folios es cien veces el mismo papel: heredar ahí sólo
        taparía los folios que no se dejaron leer."""
        resultado = clasificar(
            GroupingResult(groups=[grupo("01", [1]), grupo("02", [2])]),
            fuente({1: "Asunto: Notificación por aviso\ncuerpo", 2: FIRMA}),
            heredar=False,
        )
        assert resultado.groups[1].kind is None


class TestLoQueNoSeToca:
    def test_un_tipo_ya_puesto_se_respeta(self):
        """Quien ya sabía qué es no vuelve a preguntarlo."""
        puesto = PageGroup(
            code=ResolutionCode(value="01", raw="01"),
            page_numbers=[1],
            kind="PAGARE",
        )
        resultado = clasificar(
            GroupingResult(groups=[puesto]),
            fuente({1: "Asunto: Notificación por aviso"}),
        )
        assert resultado.groups[0].kind == "PAGARE"

    def test_sin_fuente_de_texto_no_se_inventa_nada(self):
        original = GroupingResult(groups=[grupo("01", [1])])
        assert clasificar(original, None) is original

    def test_una_pagina_que_no_se_deja_leer_cuesta_el_tipo_y_no_el_documento(self):
        def revienta(_page_number: int) -> str:
            raise OSError("la página está rota")

        resultado = clasificar(GroupingResult(groups=[grupo("01", [1])]), revienta)
        assert resultado.groups[0].kind is None

    def test_la_agrupacion_original_no_se_modifica(self):
        """`PageGroup` es inmutable, y serlo impide que una clasificación
        tardía cambie por debajo lo que el escritor ya usó para nombrar."""
        original = GroupingResult(groups=[grupo("01", [1])])
        clasificar(original, fuente({1: "ACTA DE IRREGULARIDAD\ncuerpo"}))
        assert original.groups[0].kind is None
