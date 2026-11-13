"""Lo que el operador pidió auditar en Odontología el 2026-11-12: cada nombre del FUID contra el papel.

Revisado a ojo en las cajas 00C003288-90 (actas de grado de Enfermería). Cada
caso lleva lo que el bot entregó y lo que dice la hoja.
"""

from __future__ import annotations

from resolutions.adapters.fuid_actas_de_grado import fila_de_la_ceremonia
from resolutions.domain.acta_grado import encabezado_de_la_ceremonia
from resolutions.domain.graduado import (
    nombre,
    nombre_limpio,
    nombre_y_titulo_separados,
    sin_firmantes,
    titulo_del_vocabulario,
    titulo_limpio,
)

QUIROFANO = "ESPECIALISTA EN ENFERMERIA MEDICO QUIRURGICA CON ENFASIS EN QUIROFANO"


class TestElNombre:
    def test_el_firmante_del_pie_que_se_repite_en_el_libro(self):
        nombres = [
            "EDITH BARBOSA ZARAZA CARLOS VILLALBA BUSTILLO",
            "CANDELARIA GUERRERO STAND CARLOS VILLALBA BUSTILLO",
            "DINORA MORALES MARRUGO CARLOS VILLALBA BUSTILLO",
            "EMILIA LUCIA DE LA HOZ DE LA HOZ",
        ]
        assert sin_firmantes(nombres) == [
            "EDITH BARBOSA ZARAZA",
            "CANDELARIA GUERRERO STAND",
            "DINORA MORALES MARRUGO",
            "EMILIA LUCIA DE LA HOZ DE LA HOZ",
        ]

    def test_una_sola_vez_no_es_un_firmante(self):
        assert sin_firmantes(["ELSA GRISOLLE FERNANDEZ CARLOS VILLALBA BUSTILLO"]) == [
            "ELSA GRISOLLE FERNANDEZ CARLOS VILLALBA BUSTILLO"
        ]

    def test_la_cedula_vuelta_letras_tras_el_no(self):
        assert nombre_y_titulo_separados("BELKYS JUDITH JIMENEZ BLANCO NO ASSBB", "ENFERMERA")[0] == "BELKYS JUDITH JIMENEZ BLANCO"
        assert nombre_y_titulo_separados("LUZ ELIANA MENDOZA PEÑA NO", "ENFERMERA")[0] == "LUZ ELIANA MENDOZA PEÑA"

    def test_el_lugar_de_expedicion(self):
        assert nombre_y_titulo_separados("RAMIREZ PARRA DANNY RAFAEL DE CARTAGENA", "ENFERMERA")[0] == "RAMIREZ PARRA DANNY RAFAEL"

    def test_el_apellido_compuesto_se_queda(self):
        assert nombre_y_titulo_separados("EMILIA LUCIA DE LA HOZ DE LA HOZ", "ENFERMERA")[0] == "EMILIA LUCIA DE LA HOZ DE LA HOZ"

    def test_la_cola_del_titulo_vuelve_al_titulo_y_el_nombre_se_queda_entero(self):
        assert nombre_y_titulo_separados("ERNESTINA Y RECUPERACION GUADALUPE PEÑARANDA PEREZ", QUIROFANO) == (
            "ERNESTINA GUADALUPE PEÑARANDA PEREZ",
            f"{QUIROFANO} Y RECUPERACION",
        )
        assert nombre_y_titulo_separados(
            "MARTHA Y RECUPERACION EPIFANIA OROZCO VALETA", QUIROFANO.replace("QUIROFANO", "QUIROPANO")
        ) == ("MARTHA EPIFANIA OROZCO VALETA", f"{QUIROFANO} Y RECUPERACION")

    def test_la_palabra_partida_del_titulo(self):
        nombre_, titulo = nombre_y_titulo_separados(
            "LOIDA ESTER RUGIA CASTELLANOS PATERNINA", "ESPECIALISTA EN ENFERMERIA CON ENFASIS EN NEUROCI"
        )
        assert nombre_ == "LOIDA ESTER CASTELLANOS PATERNINA"
        assert titulo.endswith("NEUROCIRUGIA")

    def test_los_trozos_del_titulo_con_el_titulo_ya_entero(self):
        neuro = "ESPECIALISTA EN ENFERMERIA MEDICO QUIRURGICA CON ENFASIS EN NEUROCIRUGIA"
        assert nombre_y_titulo_separados("LOIDA ESTER RUGIA CASTELLANOS PATERNINA", neuro)[0] == "LOIDA ESTER CASTELLANOS PATERNINA"
        assert nombre_y_titulo_separados("SILVIA CIRUGIA MERCEDES RODRIGUEZ LONDOÑO", neuro)[0] == "SILVIA MERCEDES RODRIGUEZ LONDOÑO"
        assert nombre_y_titulo_separados("MARIA LUCY GICA CON ENFASIS HERNANDEZ CHADID", neuro)[0] == "MARIA LUCY HERNANDEZ CHADID"

    def test_los_apellidos_que_se_parecen_a_un_titulo_se_quedan(self):
        """Medido sobre las 2 284 filas: SALUM no es SALUD, MATEO no es MATERNO, QUIROZ ni PERIÑAN son títulos."""
        for nombre_ in (
            "YADET ESTELA SALUM SALLEG",
            "ISAAC MATEO MOGUEA MONTES",
            "OLGA PATRICIA QUIROZ JIMENEZ",
            "PEGGY MARGARITA NIETO PERIÑAN",
        ):
            assert nombre_y_titulo_separados(nombre_, "ESPECIALISTA EN SALUD FAMILIAR")[0] == nombre_

    def test_las_partidas_del_nombre_se_unen_si_son_un_nombre_conocido(self):
        conocidas = {"CARMEN", "MERCADO", "PATRICIA", "ANA", "MARIA"}
        assert nombre_limpio("PATRICIA DEL CAR MEN SANCHEZ BERMUDEZ", None, conocidas) == "PATRICIA DEL CARMEN SANCHEZ BERMUDEZ"
        assert nombre_limpio("ANA MARIA SEGURA PAZ", None, conocidas) == "ANA MARIA SEGURA PAZ"

    def test_la_constancia_que_relaciona_a_la_estudiante(self):
        texto = (
            "Que en el libro de actas aparece relacionada entre otros el nombre de la estudiante "
            "CLARA ELENA DE JESUS BARRAGAN CORREA, identificada con cédula 45474254"
        )
        assert nombre(texto) == "CLARA ELENA DE JESUS BARRAGAN CORREA"


class TestElActaManuscrita:
    """UPD3859802 pág. 110, como la transcribió la IA: «ACTA 01», «Post-grado» al margen, NURY VARELA ESCUDERO."""

    TEXTO = (
        "64\n\n# ACTA 01\n\nPost-grado\n\nEn la ciudad de Cartagena, a los 21 días del mes\nde Mayo de 1992, se realizó "
        "la graduación in-\ndividual en ceremonia solemne a solicitud\nUniversidad, el Titulo de ESPECIALISTAS EN EN\n\n"
        "FERMERIA MEDICO QUIRURGICA con énfasis en\nQUIROFANO Y RECUPERACION a la estudiante\nNURY VARELA ESCUDERO, "
        "portadora de la cedula\nde ciudadanía Nº de a quien\nse le tomó el juramento de rigor"
    )

    def test_el_nombre_el_titulo_en_varios_renglones_el_numero_y_la_fecha(self):
        from datetime import date

        from resolutions.domain.acta_grado import leer_acta_de_grado

        acta = leer_acta_de_grado([self.TEXTO])
        assert acta.nombre == "NURY VARELA ESCUDERO"
        assert titulo_del_vocabulario(acta.titulo) == (
            "ESPECIALISTA EN ENFERMERIA MEDICO QUIRURGICA CON ENFASIS EN QUIROFANO Y RECUPERACION"
        )
        assert acta.numero == "01"
        assert acta.fecha == date(1992, 5, 21)

    def test_la_nota_al_margen_no_es_un_nombre(self):
        assert nombre_limpio("POST GRADO") is None
        assert nombre_limpio("ACTA DE GRADO NO") is None
        assert nombre_limpio("DEL MES DE DICIEMBRE") is None
        assert nombre_limpio("NURY VARELA ESCUDERO") == "NURY VARELA ESCUDERO"


class TestElTitulo:
    def test_la_letra_mal_leida(self):
        assert titulo_del_vocabulario("ENFERMENA") == "ENFERMERA"
        assert titulo_del_vocabulario("ENFERMERS (O") == "ENFERMERA (O)"
        assert titulo_del_vocabulario(QUIROFANO.replace("ENFASIS", "ENFASUS")) == QUIROFANO

    def test_lo_que_no_se_parece_no_se_toca(self):
        assert titulo_del_vocabulario("INGENIERO CIVIL") == "INGENIERO CIVIL"
        assert titulo_del_vocabulario("ESPECIALISTA EN ESTOMATOLOGIA") == "ESPECIALISTA EN ESTOMATOLOGIA"

    def test_la_frase_de_la_constancia_no_es_titulo(self):
        assert titulo_limpio("ENFERMERA APARECIENDO RELACIONADA ENTRE OTROS EL NOMBRE") == "ENFERMERA"
        assert titulo_limpio("ENFERMERA EL") == "ENFERMERA"


class TestLaHojaQueNoEsUnActa:
    RESOLUCION = (
        "UNIVERSIDAD DE CARTAGENA\nRESOLUCIÓN No. 01633\n\"Por medio de la cual se autorizan grados secretariales\"\n"
        "EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA\nCONSIDERANDO\nRESUELVE:\nArtículo 1º Otorgar el título de: ENFERMERO (A), "
        "a través de la Secretaria General, a los siguientes\negresados:\n1. CC 1047464934 YULIANIS ARELLANO RODELO"
    )
    CEREMONIA = (
        "Universidad de Cartagena\nFacultad de Enfermería\nActas de Grado No. 05418726 a 05418731\n"
        "Ceremonia de Grado: 23 de Febrero de 2018\n1 CHAPARRO CARREÑO YENNY ANDREA"
    )

    def test_la_resolucion_con_su_numero_y_lo_que_resuelve(self):
        """El operador: «en el asunto irá la resolución + resuelve (resumen)»."""
        assert encabezado_de_la_ceremonia([self.RESOLUCION]) == (
            "RESOLUCION 01633 - OTORGAR EL TITULO DE: ENFERMERO (A), A TRAVES DE LA SECRETARIA GENERAL, "
            "A LOS SIGUIENTES EGRESADOS"
        )

    def test_sin_resuelve_legible_su_epigrafe(self):
        sin_articulo = self.RESOLUCION.split("Artículo")[0] + "RESUELVE"
        assert encabezado_de_la_ceremonia([sin_articulo]) == (
            "RESOLUCION 01633 - POR MEDIO DE LA CUAL SE AUTORIZAN GRADOS SECRETARIALES"
        )

    def test_la_ceremonia_con_sus_actas(self):
        assert encabezado_de_la_ceremonia([self.CEREMONIA]) == "CEREMONIA DE GRADO - ACTAS 05418726 A 05418731"

    def test_la_resolucion_va_al_fuid_y_la_ceremonia_no(self):
        base = {"tipo": "CEREMONIA DE GRADO", "carpeta": "00C003290/UPD3859820", "fecha": "05-02-2024",
                "pagina_inicial": 7, "pagina_final": 8, "archivo": "UPD3859820.pdf"}
        fila = fila_de_la_ceremonia({**base, "acta": "RESOLUCION 01633 - POR MEDIO DE LA CUAL SE AUTORIZAN GRADOS SECRETARIALES"})
        assert fila is not None
        assert fila.asunto.startswith("RESOLUCION 01633")
        # El número completo, con su año, como en las resoluciones de la caja 3303.
        assert fila.consecutivo_inicial == fila.consecutivo_final == "01633-2024"
        assert fila_de_la_ceremonia({**base, "acta": "CEREMONIA DE GRADO - ACTAS 05418726 A 05418731"}) is None


# -- UPD3859813 (2026-11-13): el rector que firma y el apellido del renglón de «portador» --

from resolutions.domain.graduado import (  # noqa: E402
    firmantes_del_libro,
    nombre_con_la_cola_del_renglon,
)

#: El pie de las hojas de UPD3859813 como lo deja la capa del escáner.
PIES_DEL_LIBRO = [
    "Para constancia de lo expuesto, se firma la presente acta.\nCARLOS VILLALBA BUSTILLO\nRector\nPIEDAD PEREZ CESPEDES\nDecano",
    "que en ella intervinieron.\nCARIXS VILLALBA BHSTILLO\nRector\nMANUEL SIERRA NAVARRO\nEl Secretario General",
    "que en ella intervinieron,/\nCARLOS VILLALBA BüSTILLO\nRector\nMANUEL SIERRA NAVARRO\nEl Secretario General",
    "GU DE EZ\nRector",
]


class TestElQueFirmaUnaSolaVez:
    def test_los_firmantes_son_los_que_el_libro_muestra_sobre_su_cargo(self):
        firmantes = firmantes_del_libro(PIES_DEL_LIBRO)
        assert "CARLOS VILLALBA BUSTILLO" in firmantes and "MANUEL SIERRA NAVARRO" in firmantes
        # Lo que la capa deja una sola vez, sin nada parecido, es basura.
        assert "GU DE EZ" not in firmantes

    def test_con_una_vez_basta_si_es_quien_firma(self):
        """Fila 1802: la única graduada del libro con el rector pegado detrás."""
        firmantes = firmantes_del_libro(PIES_DEL_LIBRO)
        assert sin_firmantes(
            ["ELSA GRISOLLE FERNANDEZ CARLOS VILLALBA BUSTILLO", "MARIA DE LA CRUZ LOPEZ SANCHEZ"], firmantes
        ) == ["ELSA GRISOLLE FERNANDEZ", "MARIA DE LA CRUZ LOPEZ SANCHEZ"]

    def test_un_graduado_con_apellidos_parecidos_no_se_toca(self):
        firmantes = firmantes_del_libro(PIES_DEL_LIBRO)
        assert sin_firmantes(["JUANA MARIA PEREZ CESPEDES ROJAS"], firmantes) == ["JUANA MARIA PEREZ CESPEDES ROJAS"]


#: La hoja 163 de UPD3859813 como la leyó la IA: no vio «al estudiante VIVIAN
#: LOPEZ», impreso sobre el título, pero sí el apellido del renglón siguiente.
HOJA_DE_VIVIAN = """el título de ESPECIALISTA EN ENFERMERIA MEDICO QUIRURGICA

CON ENFASIS EN NEUROCIRUGIA

VERHELST portador de la cédula de ciudadanía

No. 30.761.675 expedida en Arjona (Bolívar) a quien se le tomó"""
TITULO = "ESPECIALISTA EN ENFERMERIA MEDICO QUIRURGICA CON ENFASIS EN NEUROCIRUGIA"


class TestElApellidoDelRenglonDePortador:
    def test_completa_el_nombre_del_ocr_sin_el_trozo_del_titulo(self):
        """Fila 1792: el OCR leyó «VIVIANA LOPEZ QUIRURI ENPASIS»; en el papel, VIVIAN LOPEZ VERHELST."""
        assert (
            nombre_con_la_cola_del_renglon("VIVIANA LOPEZ QUIRURI ENPASIS", HOJA_DE_VIVIAN, TITULO)
            == "VIVIANA LOPEZ VERHELST"
        )

    def test_si_el_nombre_ya_lo_trae_no_cambia(self):
        assert nombre_con_la_cola_del_renglon("VIVIAN LOPEZ VERHELST", HOJA_DE_VIVIAN, TITULO) is None

    def test_la_palabra_del_titulo_delante_de_portador_no_es_apellido(self):
        texto = "el título de ENFERMERA\nNEUROCIRUGIA portador de la cédula"
        assert nombre_con_la_cola_del_renglon("ANA PEREZ GOMEZ", texto, TITULO) is None

    def test_un_apellido_que_la_otra_lectura_si_ve_no_se_quita(self):
        """«QUIROZ» se parece a QUIROFANO, pero la hoja lo trae: no es un trozo del título."""
        texto = "al estudiante ANA QUIROZ\nVERHELST portador de la cédula"
        assert nombre_con_la_cola_del_renglon("ANA PEREZ QUIROZ", texto, TITULO) == "ANA PEREZ QUIROZ VERHELST"
