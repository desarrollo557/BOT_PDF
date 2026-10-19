from resolutions.domain.naming import WINDOWS_PATH_LIMIT, output_filename, sheet_filename
from resolutions.domain.resolution_code import ResolutionCode

CODE = ResolutionCode.parse("N° 0412/2024")


def test_el_archivo_se_llama_por_lo_que_es_y_por_su_numero():
    """El nombre que pidió el operador: la palabra, un guion bajo y el número.

    Antes el número quedaba enterrado bajo un resumen del asunto -- "00086__por-
    medio-de-la-cual-se-anula-un-diploma-y-se-autoriza-la.pdf" -- y encontrar la
    00086 entre trescientos archivos obligaba a leer. El asunto no se pierde:
    sigue en su columna del inventario, que es donde se busca por texto.
    """
    assert output_filename(CODE, "Compra de insumos informáticos") == "RESOLUCION_0412-2024.pdf"


def test_el_asunto_no_cambia_el_nombre():
    assert output_filename(CODE, None) == output_filename(CODE, "Compra de insumos")


def test_the_slash_in_a_code_never_reaches_the_filesystem():
    assert "/" not in output_filename(CODE, "Algo")


def test_distinct_codes_never_collide():
    other = ResolutionCode.parse("0555/2024")
    assert output_filename(CODE, "Compra") != output_filename(other, "Compra")


class TestSinPrefijo:
    """Lo que no es una resolución conserva el nombre largo de siempre.

    Un libro de folios se parte en registros de diploma, y su identidad es el
    folio. Llamar "RESOLUCION_728" a uno de ellos sería escribir en el disco algo
    que no es verdad, así que esa rama pide el nombre sin prefijo.
    """

    def test_lleva_el_codigo_y_el_asunto(self):
        assert output_filename(CODE, "Compra de insumos informáticos", prefix=None) == (
            "0412-2024__compra-de-insumos-informaticos.pdf"
        )

    def test_sin_asunto_queda_el_codigo_solo(self):
        assert output_filename(CODE, None, prefix=None) == "0412-2024.pdf"
        assert output_filename(CODE, "   ", prefix=None) == "0412-2024.pdf"

    def test_un_asunto_largo_se_recorta(self):
        name = output_filename(CODE, " ".join(["palabra"] * 40), prefix=None)
        assert len(name) < 120
        assert name.endswith(".pdf")


class TestElNombreNoSeRepite:
    def test_un_diploma_archivado_por_el_nombre_no_lo_dice_dos_veces(self):
        codigo = ResolutionCode(value="MARTHA MARIA SOLANO VARGAS", raw="MARTHA MARIA SOLANO VARGAS")
        nombre = output_filename(
            codigo,
            "MARTHA MARIA SOLANO VARGAS - DOCTOR EN DERECHO",
            prefix=None,
            con_titulo=True,
            mayusculas=True,
            kind="DIPLOMA",
        )
        assert nombre == "MARTHA-MARIA-SOLANO-VARGAS_DOCTOR-EN-DERECHO_DIPLOMA.pdf"

    def test_por_la_cedula_el_nombre_sigue_en_el_titulo(self):
        codigo = ResolutionCode(value="1020743211", raw="1020743211")
        nombre = output_filename(
            codigo, "DIANA GIL - ESPECIALISTA", prefix=None, con_titulo=True, mayusculas=True, kind="DIPLOMA"
        )
        assert nombre == "1020743211_DIANA-GIL-ESPECIALISTA_DIPLOMA.pdf"


class TestNombreDeLaPlanilla:
    """El acta que acompaña a un documento, sin pasarse del límite de Windows.

    MAX_PATH no recorta el nombre: hace fallar el guardado, y con él se pierde
    todo el trabajo de leer el documento. Estas pruebas fijan que el sufijo
    sobreviva siempre -- es lo que encuentra el endpoint de descarga -- y que lo
    que se sacrifique sea el nombre.
    """

    def test_usa_el_nombre_del_documento_sin_su_extension(self):
        assert sheet_filename("acta 2013.pdf", "__FUID.xlsx") == "acta 2013__FUID.xlsx"

    def test_sin_la_carpeta_de_la_que_vino_el_documento(self):
        """Con la barra dentro, el FUID se guardaba en una subcarpeta que no existe."""
        nombre = sheet_filename("00C003269\\1. 3858079 REGISTRO.pdf", "__FUID.xlsx")
        assert nombre == "1. 3858079 REGISTRO__FUID.xlsx"
        assert sheet_filename("caja/UPD1.pdf", "__inventario.xlsx") == "UPD1__inventario.xlsx"

    def test_respeta_un_nombre_que_cabe(self):
        nombre = sheet_filename("libro 8", "__FUID.xlsx", directory_length=60)
        assert nombre == "libro 8__FUID.xlsx"

    def test_recorta_el_nombre_cuando_la_ruta_no_da(self):
        largo = "6.3858084 REGISTRO DE DIPLOMAS N08 2012-2013 (30 paginas).pdf"
        nombre = sheet_filename(largo, "__FUID.xlsx", directory_length=200)
        assert nombre.endswith("__FUID.xlsx")
        assert len(nombre) + 200 + 1 <= WINDOWS_PATH_LIMIT

    def test_el_sufijo_no_se_toca_ni_en_el_peor_caso(self):
        nombre = sheet_filename("cualquiera.pdf", "__FUID.xlsx", directory_length=250)
        assert nombre == "inventario__FUID.xlsx"

    def test_un_nombre_vacio_no_produce_un_archivo_sin_nombre(self):
        assert sheet_filename("   ", "__FUID.xlsx") == "inventario__FUID.xlsx"

    def test_no_deja_el_recorte_terminado_en_puntuacion(self):
        nombre = sheet_filename("informe final - anexo.pdf", "__x.xlsx", directory_length=228)
        assert not nombre.replace("__x.xlsx", "").endswith((" ", "-", "."))
