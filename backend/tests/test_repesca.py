"""La repesca: lo que la lectura entera deja sin identidad se vuelve a buscar.

Lo pidió el operador con tres hojas del libro 7 delante -- la 105, la 149 y la
350 --, las tres con su nombre y su cédula escritos a mano y las tres sin nombre
en el archivo: «el bot se está volando esas partes». Y con una regla: «necesito
que ninguna página pase a revisión, y la que sí pase que sea en realidad por
algún error verdaderamente real».

Medido sobre ese libro, la lectura a página entera y en tanda tiene dos fallos:
se come dígitos de la cédula manuscrita (siete creíbles de doce) y devuelve el
renglón manuscrito del nombre como una imagen (diez de doce). En franjas
recortadas y ampliadas -- diez por página facturada -- salen diez de diez y doce
de doce. De ahí el orden que se fija aquí: la tanda primero, las franjas para lo
que la tanda dejó, y la cara entera sola como último recurso.
"""

from resolutions.application.ports import OcrResult
from resolutions.application.read_diploma_book import ReadDiplomaBook
from resolutions.domain.diploma import CriterioDeCorte
from tests.test_lectura_paralela import SOLO_LA_CEDULA, CascadaFalsa, FuenteDePruebas

#: Lo que la tanda devuelve de una cara del libro 7: el formulario y el título,
#: sin el nombre -- que volvió como imagen -- y con la cédula a la que le faltan
#: dígitos, que no se sostiene.
SIN_IDENTIDAD_EN_TANDA = (
    "en atención a que el Señor\n\n"
    "C.C. No. 45425 Expedida en Cartagena\n"
    "ha completado todos los Estudios Clásicos\n"
    "exigen para optar el título de:\n\n"
    "DOCTOR EN MEDICINA Y CIRUGIA\n"
)

#: Lo mismo, leído suelto: el nombre y la cédula enteros.
ENTERA_SUELTA = (
    "en atención a que el Señor\n\nSANTIAGO LOPEZ JUAREZ\n\n"
    "C.C. No. 73.090.716 Expedida en Cartagena\n"
    "exigen para optar el título de:\n\nINGENIERO CIVIL\n"
)


class CascadaConLecturaSuelta(CascadaFalsa):
    """Un motor de pago que sabe leer en tanda y también una cara suelta."""

    def __init__(self, en_tanda: str = SIN_IDENTIDAD_EN_TANDA, suelta: str = ENTERA_SUELTA):
        super().__init__(texto_local="", texto_remoto=en_tanda)
        self._suelta = suelta
        self.sueltas: list[bytes] = []

    def read_remote(self, image_png: bytes) -> OcrResult:
        self.sueltas.append(image_png)
        return OcrResult(text=self._suelta, mean_confidence=0.0)


class MosaicoFalso:
    """Un mosaico que contesta lo que se le diga de cada cara, y anota qué le pidieron.

    ``luego`` es lo que contesta a partir de la segunda vez que se le pide: la
    segunda franja de una cara dudosa.
    """

    def __init__(self, respuesta, luego=None):
        self._respuesta = respuesta
        self._luego = luego or respuesta
        self.pedidas: list[list[int]] = []

    def _contestar(self, source, paginas):
        self.pedidas.append(list(paginas))
        responder = self._respuesta if len(self.pedidas) == 1 else self._luego
        return {p: responder(p) for p in paginas if responder(p)}

    cedulas = _contestar
    nombres = _contestar


class TestLaTandaPrimeroYLasFranjasDespues:
    def test_lo_que_la_tanda_dejo_sin_cedula_se_repesca_en_franja(self):
        ocr = CascadaConLecturaSuelta()
        cedulas = MosaicoFalso(lambda p: f"4542{p:04d}")
        nombres = MosaicoFalso(lambda p: f"GRADUANDO {p} APELLIDO")
        fuente = FuenteDePruebas([("",)] * 6)

        registros, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico=nombres, mosaico_de_cedulas=cedulas
        ).execute(fuente)

        assert ocr.remotas == 6, "la tanda va primero, con todas las caras"
        assert cedulas.pedidas == [[1, 2, 3, 4, 5, 6]], "y la franja sólo con las que quedaron sin cédula"
        assert [r.identity_number for r in registros] == [f"4542{p:04d}" for p in range(1, 7)]
        assert [r.name for r in registros] == [f"GRADUANDO {p} APELLIDO" for p in range(1, 7)]
        assert ocr.sueltas == [], "con nombre y cédula ya no hay nada que releer suelto"
        assert stats.repescadas["cedulas"] == 6 and stats.repescadas["nombres"] == 6

    def test_el_titulo_de_la_tanda_no_se_pierde_al_repescar(self):
        ocr = CascadaConLecturaSuelta()
        fuente = FuenteDePruebas([("",)] * 2)
        registros, _ = ReadDiplomaBook(
            ocr=ocr,
            workers=2,
            mosaico=MosaicoFalso(lambda p: "ANA MARIA GOMEZ"),
            mosaico_de_cedulas=MosaicoFalso(lambda p: "7882907"),
        ).execute(fuente)
        assert all(r.degree == "DOCTOR EN MEDICINA Y CIRUGIA" for r in registros)

    def test_el_nombre_creible_no_se_vuelve_a_pedir_ni_se_toca(self):
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        nombres = MosaicoFalso(lambda p: "OTRO NOMBRE")
        fuente = FuenteDePruebas([("",)] * 3)

        registros, _ = ReadDiplomaBook(ocr=ocr, workers=2, mosaico=nombres).execute(fuente)

        assert nombres.pedidas == []
        assert [r.name for r in registros] == ["SANTIAGO LOPEZ JUAREZ"] * 3


class TestLaFranjaCorroboraLaCedulaDeLaPaginaEntera:
    """Dos corridas del libro 7 dieron cédulas creíbles distintas para cuatro
    caras -- 2347073 y 23089093 para la misma hoja. Una cédula creíble y
    equivocada nombra el archivo sin que nadie lo note, así que la franja se
    pide para todas y no sólo para las que quedaron sin ella."""

    def test_la_franja_se_pide_tambien_para_las_que_ya_tienen_cedula(self):
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        cedulas = MosaicoFalso(lambda p: "73090716")
        fuente = FuenteDePruebas([("",)] * 3)

        registros, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico_de_cedulas=cedulas
        ).execute(fuente)

        assert cedulas.pedidas == [[1, 2, 3]]
        assert [r.identity_number for r in registros] == ["73090716"] * 3
        assert stats.repescadas["cedulas_confirmadas"] == 3
        assert not any(r.warnings for r in registros), "coinciden: nada que revisar"

    def errores(self, registros):
        from resolutions.domain.diploma import CriterioDeCorte
        from resolutions.domain.validation import Severity, validate_diplomas

        return [
            i for i in validate_diplomas(registros, CriterioDeCorte.PAGINA)
            if i.severity is Severity.ERROR
        ]

    def test_si_discrepan_se_pide_una_segunda_franja_y_manda_la_mayoria(self):
        """Mirando el papel, la franja acertaba en ocho de diez discrepancias y
        la página entera en dos: ninguna puede mandar sola."""
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        cedulas = MosaicoFalso(lambda p: "23089093")
        fuente = FuenteDePruebas([("",)] * 2)

        registros, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico_de_cedulas=cedulas
        ).execute(fuente)

        assert cedulas.pedidas == [[1, 2], [1, 2]], "la segunda franja, sólo de las dudosas"
        assert [r.identity_number for r in registros] == ["23089093"] * 2
        assert stats.repescadas["cedulas_zanjadas"] == 2
        assert all("73090716" in a and "23089093" in a for r in registros for a in r.warnings)
        assert self.errores(registros) == [], "dos lecturas coinciden: es un aviso, no un error"
        assert not any(r.needs_review for r in registros)

    def test_si_la_segunda_franja_da_la_razon_a_la_pagina_se_queda_la_pagina(self):
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        cedulas = MosaicoFalso(lambda p: "23089093", luego=lambda p: "73090716")
        fuente = FuenteDePruebas([("",)] * 2)

        registros, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico_de_cedulas=cedulas
        ).execute(fuente)

        assert [r.identity_number for r in registros] == ["73090716"] * 2
        assert stats.repescadas["cedulas_zanjadas"] == 2
        assert self.errores(registros) == []

    def test_tres_lecturas_distintas_si_van_a_revision(self):
        """Lo único que es un error de verdad: nadie coincide con nadie."""
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        cedulas = MosaicoFalso(lambda p: "23089093", luego=lambda p: "45443342")
        fuente = FuenteDePruebas([("",)] * 2)

        registros, stats = ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico_de_cedulas=cedulas
        ).execute(fuente)

        assert stats.repescadas["cedulas_discrepantes"] == 2
        assert [r.identity_number for r in registros] == ["23089093"] * 2, "manda la primera franja"
        assert len(self.errores(registros)) == 2
        assert all(r.needs_review for r in registros)

    def test_una_pagina_sin_franja_se_queda_como_estaba(self):
        """La franja no leyó nada ni la segunda vez: la de la página sigue sin comprobar, sin ruido."""
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        cedulas = MosaicoFalso(lambda p: None)
        fuente = FuenteDePruebas([("",)] * 2)

        registros, _ = ReadDiplomaBook(ocr=ocr, workers=2, mosaico_de_cedulas=cedulas).execute(fuente)

        assert cedulas.pedidas == [[1, 2], [1, 2]]
        assert [r.identity_number for r in registros] == ["73090716"] * 2
        assert not any(r.warnings for r in registros)


class TestLaCaraEnteraSueltaEsElUltimoRecurso:
    def test_sin_franjas_lo_que_queda_sin_identidad_se_relee_suelto(self):
        ocr = CascadaConLecturaSuelta()
        fuente = FuenteDePruebas([("",)] * 4)

        registros, stats = ReadDiplomaBook(ocr=ocr, workers=2).execute(fuente)

        assert ocr.remotas == 4
        assert len(ocr.sueltas) == 4, "las cuatro quedaron sin cédula ni nombre"
        assert [r.identity_number for r in registros] == ["73090716"] * 4
        assert [r.name for r in registros] == ["SANTIAGO LOPEZ JUAREZ"] * 4
        assert stats.repescadas == {"sueltas": 4}

    def test_con_nombre_de_la_franja_ya_no_se_relee_suelto(self):
        """Una cara con nombre tiene con qué nombrarse: la relectura es para las que no."""
        ocr = CascadaConLecturaSuelta()
        fuente = FuenteDePruebas([("",)] * 4)
        ReadDiplomaBook(
            ocr=ocr, workers=2, mosaico=MosaicoFalso(lambda p: "ANA MARIA GOMEZ")
        ).execute(fuente)
        assert ocr.sueltas == []

    def test_con_la_lectura_de_ahorro_no_se_relee_nada_suelto(self):
        """El ahorro es una renuncia: franjas y nada más."""
        ocr = CascadaConLecturaSuelta()
        fuente = FuenteDePruebas([("",)] * 4)
        ReadDiplomaBook(
            ocr=ocr,
            workers=2,
            mosaico=MosaicoFalso(lambda p: None),
            mosaico_de_cedulas=MosaicoFalso(lambda p: None),
            lectura_de_ahorro=True,
        ).execute(fuente)
        assert ocr.remotas == 0, "con el ahorro la hoja entera no se paga"
        assert ocr.sueltas == []


class TestUnaTandaQueVuelveVaciaSeReleeUnaAUna:
    """Dos tandas rechazadas por el proveedor dejaron 24 caras del libro 7
    nombradas por su orden, sin que nada lo dijera."""

    class CascadaQueRechazaLaTanda(CascadaConLecturaSuelta):
        def read_many_remote(self, imagenes):
            self.tandas.append(len(imagenes))
            return ["" for _ in imagenes]

    def test_las_caras_de_la_tanda_vacia_se_leen_sueltas(self):
        ocr = self.CascadaQueRechazaLaTanda()
        fuente = FuenteDePruebas([("",)] * 5)

        registros, stats = ReadDiplomaBook(ocr=ocr, workers=2).execute(fuente)

        assert ocr.tandas == [5]
        assert len(ocr.sueltas) == 5, "una lectura suelta por cara de la tanda vacía"
        assert [r.identity_number for r in registros] == ["73090716"] * 5
        assert stats.incomplete == []


class TestElMotorLocalSoloSigueSiSacaCedulas:
    """Con un motor de pago detrás, un nombre de Tesseract no cuenta como resolver.

    Sobre el libro 7 Tesseract "resolvió" quince caras con nombres como "UUY DL
    YEC CHAUS URAS LLES", que pasaron por nombre y nunca llegaron a la IA, y de
    paso gastó seis minutos leyendo las otras trescientas setenta.
    """

    def test_nombres_sin_cedula_en_la_muestra_no_bastan_para_seguir(self):
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        ocr._local = "UUY DL YEC CHAUS URAS LLES\nNombres y apellidos del graduando"
        fuente = FuenteDePruebas([("",)] * 40)

        registros, _ = ReadDiplomaBook(ocr=ocr, workers=4).execute(fuente)

        assert len(ocr.locales) == 16, "la muestra y nada más"
        assert ocr.remotas == 40, "todas van al motor de pago"
        assert [r.name for r in registros] == ["SANTIAGO LOPEZ JUAREZ"] * 40

    def test_una_cedula_en_la_muestra_si_basta(self):
        ocr = CascadaConLecturaSuelta(en_tanda=ENTERA_SUELTA)
        ocr._local = SOLO_LA_CEDULA
        fuente = FuenteDePruebas([("",)] * 40)

        ReadDiplomaBook(ocr=ocr, workers=4, criterio=CriterioDeCorte.CEDULA).execute(fuente)

        assert len(ocr.locales) == 40, "Tesseract sirve en este libro: se sigue con todo"
        assert ocr.remotas == 0


class TestCaraACaraNoHayCosturasQueRevisar:
    class FuenteDudosa(FuenteDePruebas):
        def ink_of(self, page_number, band):
            return (0.018, 0.0)

    def test_cortando_cara_a_cara_no_se_avisa_de_uniones(self):
        registros, _ = ReadDiplomaBook(criterio=CriterioDeCorte.PAGINA).execute(
            self.FuenteDudosa([("",)] * 4)
        )
        assert not any("se unió a la anterior" in a for r in registros for a in r.warnings)

    def test_cortando_por_folio_la_costura_dudosa_si_se_declara(self):
        registros, _ = ReadDiplomaBook(criterio=CriterioDeCorte.FOLIO).execute(
            self.FuenteDudosa([("",)] * 4)
        )
        assert any("se unió a la anterior" in a for r in registros for a in r.warnings)
