"""Lo que sólo el libro entero confirma, y dónde empieza cada diploma.

Medido sobre la carpeta REGISTROS DE DIPLOMAS 3269 - 3291 (once libros, 4143
caras, tres plantillas): la mecanografiada de 2011-13, la de posgrados antigua
sin cédula y la manuscrita de 1981-85 con cédula.
"""

from resolutions.application.diploma_split import group_by_record
from resolutions.domain.diploma import (
    CriterioDeCorte,
    DiplomaRecord,
    FormaDeLaCara,
    TextLine,
    asientos_en_progresion,
    con_lo_que_dice_el_libro,
    continuaciones,
    forma_de_la_cara,
    plantilla_antigua,
)


def lines(*textos: str) -> list[TextLine]:
    return [TextLine(text=t, y=float(i)) for i, t in enumerate(textos)]


def cara(pagina, asiento=None, pie=None, titulo=None, libro=None):
    return DiplomaRecord(
        page_number=pagina,
        folio=asiento,
        registered_folio=pie,
        degree=titulo,
        book=libro,
    )


class TestElLibroConfirma:
    def test_el_libro_que_falta_es_el_de_la_mayoria(self):
        registros = [cara(n, libro="8") for n in range(1, 10)] + [cara(10)]
        assert con_lo_que_dice_el_libro(registros)[-1].book == "8"

    def test_un_libro_leido_no_se_cambia(self):
        registros = [cara(n, libro="8") for n in range(1, 10)] + [cara(10, libro="9")]
        assert con_lo_que_dice_el_libro(registros)[-1].book == "9"

    def test_sin_mayoria_clara_no_se_rellena(self):
        registros = [cara(n, libro="8" if n % 2 else "9") for n in range(1, 9)] + [cara(9)]
        assert con_lo_que_dice_el_libro(registros)[-1].book is None

    def test_la_errata_de_un_titulo_frecuente_se_corrige(self):
        bueno = "ESPECIALISTA EN SALUD OCUPACIONAL"
        registros = [cara(n, titulo=bueno) for n in range(1, 5)]
        registros.append(cara(5, titulo="ESPECIALISTA EN SALUD OCUPACIQNAL"))
        assert con_lo_que_dice_el_libro(registros)[-1].degree == bueno

    def test_un_titulo_raro_y_distinto_se_queda(self):
        registros = [cara(n, titulo="ESPECIALISTA EN SALUD OCUPACIONAL") for n in range(1, 5)]
        registros.append(cara(5, titulo="MAGISTER EN FARMACOLOGIA"))
        assert con_lo_que_dice_el_libro(registros)[-1].degree == "MAGISTER EN FARMACOLOGIA"


class TestLaProgresionDelAsiento:
    def test_los_asientos_en_recta_se_quedan(self):
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 8)]
        assert [r.registered_folio for r in asientos_en_progresion(registros)] == [
            str(100 + n) for n in range(1, 8)
        ]

    def test_el_asiento_suelto_que_no_encaja_se_descarta(self):
        """La capa leyó «7» donde va escrito «1036»: mejor N/A que un dato falso."""
        registros = [cara(n, pie=str(1030 + n)) for n in range(1, 12)]
        registros[5] = cara(6, pie="7")
        salida = asientos_en_progresion(registros)
        assert salida[5].trusted_folio is None
        assert any("no encaja con la progresión" in w for w in salida[5].warnings)

    def test_el_impreso_dos_veces_se_cree_aunque_rompa_la_recta(self):
        """Una hoja escaneada dos veces rompe la recta; el folio doble se sostiene."""
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 8)]
        registros[3] = cara(4, asiento="500", pie="500")
        assert asientos_en_progresion(registros)[3].trusted_folio == "500"

    def test_el_encabezado_que_perdio_un_digito_tambien_confirma(self):
        """«Folio 21 o» arriba y «210» al pie: el 210 leído dos veces."""
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 8)]
        registros[3] = cara(4, asiento="21", pie="210")
        assert asientos_en_progresion(registros)[3].trusted_folio == "210"

    def test_un_solo_digito_comun_no_confirma(self):
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 8)]
        registros[3] = cara(4, asiento="2", pie="210")
        assert asientos_en_progresion(registros)[3].trusted_folio is None

    def test_entre_dos_anclas_iguales_se_deduce(self):
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 4)]
        registros += [cara(4), cara(5)]
        registros += [cara(n, pie=str(100 + n)) for n in range(6, 9)]
        salida = asientos_en_progresion(registros)
        assert [salida[3].registered_folio, salida[4].registered_folio] == ["104", "105"]

    def test_entre_anclas_con_salto_no_se_deduce(self):
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 4)]
        registros += [cara(4)]
        registros += [cara(n, pie=str(200 + n)) for n in range(5, 8)]
        assert asientos_en_progresion(registros)[3].registered_folio is None

    def test_un_tramo_corto_lejos_del_libro_se_descarta(self):
        """El libro 3859768 leyó «3, 4, 5…» donde va «203, 204, 205…»."""
        registros = [cara(n, pie=str(200 + n)) for n in range(1, 31)]
        for n in range(11, 15):
            registros[n - 1] = cara(n, pie=str(n - 8))
        salida = asientos_en_progresion(registros)
        assert all(salida[n - 1].trusted_folio is None for n in range(11, 15))
        assert salida[0].trusted_folio == "201"

    def test_los_asientos_con_letras_no_entran_en_la_cuenta(self):
        registros = [cara(n, pie=str(100 + n)) for n in range(1, 6)]
        registros[2] = cara(3, pie="103BIS")
        assert asientos_en_progresion(registros)[2].registered_folio == "103BIS"


class TestLaFormaDeLaCara:
    def test_el_membrete_abre(self):
        forma = forma_de_la_cara(lines("UNIVERSIDAD DE CARTAGENA", "LIBRO DE REGISTRO DE DIPLOMAS"))
        assert forma.abre

    def test_la_leyenda_de_apertura_abre_aunque_el_membrete_no_se_lea(self):
        """En los libros antiguos el membrete decorativo sale como basura."""
        forma = forma_de_la_cara(lines("^.OOIÜEKSIDHO oe CePIRSEOñ", "en atención a que el Señor"))
        assert forma.abre

    def test_el_pie_cierra(self):
        forma = forma_de_la_cara(lines("Registrado al folio No. 1036", "En testimonio de ello"))
        assert forma.cierra and not forma.abre

    def test_una_cara_en_blanco_no_trae_texto(self):
        assert not forma_de_la_cara(lines("   ")).con_texto


def forma(abre=False, cuerpo=False, cierra=False, con_texto=True):
    return FormaDeLaCara(con_texto=con_texto, abre=abre, cuerpo=cuerpo, cierra=cierra)


class TestDondeEmpiezaCadaDiploma:
    def test_cada_cara_que_abre_es_un_diploma(self):
        assert continuaciones([forma(abre=True, cierra=True)] * 3) == set()

    def test_la_cara_sin_nada_del_formulario_continua_el_anterior(self):
        formas = [forma(abre=True, cierra=True), forma(), forma(abre=True)]
        assert continuaciones(formas) == {1}

    def test_la_mitad_de_abajo_de_un_diploma_partido_continua(self):
        formas = [forma(abre=True), forma(cuerpo=True, cierra=True)]
        assert continuaciones(formas) == {1}

    def test_el_cuerpo_tras_un_diploma_cerrado_abre_otro(self):
        """UPD3858080 p117: escaneo oscuro, sin membrete ni apertura legibles."""
        formas = [forma(abre=True, cierra=True), forma(cuerpo=True, cierra=True)]
        assert continuaciones(formas) == set()

    def test_la_cara_sin_capa_de_texto_no_se_une(self):
        formas = [forma(abre=True, cierra=True), forma(con_texto=False)]
        assert continuaciones(formas) == set()

    def test_la_primera_nunca_continua(self):
        assert continuaciones([forma()]) == set()


class TestLaContinuacionVaEnElMismoPdf:
    def test_cortando_cara_a_cara_la_continuacion_se_une(self):
        registros = [
            DiplomaRecord(page_number=1, name="ANA PEREZ"),
            DiplomaRecord(page_number=2, continuacion=True),
            DiplomaRecord(page_number=3, name="LUIS GOMEZ"),
        ]
        grupos = group_by_record(registros, CriterioDeCorte.PAGINA).groups
        assert [g.page_numbers for g in grupos] == [[1, 2], [3]]


class TestLaPlantillaAntigua:
    """Textos de la capa de UPD3858083 (mecanografiada) y UPD3859766 (manuscrita)."""

    def test_la_manuscrita_se_reconoce_por_su_prosa(self):
        assert plantilla_antigua(
            lines(
                "LA REPUBLICA DE COLOMBIA",
                "en atención a que el Señor",
                "ha completado todos los Estudios",
                "le expide el presente Diploma, - Al mismo tiempo testifica",
            )
        )

    def test_la_mecanografiada_no_es_antigua(self):
        assert not plantilla_antigua(
            lines(
                "UNIVERSIDAD DE CARTAGENA",
                "LIBRO DE REGISTRO DE DIPLOMAS DE POSTGRADOS",
                "Folio 21",
                "Nombres y apellidos del graduando",
                "Registrado a folio No._^",
                "Para constancia es firmado el presente registro de diploma",
            )
        )
