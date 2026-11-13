"""El libro de actas colectivas, hoja por hoja: lo que el libro entero UPD3859802 enseñó el 2026-11-13.

Medido sobre las 196 hojas de UPD3859802 (Odontología, actas de grado a mano de
1980 a 2012) contra la verdad del papel de 22 actas: cada prueba es una hoja
real, con el texto como lo transcribió la IA de pago. Ninguna llama a un
proveedor de pago.

* la hoja cuya lista sigue la del acta de delante es suya aunque diga «La
  ceremonia estuvo presidida…» (hojas 64 y 143);
* el encabezado abreviado que quedó en blanco no es un acta (hoja 140);
* la portada separadora va delante del acta que la sigue (hoja 59);
* la lista sin número bajo su título, con la cédula rotulada (hojas 25 y 35),
  y la de 1980, «Las graduandas son:» con la cédula partida (hoja 60);
* el orden del día no es un graduado; la cédula con un solo punto va entera;
* el acta a medio escribir no gradúa a nadie (hoja 138);
* la lectura de la IA en bucle se relee en dos mitades (hojas 74 y 80).
"""

from __future__ import annotations

from resolutions.application.acta_consejo import MITADES_DE_LA_HOJA, InventariarActa
from resolutions.application.control import NullRunControl
from resolutions.application.ports import OcrResult
from resolutions.domain.acta_grado import (
    acta_sin_terminar,
    es_acta_colectiva,
    graduados_de_la_lista,
    renglones_en_bucle,
    reparto_del_libro_colectivo,
    sigue_la_lista,
    ultimo_puesto,
)

CUERPO = (
    "En la ciudad de Cartagena a los 18 días del mes de Diciembre de 1980, se realizó la graduación colectiva "
    "en ceremonia solemne, a solicitud de la Decana, quien autorizó el acto mediante Resolución Nº 542."
)

#: Hoja 63 (folio 4): el Acta Nº 02 de 1980 y su lista hasta el 44.
ACTA_02 = "4\n\n# Acta N° 02.-\n\n" + CUERPO + "\n\n" + "\n".join(
    f"{n}. Graduada Numero{chr(64 + n % 26)} Apellido{chr(65 + n % 20)}" for n in range(1, 45)
)
#: Hoja 64 (folio 5): la cola de su lista, «no aparece» a lápiz, y el orden del día.
COLA_DEL_ACTA_02 = """5

32/1

45. Omaira Solarte Phenal 4N-434 3N6 9pm

46. Cecilia Turizo Araujo no aparece

47. Nidier Villarreal Leal no aparece

La ceremonia estuvo presidida por el Señor

Pector, Sr. Luis H. Arraut S. con el siguiente orden del día:

1º Número a Colombia

2º Lectura de la Resolución Nº 542 de Aje 11/80 encañada de la Rectoría.

5º Toma del juramento por el Sr. Rector

8º Número a Cartagena

Nury Torres García
Decana.-
"""


class TestLaHojaQueSigueLaLista:
    def test_la_cola_de_la_lista_es_del_acta_aunque_hable_de_la_ceremonia(self) -> None:
        assert ultimo_puesto(ACTA_02) == 44
        assert sigue_la_lista(ACTA_02, COLA_DEL_ACTA_02)

        partes = reparto_del_libro_colectivo([ACTA_02, COLA_DEL_ACTA_02])

        assert [(p.en_el_pdf, p.ceremonia) for p in partes] == [((1, 2), False)]
        graduados = graduados_de_la_lista(partes[0].texto)
        assert len(graduados) == 47
        # La cédula mal leída «4N-434 3N6 9pm» no se pega al nombre.
        assert graduados[44].nombre == "OMAIRA SOLARTE PHENAL"
        assert graduados[45].nota == graduados[46].nota == "marcado a lápiz: no aparece"
        # El orden del día no es un graduado.
        assert not any("COLOMBIA" in (g.nombre or "") or "CARTAGENA" in (g.nombre or "") for g in graduados)

    def test_la_lista_que_empieza_en_uno_bajo_el_acta_que_continua(self) -> None:
        """Hoja 142-143: «Acta 06 / … Según / continúa →» y arriba de la siguiente «1. Eduardo …»."""
        anterior = "141\n\n46 Zuniga Ortega Zoraida 45.517.404 Cgena\n\n# Acta 06\nEspecialista en Salud ocupacional Según\n\ncontinuo →"
        siguiente = (
            "142\n\nResolución N° 2892 de fecha 5 de diciembre de 2003\n\n1. Eduardo Isidro Blanco Granados.\n\n"
            "Diono Pastoryo Orozco\nDecora"
        )
        assert sigue_la_lista("# Acta 06\nEspecialista en Salud ocupacional Según\n\ncontinuo →", siguiente)
        assert not sigue_la_lista(anterior, "143\n\nLa ceremonia estuvo presidida por el Rector.")

    def test_la_hoja_que_no_sigue_la_numeracion_no_se_pega(self) -> None:
        assert not sigue_la_lista(ACTA_02, "6\n\n12. Pedro Perez Gomez 45.123.456\n")


class TestEncabezadoEnBlancoYPortada:
    def test_el_encabezado_abreviado_en_blanco_es_una_nota_de_la_de_delante(self) -> None:
        """Hoja 140: «Acto 04 / Especialista en.» al pie, y la 141 abre con el Acta 05."""
        hoja_140 = "139\n\n# Act 03\n\n" + CUERPO + "\n\n1. Gomez Vega Viviana c.e 22804593\n2. Quiroz Hernandez Angelica c.e 45693163\n\nActo 04\nEspecialista en."
        hoja_141 = "140\n\n# Acto 05\n\n" + CUERPO + "\n\n1. Altamar Miranda Catalina c.e 45530396\n"

        partes = reparto_del_libro_colectivo([hoja_140, hoja_141])

        assert [p.en_el_pdf for p in partes] == [(1,), (2,)]
        assert "quedó en blanco" in partes[0].notas[0]

    def test_la_portada_va_delante_del_acta_que_la_sigue(self) -> None:
        """Hoja 59: «Pregrado 1980-2012», la portada de la segunda parte del libro."""
        portada = "Pregrado. 1980 - 2012\n\nde Grado\n1980"
        acta = "1\n\n# Acta N° 01\n\n" + CUERPO + "\n\n1. Perez Bohorquez Carmen Teresa 45.120.826\n2. Yanez Parada Guadalupe 34.325.259"

        partes = reparto_del_libro_colectivo([portada, acta])

        assert len(partes) == 1
        assert partes[0].en_el_pdf == (1, 2) and not partes[0].ceremonia
        assert "portada" in partes[0].notas[0]


class TestLaListaSinNumero:
    def test_bajo_su_titulo_con_la_cedula_rotulada(self) -> None:
        """Hoja 25: el Acta 04 de 1996 nombra a sus graduados bajo dos títulos, sin número."""
        texto = (
            "# Acta 04\n\n" + CUERPO + " el título de Especialista en Salud Ocupacional a ... portador(a) de la "
            "cédula\n\nEspecialistas en Salud Ocupacional\n\n"
            "Calvo Martinez Susana (hoy Senora de Ortiz)\ncc 34.825.001 de Bucaramanga (Santander)\n\n"
            "Simanca Torres María de los Santos\ncc 45.450.613 de Cartagena (Bol)\n\n"
            "Especialista en Médico Quirurgica con Enfasis en Urgencias\n\n"
            "- Arieta Narvaez Stella del Socorro cc 45.478.083 de Cartagena (Bol)\n"
            "- Campo Torregroza Estelvia Leonor cc 49.731.465 de Valledupar (Cesar)\n\n"
            "Vilma Luz Vergara Martelo\nDecana."
        )
        graduados = graduados_de_la_lista(texto)

        assert [(g.nombre, g.cedula) for g in graduados] == [
            ("CALVO MARTINEZ SUSANA", "34825001"),
            ("SIMANCA TORRES MARÍA DE LOS SANTOS", "45450613"),
            ("ARIETA NARVAEZ STELLA DEL SOCORRO", "45478083"),
            ("CAMPO TORREGROZA ESTELVIA LEONOR", "49731465"),
        ]
        assert graduados[0].nota == "anotado en el papel: «hoy Senora de Ortiz»"
        assert graduados[0].titulo == "ESPECIALISTAS EN SALUD OCUPACIONAL"
        assert graduados[2].titulo.startswith("ESPECIALISTA EN MEDICO QUIRURGICA")

    def test_el_graduado_en_blanco_con_su_nombre_en_la_lista(self) -> None:
        """Hoja 35: «… Salud Ocupacional a - - - Portador» y debajo «1- Edgardo José Niño O. sario /ect»."""
        texto = (
            "# Acta 03\n\n" + CUERPO + " el título de Especialista en\nSalud Ocupacional a - - - - - - Portador de la\n"
            "Cédula de Ciudadanía nº - - - - - expedida en - -\n\nEspecialista en Salud Ocupacional:\n"
            "1- Edgardo José Niño O. sario /ect\n\nVilma Luz Vergara Martelo\nDecana"
        )
        graduados = graduados_de_la_lista(texto)

        assert [g.nombre for g in graduados] == ["EDGARDO JOSÉ NIÑO OSARIO"]
        assert es_acta_colectiva(texto)

    def test_las_graduandas_son_con_la_cedula_partida_en_dos_renglones(self) -> None:
        """Hoja 60, Acta 01 de 1980: «Las graduandas son:» y «con C.C. #34» / «325.259 de Cuenta»."""
        texto = (
            "# Acta N° 01\n\n" + CUERPO + " a cuatro\n(4) estudiantes quienes cumplieron lo reglamentado. Las graduandas son:\n"
            "Carmen Teresa Perez Bohanquez con T.I.\nCédula #120826 de Cuenta\n"
            "Guadalupe Yáñez Parada con C.C. #34\n325.259 de Cuenta.\n"
            "Lorica Phillips de Porras con C.C. #8-\n93-880 de Catania\n"
        )
        graduados = graduados_de_la_lista(texto)

        assert [(g.nombre, g.cedula) for g in graduados] == [
            ("CARMEN TERESA PEREZ BOHANQUEZ", "120826"),
            ("GUADALUPE YÁÑEZ PARADA", "34325259"),
            # «de Porras» es su apellido de casada, no el lugar de expedición;
            # y «93-880 de Catania» no es la graduada «DE CATANIA».
            ("LORICA PHILLIPS DE PORRAS", None),
        ]
        assert es_acta_colectiva(texto)


class TestRenglonesDeLaLista:
    def test_la_cedula_con_un_solo_punto_va_entera(self) -> None:
        texto = (
            "45. Vasquez Arrieta Javier Alfonso c.e 9.177901 Turbaco\n"
            "46. Zuniga Ortega Zoraida del C. c.e 45.517404 Cgena\n"
            "29. Olier Barraza Ishana de la C. c.e 45525.602 Cgena\n"
        )
        assert [g.cedula for g in graduados_de_la_lista(texto)] == ["9177901", "45517404", "45525602"]

    def test_la_c_leida_como_b_si_trae_su_cedula(self) -> None:
        """Hoja 74: la IA pasó la «C» a mano a «b» minúscula; la cédula prueba que es un graduado."""
        texto = "9 bostro Robles Melody 45.406.386 C/gena\n10 de la Rosa Sougoly Betty 64.542.087 Sincelejo\n"
        graduados = graduados_de_la_lista(texto)

        assert [g.orden for g in graduados] == [9, 10]
        assert graduados[1].nombre == "DE LA ROSA SOUGOLY BETTY"

    def test_sin_cedula_las_minusculas_no_pasan(self) -> None:
        assert graduados_de_la_lista("7 borbó de hidalgo con opinion\n") == []

    def test_el_orden_del_dia_no_es_un_graduado(self) -> None:
        texto = "1º Apertura de la sesión\n2º Lectura Resolución Nº 514\n1º Número a Colombia\n8º Número a Cartagena\n"
        assert graduados_de_la_lista(texto) == []


class TestActaSinTerminar:
    def test_el_formulario_en_blanco_sin_lista_no_gradua_a_nadie(self) -> None:
        """Hoja 138: el Acta 02 de 2003, escrita a medias y sin firmar."""
        texto = (
            "# Acta 02\n\n" + CUERPO + " el título de: Especialista en ____________ a ____________, portador de la "
            "cédula de ciudadanía Nº ______ expedida en ____________.\nPara constancia de lo expuesto, se firmo.\nDr:"
        )
        assert acta_sin_terminar(texto)
        assert not es_acta_colectiva(texto)

    def test_con_su_lista_no_esta_sin_terminar(self) -> None:
        texto = (
            "# Acta 02\n\n" + CUERPO + " el título de Enfermera a ____________, portador de la cédula\n"
            "1. Gomez Vega Viviana c.e 22804593\n"
        )
        assert acta_sin_terminar(texto) is None


#: Hoja 80 tal como la devolvió la IA: el primer graduado y luego el bucle.
EN_BUCLE = """22

# complementario

① Nobel Barbara Barroso
2. 2.3.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.
3. 0.1000 Rmmo Hm
5. 1. 2. 3. 4. 5. 6. 7. 8. 9. 10. 11. 12. 13. 14. 15. 16. 17. 18. 19. 20. 21. 22. 23. 24. 25.
"""


class TestLaLecturaEnBucle:
    def test_reconoce_el_bucle_y_no_la_raya_del_formulario(self) -> None:
        assert renglones_en_bucle(EN_BUCLE) == 2
        assert renglones_en_bucle("15. Galindo Gloria H. H. H. H. H. H. H. H. H. H. H. H. H. H.") == 1
        assert renglones_en_bucle("a _________________ portador (a) de\nmera (o) a _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _") == 0

    def test_relee_la_hoja_en_dos_mitades_y_se_queda_la_buena(self) -> None:
        pedidas: list[tuple[int, object, int]] = []

        class Fuente:
            def render(self, pagina, banda, dpi):  # noqa: ANN001, ANN202
                pedidas.append((pagina, banda, dpi))
                return f"{pagina}-{len(pedidas)}".encode()

        class Lector:
            def read(self, imagen: bytes) -> OcrResult:
                mitad = int(imagen.decode().split("-")[1])
                texto = "22\n① Mobel Berbesi Barroso\n2. Zully Moreno de Villalba" if mitad == 1 else "3. Alvaro Romero Herrera"
                return OcrResult(text=texto, mean_confidence=0.0)

        caso = InventariarActa.__new__(InventariarActa)
        caso._relector_de_pago = Lector()
        caso._control = NullRunControl()
        leidas = {80: EN_BUCLE, 81: "1. Pedro Perez Gomez 45.123.456"}

        caso._releer_los_bucles(Fuente(), leidas)

        assert [banda for _p, banda, _d in pedidas] == list(MITADES_DE_LA_HOJA)
        assert "Zully Moreno de Villalba" in leidas[80] and "Alvaro Romero Herrera" in leidas[80]
        assert renglones_en_bucle(leidas[80]) == 0
        # La que no estaba en bucle no se paga otra vez.
        assert {pagina for pagina, _b, _d in pedidas} == {80}
