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
from resolutions.domain.diploma import CriterioDeCorte, TextLine

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
    """Se lee lo justo: las caras que abren, y su esquina de lo ya leído.

    Dos ahorros distintos, los dos medidos sobre el libro 7.

    El primero es **no leer las vueltas**. La cara que llega con la esquina
    limpia pertenece a la hoja anterior: no nombra ningún archivo y no abre
    ninguna fila del inventario, así que pagar por leerla es pagar por un dato
    que nadie va a mirar. En un libro foliado hoja a hoja eso es la mitad.

    El segundo es **no pedir la esquina aparte**. Pedirla era pagar dos veces la
    misma tinta -- 203 peticiones y un tercio de la factura --; la página entera
    empieza por la esquina, "2/V # LA REPUBLICA DE COLOMBIA...", y con eso basta.
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

    def test_solo_se_leen_las_caras_que_abren(self):
        """Veinte caras, diez con folio en la esquina: diez lecturas y no más.

        Ni una para las diez vueltas, ni una para las diez esquinas, que salen
        de la cabecera de la página que ya se leyó.
        """
        ocr = self.OcrConEsquinaEnLaCabecera()
        fuente = self.FuenteConTinta([("",)] * 20)

        registros, stats = ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=4).execute(fuente)

        assert len(ocr.llamadas) == 10
        assert sorted(stats.no_leidas) == [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
        assert [r.folio_manuscrito for r in registros if r.folio_manuscrito] == [
            str(n) for n in range(1, 11)
        ]

    def test_las_vueltas_siguen_saliendo_en_el_libro(self):
        """No leerlas no es perderlas: sus registros están y van a su documento.

        Es la comprobación que separa "no se pagó por ese dato" de "esa página
        se cayó del libro". Lo segundo sería mucho peor que gastar de más.
        """
        fuente = self.FuenteConTinta([("",)] * 20)

        registros, _ = ReadDiplomaBook(
            criterio=CriterioDeCorte.FOLIO, ocr=self.OcrConEsquinaEnLaCabecera(), workers=4
        ).execute(fuente)

        assert [r.page_number for r in registros] == list(range(1, 21))


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



#: Una cara que Tesseract sí sabe leer entera: está mecanografiada.
LEIDA_POR_EL_LOCAL = "\n".join(
    (
        "Folio 12",
        # El nombre va **encima** de su rótulo: el formulario lo escribe
        # sobre el renglón y la leyenda debajo, y es la leyenda la que lo
        # localiza. Al revés no se lee ninguno, y la prueba pasaría por el
        # camino equivocado sin probar lo que dice probar.
        "ALIX JOSEFINA MARIN RODRIGUEZ",
        "Nombres y apellidos del graduando",
        "Titulo recibido: ESPECIALISTA EN GESTION DE LA CALIDAD",
        "Graduacion: 12/05/2019",
        "Registrado a folio No. 12",
        "libro No. 8",
    )
)


class CascadaFalsa:
    """Un motor con los dos peldaños separados, como el de produccion.

    Anota por separado lo que se le pidió a cada uno, que es justo lo que hay
    que poder comprobar: que al de pago sólo le llega lo que el de casa no supo.
    """

    def __init__(self, texto_local: str = "", texto_remoto: str = ""):
        self._local = texto_local
        self._remoto = texto_remoto
        self.locales: list[bytes] = []
        self.tandas: list[int] = []

    def read(self, image_png: bytes) -> OcrResult:
        return self.read_local(image_png)

    def read_local(self, image_png: bytes) -> OcrResult:
        self.locales.append(image_png)
        return OcrResult(text=self._local, mean_confidence=0.0)

    def read_many_remote(self, imagenes: list[bytes]) -> list[str]:
        self.tandas.append(len(imagenes))
        return [self._remoto for _ in imagenes]

    @property
    def remotas(self) -> int:
        return sum(self.tandas)


class FuenteFoliada(FuenteDePruebas):
    """Las impares llevan folio en la esquina; las pares llegan limpias.

    Rasteriza la esquina con bytes distintos de los de la página entera,
    para que una prueba pueda contar por separado lo que se pidió de cada
    cosa: leer la página y leer su esquina son dos gastos diferentes.
    """

    def ink_of(self, page_number, band):
        return (0.09, 0.0) if page_number % 2 else (0.0, 0.0)

    def render(self, page_number, band=None, dpi=200):
        imagen = super().render(page_number, band, dpi)
        return imagen + b"-esquina" if band is not None else imagen


def _de_paginas_enteras(llamadas) -> list[bytes]:
    """De todo lo que se le pidió al motor, lo que eran páginas y no esquinas."""
    return [imagen for imagen in llamadas if not imagen.endswith(b"-esquina")]


class TestLosDosMotoresColaboran:
    """Tesseract primero y gratis; al de pago sólo lo que el de casa no consiguió.

    Es lo que pidió el operador con estas palabras: "necesito que solamente
    analice las que el OCR no logre analizar, o sea necesito que las 2 colaboren
    juntas para usar menos tokens".

    Lo delicado es el **criterio** para escalar, y por eso hay una prueba para
    cada lado: no es cuánto texto trajo el local sino si dejó el registro
    resuelto. De un diploma de 1982 Tesseract saca el formulario impreso entero
    sin haber leído ninguno de los cinco datos del graduado, y medido por
    caracteres esa lectura parece buena.
    """

    def test_lo_que_el_local_resuelve_no_llega_al_de_pago(self):
        ocr = CascadaFalsa(texto_local=LEIDA_POR_EL_LOCAL)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2).execute(fuente)

        assert len(_de_paginas_enteras(ocr.locales)) == 3, (
            "las tres caras que abren, al motor de casa"
        )
        assert ocr.remotas == 0, "y ni una al de pago"

    def test_mucho_texto_sin_los_campos_escala_igual(self):
        """El caso del libro de 1982, que es el que justifica todo esto."""
        formulario = (
            "LA REPUBLICA DE COLOMBIA y en su nombre la UNIVERSIDAD DE CARTAGENA "
            "en atenci\u00f3n a que el Se\u00f1or ha completado todos los Estudios Cl\u00e1sicos "
            "que los Estatutos Universitarios exigen para optar el t\u00edtulo de"
        )
        ocr = CascadaFalsa(texto_local=formulario, texto_remoto=LEIDA_POR_EL_LOCAL)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2).execute(fuente)

        assert len(formulario) > 150, "trae texto de sobra..."
        assert ocr.remotas == 3, "...y aun as\u00ed escala, porque no trajo un solo campo"

    def test_el_de_pago_recibe_lo_que_falta_y_lo_resuelve(self):
        ocr = CascadaFalsa(texto_local="", texto_remoto=LEIDA_POR_EL_LOCAL)
        fuente = FuenteFoliada([("",)] * 6)

        registros, stats = ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2).execute(fuente)

        assert ocr.remotas == 3
        assert stats.recovered_by_ocr == 3
        assert [r.name for r in registros if r.name] == [
            "ALIX JOSEFINA MARIN RODRIGUEZ"
        ] * 3

    def test_un_motor_suelto_sigue_leyendo_como_siempre(self):
        """Quien no distingue sus pelda\u00f1os es su propio pelda\u00f1o.

        Un Tesseract a secas no tiene a qui\u00e9n escalar, as\u00ed que se le pide una
        vez por cara y se acab\u00f3, que es como funcionaba esto antes de que
        hubiera dos motores.
        """
        ocr = OcrQueTarda({}, demora=0.0)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2).execute(fuente)

        assert len(_de_paginas_enteras(ocr.llamadas)) == 3


class TestSeLeePorTandas:
    """Al motor de pago se le mandan varias caras juntas, no una por petici\u00f3n.

    Lo pidi\u00f3 el operador -- "no que se ejecute imagen por imagen" -- y tiene su
    raz\u00f3n: una petici\u00f3n por p\u00e1gina son cientos de llamadas por libro, con su
    latencia y sus rechazos por ritmo. La factura no cambia, porque el proveedor
    cobra por p\u00e1gina procesada; lo que baja es el n\u00famero de idas y vueltas.
    """

    def test_las_caras_pendientes_viajan_agrupadas(self):
        ocr = CascadaFalsa(texto_local="", texto_remoto="")
        # Cincuenta caras, veinticinco de ellas con folio: dos tandas de doce y
        # una de una.
        fuente = FuenteFoliada([("",)] * 50)

        ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=4).execute(fuente)

        assert ocr.tandas == [12, 12, 1]
        assert sum(ocr.tandas) == 25

    def test_ninguna_cara_se_pierde_ni_se_repite(self):
        ocr = CascadaFalsa(texto_local="", texto_remoto="")
        fuente = FuenteFoliada([("",)] * 50)

        registros, _ = ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=4).execute(fuente)

        assert [r.page_number for r in registros] == list(range(1, 51))

    def test_una_tanda_que_revienta_no_tumba_el_libro(self):
        """Lo que se pierde es esa tanda, y queda dicho en las estad\u00edsticas."""

        class TandaQueRevienta(CascadaFalsa):
            def read_many_remote(self, imagenes):
                raise RuntimeError("el proveedor se cay\u00f3")

        fuente = FuenteFoliada([("",)] * 8)

        registros, stats = ReadDiplomaBook(
            criterio=CriterioDeCorte.FOLIO, ocr=TandaQueRevienta(), workers=2
        ).execute(fuente)

        assert [r.page_number for r in registros] == list(range(1, 9))
        assert stats.failures, "y se dice qu\u00e9 p\u00e1ginas se quedaron sin texto"


#: Lo que devuelve un OCR que sí supo leer la cédula manuscrita, y nada más.
#: Ni nombre, ni título, ni fecha: es el caso que separa los dos criterios.
SOLO_LA_CEDULA = "C.C. No. 7.882.907 Expedida en Arizona Bolivar"


class TestCortandoPorCedulaSoloHaceFaltaLaCedula:
    """Que la OCR busque la cédula, y sólo si no la capta se pase a la IA.

    Lo pidió el operador con estas palabras: "alli necesito que como primera
    opcion sea la ocr que busque la cedula, y si no la capta o esta mal, que
    alli si pase a la ia".

    Lo que lo hace posible es que **cortando por cédula el criterio de "resuelto"
    es más estrecho**. Por folio hace falta todo lo que va al FUID -- nombre,
    título, fecha, libro --, de modo que casi cualquier cara acaba escalando. Por
    cédula, lo único que decide dónde termina cada documento y cómo se llama es
    ese número: una cara cuya cédula ya se sostiene está resuelta y no se paga.
    """

    def test_si_el_local_saca_la_cedula_no_se_paga_nada(self):
        ocr = CascadaFalsa(texto_local=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 6)

        registros, _ = ReadDiplomaBook(
            ocr=ocr, workers=2, criterio=CriterioDeCorte.CEDULA
        ).execute(fuente)

        assert ocr.remotas == 0, "la OCR la captó: la IA no entra"
        assert [r.identity_number for r in registros] == ["7882907"] * 6

    def test_la_misma_lectura_por_folio_si_escalaria(self):
        """La comprobación que da sentido a la de arriba.

        La cédula sola no cierra un registro de FUID -- faltan nombre, título y
        fecha --, así que cortando por folio esa misma página se sigue pagando.
        """
        ocr = CascadaFalsa(texto_local=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(ocr=ocr, workers=2, criterio=CriterioDeCorte.FOLIO).execute(fuente)

        assert ocr.remotas > 0

    def test_si_el_local_no_la_capta_entonces_si_pasa_a_la_ia(self):
        ocr = CascadaFalsa(texto_local="", texto_remoto=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 6)

        registros, _ = ReadDiplomaBook(
            ocr=ocr, workers=2, criterio=CriterioDeCorte.CEDULA
        ).execute(fuente)

        assert ocr.remotas == 6
        assert [r.identity_number for r in registros] == ["7882907"] * 6

    def test_una_cedula_mal_leida_cuenta_como_no_captada(self):
        """"Si no la capta **o está mal**", dijo el operador.

        `30761` son cinco dígitos: no es una cédula corta, es una cédula a la que
        el OCR le comió dígitos. Darla por buena habría nombrado los archivos con
        ella y no habría preguntado a la IA nunca.
        """
        ocr = CascadaFalsa(texto_local="C.C. No. 30761", texto_remoto=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 4)

        registros, _ = ReadDiplomaBook(
            ocr=ocr, workers=2, criterio=CriterioDeCorte.CEDULA
        ).execute(fuente)

        assert ocr.remotas == 4, "lo que no se sostiene se vuelve a preguntar"
        assert [r.identity_number for r in registros] == ["7882907"] * 4

    def test_cortando_por_cedula_no_se_salta_ninguna_cara(self):
        """Y hay que decir lo que cuesta, no sólo lo que ahorra.

        Por folio se saltan las vueltas, que no nombran nada. Por cédula no se
        salta ninguna: la señal que manda hay que leerla, y decidir sin mirarla
        sería cortar a ciegas.
        """
        ocr = CascadaFalsa(texto_local="", texto_remoto=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 10)

        _, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, criterio=CriterioDeCorte.CEDULA
        ).execute(fuente)

        assert stats.no_leidas == [], "ninguna cara se da por sabida"
        assert ocr.remotas == 10


class TestLaCintaAvanzaMientrasSeLee:
    """La pantalla tiene que ver moverse el trabajo, no esperar al final.

    Es la regresión que dejó leer por tandas, y es la misma de la que ya
    advierte `TestSeCuentaEnVivo` un poco más arriba: con una petición por
    página, cada lectura que volvía pintaba su casilla; al agrupar las páginas
    en tandas de doce, el anuncio se hacía al terminar y la cinta pasaba todo el
    trabajo en blanco para llenarse de golpe. El trabajo iba igual de bien, pero
    desde fuera era indistinguible de estar colgado.
    """

    class ReporteroConTestigo:
        """Anota, por cada casilla pintada, cuántas tandas se habían pedido."""

        def __init__(self, ocr):
            self._ocr = ocr
            self.casillas: list[tuple[int, int]] = []

        def emit(self, event):
            if str(event.stage) == "page" and event.page_number:
                self.casillas.append((event.page_number, len(self._ocr.tandas)))

    def test_se_pinta_tanda_a_tanda_y_no_al_final(self):
        ocr = CascadaFalsa(texto_local="", texto_remoto=SOLO_LA_CEDULA)
        # Cuarenta caras que abren: cuatro tandas de doce y una de cuatro.
        fuente = FuenteFoliada([("",)] * 80)
        reportero = self.ReporteroConTestigo(ocr)

        ReadDiplomaBook(
            ocr=ocr, progress=reportero, workers=2, criterio=CriterioDeCorte.FOLIO
        ).execute(fuente)

        assert len(ocr.tandas) > 3, "hubo varias tandas, que es el caso que importa"
        # La primera casilla se pinta con la primera tanda cerrada, no con todas:
        # si todo se anunciara al final, aquí habría tantas como tandas hubo.
        assert reportero.casillas[0][1] == 1

    def test_y_siempre_en_el_orden_del_libro(self):
        """Aunque las lecturas vuelvan desordenadas, que es lo normal.

        Una casilla pintada antes que la de su izquierda no informa de por
        dónde va el trabajo: parece un salteado.
        """
        ocr = CascadaFalsa(texto_local="", texto_remoto=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 40)
        reportero = self.ReporteroConTestigo(ocr)

        ReadDiplomaBook(ocr=ocr, progress=reportero, workers=4).execute(fuente)

        pintadas = [pagina for pagina, _ in reportero.casillas]
        assert pintadas == sorted(pintadas) == list(range(1, 41))

    def test_ninguna_casilla_se_pinta_dos_veces(self):
        """Pintar dos veces descuadra el contador de la pantalla."""
        ocr = CascadaFalsa(texto_local="", texto_remoto=SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 40)
        reportero = self.ReporteroConTestigo(ocr)

        ReadDiplomaBook(ocr=ocr, progress=reportero, workers=4).execute(fuente)

        pintadas = [pagina for pagina, _ in reportero.casillas]
        assert len(pintadas) == len(set(pintadas)) == 40


class TestLasTandasViajanVariasALaVez:
    """El motor de pago recibe varias tandas a la vez, no una detrás de otra.

    Era el cuello de botella entero de la ruta de pago: cada tanda de doce
    caras eran unos veinte segundos de proveedor durante los que el proceso no
    hacía nada, y un libro de cuatrocientas caras eran cuarenta tandas en fila.
    Medido con un proveedor simulado sobre el libro 7: 711 segundos en serie.
    """

    class CascadaQueCuentaElVuelo(CascadaFalsa):
        def __init__(self):
            super().__init__(texto_local="", texto_remoto=SOLO_LA_CEDULA)
            import threading

            self._candado = threading.Lock()
            self.en_vuelo = 0
            self.maximo_en_vuelo = 0

        def read_many_remote(self, imagenes):
            with self._candado:
                self.en_vuelo += 1
                self.maximo_en_vuelo = max(self.maximo_en_vuelo, self.en_vuelo)
            try:
                time.sleep(0.05)
                return super().read_many_remote(imagenes)
            finally:
                with self._candado:
                    self.en_vuelo -= 1

    def test_varias_tandas_en_vuelo(self):
        ocr = self.CascadaQueCuentaElVuelo()
        # Sesenta caras que abren: cinco tandas de doce.
        fuente = FuenteDePruebas([("",)] * 60)

        arranque = time.monotonic()
        registros, _ = ReadDiplomaBook(ocr=ocr, workers=4).execute(fuente)
        tardanza = time.monotonic() - arranque

        assert len(ocr.tandas) == 5
        assert ocr.maximo_en_vuelo >= 2, "hubo tandas viajando a la vez"
        assert tardanza < 5 * 0.05 * 2, "y no tardó como cinco tandas en fila"
        assert [r.identity_number for r in registros] == ["7882907"] * 60


class TestLasEsquinasSoloSePaganCuandoNombran:
    """Leer la esquina cuesta una página facturada, y sólo vale cuando da nombre.

    Medido: 208 esquinas y doce segundos para cero folios en el libro de 2011,
    que ya trae el folio impreso; 249 esquinas y dieciocho segundos para cero
    folios en el libro 7 leído con el motor local, que no lee manuscrito.
    """

    class PagoSinFolioEnLaCabecera:
        """Un motor de pago cuya página entera no empieza por la esquina."""

        def __init__(self, texto: str):
            self._texto = texto
            self.llamadas: list[bytes] = []

        def read(self, image_png: bytes) -> OcrResult:
            return self.read_remote(image_png)

        def read_remote(self, image_png: bytes) -> OcrResult:
            self.llamadas.append(image_png)
            return OcrResult(text=self._texto, mean_confidence=0.0)

        @property
        def esquinas(self) -> list[bytes]:
            return [imagen for imagen in self.llamadas if imagen.endswith(b"-esquina")]

    def test_sin_motor_de_pago_no_se_lee_ninguna_esquina(self):
        """El folio de la esquina está escrito a mano; Tesseract no lo lee."""
        ocr = OcrQueTarda({}, demora=0.0)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2).execute(fuente)

        assert [c for c in ocr.llamadas if c.endswith(b"-esquina")] == []

    def test_con_el_folio_impreso_no_se_paga_la_esquina(self):
        """El formulario mecanografiado ya dice el folio dos veces."""
        ocr = self.PagoSinFolioEnLaCabecera(LEIDA_POR_EL_LOCAL)
        fuente = FuenteFoliada([("",)] * 6)

        registros, _ = ReadDiplomaBook(
            criterio=CriterioDeCorte.FOLIO, ocr=ocr, workers=2
        ).execute(fuente)

        assert ocr.esquinas == []
        assert [r.folio for r in registros if r.folio] == ["12"] * 3

    def test_cara_a_cara_no_se_paga_la_esquina_de_quien_ya_tiene_nombre(self):
        ocr = self.PagoSinFolioEnLaCabecera(SOLO_LA_CEDULA)
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.PAGINA, ocr=ocr, workers=2).execute(fuente)

        assert ocr.esquinas == [], "la cédula ya nombra el archivo"

    def test_pero_si_se_paga_la_de_quien_no_tiene_con_que_nombrarse(self):
        ocr = self.PagoSinFolioEnLaCabecera("")
        fuente = FuenteFoliada([("",)] * 6)

        ReadDiplomaBook(criterio=CriterioDeCorte.PAGINA, ocr=ocr, workers=2).execute(fuente)

        assert len(ocr.esquinas) == 3, "las tres caras con folio en la esquina"


class TestLoQueViajaAlMotorDePago:
    """Al proveedor se le manda lo más barato que diga lo mismo.

    Rasterizar una cara a 300 ppp cuesta 170 ms del hilo que manda, que es el
    único que puede rasterizar: sobre un libro de cuatrocientas caras, un
    minuto largo de suelo para la ruta de pago. Un libro escaneado es, cara por
    cara, un JPEG que cubre la hoja, y mandarlo tal cual cuesta un milisegundo.
    """

    class FuenteEscaneada(FuenteDePruebas):
        """Las impares saben dar su escaneo original; las pares, no."""

        def imagen_escaneada(self, page_number):
            return f"escaneo-{page_number}".encode() if page_number % 2 else None

    class FuenteQueEligeFormato(FuenteDePruebas):
        def __init__(self, paginas):
            super().__init__(paginas)
            self.formatos: list[str] = []

        def render(self, page_number, band=None, dpi=200, formato="png"):
            self.formatos.append(formato)
            return super().render(page_number, band, dpi)

    class Pago(CascadaFalsa):
        def __init__(self):
            super().__init__(texto_local="", texto_remoto=SOLO_LA_CEDULA)
            self.recibidas: list[bytes] = []

        def read_many_remote(self, imagenes):
            self.recibidas.extend(imagenes)
            return super().read_many_remote(imagenes)

    def test_el_escaneo_original_viaja_tal_cual(self):
        ocr = self.Pago()
        fuente = self.FuenteEscaneada([("",)] * 4)

        ReadDiplomaBook(ocr=ocr, workers=2).execute(fuente)

        assert sorted(ocr.recibidas) == [b"escaneo-1", b"escaneo-3", b"pagina-2", b"pagina-4"]
        # El motor de casa rasteriza las cuatro una vez; para el de pago sólo
        # se vuelven a rasterizar las que no tienen escaneo que mandar.
        assert fuente.rasterizadas.count(1) == 1, "la que tiene escaneo no se rasteriza otra vez"
        assert fuente.rasterizadas.count(2) == 2

    def test_y_si_no_lo_hay_se_rasteriza_en_jpeg(self):
        ocr = self.Pago()
        fuente = self.FuenteQueEligeFormato([("",)] * 4)

        ReadDiplomaBook(ocr=ocr, workers=2).execute(fuente)

        assert set(ocr.recibidas) == {b"pagina-1", b"pagina-2", b"pagina-3", b"pagina-4"}
        assert "jpeg" in fuente.formatos

    def test_una_fuente_que_no_sabe_de_formatos_sigue_sirviendo(self):
        ocr = self.Pago()
        fuente = FuenteDePruebas([("",)] * 4)

        registros, _ = ReadDiplomaBook(ocr=ocr, workers=2).execute(fuente)

        assert [r.identity_number for r in registros] == ["7882907"] * 4
