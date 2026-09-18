"""Leer un libro entero sin esperar página por página.

Leer es esperar: casi tres segundos por página contra el proveedor de OCR, y
durante esos tres segundos el proceso no hace nada. Medido sobre el libro 7 --
398 páginas -- en serie eran veinte minutos de reloj y de CPU casi ninguno.

Lo que se fija aquí es que leer a la vez no cambie ni una sola de las
respuestas: los registros salen en el orden del libro, cada página se lee una
vez, y una lectura que falla se queda en su página en lugar de arrastrar a las
demás.
"""

import time

from resolutions.application.ports import OcrResult
from resolutions.application.read_diploma_book import ReadDiplomaBook
from resolutions.domain.diploma import TextLine

#: Una ficha que se lee entera de la capa de texto: no necesita escalar.
COMPLETO = (
    "Folio 336",
    "Nombres y apellidos del graduando",
    "ALIX JOSEFINA MARIN RODRIGUEZ",
    "Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD",
    "Graduacion: 12/05/2019",
    "Registrado a folio No. 336",
    "libro No. 8",
)


class FuenteDePruebas:
    """Un libro cuyas páginas dicen lo que se le indique."""

    def __init__(self, paginas):
        self._paginas = paginas
        self.rasterizadas: list[int] = []

    @property
    def page_count(self):
        return len(self._paginas)

    def lines_of(self, page_number):
        return [
            TextLine(text=texto, y=float(indice))
            for indice, texto in enumerate(self._paginas[page_number - 1])
        ]

    def render(self, page_number, band=None, dpi=200):
        # El rasterizado ocurre en el hilo que manda, nunca en el pool: MuPDF no
        # promete ser seguro entre hilos sobre el mismo documento.
        self.rasterizadas.append(page_number)
        return f"pagina-{page_number}".encode()


class OcrQueTarda:
    """Contesta lo que se le diga, después de dormir un poco."""

    def __init__(self, respuestas: dict[bytes, str], demora: float = 0.05):
        self._respuestas = respuestas
        self._demora = demora
        self.llamadas: list[bytes] = []

    def read(self, image_png: bytes) -> OcrResult:
        self.llamadas.append(image_png)
        time.sleep(self._demora)
        return OcrResult(text=self._respuestas.get(image_png, ""), mean_confidence=0.0)


class TestElOrdenSeConserva:
    def test_los_registros_salen_en_el_orden_del_libro(self):
        """Aunque las lecturas vuelvan desordenadas, que es lo normal."""
        fuente = FuenteDePruebas([COMPLETO] * 12)
        registros, _ = ReadDiplomaBook(workers=4).execute(fuente)
        assert [r.page_number for r in registros] == list(range(1, 13))

    def test_cada_pagina_se_lee_una_sola_vez(self):
        """Una página leída dos veces se paga dos veces."""
        paginas = [("",)] * 8
        ocr = OcrQueTarda({})
        fuente = FuenteDePruebas(paginas)
        ReadDiplomaBook(ocr=ocr, workers=4).execute(fuente)
        assert len(ocr.llamadas) == len(set(ocr.llamadas)) == 8


class TestUnFalloNoArrastraAlLibro:
    def test_una_lectura_que_revienta_deja_las_demas_en_pie(self):
        class OcrCaprichoso:
            def read(self, image_png: bytes) -> OcrResult:
                if image_png == b"pagina-3":
                    raise RuntimeError("el proveedor se cayó")
                return OcrResult(text="", mean_confidence=0.0)

        fuente = FuenteDePruebas([("",)] * 6)
        registros, stats = ReadDiplomaBook(ocr=OcrCaprichoso(), workers=3).execute(fuente)

        assert [r.page_number for r in registros] == [1, 2, 3, 4, 5, 6]
        assert 3 in stats.failures

    def test_una_pagina_que_no_se_rasteriza_tampoco(self):
        class FuenteRota(FuenteDePruebas):
            def render(self, page_number, band=None, dpi=200):
                if page_number == 2:
                    raise RuntimeError("página ilegible")
                return super().render(page_number, band, dpi)

        fuente = FuenteRota([("",)] * 4)
        registros, stats = ReadDiplomaBook(ocr=OcrQueTarda({}), workers=2).execute(fuente)

        assert len(registros) == 4
        assert 2 in stats.failures


class TestLeerALaVezEsMasRapido:
    def test_ocho_lectores_no_tardan_como_ocho_lecturas(self):
        """La medida que justifica todo lo demás.

        Ocho páginas a cinco centésimas cada una son cuatro décimas en serie.
        Con cuatro lectores tienen que bajar de la mitad; se deja margen para
        que la prueba no dependa de lo ocupada que esté la máquina.
        """
        fuente = FuenteDePruebas([("",)] * 8)
        ocr = OcrQueTarda({}, demora=0.05)

        arranque = time.monotonic()
        ReadDiplomaBook(ocr=ocr, workers=4).execute(fuente)
        tardanza = time.monotonic() - arranque

        assert len(ocr.llamadas) == 8
        assert tardanza < 0.30


class TestSeCuentaEnVivo:
    """La cinta tiene que avanzar mientras se lee, no al terminar.

    Es la regresión que dejó leer en paralelo: el progreso se anunciaba en
    bloque al final, y la pantalla pasaba doce minutos diciendo "0 / 398
    páginas, 0.0 p/s" con el gráfico vacío mientras el trabajo corría
    perfectamente. Un sistema que no contesta "¿por dónde va?" parece colgado
    aunque no lo esté.
    """

    class ReporteroConTestigo:
        """Anota, por cada aviso de página, cuántas lecturas se habían hecho."""

        def __init__(self, ocr):
            self._ocr = ocr
            self.paginas: list[tuple[int, int]] = []

        def emit(self, event):
            if str(event.stage) == "page" and event.page_number:
                self.paginas.append((event.page_number, len(self._ocr.llamadas)))

    def test_las_paginas_se_anuncian_segun_se_leen(self):
        fuente = FuenteDePruebas([("",)] * 8)
        ocr = OcrQueTarda({}, demora=0.01)
        reportero = self.ReporteroConTestigo(ocr)

        ReadDiplomaBook(ocr=ocr, progress=reportero, workers=2).execute(fuente)

        assert [pagina for pagina, _ in reportero.paginas] == [1, 2, 3, 4, 5, 6, 7, 8]
        # Las primeras se anuncian con la ventana apenas llena -- dos lectores,
        # cuatro lecturas en vuelo --, no con las ocho hechas: si todo se
        # anunciara al final, aquí habría un 8.
        assert reportero.paginas[0][1] <= 4
        assert reportero.paginas[1][1] <= 4

    def test_y_siempre_en_el_orden_del_libro(self):
        """Aunque las lecturas vuelvan desordenadas, que es lo normal."""
        fuente = FuenteDePruebas([("",)] * 12)
        ocr = OcrQueTarda({}, demora=0.01)
        reportero = self.ReporteroConTestigo(ocr)

        ReadDiplomaBook(ocr=ocr, progress=reportero, workers=4).execute(fuente)

        anunciadas = [pagina for pagina, _ in reportero.paginas]
        assert anunciadas == sorted(anunciadas) == list(range(1, 13))


class TestUnaSolaLecturaPorCara:
    """La esquina del folio sale de la página entera que ya se leyó.

    Pedirla aparte era pagar dos veces la misma tinta: 203 peticiones y un
    tercio de la factura del libro 7. La página entera empieza por la esquina
    -- "2/V # LA REPUBLICA DE COLOMBIA..." -- y con eso basta.
    """

    class OcrConEsquinaEnLaCabecera:
        """Un motor de pago que devuelve la página con el folio delante."""

        def __init__(self):
            self.llamadas: list[bytes] = []

        def read(self, image_png: bytes) -> OcrResult:
            return self.read_remote(image_png)

        def read_remote(self, image_png: bytes) -> OcrResult:
            self.llamadas.append(image_png)
            pagina = int(image_png.decode().split("-")[1])
            folio = (pagina + 1) // 2
            texto = f"{pagina} {folio}/V\n# LA REPUBLICA DE COLOMBIA\nen atención a que el Señor"
            return OcrResult(text=texto, mean_confidence=0.0)

    class FuenteConTinta(FuenteDePruebas):
        """Las impares llevan folio en la esquina; las pares llegan limpias."""

        def ink_of(self, page_number, band):
            return (0.09, 0.0) if page_number % 2 else (0.0, 0.0)

    def test_no_se_paga_la_esquina_si_la_pagina_entera_ya_la_trajo(self):
        ocr = self.OcrConEsquinaEnLaCabecera()
        fuente = self.FuenteConTinta([("",)] * 20)

        registros, _ = ReadDiplomaBook(ocr=ocr, workers=4).execute(fuente)

        # Diez caras que abren registro, diez folios confirmados, y ni una sola
        # lectura más que las veinte páginas enteras.
        assert len(ocr.llamadas) == 20
        assert [r.folio_manuscrito for r in registros if r.folio_manuscrito] == [
            str(n) for n in range(1, 11)
        ]


class TestElMotorLocalSePruebaAntesDeSeguir:
    """Con Tesseract se releen unas pocas páginas y se sigue sólo si sirvió.

    En un libro de fichas mecanografiadas la relectura cierra huecos; en uno de
    1982 con todo manuscrito no recupera un campo en 398 páginas y cuesta 110
    segundos. La diferencia se ve en la muestra, así que se mide en vez de
    suponerla.
    """

    class TesseractQueNoLeeNada:
        def __init__(self):
            self.llamadas = 0

        def read(self, image_png: bytes) -> OcrResult:
            self.llamadas += 1
            return OcrResult(text="", mean_confidence=0.0)

    class TesseractQueSiLee:
        def __init__(self):
            self.llamadas = 0

        def read(self, image_png: bytes) -> OcrResult:
            self.llamadas += 1
            return OcrResult(
                text=(
                    "Folio 336\nALIX MARIN\nNombres y apellidos del graduando\n"
                    "Titulo recibido: ESPECIALISTA EN GESTION\nGraduacion: 12/05/2019\n"
                    "Registrado a folio No. 336\nlibro No. 8"
                ),
                mean_confidence=0.9,
            )

    def test_si_la_muestra_no_resuelve_nada_no_se_relee_el_resto(self):
        ocr = self.TesseractQueNoLeeNada()
        registros, stats = ReadDiplomaBook(ocr=ocr, workers=4).execute(
            FuenteDePruebas([("",)] * 60)
        )
        assert ocr.llamadas == 16
        assert len(registros) == 60
        assert len(stats.incomplete) == 60

    def test_lo_que_trajo_una_muestra_inutil_se_descarta(self):
        """Tesseract siempre trae algo de un libro manuscrito y nunca sirve.

        Medido sobre el libro 7: en 16 páginas "recuperó" el libro 71, el
        nombre "exigen para optar el título de" y la cédula 6507. Si se
        conservara, iría al FUID como si fuera un dato.
        """

        class TesseractQueInventa:
            def read(self, image_png: bytes) -> OcrResult:
                return OcrResult(text="libro No. 71", mean_confidence=0.3)

        registros, _ = ReadDiplomaBook(ocr=TesseractQueInventa(), workers=4).execute(
            FuenteDePruebas([("",)] * 40)
        )
        assert all(r.book is None for r in registros)

    def test_si_la_muestra_resuelve_algo_se_sigue_con_todo(self):
        ocr = self.TesseractQueSiLee()
        ReadDiplomaBook(ocr=ocr, workers=4).execute(FuenteDePruebas([("",)] * 60))
        assert ocr.llamadas == 60

    def test_el_motor_de_pago_no_se_muestrea(self):
        """Lee manuscrito: no hay nada que probar, se relee todo."""

        class Pago(self.TesseractQueNoLeeNada):
            def read_remote(self, image_png: bytes) -> OcrResult:
                return self.read(image_png)

        ocr = Pago()
        ReadDiplomaBook(ocr=ocr, workers=4).execute(FuenteDePruebas([("",)] * 40))
        assert ocr.llamadas == 40


class TestLaVentanaSeAjustaAlProveedor:
    class OcrQueSeQueja:
        """Cuenta rechazos como lo haría el adaptador de Mistral."""

        def __init__(self):
            from resolutions.application.consumo import Consumo

            self.consumo = Consumo()
            self.llamadas = 0

        def read(self, image_png: bytes) -> OcrResult:
            self.llamadas += 1
            if self.llamadas % 5 == 0:
                self.consumo.rechazo("mistral-ocr")
            self.consumo.peticion("mistral-ocr", paginas=1)
            return OcrResult(text="", mean_confidence=0.0)

        # Es un motor de pago: lee manuscrito y no se muestrea.
        read_remote = read

    def test_los_rechazos_no_pierden_paginas_ni_desordenan(self):
        ocr = self.OcrQueSeQueja()
        registros, stats = ReadDiplomaBook(ocr=ocr, workers=4).execute(
            FuenteDePruebas([("",)] * 30)
        )
        assert [r.page_number for r in registros] == list(range(1, 31))
        assert ocr.llamadas == 30
        assert not stats.failures

