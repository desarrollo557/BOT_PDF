"""Diez nombres por página facturada, sin mezclar ninguno.

El OCR de pago cobra por **página procesada**, no por petición. Esa distinción
decide lo que cuesta un libro manuscrito y cuesta trabajo verla: agrupar páginas
en un PDF baja las llamadas de cuatrocientas a veinte y no ahorra un céntimo,
porque el proveedor sigue contando cuatrocientas páginas.

Lo que sí ahorra es mandar menos papel por página facturada. De una cara de
diploma, para nombrar el archivo basta la franja donde está escrito el nombre:
un ocho por ciento de la hoja. Diez apiladas son una página procesada. Medido
sobre el libro de posgrados `3858080` -- manuscrito, de los años setenta, sin
una sola cédula en el papel --: dieciséis caras leídas por dos páginas
facturadas y los dieciséis nombres correctos.

Lo que más importa probar aquí es lo que puede salir mal de forma invisible:
**que un nombre acabe en la página de al lado**. Un nombre que falta se ve -- el
archivo se llama por su folio y la unidad queda declarada en revisión --,
mientras que un nombre corrido no se ve nunca: el archivo parece correcto y
lleva el nombre de otro graduado.
"""

from resolutions.adapters.mosaico_de_nombres import MosaicoDeNombres, _repartir
from resolutions.application.ports import Band, LineBox

#: Lo que el proveedor devuelve de un mosaico de tres franjas del libro real.
TRES_FRANJAS = """en atención a que el Señor

Gustavo Enrique Nunez Hernandez.

ha completado todos los Estudios Clásicos que los Estatutos Universitarios

en atención a que el Señor

Guillermo Alejandro Murino Ono

ha completado todos los Estudios Clásicos que los Estatutos Universitarios

en atención a que el Señor

Concepcion Gunda Bustillo

ha completado todos los Estudios Clásicos que los Estatutos Universitarios"""


class FuenteFalsa:
    """Un libro cuyas caras dicen dónde está su leyenda, o no la dicen."""

    def __init__(self, alturas: dict[int, float]):
        self._alturas = alturas
        self.recortes: list[tuple[int, Band]] = []

    def boxes_of(self, page_number: int) -> list[LineBox]:
        altura = self._alturas.get(page_number)
        if altura is None:
            return [LineBox(text="una línea cualquiera", center_x=0.5, top=0.5)]
        return [LineBox(text="en atención a que el Señor", center_x=0.5, top=altura)]

    def render(self, page_number, band=None, dpi=200) -> bytes:
        self.recortes.append((page_number, band))
        # Un PNG de un pixel: basta para que PyMuPDF lo componga.
        import pymupdf

        return pymupdf.Pixmap(pymupdf.csGRAY, 40, 12, b"\xff" * 480, False).tobytes("png")


class TestNingunNombreAcabaEnLaPaginaDeAlLado:
    """La leyenda impresa es la tijera, y de ahí sale la alineación.

    El peligro de este reparto es un error que no se ve: si una franja no suelta
    su nombre y las de abajo se corren una posición, cada archivo sale con el
    nombre del graduado siguiente y nada lo delata.

    La primera versión se defendía contando: si no volvían tantos nombres como
    franjas, no se repartía ninguno. Era seguro y **no servía**, porque casi
    nunca cuadra -- sobre una corrida real del libro de posgrados: once nombres
    para diez franjas, nueve para diez, cero para diez --, así que el ahorro no
    llegaba nunca. Lo que alinea de verdad es la leyenda, que va impresa y el
    OCR lee sin fallar.
    """

    def test_cuando_vuelven_todos_se_reparten_en_orden(self):
        assert _repartir(TRES_FRANJAS, [5, 7, 9]) == {
            5: "Gustavo Enrique Nunez Hernandez",
            7: "Guillermo Alejandro Murino Ono",
            9: "Concepcion Gunda Bustillo",
        }

    def test_una_franja_ilegible_no_arrastra_a_las_demas(self):
        """Lo importante, y lo que la cuenta no sabía hacer.

        La franja de en medio no soltó su nombre. Su cara se queda sin él -- se
        archivará por su folio y quedará declarada en revisión -- y las otras dos
        siguen en su sitio, porque el trozo existe aunque esté vacío.
        """
        sin_el_de_en_medio = TRES_FRANJAS.replace("Guillermo Alejandro Murino Ono\n", "")
        assert _repartir(sin_el_de_en_medio, [5, 7, 9]) == {
            5: "Gustavo Enrique Nunez Hernandez",
            9: "Concepcion Gunda Bustillo",
        }

    def test_un_renglon_de_mas_dentro_de_una_franja_no_descuadra(self):
        """Pasa cuando una firma larga se lee como dos renglones: del trozo se
        toma el primero que pueda ser una persona y el resto sobra."""
        con_ruido = TRES_FRANJAS.replace(
            "Concepcion Gunda Bustillo", "Concepcion Gunda Bustillo\nAlma Maria Bustamante"
        )
        assert _repartir(con_ruido, [5, 7, 9])[9] == "Concepcion Gunda Bustillo"

    def test_si_falta_una_leyenda_no_se_reparte_nada(self):
        """Sin un trozo por franja no hay forma de saber cuál es cuál."""
        sin_leyenda = TRES_FRANJAS.replace("en atención a que el Señor\n\n", "", 1)
        assert _repartir(sin_leyenda, [5, 7, 9]) == {}

    def test_un_mosaico_vacio_no_inventa_nada(self):
        assert _repartir("", [5, 7]) == {}

    def test_una_franja_con_solo_formulario_se_queda_sin_nombre(self):
        solo_formulario = "en atención a que el Señor\nha completado todos los Estudios"
        assert _repartir(solo_formulario, [5]) == {}


class TestDondeSeRecorta:
    """La franja sale de lo que dice el papel, no de una constante escrita aquí."""

    def test_cada_cara_que_lo_dice_marca_su_propia_altura(self):
        fuente = FuenteFalsa({1: 0.30, 3: 0.50})
        bandas = MosaicoDeNombres(leer=lambda _: "")._bandas(fuente, [1, 3])
        assert bandas[1].y0 < bandas[3].y0

    def test_la_que_no_lo_dice_hereda_la_mediana_de_las_que_si(self):
        """Estos libros son cien veces el mismo formulario: el renglón del
        nombre está siempre a la misma altura, y se deduce de este libro en vez
        de darlo por sabido."""
        fuente = FuenteFalsa({1: 0.30, 3: 0.30, 5: None})
        bandas = MosaicoDeNombres(leer=lambda _: "")._bandas(fuente, [1, 3, 5])
        assert bandas[5].y0 == bandas[1].y0

    def test_si_ninguna_lo_dice_no_se_inventa_una_altura(self):
        fuente = FuenteFalsa({})
        assert MosaicoDeNombres(leer=lambda _: "")._bandas(fuente, [1, 3]) == {}

    def test_y_entonces_no_hay_mosaico(self):
        fuente = FuenteFalsa({})
        assert MosaicoDeNombres(leer=lambda _: TRES_FRANJAS).nombres(fuente, [1, 3]) == {}
        assert fuente.recortes == [], "no se rasteriza ni una franja"


class TestElAhorroEsReal:
    def test_diez_caras_son_una_sola_lectura(self):
        """Es de donde sale el factor diez: una imagen, una página facturada."""
        lecturas = []
        fuente = FuenteFalsa({n: 0.30 for n in range(1, 21)})
        mosaico = MosaicoDeNombres(leer=lambda imagen: lecturas.append(imagen) or "")
        mosaico.nombres(fuente, list(range(1, 21)))
        assert len(lecturas) == 2, "veinte caras en dos mosaicos de diez"

    def test_se_recorta_una_franja_y_no_la_hoja(self):
        fuente = FuenteFalsa({1: 0.30})
        MosaicoDeNombres(leer=lambda _: "").nombres(fuente, [1])
        _, banda = fuente.recortes[0]
        assert banda.y1 - banda.y0 < 0.12, "una franja, no media página"
        assert banda.y0 < 0.30 < banda.y1, "que rodea al renglón del nombre"

    def test_una_lectura_que_falla_no_tumba_el_libro(self):
        def revienta(_imagen):
            raise RuntimeError("el proveedor se cayó")

        fuente = FuenteFalsa({n: 0.30 for n in (1, 3)})
        assert MosaicoDeNombres(leer=revienta).nombres(fuente, [1, 3]) == {}

    def test_los_mosaicos_se_leen_varios_a_la_vez(self):
        """Leer es esperar: cuarenta mosaicos en fila eran cuarenta esperas."""
        import threading
        import time

        candado = threading.Lock()
        vuelo = {"ahora": 0, "maximo": 0}

        def leer(_imagen):
            with candado:
                vuelo["ahora"] += 1
                vuelo["maximo"] = max(vuelo["maximo"], vuelo["ahora"])
            try:
                time.sleep(0.05)
                return ""
            finally:
                with candado:
                    vuelo["ahora"] -= 1

        fuente = FuenteFalsa({n: 0.30 for n in range(1, 41)})
        MosaicoDeNombres(leer=leer, lectores=4).nombres(fuente, list(range(1, 41)))

        assert vuelo["maximo"] >= 2, "hubo mosaicos viajando a la vez"


class TestElProveedorContestaComoQuiere:
    """Unas veces en prosa y otras como tabla con la etiqueta en la primera
    columna; las dos formas tienen que repartir bien."""

    def test_una_tabla_con_la_etiqueta_pegada_reparte_por_la_etiqueta(self):
        tabla = (
            "| [105] | en atención a que el Señor Carmen E. Hoyo Campillo |\n"
            "| --- | --- |\n"
            "| [350] | Jairó Guillermo López Bedoya |"
        )
        assert _repartir(tabla, [105, 350]) == {
            105: "Carmen E. Hoyo Campillo",
            350: "Jairó Guillermo López Bedoya",
        }

    def test_las_etiquetas_sueltas_en_un_bloque_no_confunden(self):
        """Es lo otro que hace: la columna de etiquetas aparte, y después las
        franjas en orden. Se reparte por la leyenda, como siempre."""
        bloque = (
            "[105]\n[149]\n\nen atención a que el Señor\n\nCarmen E. Hoyo Campillo\n\n"
            "en atención a que el Señor\n\nSantiago López Juarez"
        )
        assert _repartir(bloque, [105, 149]) == {
            105: "Carmen E. Hoyo Campillo",
            149: "Santiago López Juarez",
        }


class TestElMosaicoDeCedulas:
    """Diez de diez sobre el libro 7, donde la página entera daba siete de doce."""

    def test_reparte_por_etiqueta_y_solo_lo_que_se_sostiene(self):
        from resolutions.adapters.mosaico_de_nombres import _repartir_cedulas

        tabla = (
            "|  [98] | C.C. No. 7.454.012 Expedida en Barranquilla ha completado |\n"
            "| --- | --- |\n"
            "|  [99] | C.C. No. 9.081624 Expedida en Cartagena ha completado |\n"
            "|  [108] | C.C. No. 4V.425.748 Expedida en Ogeza ha completado |"
        )
        assert _repartir_cedulas(tabla, [98, 99, 108]) == {98: "7454012", 99: "9081624"}

    def test_en_prosa_reparte_por_el_rotulo_en_orden(self):
        from resolutions.adapters.mosaico_de_nombres import _repartir_cedulas

        prosa = "C.C. No. 33.123.201 Expedida\nha completado\nC.C. No. 4V.425.748\nha completado"
        assert _repartir_cedulas(prosa, [105, 108]) == {105: "33123201"}

    def test_si_faltan_rotulos_no_se_reparte_ninguna(self):
        """Sin un renglón por franja no hay forma de saber cuál falta, y una
        cédula puesta en la cara de al lado es peor que ninguna."""
        from resolutions.adapters.mosaico_de_nombres import _repartir_cedulas

        assert _repartir_cedulas("C.C. No. 33.123.201\nha completado", [105, 108]) == {}

    def test_se_ancla_en_el_rotulo_de_la_cedula(self):
        from resolutions.adapters.mosaico_de_nombres import MosaicoDeCedulas

        class FuenteConRotulo(FuenteFalsa):
            def boxes_of(self, page_number):
                return [LineBox(text="C.C. No.", center_x=0.3, top=0.37)]

        bandas = MosaicoDeCedulas(leer=lambda _: "")._bandas(FuenteConRotulo({}), [1])
        assert bandas[1].y0 < 0.37 < bandas[1].y1
        assert bandas[1].y1 - bandas[1].y0 < 0.07, "un renglón, no media hoja"


class TestLaSegundaMiradaEsOtra:
    """El proveedor es determinista: la misma franja devuelve lo mismo (353 de
    353 sobre el libro 7). Una segunda lectura sólo vale si la imagen es otra."""

    def test_otra_mirada_recorta_distinto_y_con_mas_resolucion(self):
        from resolutions.adapters.mosaico_de_nombres import MosaicoDeCedulas

        primera = MosaicoDeCedulas(leer=lambda _: "")
        segunda = primera.otra_mirada()
        fuente = FuenteFalsa({})

        class FuenteConRotulo(FuenteFalsa):
            def boxes_of(self, page_number):
                return [LineBox(text="C.C. No.", center_x=0.3, top=0.37)]

        fuente = FuenteConRotulo({})
        b1, b2 = primera._bandas(fuente, [1])[1], segunda._bandas(fuente, [1])[1]
        assert (b2.y1 - b2.y0) > (b1.y1 - b1.y0), "más papel alrededor del renglón"
        assert segunda._dpi > primera._dpi
        assert primera._dpi == 300, "y la primera no cambia"
