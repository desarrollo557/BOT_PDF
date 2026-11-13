"""La cédula de cada graduado del libro colectivo, mirada con zoom en su renglón.

Auditoría del FUID de la caja 00C003288 contra el papel (2026-11-13): de 626
filas sin cédula, 28 la tenían en el papel y otras salían con la del graduado
de al lado. La hoja entera leída por la IA corría un renglón la cédula escrita
en el margen izquierdo (actas de 1985 y 1986, hojas 85 y 88), no veía la
escrita en alto entre dos renglones (hoja 79) ni la de tinta tenue (hoja 64), y
la pegada a su lugar se pasaba de cifras («45.525.2670/gena», hoja 133;
«409928675/Andrés», hoja 141). Releída en franjas de un cuarto de hoja, de
punta a punta, la IA pone cada cédula junto al nombre de su renglón. Los textos
son los que devolvió la IA de pago con esas franjas; ninguna prueba la llama.
"""

from __future__ import annotations

from test_actas_colectivas import (
    BASURA,
    HOJA_2,
    HOJA_3,
    HOJA_4,
    HOJA_5,
    HOJA_6,
    RESPUESTAS,
    LectorDeColectivas,
)

from resolutions.application.acta_consejo import GRADO, InventariarActa
from resolutions.application.ports import OcrResult
from resolutions.domain.acta_grado import (
    CEDULA_CON_ZOOM,
    FRANJAS_DE_LA_LISTA,
    NOTA_NO_APARECE,
    GraduadoDelActa,
    cedulas_con_zoom,
    necesita_zoom,
    renglones_de_la_franja,
)

#: Hoja 85, folio 27 (Acta Nº 1 de 1985): la segunda franja, como la devolvió la
#: IA. La cédula del margen va en su propio renglón, encima del nombre, con el
#: lugar abreviado delante del número del graduado.
FRANJA_85 = """33.155.799
C/ger 4- Maria Morquiza Aldoro Chico Chico
5- Consuelo Blanco Ramos 31.275.279 Cali
45.450.533
C/ger 6- Nicula Del Socorro Boborcos Ortega
45.438.300
C/ger 7- Yenisy Del Rosario Bostano Osorio
22.543.309
Palmer de Vinal 8- Narcisa Isabel Chaviro Boconegra
9- Yenisy de J. Béspedes Hernández. no aparece.
45.444.274
C/ger 10- Astud Del barmen Contreras Oruco
11- Melba Tuy Cortés Bolano no aparece.
"""
#: Lo que la hoja entera había leído de esos renglones: las cédulas del margen,
#: sueltas y corridas.
HOJA_85 = (
    "4- Maria Marquiza Alvory Chico Chico\n5- Consuelo Blanco Ramos 31.275.279 Cali\n"
    "45.450.533 C/gena 45.438.300 C/gena 22.543.309 45.444.274\n"
    "6- Nivila del Socorro Boborcos Ortega\n7- Yening del Rosario Bostano Osorio\n"
)
#: Como salieron en el FUID: la de Nivila era la de Yening, la de Yening la de
#: Narcisa, y Yening de J. Céspedes («no aparece») llevaba la de Astrid.
DEL_FUID = [
    GraduadoDelActa(orden=4, nombre="MARIA MARQUIZA ALVORY CHICO CHICO"),
    GraduadoDelActa(orden=5, nombre="CONSUELO BLANCO RAMOS", cedula="31275279"),
    GraduadoDelActa(orden=6, nombre="NIVILA DEL SOCORRO BOBORCOS ORTEGA", cedula="45438300"),
    GraduadoDelActa(orden=7, nombre="YENING DEL ROSARIO BOSTANO OSORIO", cedula="22543309"),
    GraduadoDelActa(orden=8, nombre="NARCISA ISABEL CHAVIS BOCONEGRA"),
    GraduadoDelActa(orden=9, nombre="YENING DE DESPEDOS HERNANDEZ", cedula="45444274"),
    GraduadoDelActa(orden=10, nombre="ASTUD DEL BORMEN CONTRERAS ORQCO"),
    GraduadoDelActa(orden=11, nombre="MELBA LUZ CORTES BOLANO"),
]


def _cedulas(graduados):
    return {g.orden: g.cedula for g in graduados}


class TestElRenglonAmpliado:
    def test_la_cedula_del_margen_va_con_el_nombre_de_debajo(self):
        renglones = renglones_de_la_franja(FRANJA_85)
        nicula = next(r for r in renglones if "BOBORCOS" in r.palabras)
        assert nicula.cedula == "45450533"
        assert next(r for r in renglones if "BLANCO" in r.palabras).cedula == "31275279"

    def test_el_lugar_del_margen_no_es_del_nombre(self):
        nicula = next(r for r in renglones_de_la_franja(FRANJA_85) if "BOBORCOS" in r.palabras)
        assert "GER" not in nicula.palabras

    def test_no_aparece_a_lapiz_se_lee(self):
        melba = next(r for r in renglones_de_la_franja(FRANJA_85) if "BOLANO" in r.palabras)
        assert melba.no_aparece and melba.cedula is None
        assert next(r for r in renglones_de_la_franja("no ap. 22- Guiomar Maria Hernondy Olroy") if r).no_aparece

    def test_la_cifra_de_mas_pegada_al_lugar(self):
        # La «C» de «C/gena» leída como un 0, y la «S» de «S/Andrés» como un 5.
        (saidys,) = renglones_de_la_franja("4- Alvarez Martinez Saidys Elena 45.525.2670/gena")
        assert saidys.cedula == "45525267"
        (esther,) = renglones_de_la_franja("15 De Leon Berrio Esther Helena c.c 409928675/Andrés")
        assert esther.cedula == "40992867"

    def test_el_bloque_de_cedulas_va_en_orden_con_sus_nombres(self):
        # Hoja 142: la IA devolvió los nombres y debajo sus cédulas, como dos columnas.
        franja = (
            "15 De Seón Berrio Esther Helena\n16 Del Castillo Santos Ana Horia\n17 Díaz Faranillo Victor Homel\n\n"
            "e.e 40992 8675/mbis\n\ne.e 64578237 Smalyo\n\ne.e 3'928794 Arjona\n"
        )
        cedulas = [r.cedula for r in renglones_de_la_franja(franja)]
        assert cedulas == ["40992867", "64578237", "3928794"]

    def test_la_escrita_en_alto_al_final_del_renglon_de_arriba(self):
        # Hoja 79: la de Dora, escrita en alto, la IA la pegó detrás de la de Joery.
        franja = "35 Joery Osorio Eliana 45.454.974.0/zen 38.859.944\n36 Santos Soaredro Dora Patricia Buga"
        joery, dora = renglones_de_la_franja(franja)
        assert joery.cedula == "45454974" and dora.cedula == "38859944"

    def test_la_cedula_escrita_en_alto_va_al_renglon_de_debajo(self):
        franja = "35 Joery Osorio Eliana 45.454.974 C/gena\n38.859.944 Buga\n36 Santos Saavedra Dora Patricia"
        dora = next(r for r in renglones_de_la_franja(franja) if "SAAVEDRA" in r.palabras)
        assert dora.cedula == "38859944"


class TestLasCedulasConZoom:
    def test_las_del_margen_vuelven_a_su_renglon(self):
        graduados, hecho = cedulas_con_zoom(DEL_FUID, [FRANJA_85], HOJA_85)
        cedulas = _cedulas(graduados)
        assert cedulas[4] == "33155799"  # la del margen que no se veía
        assert cedulas[6] == "45450533"  # corridas un renglón: cada una a su dueño
        assert cedulas[7] == "45438300"
        assert cedulas[8] == "22543309"
        assert cedulas[10] == "45444274"
        assert cedulas[5] == "31275279"
        assert hecho and "con zoom en los renglones de la lista" in hecho[0]

    def test_la_cedula_del_vecino_se_quita_y_el_no_aparece_se_dice(self):
        graduados, _hecho = cedulas_con_zoom(DEL_FUID, [FRANJA_85], HOJA_85)
        yening = next(g for g in graduados if g.orden == 9)
        assert yening.cedula is None
        assert NOTA_NO_APARECE in yening.nota and "45444274" in yening.nota
        melba = next(g for g in graduados if g.orden == 11)
        assert melba.cedula is None and NOTA_NO_APARECE in melba.nota

    def test_la_leida_con_zoom_lo_dice(self):
        graduados, _hecho = cedulas_con_zoom(DEL_FUID, [FRANJA_85], HOJA_85)
        assert CEDULA_CON_ZOOM in next(g for g in graduados if g.orden == 4).nota

    def test_la_que_la_hoja_no_ve_no_reemplaza_a_la_leida(self):
        # El zoom lee otra cédula y la hoja no la trae: se queda la de la hoja y se anota.
        graduados = [GraduadoDelActa(orden=1, nombre="SAMUEL CONTRERAS CALDERON", cedula="77006212")]
        (samuel,), _hecho = cedulas_con_zoom(
            graduados, ["1- Samuel Cortuero Calderon 77.006.952 Valledupar"], "1- Samuel Contreras Calderon 77.006.212"
        )
        assert samuel.cedula == "77006212"
        assert "77006952" in samuel.nota

    def test_a_una_cifra_de_la_hoja_es_la_de_la_hoja(self):
        # «46.500.293» con zoom; la hoja leyó «45.500.293» y se la dio al de arriba.
        graduados = [
            GraduadoDelActa(orden=31, nombre="MYRA DEL CARMEN VILLAREAL AMOS", cedula="45500293"),
            GraduadoDelActa(orden=32, nombre="MARIA TERESA VIBRIA DE ARMOS"),
        ]
        franja = "no aparece 31 Myra Del Carmen Villareal Amos\n46.500.293 32 Maria Teresa Vibria De Armos"
        (myra, maria), _hecho = cedulas_con_zoom(graduados, [franja], "31 Myra Villareal 45.500.293\n32 Maria Teresa Vibria")
        assert maria.cedula == "45500293"
        assert "el zoom la 46500293: revise esa cifra" in maria.nota
        assert myra.cedula is None and NOTA_NO_APARECE in myra.nota

    def test_el_parecido_es_de_todo_el_nombre(self):
        # Hoja 121: «Larios» y «Carmen» pasan por «Barrios» y «Carmona»; gana el nombre entero.
        graduados = [
            GraduadoDelActa(orden=6, nombre="BARRIOS CARMONA PAOLA"),
            GraduadoDelActa(orden=49, nombre="RUIZ LARIOS JUGID DEL CARMEN"),
        ]
        paola, ruiz = cedulas_con_zoom(graduados, ["49- Ruiz Larios Ingrid Del Carmen 45'690.444 C/geua"], "")[0]
        assert ruiz.cedula == "45690444" and paola.cedula is None

    def test_dos_cedulas_para_el_mismo_renglon_no_deciden(self):
        graduados = [GraduadoDelActa(orden=1, nombre="DORA PATRICIA SANTOS SAAVEDRA")]
        franjas = ["1 Santos Saavedra Dora Patricia 38.859.944", "1 Santos Saavedra Dora Patricia 38.869.944"]
        (dora,), _hecho = cedulas_con_zoom(graduados, franjas, "")
        assert dora.cedula is None and "dos cédulas" in dora.nota

    def test_el_renglon_que_se_parece_a_dos_no_es_de_ninguno(self):
        # El mismo graduado en dos filas (Ricky Santiago Berdugo, acta 1 de 1985).
        graduados = [
            GraduadoDelActa(orden=28, nombre="RICKY SANTIAGO BERDUGO"),
            GraduadoDelActa(orden=33, nombre="RICKY SANTIAGO BERDUGO"),
        ]
        nuevos, _hecho = cedulas_con_zoom(graduados, ["28 Kiedy Santiago Berdugo 33.621.313"], "")
        assert [g.cedula for g in nuevos] == [None, None]

    def test_casi_igual_a_dos_tampoco_decide(self):
        # A «… DE LUNA» sólo le falta una palabra: ante la duda, la cédula no se le da a nadie.
        graduados = [
            GraduadoDelActa(orden=1, nombre="ANA MARIA PEREZ GOMEZ"),
            GraduadoDelActa(orden=2, nombre="ANA MARIA PEREZ GOMEZ DE LUNA"),
        ]
        nuevos, _hecho = cedulas_con_zoom(graduados, ["1 Ana Maria Perez Gomez 45.111.222"], "")
        assert [g.cedula for g in nuevos] == [None, None]

    def test_hermanas_con_los_mismos_apellidos_se_distinguen(self):
        graduados = [
            GraduadoDelActa(orden=17, nombre="LUZ MILENA GUERRERO ROMERO"),
            GraduadoDelActa(orden=18, nombre="MAYRA ALEJANDRA GUERRERO ROMERO"),
        ]
        franja = "17. Luz Milena Guerrero Romero 45.111.222\n18. Mayra Alejandra Guerrero Romero 45.333.444"
        assert [g.cedula for g in cedulas_con_zoom(graduados, [franja], "")[0]] == ["45111222", "45333444"]

    def test_quien_ya_dice_por_que_no_la_tiene_no_se_mira(self):
        assert not necesita_zoom(GraduadoDelActa(orden=1, nombre="X Y", nota=NOTA_NO_APARECE))
        assert not necesita_zoom(GraduadoDelActa(orden=1, nombre="X Y", nota="anotado en el papel: «no se graduó»"))
        assert not necesita_zoom(GraduadoDelActa(orden=1, nombre="X Y", cedula="45111222"))
        assert necesita_zoom(GraduadoDelActa(orden=1, nombre="X Y"))


#: La hoja 1 del libro de prueba con la cédula de la tercera graduada escrita
#: tenue: la hoja entera no la ve.
HOJA_1_TENUE = """155
80/V

# Acta de Grado Nº 01

En la ciudad de Cartagena a los catorce (14) días del mes de Julio de 2006, se llevó a cabo la graduación
Colectiva en ceremonia Solemne por solicitud de la Decana de la Facultad de Enfermería a la Rectoría quien
autorizó el acto mediante Resolución Nº 1430 de fecha 30 de Junio de 2006 por medio de la cual, otorga de
acuerdo a la Ley y los estatutos de la Universidad, el Título de: Enfermera (o) al estudiante
_______________, portador de la cédula de Ciudadanía Nº _______ expedida en ______.

Enfermera (o)
1. Karolay Acevedo Jiménez 45.521.842 Cartagena
2. Yanis Isabel Alvarez Salgado 64.720.465 Sampués
3. Verónica Patricia Ariza Zabaleta
"""
LIBRO_TENUE = [HOJA_1_TENUE, HOJA_2, HOJA_3, HOJA_4, HOJA_5, HOJA_6]
RESPUESTAS_TENUE = {
    **RESPUESTAS,
    "Nº 01": RESPUESTAS["Nº 01"].replace("ARIZA ZABALETA | 45541702", "ARIZA ZABALETA | NINGUNO"),
}


class LibroConFranjas:
    """El PDF de mentira: cada página rasterizada dice cuál es, y cada franja, de qué página y altura."""

    def __init__(self, paginas):
        self._paginas = paginas

    @property
    def page_count(self):
        return len(self._paginas)

    def text_of(self, numero):
        return BASURA

    def render(self, numero, band=None, dpi=200):
        return f"P{numero}".encode() if band is None else f"F{numero}:{band.y0:.2f}".encode()

    def ink_of(self, numero, band):
        return (0.02, 0.0)


class IaConZoom:
    """La IA de pago: la página entera como siempre; en la franja de arriba de la hoja 1, la cédula tenue."""

    def __init__(self, paginas):
        self._paginas = paginas
        self.franjas: list[bytes] = []

    def read(self, imagen):
        if imagen.startswith(b"P"):
            return OcrResult(text=self._paginas[int(imagen[1:].split(b":")[0]) - 1])
        self.franjas.append(imagen)
        if imagen == b"F1:0.60":
            return OcrResult(text="2. Yanis Isabel Alvarez Salgado 64.720.465\n3. Verónica Patricia Ariza Zabaleta 45.541.702 Cartagena")
        return OcrResult(text="")


class LectorTenue(LectorDeColectivas):
    def resumir(self, texto):
        self.leidas.append(texto)
        return next((respuesta for clave, respuesta in RESPUESTAS_TENUE.items() if clave in texto[:200]), "")


def _inventariar(ia):
    return InventariarActa(perfil=GRADO, relector_de_pago=ia, lector_de_actas_colectivas=LectorTenue()).execute(
        LibroConFranjas(LIBRO_TENUE), document_name="UPD3859802.pdf", carpeta="00C003288\\UPD3859802"
    )


class TestElAgenteDelInventario:
    def test_la_cedula_tenue_se_lee_con_zoom(self):
        ia = IaConZoom(LIBRO_TENUE)
        outcome = _inventariar(ia)
        ariza = next(f for f in outcome.filas if "ARIZA" in f.nombre)
        assert ariza.cedula == "45541702"

    def test_solo_se_releen_las_hojas_del_acta_que_lo_necesita(self):
        ia = IaConZoom(LIBRO_TENUE)
        _inventariar(ia)
        # El Acta 01 va en las hojas 1 y 2; las dos traen lista: cinco franjas
        # cada una. Las de las otras actas colectivas (hojas 3 y 4), que tienen
        # todas sus cédulas, no se pagan. (La 5 es el acta individual, que
        # relee su propia franja como siempre.)
        de_las_colectivas = [franja for franja in ia.franjas if franja.split(b":")[0] in (b"F1", b"F2", b"F3", b"F4")]
        assert sorted({franja.split(b":")[0] for franja in de_las_colectivas}) == [b"F1", b"F2"]
        assert len(de_las_colectivas) == 2 * len(FRANJAS_DE_LA_LISTA)

    def test_sin_la_ia_no_se_paga_nada(self):
        outcome = InventariarActa(perfil=GRADO, relector_de_pago=None, lector_de_actas_colectivas=None).execute(
            LibroConFranjas(LIBRO_TENUE), document_name="UPD3859802.pdf", carpeta="00C003288\\UPD3859802"
        )
        assert outcome.filas
