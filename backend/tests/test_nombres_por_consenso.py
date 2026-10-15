"""El nombre y la cédula de cada graduado, votados entre todas las lecturas de su hoja.

Los casos son de la caja de Odontología 3284-3290: lo que leyó cada motor de
la misma hoja, y lo que dice el papel. Ninguna prueba llama a la IA.
"""

from __future__ import annotations

import pytest

from resolutions.application.acta_consejo import _nombres_del_archivo, nombres_conocidos
from resolutions.domain.nombres import (
    consenso,
    consenso_de_cedulas,
    palabras_de,
    parece_palabra_de_nombre,
    sin_perder_conocidas,
    zona_del_nombre,
)


@pytest.fixture(scope="module")
def diccionario():
    de_pila, apellidos = _nombres_del_archivo()
    return {"conocidas": nombres_conocidos(), "de_pila": de_pila, "apellidos": apellidos}


def _votar(lecturas, diccionario):
    return consenso([(texto, 1.0) for texto in lecturas], diccionario["conocidas"],
                    de_pila=diccionario["de_pila"], apellidos=diccionario["apellidos"])


class TestLaZonaDelNombre:
    def test_trae_los_dos_renglones(self):
        texto = "X.X.X. al estudiante LEDA MARIA\nGARCES GUERRA .X.XeXoXoXoXoXoXoX.X portador de la cédula"
        assert zona_del_nombre(texto) == "LEDA MARIA GARCES GUERRA"

    def test_corrige_las_cifras_por_letras(self):
        texto = "CIONAL al estudiante $ARAY ELENA\nCASTILLO SIERRA portador de la cédula"
        assert zona_del_nombre(texto) == "SARAY ELENA CASTILLO SIERRA"

    def test_la_profesion_no_es_el_rotulo(self):
        texto = "el ejercicio de la profesión de ENFERMERA según las disposiciones vigentes"
        assert zona_del_nombre(texto) is None

    def test_sin_zona_no_hay_nombre(self):
        assert zona_del_nombre("ACTA DE GRADO No. 03") is None


class TestLasPalabrasDelNombre:
    def test_quita_el_titulo_y_la_fecha(self):
        assert palabras_de("SARAY ELENA OCUPACIONAL CASTILLO", titulo="ESPECIALISTA EN SALUD OCUPACIONAL") == [
            "SARAY", "ELENA", "CASTILLO",
        ]
        assert palabras_de("GONZALEZ VIDES MIL NOVECIENTOS NOVENTA Y SXETE") == ["GONZALEZ", "VIDES", "Y"]

    def test_no_confunde_apellidos_con_numeros(self):
        # CASTRO no es CUATRO, ni TERESA es TRES.
        assert palabras_de("CELINA ISABEL CASTRO ACOSTA") == ["CELINA", "ISABEL", "CASTRO", "ACOSTA"]
        assert palabras_de("MARIA TERESA GIL GAMEZ") == ["MARIA", "TERESA", "GIL", "GAMEZ"]

    def test_quita_el_formato_de_la_ia(self):
        assert palabras_de("**ENFERMERO** **JORGE LEONARDO GUTIERREZ**") == ["JORGE", "LEONARDO", "GUTIERREZ"]

    def test_palabras_imposibles(self):
        assert not parece_palabra_de_nombre("MSCSDSS")
        assert not parece_palabra_de_nombre("NAANNANCANAACANAA")
        assert parece_palabra_de_nombre("URBINA")


class TestElConsenso:
    @pytest.mark.parametrize(
        ("lecturas", "papel"),
        [
            (
                ["ROSA HARÍA CABALLERO MONTÜXA", "ROSA VARIA CABALLERO MONTOYA",
                 "NOSA ARIA CABALLERO MONTOVA", "MOSA MARRA CABALLENO MONTOYA"],
                "ROSA MARIA CABALLERO MONTOYA",
            ),
            (["LEDA MARIA", "LEDA MARIA GARCES GUERRA"], "LEDA MARIA GARCES GUERRA"),
            (["E DNA D N A VALIENTE CARABALLO", "E DNA VALIENTE CARABALLO", "EDNA VALIENTE CARABALLO"],
             "EDNA VALIENTE CARABALLO"),
            (["GONZALEZ VIDES MIL NOVECIENTOS NOVENTA Y SXETE", "GONZALEZ VIDES", "SUILLERMO GONSALEZ VDES"],
             "GUILLERMO GONZALEZ VIDES"),
            (["Y MARTHA OSORIO LAMEIS", "MARRHA Y OSORIO LAMBIS NAANNANCANAACANAA",
              "MARRHA Y OSORIO LAMBIS ENAANAAACANAANANAA"], "MARTHA OSORIO LAMBIS"),
            (["LUZ CENITÍI CÜFÍ", "UZ CENRRA VASQUEZ BOJATO", "IUZ CENITH VASQUEZ BOJATO",
              "LUZ CENITH VASQUEZ BOJATO"], "LUZ CENITH VASQUEZ BOJATO"),
        ],
    )
    def test_casos_de_la_caja(self, lecturas, papel, diccionario):
        assert _votar(lecturas, diccionario).nombre == papel

    def test_un_nombre_valido_que_no_esta_en_la_lista_no_se_toca(self, diccionario):
        # Usado solo, el diccionario convertía URBINA en RINA.
        assert _votar(["CECILIA ÜRBINA ARIAS"], diccionario).nombre == "CECILIA URBINA ARIAS"

    def test_dos_lecturas_iguales_no_bastan_para_confirmar(self, diccionario):
        # La capa y la franja pueden equivocarse igual: PIIAMA dos veces.
        votado = _votar(["PIIAMA DEL ROSARIO RESTREPO", "PIIAMA DEL ROSARIO RESTREPO"], diccionario)
        assert not votado.confirmado


class TestNoEmpeorarLoLeido:
    def test_se_repone_la_palabra_conocida(self, diccionario):
        assert sin_perder_conocidas(
            ["EDGARDO", "JOSE"], ["ENCARDO", "JOSE", "NUNO", "OSORIO"], diccionario["conocidas"]
        ) == ["EDGARDO", "JOSE", "NUNO", "OSORIO"]

    def test_sin_donde_reponerla_el_voto_no_vale(self, diccionario):
        assert sin_perder_conocidas(
            ["EVANGELINA", "ESPITIA"], ["ANGELINA", "ESPITIA"], diccionario["conocidas"]
        ) is None


class TestLaCedula:
    def test_el_uno_de_mas(self):
        assert consenso_de_cedulas([("133155659", 1), ("33155659", 1)]) == ("33155659", True)

    def test_gana_la_mayoria(self):
        assert consenso_de_cedulas([("45366705", 1), ("45366705", 1), ("4536670", 1)]) == ("45366705", True)

    def test_un_empate_no_decide(self):
        assert consenso_de_cedulas([("45366705", 1), ("45366706", 1)]) == (None, False)
