"""El libro manuscrito de actas de grado colectivas: un PDF por acta, una fila del FUID por graduado.

Odontología, UPD3859802 (2026-11-12): un libro a mano en que cada acta
gradúa a una promoción -- «Acta de Grado Nº 01» con la lista de sus
graduados, «Acta de Grado Nº 05408120 a 05408124» -- y la siguiente empieza a
mitad de la hoja en que acaba la anterior. La capa del escáner es basura; los
textos de aquí son como los transcribe la IA de pago, con su Markdown. El
operador eligió: un PDF por acta, una fila por graduado con su número del
rango y su cédula, los folios sólo en la fila del primero, y la hoja
compartida en el PDF del acta que empieza en ella. Las actas individuales
--también las manuscritas, como la de NURY VARELA ESCUDERO-- siguen como
siempre. Ninguna prueba llama a un proveedor de pago.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from test_acta_grado import MODERNA_COMPLETA
from test_razonar_lo_que_falta import _grado

from resolutions.adapters.fuid_de_la_entrega import filas_del_fuid
from resolutions.application.acta_consejo import (
    GRADO,
    InventariarActa,
    nombre_de_la_sesion,
    resultado_de_cada_acta,
)
from resolutions.application.perfiles_de_revision import (
    REGLAS_DEL_LIBRO_COLECTIVO,
    perfil_de,
)
from resolutions.application.ports import OcrResult
from resolutions.domain.acta_grado import (
    GraduadoDelActa,
    es_acta_colectiva,
    es_hoja_de_acta_colectiva,
    es_libro_de_actas_colectivas,
    graduados_de_la_lista,
    juntar_graduados,
    lectura_colectiva_de_la_ia,
    numero_y_rango,
    numeros_de_los_graduados,
    reparto_del_libro_colectivo,
    rotulo_del_acta_colectiva,
)

#: Lo que trae la capa del escáner de este libro: nada que leer.
BASURA = "•V- ) 'ñ (P i*!? ~ ,,"

#: Hoja 1: el «Acta de Grado Nº 01» de 2006, con el estudiante en blanco y
#: los tres primeros de su lista.
HOJA_1 = """155
80/V

# Acta de Grado Nº 01

En la ciudad de Cartagena a los catorce (14) días del mes de Julio de 2006, se llevó a cabo la graduación
Colectiva en ceremonia Solemne por solicitud de la Decana de la Facultad de Enfermería a la Rectoría quien
autorizó el acto mediante Resolución Nº 1430 de fecha 30 de Junio de 2006 por medio de la cual, otorga de
acuerdo a la Ley y los estatutos de la Universidad, el Título de: Enfermera (o) al estudiante
_______________, portador de la cédula de Ciudadanía Nº _______ expedida en ______, a quien se le tomó el
Juramento de rigor y se le hizo entrega del diploma que lo autoriza para el ejercicio profesional como:
Enfermera (o). Según las disposiciones legales vigentes.
Para constancia de lo expuesto, se firma la presente acta por todos los que en ella intervinieron.
Doctor Germán Arturo Sierra Anaya, Rector; Doctora Marly Mardini Llamas, Secretaria General; Amparo
Montalvo Prieto, Decana.

Enfermera (o)
1. Karolay Acevedo Jiménez 45.521.842 Cartagena
2. Yanis Isabel Alvarez Salgado 64.720.465 Sampués
3. Verónica Patricia Ariza Zabaleta 45.541.702 Cartagena
"""
#: Hoja 2: la cola de la lista del 01 -- como tabla, como la devuelve a veces
#: la IA --, sus firmas, y el «Acta de Grado Nº 02» que empieza a mitad de hoja.
HOJA_2 = """156

| 4. | Carmen Isabel Barrios Caro | 33.272.987 | San Juan Nepomuceno |
| 5. | Nellys Barrios Palencia | 45.551.367 | Cartagena |

Amparo Montalvo Prieto          Edna Gómez Bustamante
Decana                          Jefe Departamento Académico

## Acta de Grado Nº 02.

En la ciudad de Cartagena a los catorce (14) días del mes de julio de 2006, se llevó a cabo la graduación
colectiva en ceremonia solemne por solicitud de la Decana de la Facultad de Enfermería a la Rectoría quien
autorizó el acto mediante Resolución Nº 1453 de fecha 05 de julio de 2006 por medio de la cual, otorga de
acuerdo a la Ley y los estatutos de la Universidad, el título de: Especialista en Salud Ocupacional al
estudiante
"""
#: Hoja 3: lo que le falta al 02 -- el blanco, su lista, sus firmas -- y, al
#: pie, el encabezado del acta con rango, cuyo cuerpo va arriba de la hoja 4.
HOJA_3 = """157

x x x portador de la cédula de ciudadanía Nº x x expedida en x x, a quien se le tomó el juramento de rigor.
Especialista en Salud Ocupacional
1. Juan Carlos Becerra Salinas 88.221.420 Cúcuta
2. José Alexander Del Rosario Bermúdez Pineda 19.052.077 Bogotá D.E.

Amparo Montalvo Prieto
Decana

Acta de Grado Nº
05408120 a 05408124
"""
HOJA_4 = """158
88/V

En la ciudad de Cartagena a los veintiséis (26) días del mes de septiembre del año dos mil ocho (2008) se
llevó a cabo la graduación Colectiva en ceremonia solemne por solicitud del Decano(a) de la Facultad de
Enfermería a la Rectoría, quien autorizó el acto mediante Resolución Nº 2330 de fecha 3 de septiembre de
2008, por medio de la cual, otorga de acuerdo a la Ley y los estatutos de la Universidad, el título de:
ENFERMERA (O) al estudiante ....... portador de la cédula de ciudadanía Nº ...... expedida en ......
ENFERMERA (O)
1. Castillo Castilla Freddy CC 45.761.728 de Cartagena
2. Ramírez Parra Danny Rafael CC 1.047.366.182 de Cartagena
3. Ramos Caballero Edgardo Javier CC 1.128.049.264 de Cartagena
4. Ramos Camargo Karina CC 1.085.165.668 de Guamal
5. Rincón Correa Damaris Adriana CC 1.047.389.211 de Cartagena

Amparo Montalvo Prieto                    Julia Teresa Medina Arnedo
Decana                                    Jefa Dpto. Académico
"""
#: Hojas 5 y 6: un acta individual manuscrita, como la de la pág. 110 del libro.
HOJA_5 = """160

Acta de Grado Nº 07

En la ciudad de Cartagena a los veintiún (21) días del mes de mayo de 1992, se realizó la graduación en
ceremonia privada a solicitud de la Decana de la Facultad de Enfermería, quien autorizó el acto mediante
Resolución Nº 0512 del 15 de mayo de 1992, otorga el título de Especialista en Enfermería Materno Infantil
a la estudiante NURY VARELA ESCUDERO, portadora de la cédula de ciudadanía Nº 45.481.150 expedida en
Cartagena, a quien se le tomó el juramento de rigor.
"""
HOJA_6 = """161/V

Para constancia de lo expuesto se firma la presente acta.
Amparo Montalvo Prieto, Decana
"""
LIBRO = [HOJA_1, HOJA_2, HOJA_3, HOJA_4, HOJA_5, HOJA_6]

#: Lo que contesta el lector de la IA de cada acta colectiva.
RESPUESTAS = {
    "Nº 01": (
        "NUMERO_DESDE: 01\nNUMERO_HASTA: NINGUNO\nFECHA: 14-07-2006\nTITULO: ENFERMERA (O)\n"
        "GRADUADO: 1 | KAROLAY ACEVEDO JIMÉNEZ | 45521842 | NINGUNO\n"
        "GRADUADO: 2 | YANIS ISABEL ALVAREZ SALGADO | 64720465 | NINGUNO\n"
        "GRADUADO: 3 | VERÓNICA PATRICIA ARIZA ZABALETA | 45541702 | NINGUNO\n"
        "GRADUADO: 4 | CARMEN ISABEL BARRIOS CARO | 33272987 | NINGUNO\n"
        "GRADUADO: 5 | NELLYS BARRIOS PALENCIA | 45551367 | NINGUNO"
    ),
    "Nº 02": (
        "NUMERO_DESDE: 02\nNUMERO_HASTA: NINGUNO\nFECHA: 14-07-2006\nTITULO: ESPECIALISTA EN SALUD OCUPACIONAL\n"
        "GRADUADO: 1 | JUAN CARLOS BECERRA SALINAS | 88221420 | NINGUNO\n"
        "GRADUADO: 2 | JOSÉ ALEXANDER DEL ROSARIO BERMÚDEZ PINEDA | 19052077 | NINGUNO"
    ),
    "05408120": (
        "NUMERO_DESDE: 05408120\nNUMERO_HASTA: 05408124\nFECHA: 26-09-2008\nTITULO: ENFERMERA (O)\n"
        "GRADUADO: 1 | CASTILLO CASTILLA FREDDY | 45761728 | NINGUNO\n"
        "GRADUADO: 2 | RAMÍREZ PARRA DANNY RAFAEL | 1047366182 | NINGUNO\n"
        "GRADUADO: 3 | RAMOS CABALLERO EDGARDO JAVIER | 1128049264 | NINGUNO\n"
        "GRADUADO: 4 | RAMOS CAMARGO KARINA | 1085165668 | NINGUNO\n"
        "GRADUADO: 5 | RINCÓN CORREA DAMARIS ADRIANA | 1047389211 | NINGUNO"
    ),
}


class Libro:
    """El PDF de mentira: la capa es basura y cada página rasterizada dice cuál es."""

    def __init__(self, paginas):
        self._paginas = paginas

    @property
    def page_count(self):
        return len(self._paginas)

    def text_of(self, numero):
        return BASURA

    def render(self, numero, band=None, dpi=200):
        return f"P{numero}".encode() if band is None else b"FRANJA"

    def ink_of(self, numero, band):
        return (0.02, 0.0)


class IaDePago:
    """La IA que lee cada página entera; cuenta las que se le pagan."""

    def __init__(self, paginas):
        self._paginas = paginas
        self.paginas_leidas = 0

    def read(self, imagen):
        if imagen.startswith(b"P"):
            self.paginas_leidas += 1
            return OcrResult(text=self._paginas[int(imagen[1:]) - 1])
        return OcrResult(text="")


class LectorDeColectivas:
    """El lector de texto de la IA para las actas colectivas, con sus respuestas fijas."""

    def __init__(self):
        self.leidas: list[str] = []

    def resumir(self, texto):
        self.leidas.append(texto)
        return next((respuesta for clave, respuesta in RESPUESTAS.items() if clave in texto[:200]), "")


def _inventariar(paginas=LIBRO, lector=None):
    ia = IaDePago(paginas)
    outcome = InventariarActa(
        perfil=GRADO, relector_de_pago=ia, lector_de_actas_colectivas=lector
    ).execute(Libro(paginas), document_name="UPD3859802.pdf", carpeta="00C003288\\UPD3859802")
    return outcome, ia


class TestReconocerElLibro:
    def test_el_libro_colectivo_se_reconoce(self):
        assert es_libro_de_actas_colectivas(LIBRO)
        assert es_hoja_de_acta_colectiva(HOJA_1)

    def test_graduacion_colectiva_sola_no_basta(self):
        # Las actas individuales de hoy dicen «graduación colectiva» y nombran a
        # un graduado: no son un libro colectivo.
        modernas = [MODERNA_COMPLETA] * 4
        assert not es_libro_de_actas_colectivas(modernas)
        assert not es_hoja_de_acta_colectiva(MODERNA_COMPLETA)
        a_maquina = [_grado("03", "LUZ FELFLE CASTILLA", "45.760.742"), _grado("03", "VIVIAN LOPEZ", "22.793.650")]
        assert not es_libro_de_actas_colectivas(a_maquina * 2)

    def test_el_acta_individual_no_es_colectiva(self):
        assert not es_acta_colectiva(HOJA_5)
        assert es_acta_colectiva(HOJA_1)

    def test_el_rango_del_encabezado(self):
        assert numero_y_rango("Acta de Grado Nº\n05408120 a 05408124\nEn la ciudad") == ("05408120", "05408124")
        assert numero_y_rango("# Acta de Grado Nº 01\n\nEn la ciudad") == ("01", None)
        assert numero_y_rango("Acta Nº 1\nEn la ciudad") == ("1", None)


class TestElReparto:
    def test_la_hoja_compartida_va_en_los_dos_pdf(self):
        """El operador, 2026-11-13: cada PDF lleva su acta entera, también la hoja
        donde acaba su lista aunque en ella empiece la siguiente (en la 87 de
        UPD3859802 faltaban 25 de 30 nombres)."""
        partes = reparto_del_libro_colectivo(LIBRO)
        # El Acta 02 empieza al pie de la hoja 2 y su lista (Becerra, Bermúdez)
        # está en la 3, donde al pie empieza la 05408120: 2 y 3 son compartidas.
        assert [(p.desde, p.hasta, p.ceremonia) for p in partes] == [
            (1, 2, False),
            (2, 3, False),
            (3, 4, False),
            (5, 6, False),
        ]
        cubiertas = [pagina for p in partes for pagina in range(p.desde, p.hasta + 1)]
        # Todas las hojas, y sólo las compartidas dos veces.
        assert sorted(set(cubiertas)) == list(range(1, len(LIBRO) + 1))
        assert sorted(p for p in set(cubiertas) if cubiertas.count(p) > 1) == [2, 3]

    def test_el_texto_de_cada_acta_va_hasta_donde_empieza_la_siguiente(self):
        uno, dos, rango, _individual = reparto_del_libro_colectivo(LIBRO)
        # La cola del 01 -- su lista en la hoja 2 -- es suya, y su cierre lo dice.
        assert "Nellys Barrios Palencia" in uno.texto
        assert "Acta de Grado Nº 02" not in uno.texto
        assert uno.cierre == 2
        assert dos.texto.startswith("Acta de Grado Nº 02")
        assert "Juan Carlos Becerra" in dos.texto and dos.cierre == 3
        # El encabezado al pie de la hoja 3 abre el acta en esa hoja.
        assert rango.texto.startswith("Acta de Grado Nº\n05408120")
        assert numero_y_rango(rango.texto) == ("05408120", "05408124")

    def test_la_lista_se_lee_por_regla(self):
        graduados = graduados_de_la_lista(reparto_del_libro_colectivo(LIBRO)[0].texto)
        assert [(g.orden, g.nombre, g.cedula) for g in graduados] == [
            (1, "KAROLAY ACEVEDO JIMÉNEZ", "45521842"),
            (2, "YANIS ISABEL ALVAREZ SALGADO", "64720465"),
            (3, "VERÓNICA PATRICIA ARIZA ZABALETA", "45541702"),
            (4, "CARMEN ISABEL BARRIOS CARO", "33272987"),
            (5, "NELLYS BARRIOS PALENCIA", "45551367"),
        ]

    def test_un_renglon_del_cuerpo_no_es_un_graduado(self):
        texto = "30 de Junio de 2006 por medio de la cual\n14 días del mes de julio\n1- Margarita Rosa Andrade García"
        assert [g.nombre for g in graduados_de_la_lista(texto)] == ["MARGARITA ROSA ANDRADE GARCÍA"]


#: El acta Nº 02 de 2006 tal como salió en UPD3859802 (págs. 159-160): es de
#: una sola graduada, y su nombre va arriba de la hoja siguiente, detrás del folio.
ACTA_02_AL_PIE = """156

15. María Carolina González Víctor 45.556.182 Cartagena

Amparo Montalvo Prieto          Edna Gómez Bustamante
Decana                          Jefe Departamento Académico

# Acta de Grado Nº 02.

En la ciudad de Cartagena a los catorce (14) días del mes de julio de 2006, se llevó a cabo la graduación colectiva en
ceremonia solemne por solicitud de la Decana de la Facultad de Enfermería, el título de: Especialista en Salud
Ocupacional al estudiante
"""
ACTA_02_ARRIBA = """157
81/V

Peggy Margarita Nieto Periñan, portador de la cédula de Ciudadanía Nº 45.592.293 expedida en Turbaco, a quien se le tomó
el Juramento de rigor.
Amparo Montalvo Prieto          Edna Gómez Bustamante
Decana                          Jefe Departamento Académico

# Acta de Grado Nº 03.

En la ciudad de Cartagena a los catorce (14) días del mes de julio del año dos mil seis (2006) se llevó a cabo la
graduación colectiva, el título de: Especialista en Salud Ocupacional al estudiante Leonel Enrique Herrera Roa,
portador de la cédula de ciudadanía Nº 91.284.634 expedida en Bucaramanga
"""


class TestLoQueMostroLaPruebaReal:
    def test_el_nombre_arriba_de_la_hoja_siguiente_es_del_acta(self):
        from resolutions.domain.acta_grado import leer_acta_de_grado

        dos, tres = reparto_del_libro_colectivo([ACTA_02_AL_PIE, ACTA_02_ARRIBA])
        assert not es_acta_colectiva(dos.texto) and dos.cierre == 2
        acta = leer_acta_de_grado([dos.texto])
        assert (acta.numero, acta.nombre, acta.cedula) == ("02", "PEGGY MARGARITA NIETO PERIÑAN", "45592293")
        assert leer_acta_de_grado([tres.texto]).nombre == "LEONEL ENRIQUE HERRERA ROA"

    def test_quien_firma_no_es_graduado(self):
        from resolutions.domain.acta_grado import sin_quien_firma

        graduados = [GraduadoDelActa(1, "NEILA PACHECO", "1234567"), GraduadoDelActa(2, "EDNA GÓMEZ BUSTAMANTE")]
        assert [g.nombre for g in sin_quien_firma(graduados, ACTA_02_ARRIBA)] == ["NEILA PACHECO"]


class TestLosNumerosDeLosGraduados:
    def test_el_rango_que_cuadra_da_uno_a_cada_uno(self):
        numeros, nota = numeros_de_los_graduados("05408120", "05408124", 5)
        assert numeros == ["05408120", "05408121", "05408122", "05408123", "05408124"]
        assert nota is None

    def test_el_rango_que_no_cuadra_va_entero_y_se_dice(self):
        numeros, nota = numeros_de_los_graduados("05408120", "05408124", 4)
        assert numeros == ["05408120 A 05408124"] * 4
        assert "no se sabe qué número es de cada uno" in nota

    def test_sin_rango_el_numero_del_acta(self):
        assert numeros_de_los_graduados("03", None, 3) == (["03", "03", "03"], None)

    def test_el_rotulo_del_acta(self):
        assert rotulo_del_acta_colectiva("05408120", "05408124") == "ACTA DE GRADO 05408120 A 05408124"
        assert rotulo_del_acta_colectiva("03", None) == "ACTA DE GRADO No. 03"


class TestLoQueLeeLaIa:
    def test_lo_que_el_texto_no_dice_no_vale(self):
        texto = reparto_del_libro_colectivo(LIBRO)[2].texto
        respuesta = (
            "NUMERO_DESDE: 05408120\nNUMERO_HASTA: 05408124\nFECHA: 26-09-2008\nTITULO: ENFERMERA (O)\n"
            "GRADUADO: 1 | CASTILLO CASTILLA FREDDY | 45761728 | NINGUNO\n"
            # Un nombre que el texto no trae y una cédula inventada.
            "GRADUADO: 2 | RAMIRO PARRAGA DANIEL | 99999999 | NINGUNO\n"
            "GRADUADO: 3 | RAMOS CABALLERO EDGARDO JAVIER | 11111111 | NINGUNO"
        )
        leida = lectura_colectiva_de_la_ia(respuesta, texto)
        assert (leida.desde, leida.hasta, leida.fecha) == ("05408120", "05408124", date(2008, 9, 26))
        assert [(g.orden, g.nombre, g.cedula) for g in leida.graduados] == [
            (1, "CASTILLO CASTILLA FREDDY", "45761728"),
            (3, "RAMOS CABALLERO EDGARDO JAVIER", None),
        ]

    def test_lo_que_la_ia_se_salto_lo_completa_la_regla(self):
        de_la_ia = [GraduadoDelActa(1, "CASTILLO CASTILLA FREDDY", None)]
        de_la_lista = [
            GraduadoDelActa(1, "CASTILLO CASTILLA FREDDY", "45761728"),
            GraduadoDelActa(2, "RAMIREZ PARRA DANNY RAFAEL", "1047366182"),
        ]
        juntos = juntar_graduados(de_la_ia, de_la_lista)
        assert [(g.orden, g.cedula) for g in juntos] == [(1, "45761728"), (2, "1047366182")]
        assert juntos[1].nota and "sin la IA" in juntos[1].nota


class TestElInventario:
    def test_una_fila_por_graduado_y_un_pdf_por_acta(self):
        lector = LectorDeColectivas()
        outcome, ia = _inventariar(lector=lector)
        assert outcome.colectivo
        # Una página pagada por hoja: las actas colectivas no se releen.
        assert ia.paginas_leidas == len(LIBRO)
        assert len(lector.leidas) == 3
        # Cada acta acaba en la hoja donde empieza la siguiente: esas van en las dos.
        assert [(s.desde, s.hasta) for s in outcome.sesiones] == [(1, 2), (2, 3), (3, 4), (5, 6)]
        assert [s.nombre for s in outcome.sesiones[:3]] == [
            "ACTA DE GRADO No. 01 - 14-07-2006",
            "ACTA DE GRADO No. 02 - 14-07-2006",
            "ACTA DE GRADO 05408120 A 05408124 - 26-09-2008",
        ]
        assert all(s.literal for s in outcome.sesiones)
        del_rango = [f for f in outcome.filas if f.sesion == 3]
        assert [(f.numero, f.nombre, f.cedula) for f in del_rango] == [
            ("05408120", "CASTILLO CASTILLA FREDDY", "45761728"),
            ("05408121", "RAMÍREZ PARRA DANNY RAFAEL", "1047366182"),
            ("05408122", "RAMOS CABALLERO EDGARDO JAVIER", "1128049264"),
            ("05408123", "RAMOS CAMARGO KARINA", "1085165668"),
            ("05408124", "RINCÓN CORREA DAMARIS ADRIANA", "1047389211"),
        ]
        assert all(f.fecha == "26-09-2008" and f.titulo.startswith("ENFERMER") for f in del_rango)
        del_01 = [f for f in outcome.filas if f.sesion == 1]
        assert len(del_01) == 5 and {f.numero for f in del_01} == {"01"}
        # Los folios, en la fila del primero; las demás dicen dónde están.
        assert del_01[0].folios_en == ""
        assert all(f.folios_en == "KAROLAY ACEVEDO JIMÉNEZ" for f in del_01[1:])
        assert "folios en la fila de KAROLAY ACEVEDO JIMÉNEZ" in del_01[1].observaciones
        # Y su cierre, en la hoja 2, que va en el PDF del 02.
        assert "sigue en la hoja 2" in del_01[0].observaciones

    def test_el_acta_individual_sigue_como_siempre(self):
        outcome, _ia = _inventariar(lector=LectorDeColectivas())
        (individual,) = [f for f in outcome.filas if f.sesion == 4]
        assert individual.nombre == "NURY VARELA ESCUDERO"
        assert individual.acta_colectiva == "" and individual.cedula == "45481150"
        assert outcome.sesiones[3].nombre.startswith("NURY VARELA ESCUDERO")

    def test_sin_la_ia_de_texto_la_lista_se_lee_por_regla(self):
        outcome, _ia = _inventariar(lector=None)
        del_rango = [f for f in outcome.filas if f.sesion == 3]
        assert [f.numero for f in del_rango] == ["05408120", "05408121", "05408122", "05408123", "05408124"]
        assert del_rango[0].nombre == "CASTILLO CASTILLA FREDDY"

    def test_el_fuid_una_fila_por_graduado_con_su_pdf(self):
        outcome, _ia = _inventariar(lector=LectorDeColectivas())
        salidas = [f"UPD3859802/{s.orden:02d}_{s.nombre}.pdf" for s in outcome.sesiones]
        filas = resultado_de_cada_acta(outcome.filas, salidas, pidio_dividir=True)
        fuid = filas_del_fuid([asdict(fila) for fila in filas])
        del_rango = [f for f in fuid if f.consecutivo_inicial.startswith("054081")]
        assert [(f.consecutivo_inicial, f.consecutivo_final) for f in del_rango] == [
            ("05408120", "45761728"),
            ("05408121", "1047366182"),
            ("05408122", "1128049264"),
            ("05408123", "1085165668"),
            ("05408124", "1047389211"),
        ]
        assert del_rango[0].asunto.startswith("CASTILLO CASTILLA FREDDY - ENFERMER")
        assert del_rango[0].folios >= 1 and del_rango[0].folios_siar == 2
        assert all(f.folios == 0 and f.folios_siar == 0 for f in del_rango[1:])
        assert all("03_ACTA DE GRADO 05408120 A 05408124 - 26-09-2008.pdf" in f.notas for f in del_rango)

    def test_el_nombre_del_pdf_lleva_la_fecha_revisada(self):
        outcome, _ia = _inventariar(lector=LectorDeColectivas())
        primera = next(f for f in outcome.filas if f.sesion == 3)
        assert nombre_de_la_sesion(primera) == "ACTA DE GRADO 05408120 A 05408124 - 26-09-2008"


class TestLaRevision:
    def test_el_libro_colectivo_no_cuenta_dos_cedulas_como_dos_personas(self):
        perfil = perfil_de("actas-de-grado")
        patrones = perfil.patrones({}, una_persona_por_pdf=False, reglas=REGLAS_DEL_LIBRO_COLECTIVO)
        assert not patrones.una_persona_por_pdf
        assert "colectiva" in patrones.reglas
        # La auditoría sólo sabe la habilidad: la regla del perfil dice la excepción.
        assert "acta colectiva" in perfil.reglas
