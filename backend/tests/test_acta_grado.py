"""Las actas de grado: dónde empieza cada una, su número, su fecha y su inventario."""

from __future__ import annotations

from datetime import date

from openpyxl import load_workbook

from resolutions.adapters.excel_actas import escribir_inventario_de_actas
from resolutions.application.acta_consejo import CONSEJO, GRADO, FilaDeActa
from resolutions.domain.acta_grado import (
    actas_de_grado_del_pdf,
    apertura,
    fecha_de_grado,
    fecha_en_letras,
    leer_acta_de_grado,
)

MODERNA = (
    "UNIVERSIDAD DE CARTAGENA\nACTA DE GRADO N°. {numero}\n"
    "En la ciudad de Cartagena de Indias, a los doce (12) días del mes de "
    "Diciembre del año 2023, se reunieron en ceremonia de graduación..."
)
ANTIGUA = (
    "ACTA DE GRADO No. {numero}\nEn la ciudad de Cartagena, a los veintisiete (27) "
    "días del mes de Noviembre de mil novecientos ochenta (1.980), se graduó..."
)


class TestLaFecha:
    def test_moderna(self):
        assert fecha_de_grado(MODERNA.format(numero="054231116")) == date(2023, 12, 12)

    def test_antigua_con_el_anio_en_letras_y_cifra(self):
        assert fecha_de_grado(ANTIGUA.format(numero="03")) == date(1980, 11, 27)

    def test_mes_mal_leido(self):
        texto = "a los doce (12) dias del mes de Dicienbre del año 2023"
        assert fecha_de_grado(texto) == date(2023, 12, 12)

    def test_sin_fecha(self):
        assert fecha_de_grado("ACTA DE GRADO sin nada más") is None


class TestLaApertura:
    def test_el_numero_con_su_cero(self):
        hoja = apertura(MODERNA.format(numero="054231116"), 4)
        assert hoja is not None
        assert (hoja.pagina, hoja.numero, hoja.fecha) == (4, "054231116", date(2023, 12, 12))

    def test_el_listado_no_abre_un_acta(self):
        listado = "Actas de Grado No. 05417710 a 05417725\nEn la ciudad de Cartagena..."
        assert apertura(listado) is None

    def test_sin_cuerpo_no_es_un_acta(self):
        assert apertura("Constancia: se expidió el ACTA DE GRADO No. 12.") is None


def _fila(**cambios) -> FilaDeActa:
    datos = dict(
        archivo="UPD.pdf",
        acta="",
        fecha="12-12-2023",
        folio_inicial=1,
        folio_final=1,
        folios=1,
        resumen="no debe salir",
        carpeta="00C003290",
    )
    return FilaDeActa(**{**datos, **cambios})


class TestElExcelDeGrado:
    def test_sin_resumen_y_con_su_titulo(self, tmp_path):
        fila = _fila(acta="ACTA DE GRADO No. 054231116", tipo=GRADO.tipo_documental)
        destino = escribir_inventario_de_actas(
            [fila], tmp_path / "grado.xlsx", titulo=GRADO.titulo, con_resumen=GRADO.con_resumen
        )
        hoja = load_workbook(destino).active
        assert hoja["A1"].value == "INVENTARIO DE ACTAS DE GRADO"
        columnas = [c.value for c in hoja[8]]
        assert "Acta" in columnas
        assert not any(c and "Resumen" in c for c in columnas)
        assert "no debe salir" not in [c.value for c in hoja[9]]

    def test_el_de_consejo_sigue_con_resumen(self, tmp_path):
        destino = escribir_inventario_de_actas(
            [_fila(acta="ACTA ORDINARIA No. 001")],
            tmp_path / "consejo.xlsx",
            titulo=CONSEJO.titulo,
            con_resumen=CONSEJO.con_resumen,
        )
        hoja = load_workbook(destino).active
        assert hoja["A1"].value == "INVENTARIO DE ACTAS DE CONSEJO"
        assert any(c.value and "Resumen" in c.value for c in hoja[8])


class TestLosNumerosDudosos:
    def test_el_cero_no_es_un_numero(self):
        hoja = apertura(ANTIGUA.format(numero="0"))
        assert hoja is not None and hoja.numero is None


class TestSiDividirFallaElInventarioSeEscribeIgual:
    def test_el_excel_sale_con_el_motivo(self, tmp_path, monkeypatch):
        import fitz

        from resolutions.api.worker import inventario as trabajo
        from resolutions.application import acta_consejo

        origen = tmp_path / "libro.pdf"
        with fitz.open() as doc:
            for numero in ("054231116", "054231117"):
                doc.new_page().insert_text((40, 60), MODERNA.format(numero=numero)[:120])
            doc.save(origen)

        def roto(*_a, **_k):
            raise OSError("[WinError 206] El nombre del archivo es demasiado largo")

        monkeypatch.setattr(acta_consejo, "dividir_actas", roto)
        payload = {
            "job_id": "t",
            "source": str(origen),
            "filename": "libro.pdf",
            "task": "both",
            "settings": {"ocr_language": "spa", "output_dir": str(tmp_path / "salida")},
        }

        informe = trabajo._acta_consejo_job(payload, grado=True)

        assert "WinError 206" in informe["division_error"]
        assert any("no se pudo dividir" in aviso for aviso in informe["notices"])
        assert informe.get("inventario"), informe.get("inventario_error")
        assert all(
            fila["resultado"].startswith("No se pudo dividir") for fila in informe["inventario_actas"]
        )


class TestLaFechaEnLetras:
    """Los formularios de 1980 a 2005: huecos rellenos a máquina, cifras rotas."""

    def test_la_frase_en_orden_con_las_cifras_rotas(self):
        texto = (
            "EN LA CIUDAD DE CARTAGENA, A LOS VEINTISIETE (2?) DIAS DEL MES DE NOVIEMBRE DE "
            "MIL NOVECIENTOS OCHENTA (1.980), REALIZO LA GRADUACION"
        )
        assert fecha_de_grado(texto) == date(1980, 11, 27)

    def test_el_dia_detras_del_anio(self):
        texto = (
            "EN LA CIUDAD DE CARTAGENA, A LOS DE MIL NOVECIENTOS NOVENTA Y DOS ONCE I "
            "DICIEMBRE LA GRADUACION A SOLICITUD DEL DECANO, QUIEN AUTORIZO EL ACTO MEDIANTE "
            "RESOLUCION NO DE FECHA DIEZ (10) DE DICIEMBRE"
        )
        assert fecha_de_grado(texto) == date(1992, 12, 11)

    def test_el_uno_escrito_un_entre_novecientos_y_la_decena(self):
        texto = "EN LA CIUDAD DE CARTAGENA, A LOS DE MIL NOVECIENTOS UN NOVENTA Y SEIS MARZO LA GRADUACION"
        assert fecha_de_grado(texto) == date(1996, 3, 1)

    def test_una_palabra_rota_en_medio_del_anio(self):
        texto = (
            "EN LA CIUDAD DE CARTAGENA, A LOS DIECIOCHO DE MIL NOVECIENTOS OCHENTA Y "
            "COLECTIVA.- SIETE DICIEMBRE.- LA GRADUACION"
        )
        assert fecha_de_grado(texto) == date(1987, 12, 18)

    def test_palabras_mal_leidas(self):
        texto = "EN LA CIUDAD DE CARTAGENA, A LOS CUATRO DE MIL NOVECIENTOS NOVENTA Y AIETE ABRIL LA GRADUACION"
        assert fecha_de_grado(texto) == date(1997, 4, 4)

    def test_el_dia_en_letras_y_el_anio_en_cifras(self):
        texto = "EN LA CIUDAD DE CARTAGENA A LOS DIEZ (LO) DIAS DEL MES DE DICIEMBRE DE 2004 A CABO"
        assert fecha_de_grado(texto) == date(2004, 12, 10)

    def test_dos_mil(self):
        assert fecha_en_letras("A LOS TRES DIAS DEL MES DE MAYO DE DOS MIL CINCO") == date(2005, 5, 3)

    def test_demasiado_roto_no_inventa(self):
        texto = "EN LA CIUDAD DE CARTAGENA, A LOS DE MIL NOVECIENTOS NOOENTA CATOXHSE DIEIMINII - LA GRADUACION"
        assert fecha_de_grado(texto) is None


ANTIGUA_EN_FECHA = (
    "ACTA DE GRADO No. {numero}\nEn la ciudad de Cartagena, a los catorce (14) días del mes de "
    "Diciembre de mil novecientos ochenta y ocho (1.988), se graduó..."
)


class TestLasFechasFueraDeLugar:
    def test_la_que_se_aparta_de_sus_vecinas(self):
        from resolutions.domain.acta_consejo import fechas_fuera_de_lugar

        fechas = [date(1981, 6, 23), date(1981, 11, 27), date(1947, 11, 7), date(1982, 3, 16), date(1983, 5, 23)]
        assert fechas_fuera_de_lugar(fechas) == {2: (1981, 1983)}

    def test_un_libro_en_orden_no_pierde_ninguna(self):
        from resolutions.domain.acta_consejo import fechas_fuera_de_lugar

        fechas = [date(2007, 1, 29), None, date(2008, 2, 6), date(2008, 9, 1), date(2009, 2, 4)]
        assert fechas_fuera_de_lugar(fechas) == {}

    def test_el_inventario_la_quita_y_dice_cual_era(self):
        from test_acta_consejo import Fuente

        from resolutions.application.acta_consejo import InventariarActa

        def acta(numero, anio):
            return ANTIGUA_EN_FECHA.format(numero=numero).replace("ochenta y ocho (1.988)", f"({anio})")

        paginas = [acta("01", 1981), acta("02", 1981), acta("03", 1947), acta("04", 1982), acta("05", 1983)]
        outcome = InventariarActa(perfil=GRADO).execute(Fuente(paginas), document_name="libro.pdf")

        tercera = outcome.filas[2]
        assert tercera.fecha == "N/A"
        assert "se leyó la fecha 14-12-1947" in tercera.observaciones
        assert [f.fecha for f in outcome.filas if f is not tercera] == [
            "14-12-1981", "14-12-1981", "14-12-1982", "14-12-1983",
        ]


class TestLosNombres:
    def test_una_carpeta_con_punto_no_pierde_su_nombre(self):
        from resolutions.domain.naming import document_folder, sheet_filename

        assert sheet_filename("ACTAS 15. ODONTOLOGIA 3284 - 3290", "__inventario.xlsx") == (
            "ACTAS 15. ODONTOLOGIA 3284 - 3290__inventario.xlsx"
        )
        assert sheet_filename("libro.pdf", "__inventario.xlsx") == "libro__inventario.xlsx"
        assert document_folder("UPD3859797-ACTAS.pdf") == "UPD3859797-ACTAS"

    def test_la_leyenda_del_de_grado_no_habla_del_resumen(self, tmp_path):
        destino = escribir_inventario_de_actas(
            [_fila(acta="ACTA DE GRADO No. 1")], tmp_path / "g.xlsx", titulo=GRADO.titulo, con_resumen=False
        )
        hoja = load_workbook(destino).active
        textos = [c.value for fila in hoja.iter_rows() for c in fila if isinstance(c.value, str)]
        leyenda = next(t for t in textos if t.startswith("El acta y la fecha"))
        assert "resumen" not in leyenda


# -- una fila por graduado ------------------------------------------------------

LISTADO = "UNIVERSIDAD DE CARTAGENA\nFacultad de Enfermería\nListado de Graduandos\nCeremonia de Grado: 12 de diciembre de 2023"
RESOLUCION = "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 02865\nPor medio de la cual se autoriza una ceremonia de grado"
REVERSO = "22 de dic de 2017"


class TestElRepartoPorEstudiante:
    def test_cada_acta_es_un_graduado_y_la_ceremonia_va_aparte(self):
        paginas = [
            LISTADO,
            RESOLUCION,
            MODERNA.format(numero="054231116"),
            REVERSO,
            MODERNA.format(numero="054231117"),
            LISTADO,
            MODERNA.format(numero="054231118"),
        ]
        reparto = actas_de_grado_del_pdf(paginas)

        assert [(t.desde, t.hasta, t.ceremonia) for t in reparto.tramos] == [
            (1, 2, True),
            (3, 4, False),
            (5, 5, False),
            (6, 6, True),
            (7, 7, False),
        ]
        # El reverso va con su acta: dos páginas en «No. de folios».
        assert [t.hojas for t in reparto.tramos if not t.ceremonia] == [2, 1, 1]
        assert reparto.previas is None

    def test_el_mismo_numero_en_varias_hojas_son_varios_graduados(self):
        # Los libros antiguos: el número de la ceremonia en la hoja de cada uno.
        paginas = [ANTIGUA.format(numero="03")] * 3
        assert len(actas_de_grado_del_pdf(paginas).tramos) == 3

    def test_un_acta_sin_encabezado_legible_sigue_siendo_un_graduado(self):
        cuerpo = "En la ciudad de Cartagena ... la graduación ... cédula de ciudadanía No. 1 ... el juramento"
        paginas = [MODERNA.format(numero="054231116"), cuerpo]
        assert [t.ceremonia for t in actas_de_grado_del_pdf(paginas).tramos] == [False, False]

    def test_cubre_todas_las_hojas_una_vez(self):
        paginas = ["portada", LISTADO, MODERNA.format(numero="1"), REVERSO, RESOLUCION]
        tramos = actas_de_grado_del_pdf(paginas).tramos
        cubiertas = [p for t in tramos for p in range(t.desde, t.hasta + 1)]
        assert cubiertas == list(range(1, len(paginas) + 1))

    def test_la_hoja_sin_folio_es_el_vuelto_de_la_anterior(self):
        # Como UPD3859820: el listado (146) con su folio, la resolución (147,
        # «140/V») y su segunda página sin folio (148), y los graduados.
        paginas = [LISTADO, RESOLUCION, "continuación de la resolución", MODERNA.format(numero="1")]
        reparto = actas_de_grado_del_pdf(paginas, foliadas=[1, 2, 4])
        assert [(t.desde, t.hasta, t.ceremonia, t.hojas) for t in reparto.tramos] == [
            (1, 1, True, 1),
            (2, 3, True, 2),
            (4, 4, False, 1),
        ]

    def test_un_acta_sin_folio_visible_sigue_siendo_su_fila(self):
        paginas = [MODERNA.format(numero="1"), MODERNA.format(numero="2")]
        assert len(actas_de_grado_del_pdf(paginas, foliadas=[1]).tramos) == 2

    def test_la_ceremonia_se_lee_como_ceremonia(self):
        acta = leer_acta_de_grado([LISTADO, RESOLUCION])
        assert acta.rotulo == "CEREMONIA DE GRADO"
        assert acta.fecha == date(2023, 12, 12)


MODERNA_COMPLETA = (
    "LA UNIVERSIDAD DE CARTAGENA\nCartagena de Indias, Colombia\n"
    "ACTA DE GRADO N\". 054231116\n"
    "En la ciudad de Cartagena a los doce (12) días del mes de Diciembre del año\n"
    "2023, se llevó a cabo ceremonia solemne de graduación colectiva, por solicitud\n"
    "de la decana de la Facultad de Enfermería al señor Rector, otorga el título de;\n"
    "ENFERMERO\nA\nANDRES FELIPE BALLESTAS MENDOZA\n"
    "Portador de la cédula de ciudadanía N°. 1.049.539.266 expedida en SAN\n"
    "ESTANISLAO, a quien se le tomó el juramento de rigor y se le hizo entrega del\n"
    "diploma que lo autoriza para ejercicio profesional como ENFERMERO, según\n"
    "las disposiciones legales vigentes.\nPara constancia de lo expuesto, se firma\n"
    "SERGIO HERNANDEZ GAMARRA\nRector"
)
#: El modelo del operador: el formulario de 2005, con «al profesional».
FORMULARIO_2005 = (
    "LA UNIVERSIDAD DE CARTAGENA\nACTA DE GRADO No. 01/05\n"
    "En la ciudad de Cartagena a los 3 días del mes de marzo de 2005 , se llevo\n"
    "por medio de la cual, otorga de acuerdo a la Ley y los estatutos de la Universidad,\n"
    "el título de: ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA al profesional\n"
    "MARTHA LUCIA HERRERA VILLAMIZAR ,portador de la cédula de\n"
    "ciudadanía No.39.692.338 expedida en Bogotá D.C. , a quien se le\n"
    "tomó el juramento de rigor y se le hizo entrega del diploma que lo autoriza para el\n"
    "ejercicio profesional como: ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD"
)
#: Un libro de 1989: la capa del escáner parte el nombre y aleja la cédula.
FORMULARIO_1989 = (
    "ACTA DE GRADO No. 02\nEn la ciudad de Cartagena, a los ve inte y seis —— (26 ) días del mes de\n"
    "cual, otorga, de acuerdo a la Ley y los Estatutos de la Universidad,\n"
    "al estudiante LIGIA del pilar\nde mayo\nde fecha 24\nel titulo de enfermera\n"
    "portador de la cédula de ciudadanía\na quien se le tomó\nPEREZ REYES\nNq 50.847.263\n"
    "expedida entere té (Córdoba)\nel juramento de rigor"
)


class TestElGraduado:
    def test_el_acta_moderna(self):
        from resolutions.domain.graduado import graduado

        g = graduado(MODERNA_COMPLETA)
        assert (g.numero, g.nombre, g.titulo, g.cedula) == (
            "054231116", "ANDRES FELIPE BALLESTAS MENDOZA", "ENFERMERO", "1049539266",
        )
        assert g.dudas == ()

    def test_el_modelo_del_operador(self):
        from resolutions.domain.graduado import graduado

        g = graduado(FORMULARIO_2005)
        assert g.numero == "01/05"
        assert g.nombre == "MARTHA LUCIA HERRERA VILLAMIZAR"
        assert g.titulo == "ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD"
        assert g.cedula == "39692338"

    def test_el_formulario_antiguo_con_el_nombre_partido(self):
        from resolutions.domain.graduado import graduado

        g = graduado(FORMULARIO_1989)
        assert g.nombre == "LIGIA DEL PILAR PEREZ REYES"
        assert g.cedula == "50847263"
        assert g.numero == "02"

    def test_el_numero_sin_el_no_y_con_letras_del_ocr(self):
        from resolutions.domain.graduado import numero_impreso

        assert numero_impreso("ACTA DE GRADO 054i6609\nEn la ciudad") == "05416609"
        assert numero_impreso("ACTA DE GRADO No. oi\nEn la ciudad") == "01"
        assert numero_impreso("ACTA DE GRADO No. 082-2005") == "082-2005"

    def test_la_cedula_que_la_capa_puso_delante(self):
        from resolutions.domain.graduado import cedula

        texto = "JUAN CAMILO ARIAS BARRAZA\n1.047.473.026 expedida en\nPortador de la cédula de ciudadanía N°.\nCARTAGENA"
        assert cedula(texto) == "1047473026"

    def test_un_trozo_de_cifra_no_es_una_cedula(self):
        from resolutions.domain.graduado import cedula

        assert cedula("portador de la cédula de ciudadanía No. 45.474 expedida") is None

    def test_el_relleno_de_la_maquina_se_quita(self):
        from resolutions.domain.graduado import titulo

        assert titulo("profesional como: ENFERMERA .X.X.X.X.X,X.X.X") == "ENFERMERA"

    def test_un_nombre_con_signos_se_marca_dudoso(self):
        from resolutions.domain.graduado import graduado

        texto = FORMULARIO_2005.replace("MARTHA LUCIA HERRERA VILLAMIZAR", "MARTHA LUC:A HERRERA VILLAMIZAR")
        assert graduado(texto).dudas


class Ocr:
    """Un motor que devuelve un texto y cuenta cuántas hojas leyó."""

    def __init__(self, texto):
        self.texto = texto
        self.leidas = 0

    def read(self, imagen):
        from resolutions.application.ports import OcrResult

        self.leidas += 1
        return OcrResult(text=self.texto)


class TestLaRelectura:
    def _inventario(self, paginas, ocr, pago=None):
        from test_acta_consejo import Fuente

        from resolutions.application.acta_consejo import InventariarActa

        return InventariarActa(ocr=ocr, perfil=GRADO, relector_de_pago=pago).execute(
            Fuente(paginas, foliadas=range(1, len(paginas) + 1)), document_name="libro.pdf"
        )

    def test_tesseract_completa_lo_que_la_capa_no_trae(self):
        sin_cedula = MODERNA_COMPLETA.replace("N°. 1.049.539.266", "N°. ilegible")
        casa = Ocr(MODERNA_COMPLETA)
        outcome = self._inventario([sin_cedula], casa)

        fila = outcome.filas[0]
        assert (fila.cedula, fila.nombre) == ("1049539266", "ANDRES FELIPE BALLESTAS MENDOZA")
        assert casa.leidas == 1
        assert fila.observaciones == ""

    def test_con_la_ia_se_lee_cada_hoja_una_vez(self):
        """Tesseract, sólo lo que falta; la IA, toda hoja de graduado, una vez (2026-10-31)."""
        completa = MODERNA_COMPLETA
        sin_cedula = completa.replace("N°. 1.049.539.266", "N°. ilegible")
        casa, pago = Ocr(sin_cedula), Ocr(completa)
        outcome = self._inventario([completa, sin_cedula], casa, pago)

        assert [f.cedula for f in outcome.filas] == ["1049539266", "1049539266"]
        assert (casa.leidas, pago.leidas) == (1, 2)
        assert all(f.observaciones == "" for f in outcome.filas)

    def test_la_cedula_que_la_ia_lee_distinta_se_corrige_y_se_anota(self):
        """Una cifra mal leída pero completa ya no sale sin aviso."""
        mal = MODERNA_COMPLETA.replace("1.049.539.266", "1.049.539.286")
        outcome = self._inventario([mal], Ocr(mal), Ocr(MODERNA_COMPLETA))

        fila = outcome.filas[0]
        assert fila.cedula == "1049539266"
        assert "la cédula: el OCR leyó 1049539286 y la IA 1049539266" in fila.observaciones

    def test_lo_que_no_se_lee_va_a_las_notas(self):
        sin_cedula = MODERNA_COMPLETA.replace("N°. 1.049.539.266", "N°. ilegible")
        outcome = self._inventario([sin_cedula], Ocr(sin_cedula))
        assert outcome.filas[0].observaciones == "no se pudo leer la cédula"

    def test_la_ceremonia_no_se_relee(self):
        casa = Ocr(LISTADO)
        outcome = self._inventario([LISTADO, MODERNA_COMPLETA], casa)
        assert casa.leidas == 0
        assert [f.tipo for f in outcome.filas] == ["CEREMONIA DE GRADO", "ACTA DE GRADO"]

    def test_no_se_paga_el_folio_de_la_esquina(self):
        from test_acta_consejo import FolioPorActa, Fuente

        from resolutions.application.acta_consejo import InventariarActa

        folios = FolioPorActa("1")
        InventariarActa(perfil=GRADO, lector_de_folios=folios).execute(
            Fuente([MODERNA_COMPLETA], foliadas=[1]), document_name="libro.pdf"
        )
        assert folios.pedidas == []


class TestElFuidDeGrado:
    def _filas(self):
        from test_acta_consejo import Fuente

        from resolutions.application.acta_consejo import InventariarActa

        outcome = InventariarActa(perfil=GRADO).execute(
            Fuente([LISTADO, FORMULARIO_2005, MODERNA_COMPLETA.replace("1.049.539.266", "x")]),
            document_name="UPD3859821-ACTAS DE GRADO 2005.pdf",
            carpeta="00C003292",
        )
        return outcome.filas

    def test_la_fila_del_modelo(self, tmp_path):
        from resolutions.adapters.fuid_actas_de_grado import (
            escribir_fuid_de_actas_de_grado,
        )

        hoja = load_workbook(escribir_fuid_de_actas_de_grado(self._filas(), tmp_path / "f.xlsx")).active
        fila = [hoja.cell(14, columna).value for columna in range(1, 17)]
        assert fila[:12] == [
            1, None, "MARTHA LUCIA HERRERA VILLAMIZAR - ACTA DE GRADO No. 01/05 - "
            "ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD",
            "39692338", "N/A", "03/03/2005", "03/03/2005", "00C003292", "UPD3859821", None, None, 1,
        ]
        # Sin la IA el folio manuscrito no se lee: N/A en las dos columnas.
        assert fila[12] == fila[11]

    def test_la_cabecera_es_la_de_la_plantilla(self, tmp_path):
        from resolutions.adapters.fuid_actas_de_grado import (
            escribir_fuid_de_actas_de_grado,
        )

        hoja = load_workbook(escribir_fuid_de_actas_de_grado(self._filas(), tmp_path / "f.xlsx")).active
        assert hoja["C1"].value == "GESTIÓN DOCUMENTAL"
        assert hoja["P1"].value == "CÓDIGO: FO-GD-008"
        assert hoja["B8"].value.startswith("OFICINA PRODUCTORA:")

    def test_la_ceremonia_no_lleva_fila_y_lo_no_leido_va_a_las_notas(self, tmp_path):
        from resolutions.adapters.fuid_actas_de_grado import (
            escribir_fuid_de_actas_de_grado,
        )

        hoja = load_workbook(escribir_fuid_de_actas_de_grado(self._filas(), tmp_path / "f.xlsx")).active
        segunda = [hoja.cell(15, columna).value for columna in range(1, 17)]
        assert segunda[0] == 2
        assert segunda[3] == "N/A"
        assert segunda[15] is None  # NOTAS va vacía en el FUID que se entrega (2026-10-30)
        assert hoja.cell(16, 3).value in (None, "")

    def test_caja_y_carpeta_de_las_dos_formas_de_guardar(self):
        from resolutions.adapters.fuid_actas_de_grado import ubicacion

        assert ubicacion("00C003290", "UPD3859819-ACTA DE GRADO 2023.pdf") == ("00C003290", "UPD3859819")
        assert ubicacion("00C003284\\UPD3859771", "1N°22.pdf") == ("00C003284", "UPD3859771")
        assert ubicacion("", "libro.pdf") == ("", "")

    def test_sin_numero_el_asunto_conserva_su_forma(self, tmp_path):
        from resolutions.adapters.fuid_actas_de_grado import filas_del_fuid

        fila = {**{k: "" for k in ("carpeta", "archivo")}, "acta": "N/A", "nombre": "ANA RUIZ", "titulo": "ENFERMERA", "tipo": "ACTA DE GRADO"}
        assert filas_del_fuid([fila])[0].asunto == "ANA RUIZ - ACTA DE GRADO No. N/A - ENFERMERA"


class TestElFolioManuscrito:
    """El folio escrito a mano en la esquina de la hoja de cada graduado."""

    def test_la_foliacion_seguida_confirma_corrige_y_deduce(self):
        from resolutions.domain.acta_grado import folios_de_la_foliacion

        orden = {pagina: puesto for puesto, pagina in enumerate([3, 4, 5, 6, 7, 8, 9, 10], start=1)}
        leidos = {3: 4, 4: 5, 6: 7, 7: 99, 8: 9, 10: 11}
        folios = folios_de_la_foliacion(leidos, orden)
        assert folios[3] == (4, "leído", None)
        assert folios[7] == (8, "corregido", 99)
        assert folios[5] == (6, "deducido", None)

    def test_las_etiquetas_dicen_de_que_hoja_es_cada_numero(self):
        from resolutions.adapters.esquinas_del_folio import folios_etiquetados

        texto = "P146 139\n\nP147 140/V\n\nP149\n\nP150 142"
        assert folios_etiquetados(texto, [146, 147, 149, 150]) == {146: 139, 147: 140, 150: 142}

    def test_el_folio_llega_a_la_fila_y_al_fuid(self, tmp_path):
        from test_acta_consejo import Fuente

        from resolutions.adapters.fuid_actas_de_grado import (
            escribir_fuid_de_actas_de_grado,
        )
        from resolutions.application.acta_consejo import InventariarActa

        class LectorEtiquetado:
            def __init__(self):
                self.mosaicos = 0

            def armar_mosaico_etiquetado(self, source, paginas):
                return b"mosaico"

            def leer_mosaico_etiquetado(self, imagen, paginas):
                self.mosaicos += 1
                return {pagina: pagina + 100 for pagina in paginas}

        lector = LectorEtiquetado()
        paginas = [MODERNA_COMPLETA, "vuelto", MODERNA_COMPLETA]
        outcome = InventariarActa(perfil=GRADO, lector_de_folios=lector).execute(
            Fuente(paginas, foliadas=[1, 3]), document_name="UPD3859820-ACTAS.pdf", carpeta="00C003290"
        )
        assert [(f.folio_inicial, f.pagina_inicial, f.pagina_final) for f in outcome.filas] == [
            (101, 1, 2),
            (103, 3, 3),
        ]
        assert lector.mosaicos == 1  # las dos hojas en una página facturada
        hoja = load_workbook(escribir_fuid_de_actas_de_grado(outcome.filas, tmp_path / "f.xlsx")).active
        # Un folio (el 101 con su vuelto) y dos páginas escaneadas (2026-10-31).
        assert (hoja["L14"].value, hoja["M14"].value) == (1, 2)

    def test_el_folio_se_pide_mientras_se_releen_las_franjas(self):
        """La IA lee las esquinas por la red mientras Tesseract relee en la CPU.

        Iban una detrás de otra: primero todas las franjas, y sólo después los
        folios. Aquí la franja espera a ver el folio ya pedido; con el orden
        viejo esperaría en vano.
        """
        import threading

        from test_acta_consejo import Fuente

        from resolutions.application.acta_consejo import InventariarActa

        en_marcha = threading.Event()

        class LectorEtiquetado:
            def armar_mosaico_etiquetado(self, source, paginas):
                return b"mosaico"

            def leer_mosaico_etiquetado(self, imagen, paginas):
                en_marcha.set()
                return {pagina: pagina + 100 for pagina in paginas}

        class Franja:
            def __init__(self):
                self.vio_el_folio_pedido: list[bool] = []

            def read_con_confianza(self, imagen):
                self.vio_el_folio_pedido.append(en_marcha.wait(timeout=2))
                return "", {}

        class ConZonas(Fuente):
            def trozos_of(self, numero):
                return []

            def size_of(self, numero):
                return (600.0, 800.0)

        franja = Franja()
        outcome = InventariarActa(
            perfil=GRADO, lector_de_folios=LectorEtiquetado(), lector_de_franja=franja
        ).execute(
            ConZonas([MODERNA_COMPLETA, "vuelto", MODERNA_COMPLETA], foliadas=[1, 3]),
            document_name="UPD3859820-ACTAS.pdf",
        )
        assert franja.vio_el_folio_pedido and all(franja.vio_el_folio_pedido)
        assert [f.folio_inicial for f in outcome.filas] == [101, 103]

    def test_sin_ia_el_folio_queda_na(self, tmp_path):
        from test_acta_consejo import Fuente

        from resolutions.adapters.fuid_actas_de_grado import (
            escribir_fuid_de_actas_de_grado,
        )
        from resolutions.application.acta_consejo import InventariarActa

        outcome = InventariarActa(perfil=GRADO).execute(Fuente([MODERNA_COMPLETA]), document_name="x.pdf")
        hoja = load_workbook(escribir_fuid_de_actas_de_grado(outcome.filas, tmp_path / "f.xlsx")).active
        # Sin la IA no se lee el folio de la esquina, pero el acta tiene un folio y una página.
        assert (hoja["L14"].value, hoja["M14"].value) == (1, 1)


class TestElFormularioPorZonas:
    """Lo rellenado a máquina va en otra letra y por encima de su renglón: se lee en su sitio."""

    def _trozos(self):
        from resolutions.domain.formulario import Trozo

        impresa, maquina = "Times|0", "Times|16"
        # Las cajas del acta 87 de UPD3859807 (CLARA INES VARGAS CASSIANI).
        return [
            Trozo("03", 423.9, 107.8, 437.1, 120.7, "Arial|0"),
            Trozo("ACTA DE GRADO No.", 186.0, 120.6, 400.6, 137.1, impresa),
            Trozo("CLARA INES", 473.0, 346.8, 546.1, 360.1, maquina),
            Trozo("ENFERMERA", 167.8, 349.3, 257.4, 363.7, maquina),
            Trozo("al estudiante", 366.7, 356.4, 448.9, 371.5, impresa),
            Trozo("el titulo de", 48.0, 356.6, 126.3, 371.7, impresa),
            Trozo("VARGAS CASSIANI", 73.2, 379.3, 183.6, 392.7, maquina),
            Trozo("portador de la cédula de ciudadanía", 303.9, 385.7, 537.2, 400.8, impresa),
            Trozo("45.582.244", 93.6, 407.6, 156.2, 422.0, maquina),
            Trozo("expedida en", 172.3, 415.5, 246.5, 430.2, impresa),
            Trozo("No.", 48.5, 416.4, 67.2, 430.2, impresa),
        ]

    def test_cada_dato_queda_junto_a_su_rotulo(self):
        from resolutions.domain.formulario import texto_del_formulario

        renglones = texto_del_formulario(self._trozos()).splitlines()
        assert renglones == [
            "ACTA DE GRADO No. 03",
            "el titulo de ENFERMERA al estudiante CLARA INES",
            "VARGAS CASSIANI portador de la cédula de ciudadanía",
            "No. 45.582.244 expedida en",
        ]

    def test_gana_la_lectura_que_mas_dice(self):
        from resolutions.domain.acta_grado import mejor_lectura
        from resolutions.domain.formulario import texto_del_formulario
        from resolutions.domain.graduado import graduado

        # La capa del escáner, con cada dato fuera de su sitio.
        capa = "\n".join(
            ["03", "ACTA DE GRADO No.", "CLARA INES", "ENFERMERA", "al estudiante", "el titulo de", "VARGAS CASSIANI"]
        )
        g = graduado(mejor_lectura(capa, texto_del_formulario(self._trozos())))
        assert (g.numero, g.nombre, g.cedula) == ("03", "CLARA INES VARGAS CASSIANI", "45582244")

    def test_diez_y_siete(self):
        assert fecha_en_letras("A LOS DIEZ Y SIETE ( J DIAS DEL MES DE DICIEMBRE DE MIL NOVECIENTOS NOVENTA Y NUEVE") == date(1999, 12, 17)

    def test_una_mancha_del_margen_no_se_pega_al_nombre(self):
        from resolutions.domain.formulario import Trozo, texto_del_formulario
        from resolutions.domain.graduado import graduado

        impresa, maquina = "Times|0", "Times|16"
        # Como el acta de RAQUEL MARIA ROCHA MARIN: una «I» en el borde derecho.
        trozos = [
            Trozo("el titulo de", 44.4, 355.4, 122.9, 369.6, impresa),
            Trozo("ENFERMERA", 133.2, 350.0, 213.5, 361.5, maquina),
            Trozo("al estudiante", 363.4, 353.8, 445.6, 368.9, impresa),
            Trozo("RAQUEL", 448.3, 355.2, 499.3, 368.5, maquina),
            Trozo("I", 574.1, 343.3, 576.3, 353.3, "Arial|16"),
            Trozo("MARIA ROCHA MARIN", 60.0, 380.0, 180.0, 393.0, maquina),
            Trozo("portador de la cédula de ciudadanía", 303.9, 385.7, 537.2, 400.8, impresa),
        ]
        assert graduado(texto_del_formulario(trozos)).nombre == "RAQUEL MARIA ROCHA MARIN"

    def test_el_recuadro_del_numero_va_detras_de_su_rotulo(self):
        from resolutions.domain.formulario import Trozo, recuadro_tras

        impresa = "Times|0"
        trozos = [
            Trozo("ACTA", 182.6, 119.4, 232.8, 135.7, impresa),
            Trozo("DE", 248.9, 120.2, 270.3, 135.4, impresa),
            Trozo("GRADO", 285.9, 118.5, 357.6, 135.9, impresa),
            Trozo("No.", 378.0, 121.0, 397.7, 135.2, impresa),
        ]
        x0, y0, x1, y1 = recuadro_tras(trozos, "ACTA DE GRADO")
        # Desde el «No.» hacia la derecha, y por encima del renglón.
        assert x0 == 397.7 and y0 < 121.0 and x1 > 500 and y1 >= 135.2

    def test_la_cedula_con_apostrofo_en_los_millones(self):
        from resolutions.domain.graduado import cedula

        assert cedula("portador de la cédula de ciudadanía\nNo. 45 ’ 430.411 expedida en") == "45430411"
        assert cedula("portador de la cédula de ciudadanía\nNo. 45'366.705 expedida en") == "45366705"

    def test_la_basura_del_ocr_junto_al_nombre_se_quita(self):
        from resolutions.domain.graduado import nombre

        texto = (
            "el título de ESPECIALISTA EN SALUD FAMILIAR al estudiante marelvis ',3\n"
            "MIRANDA FILOTH portador de la cédula de ciudadanía"
        )
        assert nombre(texto, "ESPECIALISTA EN SALUD FAMILIAR") == "MARELVIS MIRANDA FILOTH"


class TestLaFranjaReleida:
    """La capa del escáner y la franja releída con Tesseract, juntas palabra a palabra."""

    def test_cada_lectura_pone_lo_que_la_otra_no_supo(self):
        from resolutions.domain.graduado import fusionar_nombres

        casos = [
            # (capa, franja, confianza de Tesseract por palabra, nombre real)
            ("LEONOR CAMPO TORREGROZA", "ETILVIA TEDIDE CAAO TORRCECOIDA",
             {"ETILVIA": 90, "TEDIDE": 0, "CAAO": 36, "TORRCECOIDA": 0}, "ETILVIA LEONOR CAMPO TORREGROZA"),
            ("REGINA BORDA MARTELO", "NORA REGINA BORDA MARTELO",
             {"NORA": 88, "REGINA": 88, "BORDA": 92, "MARTELO": 93}, "NORA REGINA BORDA MARTELO"),
            ("BELINDA INES LEE OSORIO", "BELINDA INES", {"BELINDA": 90, "INES": 90}, "BELINDA INES LEE OSORIO"),
            ("?M.O MAHUEL MAKTUIEZ CEFFIÍEÍLO", "PEDRO MANUEL MARTINEZ CERMEÑO",
             {"PEDRO": 92, "MANUEL": 93, "MARTINEZ": 93, "CERMEÑO": 90}, "PEDRO MANUEL MARTINEZ CERMEÑO"),
            # El relleno pegado le baja la confianza a una palabra bien leída.
            ("JANIRES DEL CARMEN MEDINA IWITINEZ", "JANIRES DEL CARMEN MEDINA MARTINEZ",
             {"JANIRES": 87, "DEL": 93, "CARMEN": 93, "MEDINA": 92, "MARTINEZ,X.XEXOX.X.X.": 5},
             "JANIRES DEL CARMEN MEDINA MARTINEZ"),
        ]
        for capa, franja, confianza, real in casos:
            assert fusionar_nombres(capa, franja, confianza)[0] == real

    def test_lo_que_ninguna_supo_queda_dudoso(self):
        from resolutions.domain.graduado import fusionar_nombres

        nombre, dudoso = fusionar_nombres(
            "OHIRLEÍ DEL CMEN CARMOM VELEZ", "SURREY DEL CARMEN CARMONA VELEG",
            {"SURREY": 7, "DEL": 90, "CARMEN": 81, "CARMONA": 89, "VELEG": 14},
        )
        assert nombre.endswith("DEL CARMEN CARMONA VELEZ") and dudoso

    def test_la_cedula_releida_solo_gana_si_es_segura(self):
        from resolutions.domain.graduado import Graduado, fusionar

        capa = Graduado(nombre="ANA RUIZ", cedula="45366705")
        insegura = fusionar(capa, Graduado(cedula="204705"), {"204.705": 40})
        segura = fusionar(capa, Graduado(cedula="45366706"), {"45'366.706": 95})
        assert (insegura.cedula, segura.cedula) == ("45366705", "45366706")

    def test_el_titulo_sin_lo_que_se_le_pega(self):
        from resolutions.domain.graduado import titulo

        assert titulo("el titulo de ENFERMERA ,X.XEXOXOXOXO al estudiante") == "ENFERMERA"
        assert titulo("el título de: ESPECIALISTA EN SALUD OCUPACIONAL a| estudiante") == (
            "ESPECIALISTA EN SALUD OCUPACIONAL"
        )
        assert titulo("el titulo de CON ENFASIS EN CUIDADOS INTENSIVOS A(F ESTUDIANTE INGRID") == (
            "CON ENFASIS EN CUIDADOS INTENSIVOS"
        )

    def test_el_titulo_suelto_se_lleva_al_que_se_repite_en_el_libro(self):
        from resolutions.domain.graduado import titulos_unificados

        titulos = ["ESPECIALISTA EN SALUD FAMILIAR"] * 3 + ["ESPECIALISTA ENSALUD FAMILIAR", "ODONTOLOGO"]
        assert titulos_unificados(titulos)[3:] == ["ESPECIALISTA EN SALUD FAMILIAR", "ODONTOLOGO"]


class TestElNombreYElTituloLimpios:
    """Secretaría 3292 contra el modelo del operador (2026-10-31): de 42 a 52 nombres exactos de 54."""

    def test_el_titulo_pegado_al_nombre_se_quita(self):
        from resolutions.domain.graduado import nombre_limpio

        assert nombre_limpio("ILUMINADA CASTELLAR ARRIETA TNGENIERO", "INGENIERO CIVIL") == "ILUMINADA CASTELLAR ARRIETA"
        assert nombre_limpio("TITULODE INGENIERA ODALIS BEATRIZ OLEA SUAREZ") == "ODALIS BEATRIZ OLEA SUAREZ"
        assert nombre_limpio("JOSE MARIO GUARDO ROA INGENIERO CIVIL") == "JOSE MARIO GUARDO ROA"
        assert nombre_limpio("SENEN CANTILLO PATERNINA N TNA") == "SENEN CANTILLO PATERNINA"

    def test_la_x_de_chequeo_no_es_del_apellido(self):
        from resolutions.domain.graduado import nombre_limpio

        assert nombre_limpio("NASLY MARIA ESPINOSA BAENAX") == "NASLY MARIA ESPINOSA BAENA"
        assert nombre_limpio("FELIX ALEX PEREZ PAZ") == "FELIX ALEX PEREZ PAZ"

    def test_el_trozo_de_la_palabra_partida_no_es_otro_nombre(self):
        """UPD3859819 p. 21: la capa dice «MONTO YA»; el voto unió MONTOYA y «YA» se quedaba."""
        from resolutions.domain.graduado import nombre_limpio

        assert nombre_limpio("MALYTH MERCETT MONTOYA YA MENDOZA") == "MALYTH MERCETT MONTOYA MENDOZA"
        assert nombre_limpio("LUISA FERNANDA ARRIETA DE LA BARRERA") == "LUISA FERNANDA ARRIETA DE LA BARRERA"
        assert nombre_limpio("ANA MARIA LIA") == "ANA MARIA LIA"

    def test_el_titulo_que_es_un_renglon_del_formulario_no_vale(self):
        from resolutions.domain.graduado import titulo_limpio, titulos_unificados

        assert titulo_limpio("CIUDADANIA NO") is None
        assert titulo_limpio("SEGUN LAS DISPOSICIONES LEGALES VIGENTES") is None
        assert titulo_limpio("INGENIERA CIVIL") == "INGENIERA CIVIL"
        # Sin cambiar el género al unificar.
        assert titulos_unificados(["INGENIERO CIVIL", "INGENIERO CIVIL", "INGENIERA CIVIL"])[2] == "INGENIERA CIVIL"

    def test_el_pdf_del_graduado_se_llama_nombre_y_titulo(self):
        from resolutions.application.acta_consejo import (
            TIPO_DE_GRADO,
            FilaDeActa,
            nombre_de_la_sesion,
        )

        fila = FilaDeActa(
            archivo="a.pdf", acta="ACTA DE GRADO No. 01/05", fecha="03-03-2005", folio_inicial=1, folio_final=1,
            folios=1, resumen="", tipo=TIPO_DE_GRADO, nombre="MARTHA LUCIA HERRERA VILLAMIZAR",
            titulo="ESPECIALISTA EN GESTION DE LA CALIDAD", cedula="39692338",
        )
        assert nombre_de_la_sesion(fila) == "MARTHA LUCIA HERRERA VILLAMIZAR - ESPECIALISTA EN GESTION DE LA CALIDAD"


def test_el_dia_no_sale_del_numero_del_acta():
    """UPD3859825 p. 44: «No. 29/05 días del mes de Julio de 2005»: el 05 es del acta, no el día."""
    from datetime import date

    from resolutions.domain.acta_grado import fecha_de_grado

    assert fecha_de_grado("ACTA DE GRADO No. 29/05 días del mes de Julio de 2005") is None
    assert fecha_de_grado("a los veintidos (22) días del mes de Julio de 2005") == date(2005, 7, 22)


class TestLaBasuraDeSecretaria:
    """Lo que salió en la corrida real de Secretaría 3292 (2026-10-31)."""

    def test_las_colas_del_formulario_se_quitan_del_titulo(self):
        from resolutions.domain.graduado import titulo_limpio

        assert titulo_limpio("ESPECIALISTA EN PEDIATRIA AL DOCTOR") == "ESPECIALISTA EN PEDIATRIA"
        assert titulo_limpio("ESPECIALISTA EN ORTODONCIA AL ODONTÓLOGO") == "ESPECIALISTA EN ORTODONCIA"
        assert titulo_limpio("ABOGADO, A EGRESADO DE LA FACULTAD DE DERECHO") == "ABOGADO"
        assert titulo_limpio("ESPECIALISTA EN SEGURIDAD SOCIAL.- A] *STUDIANTE") == "ESPECIALISTA EN SEGURIDAD SOCIAL"
        assert titulo_limpio("INGENIERO CIVIL AL ESTUIMANTE") == "INGENIERO CIVIL"

    def test_el_titulo_mal_leido_va_al_del_libro_sin_cambiar_de_especialidad(self):
        from resolutions.domain.graduado import titulos_unificados

        libro = ["TRABAJADORA SOCIAL"] * 5 + ["ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA"] * 3 + [
            "ESPECIALISTA EN ENDODONCIA", "ESPECIALISTA EN ENDODONCIA",
        ]
        unificados = titulos_unificados(
            libro + ["TRABAJADORA SOCIA", "ED EN GESTION DE LA CALIDAD Y AUDITORIA", "ESPECIALISTA EN ORTODONCIA"]
        )
        assert unificados[-3:] == [
            "TRABAJADORA SOCIAL", "ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA", "ESPECIALISTA EN ORTODONCIA",
        ]

    def test_el_nombre_sin_lo_de_la_resolucion_ni_palabras_imposibles(self):
        from resolutions.domain.graduado import nombre_limpio

        assert nombre_limpio("USO DE SUS ATRIBUCIONES LEGALES Y CORREA SOLANO LILIBETH") == "CORREA SOLANO LILIBETH"
        assert nombre_limpio("LUIS MIGUEL URIBE ARDILA COOCOMONMAMANNAMANACADANMAMAMOS") == "LUIS MIGUEL URIBE ARDILA"
        assert nombre_limpio("II BRAVO NIEVES JOSE JOAQUIN") == "BRAVO NIEVES JOSE JOAQUIN"
        # «DE LA HOZ» es un apellido y se queda.
        assert nombre_limpio("DE LA HOZ SIEGLER ILICH HERBERT") == "DE LA HOZ SIEGLER ILICH HERBERT"
