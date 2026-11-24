"""Cada anexo con su documento: la secuencia del PDF, la persona del anexo y la IA (el operador, 2026-11-23).

«Necesito que el bot tenga la habilidad de razonar, de acuerdo al orden de
secuencia en el PDF, cuál es anexo de cada página principal»; «si ve que la
página principal es la carta y la segunda también, pero la tercera es una
cédula que no pertenece a la hoja…»; «aproxima la unión de páginas por
razonamiento también, con IA»; «que cubra todos los escenarios posibles».

Datos inventados: ninguna persona, cédula ni NIC es de un expediente real.
"""

from __future__ import annotations

import pytest

from resolutions.application.anexos_declarados import (
    asignar_por_secuencia,
    es_anexo_por_secuencia,
    los_anexos_detras,
)
from resolutions.domain.anexos_declarados import titular_del_recibo
from resolutions.domain.asunto_del_documento import (
    ACUERDO_DE_PAGO,
    DECLARACION_JURAMENTADA,
    FORMATO_DE_LA_EMPRESA,
    formulario_que_abre,
    trae_el_membrete,
)
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.secuencia_de_anexos import (
    AL_INICIO,
    CON_SU_PRINCIPAL,
    CONFIRMADO_POR_LA_IA,
    DE_SU_PERSONA,
    NADIE_LO_NOMBRA,
    NO_SE_CONFIRMO,
    NO_SE_LEYO,
    POR_LA_IA,
    TRAS_LA_CONSTANCIA,
    TRAS_LA_CONSTANCIA_AL_ANTERIOR,
    auditar_la_secuencia,
    dueno_razonado,
    duenos_por_secuencia,
    eleccion_del_juez_de_anexos,
    opciones_para_el_juez,
)

CARTA_DE_PEDRO = (
    "Magangué, 3 de marzo de 2022\nSeñores AFINIA\nAsunto: Reclamo por cobro de energía\n"
    "Yo, PEDRO PEREZ PAEZ, identificado con C.C. 12.345.678, solicito respetuosamente la revisión del "
    "cobro de energía que llegó en la factura del mes pasado, porque el consumo registrado no corresponde "
    "con lo que realmente se gasta en la vivienda ni con los meses anteriores."
)
SEGUNDA_HOJA = (
    "y por lo anterior solicito que se revise el consumo del mes y se corrija el valor cobrado, que se "
    "verifique el medidor instalado en la vivienda y que se me informe por escrito el resultado de la "
    "visita técnica realizada por los funcionarios de la empresa."
)
DECLARACION_DE_ANA = (
    "Una filial del Grupo EPM\nLugar: Magangué Fecha: 04-03-2022\n"
    "REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO\n"
    "Mediante la presente, el suscrito ANA MARIA GOMEZ RUIZ, identificado con Cédula de Ciudadanía "
    "número 98.765.432, declaro bajo la gravedad de juramento."
)


def _cedula(numero: str, apellidos: str, nombres: str) -> str:
    return (
        "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n"
        f"{numero} NUMERO\n{apellidos}\nAPELLIDOS\n{nombres}\nNOMBRES"
    )


CEDULA_DE_PEDRO = _cedula("12.345.678", "PEREZ PAEZ", "PEDRO PABLO")
CEDULA_DE_ANA = _cedula("98.765.432", "GOMEZ RUIZ", "ANA MARIA")
CEDULA_ILEGIBLE = "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n~~ ;; ''"
FACTURA_DE_PEDRO = (
    "Operador de Red: Caribemar de la Costa S.A.S E.S.P NIU: 17600001\n"
    "Titular de Pago PEREZ PAEZ PEDRO PABLO Usuario o suscriptor PEREZ PAEZ PEDRO PABLO Estrato 2"
)
CONSTANCIA = (
    "CARIBEMAR DE LA COSTA S.A.S. ESP Nit: 901.380.949-1\nCONSTANCIA DE RECEPCIÓN DE PETICIONES\n"
    "N° PQR: RE2310202200001 Cliente PEDRO PEREZ PAEZ C.C. 12.345.678 Dirección calle principal del barrio "
    "centro Causa reclamación por alto consumo Fecha de atención vence según términos de ley para responder "
    "la petición presentada por el usuario en la oficina comercial"
)
MUDA = "  .  "


def _grupos(*documentos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(hojas))
            for i, hojas in enumerate(documentos, start=1)
        ]
    )


def _hojas(resultado) -> list[list[int]]:
    return [list(g.page_numbers) for g in resultado.grupos.groups]


def _de_la_capa(textos):
    """La identidad como la lee el worker de la capa: el número y el nombre de la cédula, el titular de la factura."""
    from resolutions.domain.tramites import identidad_de_la_cedula

    def identidad_de(pagina, clase):
        texto = textos.get(pagina, "")
        identidad = titular_del_recibo(texto) if clase == "factura" else identidad_de_la_cedula(texto)
        return (identidad, "capa") if identidad else (None, None)

    return identidad_de


# -- la secuencia, pura ----------------------------------------------------------------


class TestLaSecuencia:
    def test_cada_anexo_con_la_principal_anterior(self):
        documento_de = {1: 0, 2: 1, 3: 1, 4: 1, 5: 2}
        assert duenos_por_secuencia([1, 2, 3, 4, 5], {2, 3, 4}, documento_de) == {2: (0, 1), 3: (0, 1), 4: (0, 1)}

    def test_los_anexos_del_principio_van_con_la_primera_principal(self):
        assert duenos_por_secuencia([1, 2, 3], {1, 2}, {1: 0, 2: 0, 3: 1}) == {1: (1, 3), 2: (1, 3)}

    def test_un_pdf_solo_de_anexos_se_queda_como_esta(self):
        assert duenos_por_secuencia([1, 2], {1, 2}, {1: 0, 2: 0}) == {1: (0, None), 2: (0, None)}

    def test_el_anexo_sigue_a_su_hoja_aunque_su_hoja_haya_ido_a_otro_documento(self):
        # La Habeas Data (hoja 4) se fue al acuerdo (documento 0); su cédula (hoja 5) va con ella.
        assert duenos_por_secuencia([1, 2, 3, 4, 5], {5}, {1: 0, 2: 0, 3: 1, 4: 0, 5: 1}) == {5: (0, 4)}


# -- la persona del anexo ----------------------------------------------------------------


class TestLaPersona:
    PRINCIPALES = {0: CARTA_DE_PEDRO, 1: DECLARACION_DE_ANA}
    ANCLAS = {0: 1, 1: 4}

    def test_la_principal_anterior_la_nombra_y_se_queda(self):
        dueno = dueno_razonado((0, 1), CON_SU_PRINCIPAL, CEDULA_DE_PEDRO, self.PRINCIPALES, self.ANCLAS, siguiente=1)
        assert (dueno.documento, dueno.regla, dueno.aviso) == (0, CON_SU_PRINCIPAL, None)
        assert any(p.startswith("n.º") for p in dueno.pruebas)

    def test_la_cedula_de_otra_persona_va_al_documento_que_la_nombra(self):
        """El caso del operador: carta de Pedro en las hojas 1-2, cédula de Ana en la 3, declaración de Ana en la 4."""
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, CEDULA_DE_ANA, self.PRINCIPALES, self.ANCLAS, siguiente=1)
        assert (dueno.documento, dueno.ancla, dueno.regla) == (1, 4, DE_SU_PERSONA)

    def test_con_una_cifra_mal_leida_tambien_casa(self):
        mal_leida = CEDULA_DE_ANA.replace("98.765.432", "98.765.482")
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, mal_leida, self.PRINCIPALES, self.ANCLAS, siguiente=1)
        assert dueno.documento == 1

    def test_si_la_nombran_dos_va_al_mas_cercano_y_el_siguiente_gana_el_empate(self):
        principales = {0: CARTA_DE_PEDRO, 1: DECLARACION_DE_ANA, 2: DECLARACION_DE_ANA}
        anclas = {0: 1, 1: 4, 2: 8}
        cerca = dueno_razonado(
            (0, 2), CON_SU_PRINCIPAL, CEDULA_DE_ANA, principales, anclas, siguiente=None, distancia={0: 1, 1: 5, 2: 2}
        )
        assert cerca.documento == 2
        empate = dueno_razonado(
            (0, 2), CON_SU_PRINCIPAL, CEDULA_DE_ANA, principales, anclas, siguiente=1, distancia={0: 1, 1: 2, 2: 2}
        )
        assert empate.documento == 1

    def test_si_nadie_la_nombra_se_queda_con_aviso(self):
        extrana = _cedula("55.555.555", "TORRES LUNA", "CARLOS JOSE")
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, extrana, self.PRINCIPALES, self.ANCLAS, siguiente=1)
        assert (dueno.documento, dueno.aviso) == (0, NADIE_LO_NOMBRA)

    def test_si_la_nombran_todos_no_distingue_y_se_queda(self):
        # El titular del servicio está en todos los documentos del expediente.
        principales = {0: CARTA_DE_PEDRO, 1: CARTA_DE_PEDRO.replace("3 de marzo", "9 de abril"), 2: CARTA_DE_PEDRO}
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, CEDULA_DE_PEDRO, principales, {0: 1, 1: 4, 2: 6}, siguiente=1)
        assert (dueno.documento, dueno.aviso) == (0, None)

    def test_un_solo_par_de_palabras_no_basta_para_moverla(self):
        solo_el_apellido = {0: CARTA_DE_PEDRO, 1: "Señores AFINIA. La señora GOMEZ RUIZ pide la revisión."}
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, CEDULA_DE_ANA, solo_el_apellido, self.ANCLAS, siguiente=1)
        assert dueno.documento == 0 and dueno.aviso == NADIE_LO_NOMBRA

    def test_sin_leer_de_quien_es_se_queda_con_aviso(self):
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, None, self.PRINCIPALES, self.ANCLAS, siguiente=1)
        assert (dueno.documento, dueno.aviso) == (0, NO_SE_LEYO)

    def test_con_un_solo_documento_no_hay_nada_que_decidir(self):
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, None, {0: CARTA_DE_PEDRO}, {0: 1})
        assert (dueno.documento, dueno.aviso) == (0, None)

    def test_la_principal_que_no_nombra_a_nadie_se_queda_con_su_anexo(self):
        """La repetición del 2026-11-23: el pagaré, la declaración, la carta de instrucciones se llenan a mano.

        Su capa no deja leer el nombre, y otro documento de la caja nombra a la misma persona -- la constancia --:
        no saber de quién habla no es saber que habla de otro (1000186, 1000265, 4251565).
        """
        a_mano = "CARTA DE INSTRUCCIONES ANEXA A PAGARE No. 7700001 con espacios en blanco que el deudor autoriza llenar"
        principales = {0: CARTA_DE_PEDRO, 1: a_mano}
        dueno = dueno_razonado((1, 4), CON_SU_PRINCIPAL, CEDULA_DE_PEDRO, principales, {0: 1, 1: 3}, siguiente=None)
        assert (dueno.documento, dueno.aviso) == (1, None)

    def test_la_factura_de_otro_titular_va_con_su_documento(self):
        factura_de_ana = FACTURA_DE_PEDRO.replace("PEREZ PAEZ PEDRO PABLO", "GOMEZ RUIZ ANA MARIA")
        dueno = dueno_razonado(
            (0, 2), CON_SU_PRINCIPAL, titular_del_recibo(factura_de_ana), self.PRINCIPALES, self.ANCLAS, siguiente=1
        )
        assert dueno.documento == 1


# -- el juez de la IA ------------------------------------------------------------------------


class TestElJuez:
    @pytest.mark.parametrize(
        ("respuesta", "esperada"),
        [("B", 1), ("b)", 1), ("Opción A", 0), ("A) hojas 1-2", 0), ("NINGUNO", None), ("Z", None), ("", None),
         ("Creo que pertenece al documento de las hojas 4-6", None)],
    )
    def test_solo_vale_una_letra_de_la_lista(self, respuesta, esperada):
        assert eleccion_del_juez_de_anexos(respuesta, 3) == esperada

    def test_las_opciones_dicen_las_hojas_y_el_principio_del_texto(self):
        opciones = opciones_para_el_juez([([1, 2], CARTA_DE_PEDRO), ([4], DECLARACION_DE_ANA)])
        assert opciones[0].startswith("A) hojas 1-2: Magangué, 3 de marzo") and opciones[1].startswith("B) hoja 4:")
        marcadas = opciones_para_el_juez([([1, 2], CARTA_DE_PEDRO), ([4], DECLARACION_DE_ANA)], antes=0)
        assert marcadas[0].startswith("A) hojas 1-2 (va justo antes del anexo):")


# -- el seguro final F5g ---------------------------------------------------------------------------


class TestAsignarPorSecuencia:
    def test_el_ejemplo_del_operador_la_principal_con_su_cedula_y_sus_dos_recibos(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: FACTURA_DE_PEDRO, 4: FACTURA_DE_PEDRO}
        resultado = asignar_por_secuencia(_grupos([1], [2], [3, 4]), textos, {}, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2, 3, 4]]
        assert {d["pagina"]: d["regla"] for d in resultado.decisiones} == {2: CON_SU_PRINCIPAL, 3: CON_SU_PRINCIPAL, 4: CON_SU_PRINCIPAL}

    def test_dos_principales_cada_una_con_sus_anexos(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: DECLARACION_DE_ANA, 4: CEDULA_DE_ANA}
        resultado = asignar_por_secuencia(_grupos([1], [2, 3, 4]), textos, {}, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2], [3, 4]]

    def test_la_constancia_va_sin_anexos_y_su_cedula_va_al_siguiente(self):
        """El operador, 2026-11-24: «las constancias van solas, no deberían llevar ningún anexo»."""
        textos = {1: CONSTANCIA, 2: CEDULA_DE_PEDRO, 3: CARTA_DE_PEDRO}
        resultado = asignar_por_secuencia(
            _grupos([1, 2], [3]), textos, {}, sin_anexos=frozenset({1}), identidad_de=_de_la_capa(textos)
        )
        assert _hojas(resultado) == [[1], [2, 3]]
        assert resultado.decisiones[0]["regla"] == TRAS_LA_CONSTANCIA
        # Y en el PDF, detrás de la carta.
        assert los_anexos_detras(resultado.grupos, textos).groups[1].en_el_pdf == [3, 2]

    def test_tras_la_constancia_la_cedula_de_la_persona_de_antes_va_con_ese(self):
        textos = {1: DECLARACION_DE_ANA, 2: CONSTANCIA, 3: CEDULA_DE_ANA, 4: CARTA_DE_PEDRO}
        resultado = asignar_por_secuencia(
            _grupos([1], [2, 3], [4]), textos, {}, sin_anexos=frozenset({2}), identidad_de=_de_la_capa(textos)
        )
        assert _hojas(resultado) == [[1, 3], [2], [4]]
        assert resultado.decisiones[0]["regla"] == TRAS_LA_CONSTANCIA_AL_ANTERIOR

    def test_la_constancia_nunca_recibe_un_anexo_aunque_nombre_a_su_persona(self):
        # La constancia nombra a Pedro con su cédula; la cédula de Pedro va con la carta de Ana de delante.
        textos = {1: DECLARACION_DE_ANA, 2: CEDULA_DE_PEDRO, 3: CONSTANCIA}
        resultado = asignar_por_secuencia(
            _grupos([1, 2], [3]), textos, {}, sin_anexos=frozenset({3}), identidad_de=_de_la_capa(textos)
        )
        assert _hojas(resultado) == [[1, 2], [3]]

    def test_la_cedula_que_no_pertenece_a_la_carta_va_con_su_persona_y_detras(self):
        """El caso del operador: «la tercera página es una cédula que no pertenece a la hoja»."""
        textos = {1: CARTA_DE_PEDRO, 2: SEGUNDA_HOJA, 3: CEDULA_DE_ANA, 4: DECLARACION_DE_ANA}
        resultado = asignar_por_secuencia(_grupos([1, 2, 3], [4]), textos, {}, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2], [3, 4]]
        decision = resultado.decisiones[0]
        assert (decision["pagina"], decision["regla"], decision["ancla"], decision["movida_desde"]) == (3, DE_SU_PERSONA, 4, 1)
        assert resultado.movidas == {3: 4}
        # Y en el PDF, detrás de la declaración.
        assert los_anexos_detras(resultado.grupos, textos).groups[1].en_el_pdf == [4, 3]

    def test_los_anexos_del_principio_van_con_la_primera_principal_y_detras(self):
        textos = {1: CEDULA_DE_PEDRO, 2: CARTA_DE_PEDRO}
        resultado = asignar_por_secuencia(_grupos([1], [2]), textos, {})
        assert _hojas(resultado) == [[1, 2]]
        assert resultado.decisiones[0]["regla"] == AL_INICIO
        assert los_anexos_detras(resultado.grupos, textos).groups[0].en_el_pdf == [2, 1]

    def test_el_reverso_mudo_sigue_a_su_anexo_y_la_muda_tras_una_principal_no_se_toca(self):
        textos = {1: CARTA_DE_PEDRO, 2: MUDA, 3: DECLARACION_DE_ANA, 4: CEDULA_DE_ANA, 5: MUDA}
        resultado = asignar_por_secuencia(_grupos([1, 2], [3], [4, 5]), textos, {}, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2], [3, 4, 5]]

    def test_la_hoja_muda_en_otro_documento_no_es_el_reverso(self):
        # Una carta con la capa rota tras la cédula, que otro filtro abrió aparte: el seguro no se la lleva.
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: MUDA, 4: SEGUNDA_HOJA}
        resultado = asignar_por_secuencia(_grupos([1, 2], [3, 4]), textos, {}, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2], [3, 4]]

    def test_lo_fijo_no_se_mueve_aunque_parezca_anexo(self):
        # La hoja 2 abre por su sello, o la retuvo la lista de ANEXOS: no se toca.
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: CEDULA_DE_PEDRO}
        resultado = asignar_por_secuencia(_grupos([1], [2, 3]), textos, {}, fijas=frozenset({2}))
        assert _hojas(resultado) == [[1], [2, 3]]

    def test_el_seguro_corrige_un_anexo_que_un_filtro_dejo_lejos(self):
        # Un filtro anterior dejó la cédula de Pedro (hoja 2) en el documento de Ana.
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: DECLARACION_DE_ANA, 4: CEDULA_DE_ANA}
        anexos = {"02": [2, 4]}
        resultado = asignar_por_secuencia(_grupos([1], [3, 2, 4]), textos, anexos, identidad_de=_de_la_capa(textos))
        assert _hojas(resultado) == [[1, 2], [3, 4]]
        assert resultado.movidas == {2: 1}
        assert resultado.anexos == {"01": [2], "02": [4]}

    def test_el_documento_que_queda_vacio_desaparece_y_se_renumera(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: DECLARACION_DE_ANA}
        resultado = asignar_por_secuencia(_grupos([1], [2], [3]), textos, {})
        assert _hojas(resultado) == [[1, 2], [3]]
        assert [g.code.value for g in resultado.grupos.groups] == ["01", "02"]

    def test_la_identidad_que_solo_lee_la_ia(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_ILEGIBLE, 3: DECLARACION_DE_ANA}
        leidas = []

        def con_la_ia(pagina, clase):
            leidas.append(pagina)
            return CEDULA_DE_ANA, "ocr de pago"

        resultado = asignar_por_secuencia(_grupos([1, 2], [3]), textos, {}, identidad_de=con_la_ia)
        assert _hojas(resultado) == [[1], [2, 3]] and leidas == [2]
        assert resultado.decisiones[0]["leido_por"] == "ocr de pago"

    def test_sin_identidad_decide_el_juez_entre_los_documentos(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_ILEGIBLE, 3: DECLARACION_DE_ANA}
        preguntas = []

        def juez(pagina, opciones):
            preguntas.append((pagina, opciones))
            return 1  # la declaración

        resultado = asignar_por_secuencia(
            _grupos([1, 2], [3]), textos, {}, identidad_de=lambda p, c: (None, None), juez=juez
        )
        assert _hojas(resultado) == [[1], [2, 3]]
        assert resultado.decisiones[0]["regla"] == POR_LA_IA and resultado.decisiones[0]["confianza"] == "baja"
        assert preguntas[0][0] == 2 and len(preguntas[0][1]) == 2

    def test_el_juez_que_confirma_la_secuencia_o_no_sabe(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_ILEGIBLE, 3: DECLARACION_DE_ANA}
        sin_identidad = lambda p, c: (None, None)  # noqa: E731
        confirma = asignar_por_secuencia(_grupos([1, 2], [3]), textos, {}, identidad_de=sin_identidad, juez=lambda p, o: 0)
        assert _hojas(confirma) == [[1, 2], [3]] and CONFIRMADO_POR_LA_IA in confirma.decisiones[0]["regla"]
        no_sabe = asignar_por_secuencia(_grupos([1, 2], [3]), textos, {}, identidad_de=sin_identidad, juez=lambda p, o: None)
        assert _hojas(no_sabe) == [[1, 2], [3]] and no_sabe.decisiones[0]["aviso"] == NO_SE_LEYO

    def test_lo_que_la_regla_no_prueba_lo_razona_la_ia(self):
        """El operador, 2026-11-24: «que el bot sepa razonar con la ayuda de la IA cuándo una cédula pertenece a un grupo de páginas y cuándo no».

        La carta llenada a mano no nombra a nadie: la regla no la saca, pero la IA mira la cédula y la lista.
        """
        a_mano = "CARTA DE INSTRUCCIONES ANEXA A PAGARE No. 7700001 con espacios en blanco que el deudor autoriza llenar"
        textos = {1: a_mano, 2: CEDULA_DE_ANA, 3: DECLARACION_DE_ANA}
        vistas = []

        def juez(pagina, opciones):
            vistas.append(opciones)
            return 1

        resultado = asignar_por_secuencia(_grupos([1, 2], [3]), textos, {}, identidad_de=_de_la_capa(textos), juez=juez)
        assert _hojas(resultado) == [[1], [2, 3]] and resultado.decisiones[0]["regla"] == POR_LA_IA
        assert "(va justo antes del anexo)" in vistas[0][0]
        # Sin respuesta de la IA, se queda con su secuencia y lo dice.
        sin_respuesta = asignar_por_secuencia(
            _grupos([1, 2], [3]), textos, {}, identidad_de=_de_la_capa(textos), juez=lambda p, o: None
        )
        assert _hojas(sin_respuesta) == [[1, 2], [3]] and sin_respuesta.decisiones[0]["aviso"] == NO_SE_CONFIRMO

    def test_lo_que_la_regla_prueba_no_se_le_pregunta_a_la_ia(self):
        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_DE_PEDRO, 3: DECLARACION_DE_ANA}
        preguntas = []
        resultado = asignar_por_secuencia(
            _grupos([1, 2], [3]), textos, {}, identidad_de=_de_la_capa(textos),
            juez=lambda p, o: preguntas.append(p),
        )
        assert _hojas(resultado) == [[1, 2], [3]] and preguntas == []

    def test_el_juez_que_falla_no_tumba_la_caja(self):
        def roto(pagina, opciones):
            raise RuntimeError("sin red")

        textos = {1: CARTA_DE_PEDRO, 2: CEDULA_ILEGIBLE, 3: DECLARACION_DE_ANA}
        resultado = asignar_por_secuencia(_grupos([1, 2], [3]), textos, {}, identidad_de=lambda p, c: (None, None), juez=roto)
        assert _hojas(resultado) == [[1, 2], [3]]

    def test_sin_anexos_no_cambia_nada(self):
        grupos = _grupos([1], [2])
        resultado = asignar_por_secuencia(grupos, {1: CARTA_DE_PEDRO, 2: DECLARACION_DE_ANA}, {})
        assert resultado.grupos is grupos and resultado.decisiones == []

    def test_la_auditoria_no_encuentra_nada_fuera_y_detecta_lo_que_se_saliera(self):
        textos = {1: CARTA_DE_PEDRO, 2: SEGUNDA_HOJA, 3: CEDULA_DE_ANA, 4: DECLARACION_DE_ANA}
        resultado = asignar_por_secuencia(_grupos([1, 2, 3], [4]), textos, {}, identidad_de=_de_la_capa(textos))
        assert auditar_la_secuencia(_hojas(resultado), resultado.duenos()) == []
        assert auditar_la_secuencia([[1, 2, 3], [4]], resultado.duenos()) == [3]


# -- el orden dentro del PDF ---------------------------------------------------------------------------


class TestLosAnexosDetras:
    def test_la_factura_con_que_empieza_va_detras(self):
        textos = {1: FACTURA_DE_PEDRO, 2: CARTA_DE_PEDRO}
        assert los_anexos_detras(_grupos([1, 2]), textos).groups[0].en_el_pdf == [2, 1]

    def test_el_pdf_que_es_solo_anexos_y_la_hoja_que_abre_no_se_tocan(self):
        textos = {1: CEDULA_DE_PEDRO, 2: FACTURA_DE_PEDRO, 3: CARTA_DE_PEDRO}
        assert los_anexos_detras(_grupos([1, 2]), textos).groups[0].en_el_pdf == [1, 2]
        assert los_anexos_detras(_grupos([1, 3]), textos, abren=frozenset({1})).groups[0].en_el_pdf == [1, 3]


# -- qué es anexo y qué va solo ---------------------------------------------------------------------------


class TestQueEsAnexoYQueVaSolo:
    EXPEDIENTE = (
        "Una filial del Grupo EPM\nCARIBEMAR DE LA COSTA S.A.S. ESP\nNit: 901.380.949-1\nDISTRITO: Sector Bolívar Sur\n"
        "No. Expediente: P23112020110000\nEXPEDIENTE\nFecha de solicitud del Servicio: 11/11/2020"
    )
    ESTADO_DE_CUENTA = (
        "Fecha edición: 09/11/2021 Página: 1 de 1\nCARIBEMAR DE LA COSTA S.A.S. ESP\nNit 901.380.949-1\n"
        "ESTADO DE CUENTA POR NIC\nNIC: 7700000 CLIENTE: PEDRO PEREZ PAEZ"
    )
    PAGARE = (
        "CARIBEMAR DE LA COSTA S.A.S. ESP EMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS\nNit 901.380.949-1\n"
        "PAGARE No. 7700000-1 FECHA VENCIMIENTO"
    )

    def test_el_formato_con_membrete_va_solo(self):
        """4251482 pág. 8: el EXPEDIENTE salía dentro de la declaración de delante."""
        assert trae_el_membrete(self.EXPEDIENTE)
        assert formulario_que_abre(self.EXPEDIENTE) == FORMATO_DE_LA_EMPRESA

    def test_la_declaracion_va_sola(self):
        assert formulario_que_abre(DECLARACION_DE_ANA) == DECLARACION_JURAMENTADA

    def test_el_estado_de_cuenta_trae_el_membrete_pero_es_anexo(self):
        assert formulario_que_abre(self.ESTADO_DE_CUENTA) is None
        assert es_anexo_por_secuencia(self.ESTADO_DE_CUENTA) == "factura"

    def test_el_pagare_sigue_siendo_del_acuerdo(self):
        assert formulario_que_abre(self.PAGARE) == ACUERDO_DE_PAGO

    def test_la_carta_que_cita_al_titular_no_es_anexo(self):
        assert es_anexo_por_secuencia(CARTA_DE_PEDRO) is None
        assert es_anexo_por_secuencia(CEDULA_DE_PEDRO) == "documento de identidad"

    def test_de_quien_es_la_factura(self):
        assert titular_del_recibo(FACTURA_DE_PEDRO) == "PEREZ PAEZ PEDRO PABLO"
        assert titular_del_recibo("una hoja sin titular") is None


# -- el nombre de la declaración por su proceso ------------------------------------------------------


class TestElProcesoDeLaDeclaracion:
    """El operador, 2026-11-23: «le colocarás el título dependiendo lo que esté seleccionado», «DECLARACION BGDJ - PROCESO»."""

    @staticmethod
    def _formato(casillas: str, cual: str = "") -> str:
        return (
            'REFERENCIA: DECLARACION BAJO GRAVEDAD DE JURAMENTO\nPROCESO (Marcar con una "x" el objeto de su petición)\n'
            f"{casillas}\nOtro Proceso, Cual? {cual}\nMediante la presente, el suscrito PEDRO PEREZ PAEZ"
        )

    def test_la_casilla_marcada_da_el_proceso(self):
        from resolutions.domain.asunto_del_documento import (
            nombre_de_la_declaracion,
            proceso_de_la_declaracion,
        )

        texto = self._formato(
            "Reconocimiento de Activos ☐ Cambio de Titular de Contrato ☑ Solicitud de Contratación Nuevo "
            "Suministro ☐ Baja de Contrato ☐"
        )
        assert proceso_de_la_declaracion(texto) == "CAMBIO DE TITULAR DE CONTRATO"
        assert nombre_de_la_declaracion("CAMBIO DE TITULAR DE CONTRATO") == "DECLARACION BGDJ - CAMBIO DE TITULAR DE CONTRATO"

    def test_otro_proceso_toma_lo_escrito(self):
        from resolutions.domain.asunto_del_documento import proceso_de_la_declaracion

        texto = self._formato(
            "Reconocimiento de Activos Cambio de Titular de Contrato Solicitud de Contratación Nuevo Suministro "
            "Baja de Contrato",
            "Aumento de Potencia",
        )
        assert proceso_de_la_declaracion(texto) == "AUMENTO DE POTENCIA"

    def test_sin_saberlo_no_se_adivina(self):
        from resolutions.domain.asunto_del_documento import (
            DECLARACION_JURAMENTADA,
            nombre_de_la_declaracion,
            proceso_de_la_declaracion,
        )

        vacia = self._formato("Reconocimiento de Activos ☐ Cambio de Titular de Contrato ☐ Baja de Contrato ☐", "________")
        dos = self._formato("Reconocimiento de Activos ☑ Cambio de Titular de Contrato ☑")
        # La capa del escáner rompe la «x»: «Leo]», «JU]».
        rota = self._formato("Reconocimiento de Activos Cambio de Titular de Contrato Leo] Baja de Contrato", ".. ;")
        assert [proceso_de_la_declaracion(t) for t in (vacia, dos, rota)] == [None, None, None]
        assert nombre_de_la_declaracion(None) == DECLARACION_JURAMENTADA


# -- lo que enseñó la repetición de las 116 cajas (2026-11-23) --------------------------------


class TestLoQueEnsenoLaRepeticion:
    def test_la_cedula_dice_su_numero_y_su_nombre_y_nada_mas(self):
        from resolutions.domain.tramites import identidad_de_la_cedula

        assert identidad_de_la_cedula(CEDULA_DE_ANA) == "C.C. 98765432 GOMEZ RUIZ ANA MARIA"
        # El reverso: el número del código de barras, no la fecha de expedición ni los demás códigos.
        reverso = (
            "FECHA DE NACIMIENTO 05-NOV-1948 LUGAR DE NACIMIENTO ESTATURA 1.60 G.S. RH O+ 31-JUL-1970 "
            "FECHA Y LUGAR DE EXPEDICION INDICE DERECHO A-2700100-00148287-F-0098765432-20090129 "
        )
        assert identidad_de_la_cedula(reverso) == "C.C. 98765432"
        # La tarjeta ilegible no da nada: sus fechas y códigos no son de nadie (7740578 hoja 6).
        ilegible = "IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA NUWierír ;; 20070711 242614503 fANiAPAOLA"
        assert identidad_de_la_cedula(ilegible) is None

    def test_el_nombre_roto_de_la_capa_no_es_otra_persona(self):
        """6833800 hoja 15: «Yo, RVG GCIJQRDO ENO» era Eduardo Gutiérrez Moreno, a mano: su factura se queda."""
        from resolutions.domain.secuencia_de_anexos import nombra_a_otra_persona

        recurso = "FORMATO PARA LA PRESENTACION DE RECURSO DE REPOSICION Yo, RVG GCIJQRDO ENO, identificado con"
        assert not nombra_a_otra_persona("GOMEZ RUIZ ANA MARIA", recurso)
        assert nombra_a_otra_persona("C.C. 98765432 GOMEZ RUIZ ANA MARIA", CARTA_DE_PEDRO)
        assert not nombra_a_otra_persona("C.C. 12345678 PEREZ PAEZ", CARTA_DE_PEDRO)

    def test_la_principal_que_la_nombra_a_medias_se_la_queda(self):
        # Un solo par del nombre en su principal: no se aparta, aunque otro documento la nombre entera.
        a_medias = CARTA_DE_PEDRO + " en nombre de la señora GOMEZ RUIZ"
        principales = {0: a_medias, 1: DECLARACION_DE_ANA}
        dueno = dueno_razonado((0, 2), CON_SU_PRINCIPAL, "GOMEZ RUIZ ANA MARIA", principales, {0: 1, 1: 4}, siguiente=1)
        assert dueno.documento == 0

    def test_la_constancia_solo_se_queda_lo_que_la_sigue_en_el_papel(self):
        """6833917: la hoja 9 va detrás de la Habeas Data de la 8 (en el acuerdo), no de la constancia de la 7."""
        from resolutions.application.anexos_declarados import constancias_solas

        textos = {7: CONSTANCIA, 9: MUDA}
        solas = constancias_solas(_grupos([7, 9]), textos, {}, constancias={7: "RE2310202200001"})
        assert _hojas(solas) == [[7], [9]]

    def test_la_hoja_muda_sola_en_un_documento_sigue_su_secuencia(self):
        textos = {1: CONSTANCIA, 2: CARTA_DE_PEDRO, 3: MUDA}
        resultado = asignar_por_secuencia(_grupos([1], [2], [3]), textos, {})
        assert _hojas(resultado) == [[1], [2, 3]]


# -- los casos del 2026-11-24: 4251555, 4251556 -------------------------------------------------


class TestLosCasosDelVeinticuatro:
    def test_el_re_escrito_con_su_re_roto(self):
        """4251555: la visión leyó «Rt 2311202107751» y el OCR de pago «Pit 2311…»; el RE se descartaba."""
        from resolutions.domain.evidencia import res_en_la_lectura
        from resolutions.domain.sello import radicado_escrito

        assert res_en_la_lectura("sello | Rt 2311202107751") == ["RE2311202107751"]
        assert res_en_la_lectura("Pit 2311202107751") == ["RE2311202107751"]
        assert res_en_la_lectura("R+ 2311202107751") == ["RE2311202107751"]
        # Una palabra cualquiera seguida de cifras no es un RE.
        assert res_en_la_lectura("Parte 2311202107751") == []
        assert radicado_escrito("PIT 2311202107751", 2021) == "RE2311202107751"

    def test_el_sello_con_sus_rotulos_rotos(self):
        """4251555: «ACESTACIÓN» y «¡MPLICA» con la tinta realzada; el sello al pie no se veía."""
        from resolutions.application.sellos import parece_un_sello

        assert parece_un_sello("OFICINA SANTA ROSA DEL SUR FECBoo NO ¡MPLICA ACESTACIÓN")

    def test_la_peticion_es_derecho_de_peticion(self):
        """4251556: una carta salía PETICION y la de al lado DERECHO DE PETICION."""
        from resolutions.domain.nombre_oficial import nombre_oficial

        assert nombre_oficial("PETICION") == nombre_oficial("DERECHO DE PETICION") == "DERECHO DE PETICION"

    def test_la_fecha_en_blanco_del_formato(self):
        from resolutions.domain.fecha_por_estructura import fecha_en_blanco

        assert fecha_en_blanco("________, ___ de ________ de 20___\nSeñores:")
        assert not fecha_en_blanco("t'oso-N OZ de 9iWi:vode 2o2-n\nSeñores:")
        assert not fecha_en_blanco("Magangué 8 de marzo de 2021\nSeñores:")

    def test_el_nombrador_de_la_ia_tambien_unifica_la_peticion(self):
        from resolutions.domain.nombre_oficial import tipo_unificado

        assert tipo_unificado("PETICION") == "DERECHO DE PETICION"
        assert tipo_unificado("RECLAMO") == "RECLAMO" and tipo_unificado(None) is None

    def test_el_agente_no_elige_un_ano_que_su_auditor_rechaza(self):
        """4251555: elegía RE2311202707751 (año 2027), el auditor lo revertía y quedaba sin RE."""
        from resolutions.domain.evidencia import Candidato
        from resolutions.domain.resolutor_del_re import (
            ContextoDelRe,
            resolver_sin_certeza,
        )

        candidatos = [
            Candidato("RE2311202707751", "hallado en el barrido de la hoja, lo lee un solo lector (ocr de pago)", 1),
            Candidato("RE2311202107751", "hallado en el barrido de la hoja, lo lee un solo lector (visión)", 1),
        ]
        decision = resolver_sin_certeza(candidatos, ContextoDelRe(anio=2021))
        assert decision is not None and decision.valor == "RE2311202107751"

    # La carta de Electricaribe al usuario, con datos inventados en el formato de
    # 920933 (UPD2998261 pág. 2): «MESUC» en el encabezado y «Estimado usuario».
    CARTA_MESUC = (
        "Electricarihe\nMESUC 1234\nOficina Comercial: Electricaribe S.A. ESP - Mercados Especiales\n"
        "Sincelejo, marzo 03 de 2020\nSenor(a):\nPEDRO PEREZ GOMEZ\nCALLE 1 SECTOR 2\n"
        "Código de usuario: 111111\nEstimado usuario:\nComo se le informo en la comunicación MESUC 1200 "
        "de febrero 06 de 2020, «contra la presente decisión procede el recurso de queja», el cual debe "
        "interponerse directamente ante la Superintendencia de Servicios Públicos Domiciliarios."
    )

    def test_la_carta_mesuc_es_respuesta_a_usuario(self):
        """920933: la IA la llamaba RECURSO DE QUEJA por el recurso que el cuerpo explica (el operador, 2026-11-24)."""
        from resolutions.domain.asunto_del_documento import (
            NOMBRES_DEL_OPERADOR,
            RESPUESTA_A_USUARIO,
            RESPUESTA_DE_LA_EMPRESA,
            es_carta_de_la_empresa,
            es_contestacion_a_reclamacion,
            formulario_que_abre,
            titulo_del_documento,
        )
        from resolutions.domain.nombre_oficial import (
            estandarizar,
            le_falta_su_re,
            nombre_oficial,
        )

        assert titulo_del_documento(self.CARTA_MESUC) == RESPUESTA_A_USUARIO == "RESPUESTA A USUARIO"
        # El catálogo y la IA no se lo cambian, y no lleva RE.
        assert nombre_oficial(RESPUESTA_A_USUARIO) == estandarizar(RESPUESTA_A_USUARIO) == RESPUESTA_A_USUARIO
        assert RESPUESTA_A_USUARIO in NOMBRES_DEL_OPERADOR
        assert not le_falta_su_re(RESPUESTA_A_USUARIO, [self.CARTA_MESUC])
        # Es carta de la empresa: abre como su respuesta, pero no es la respuesta a la reclamación.
        assert es_carta_de_la_empresa(self.CARTA_MESUC)
        assert formulario_que_abre(self.CARTA_MESUC) == RESPUESTA_DE_LA_EMPRESA
        assert not es_contestacion_a_reclamacion(self.CARTA_MESUC + "\nEn atención a su petición")

    def test_el_aviso_con_el_mismo_mesuc_sigue_siendo_aviso(self):
        """920933 pág. 1: el aviso que notifica la carta trae el mismo «MESUC» en el encabezado."""
        from resolutions.domain.asunto_del_documento import titulo_del_documento

        aviso = (
            "Electricaribe\nMESUC 1234\nSincelejo, marzo 11 de 2020.\nSenor(a):\nPEDRO PEREZ GOMEZ\n"
            "Estimado usuario:\npor intermedio de este AVISO nos permitimos notificarlo del acto administrativo"
        )
        assert titulo_del_documento(aviso) == "NOTIFICACION POR AVISO"

    def test_el_escrito_que_cita_un_mesuc_no_es_la_carta(self):
        """El «MESUC» citado en el cuerpo, o en la carta dirigida a la empresa, no es su formato."""
        from resolutions.domain.asunto_del_documento import es_respuesta_a_usuario

        cuerpo = "Magangué, 10 de marzo de 2020\nSeñores\nELECTRICARIBE\nAsunto: recurso\nRespetados señores:\n"
        assert not es_respuesta_a_usuario(cuerpo + "contra la comunicación MESUC 1234 interpongo recurso de queja")
        a_la_empresa = "MESUC 1234\nSeñores ELECTRICARIBE S.A. E.S.P.\nOficina Comercial\nyo PEDRO PEREZ"
        assert not es_respuesta_a_usuario(a_la_empresa)
        # Con lo que el escáner hace del rótulo.
        assert es_respuesta_a_usuario(self.CARTA_MESUC.replace("MESUC 1234", "MES UC1234"))

    def test_la_auditoria_avisa_la_carta_mesuc_mal_nombrada(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        mal = auditar_los_radicados([ArchivoEntregado("01_RECURSO-DE-QUEJA.pdf", (1,))], {1: self.CARTA_MESUC})
        assert any("RESPUESTA A USUARIO y se llama" in d for d in mal.dudas)
        bien = auditar_los_radicados([ArchivoEntregado("01_RESPUESTA-A-USUARIO.pdf", (1,))], {1: self.CARTA_MESUC})
        assert not any("su formato es" in d for d in bien.dudas)

    def test_la_auditoria_vigila_el_reconocimiento_y_el_nombre_con_par(self):
        """Lo que se saltó el 24 queda vigilado en cada entrega: el reconocimiento escrito al final y PETICION."""
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        acuerdo = "01_RECONOCIMIENTO-DE-DEUDA-Y-PROPUESTA-DE-ACUERDO-DE-PAGO.pdf"
        pagare = "PAGARE No. 123\nYo PEDRO PEREZ pagaré incondicionalmente"
        escrito = "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO\nt'oso-N OZ de 9iWi:vode 2o2-n\nSeñores"
        en_blanco = "RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO\n________, ___ de ________ de 20___\nSeñores"
        al_final = auditar_los_radicados([ArchivoEntregado(acuerdo, (1, 2))], {1: pagare, 2: escrito})
        assert any("renglón de su fecha" in d for d in al_final.dudas)
        sin_fecha = auditar_los_radicados([ArchivoEntregado(acuerdo, (1, 2))], {1: pagare, 2: en_blanco})
        assert not any("renglón de su fecha" in d for d in sin_fecha.dudas)
        primero = auditar_los_radicados([ArchivoEntregado(acuerdo, (2, 1))], {1: pagare, 2: escrito})
        assert not any("renglón de su fecha" in d for d in primero.dudas)

        peticion = auditar_los_radicados([ArchivoEntregado("02_PETICION.pdf", (1,))], {1: "Señores AFINIA"})
        assert any("DERECHO DE PETICION" in d for d in peticion.dudas)
        derecho = auditar_los_radicados([ArchivoEntregado("02_DERECHO-DE-PETICION.pdf", (1,))], {1: "Señores AFINIA"})
        assert not any("ese documento es" in d for d in derecho.dudas)

    # La nota crédito de Aseopronto, con datos inventados en el formato de 1000501.
    CARTA_ASEO = (
        "ASEOPRONTO SAS ESP\nNIT 901.380.755-1 Vigilada por la S.S.P.D.\nAUT- 1234 -ASEO\n"
        "Magangue, 10 de abril del 2024\nSeñor(a):\nJefe Oficina Comercial\nCARIBEMAR S.A.S\nCordial saludo,\n"
        "A Continuación relaciono usuario para aplicar descuento(s) o Notas Creditos.\n"
        "Esta autorización se otorga porque el usuario presentó una Reclamacion"
    )

    def test_la_nota_credito_del_aseo_se_llama_por_su_formato(self):
        """1000501 (el operador, 2026-11-24): «RECLAMO -> DESCUENTO/NOTA DE CREDITO ASEOPRONTO ESP -> AUTORIZACION DESCUENTO/NOTA DE CREDITO»."""
        from resolutions.domain.asunto_del_documento import (
            AUTORIZACION_DEL_ASEO,
            NOMBRES_DEL_OPERADOR,
            titulo_del_documento,
        )
        from resolutions.domain.naming import kind_fragment
        from resolutions.domain.nombre_oficial import (
            estandarizar,
            le_falta_su_re,
            nombre_oficial,
        )

        assert titulo_del_documento(self.CARTA_ASEO) == AUTORIZACION_DEL_ASEO
        nombre = nombre_oficial(AUTORIZACION_DEL_ASEO)
        assert nombre == "AUTORIZACION DESCUENTO/NOTA DE CREDITO"
        # Ni el catálogo ni la IA se lo cambian, y no lleva RE.
        assert estandarizar(nombre) == nombre and nombre in NOMBRES_DEL_OPERADOR
        assert not le_falta_su_re(nombre, [self.CARTA_ASEO])
        # En el disco, la barra que Windows no admite es un guion.
        assert kind_fragment(nombre) == "AUTORIZACION-DESCUENTO-NOTA-DE-CREDITO"

    def test_la_auditoria_avisa_la_nota_credito_mal_nombrada(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        textos = {1: self.CARTA_ASEO}
        viejo = auditar_los_radicados([ArchivoEntregado("01_RECLAMACION.pdf", (1,))], textos)
        assert any("AUTORIZACION DESCUENTO/NOTA DE CREDITO y se llama RECLAMACION" in d for d in viejo.dudas)
        # El nombre de unas horas del 24 también es viejo.
        intermedio = auditar_los_radicados(
            [ArchivoEntregado("01_DESCUENTO-NOTA-DE-CREDITO-ASEOPRONTO-ESP.pdf", (1,))], textos
        )
        assert any("su formato es" in d for d in intermedio.dudas)
        nuevo = auditar_los_radicados(
            [ArchivoEntregado("01_AUTORIZACION-DESCUENTO-NOTA-DE-CREDITO.pdf", (1,))], textos
        )
        assert not any("su formato es" in d for d in nuevo.dudas)

    def test_la_auditoria_avisa_el_pagare_fuera_de_su_sitio(self):
        """1000478, 6833800, 7740523: el pagaré pegado a un contrato, un recurso o una constancia de contratación."""
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        contrato = "aFinia\nCONTRATO DE TRANSACCIÓN\nEntre las siguientes partes\n"
        pagare = "CARIBEMAR DE LA COSTA S.A.S. ESP\nPAGARE No. 1000265 -2\n"
        carta = "CARIBEMAR DE LA COSTA S.A.S. ESP\nCARTA DE INSTRUCCIONES ANEXA A PAGARE No. 1000265 2\n"
        textos = {1: contrato, 2: pagare, 3: carta}
        pegado = auditar_los_radicados([ArchivoEntregado("01_CONTRATO-DE-TRANSACCION.pdf", (1, 2, 3))], textos)
        assert any("lleva un pagaré" in e and "hoja 2 de 3" in e for e in pegado.errores)
        aparte = auditar_los_radicados(
            [ArchivoEntregado("01_CONTRATO-DE-TRANSACCION.pdf", (1,)), ArchivoEntregado("02_PAGARE.pdf", (2, 3))], textos
        )
        assert not any("lleva un pagaré" in e for e in aparte.errores)


class TestElPaqueteDeLaEmpresa:
    """4251482 (UPD2447022, el operador, 2026-11-24): «de la página 1 a la 7, y el otro grupo de la 8 a la 18».

    Hoja 1 la CONSTANCIA DE CONTRATACIÓN DE SERVICIO y hoja 8 el EXPEDIENTE, cada una con lo que la sigue: la
    carta que pide el servicio, la cédula, la declaración juramentada, la factura, el certificado de tradición, la
    solicitud de servicio y el RETIE. Salía en siete PDF.
    """

    def test_4251482_dos_paquetes(self):
        from resolutions.application.anexos_declarados import (
            unir_el_paquete_de_la_empresa,
        )

        cortado = _grupos([1], [2, 3], [4, 5, 6, 7], [8], [9, 10], [11], [12, 13, 14, 15, 16, 17, 18])
        unido = unir_el_paquete_de_la_empresa(cortado, {}, abren_paquete={1, 8}, paradas=set())
        assert [g.page_numbers for g in unido.grupos.groups] == [list(range(1, 8)), list(range(8, 19))]
        assert unido.movidas[2] == 1 and unido.movidas[11] == 8

    def test_lo_cierra_la_constancia_de_reclamacion(self):
        from resolutions.application.anexos_declarados import (
            unir_el_paquete_de_la_empresa,
        )

        unido = unir_el_paquete_de_la_empresa(_grupos([1], [2], [3], [4]), {}, abren_paquete={1}, paradas={3})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2], [3], [4]]

    def test_el_documento_que_cruza_la_parada_se_queda(self):
        from resolutions.application.anexos_declarados import (
            unir_el_paquete_de_la_empresa,
        )

        unido = unir_el_paquete_de_la_empresa(_grupos([1], [2, 3, 4]), {}, abren_paquete={1}, paradas={3})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1], [2, 3, 4]]

    def test_sin_caratula_no_cambia_nada(self):
        from resolutions.application.anexos_declarados import (
            unir_el_paquete_de_la_empresa,
        )

        cortado = _grupos([1], [2, 3], [4])
        unido = unir_el_paquete_de_la_empresa(cortado, {"02": [3]}, abren_paquete=set(), paradas=set())
        assert [g.page_numbers for g in unido.grupos.groups] == [[1], [2, 3], [4]]
        assert unido.anexos == {"02": [3]} and not unido.movidas

    def test_lo_de_delante_de_la_caratula_no_entra(self):
        """La declaración de antes de la carátula es de otro trámite: el paquete empieza en la carátula."""
        from resolutions.application.anexos_declarados import (
            unir_el_paquete_de_la_empresa,
        )

        unido = unir_el_paquete_de_la_empresa(_grupos([1, 2], [3], [4]), {}, abren_paquete={3}, paradas=set())
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2], [3, 4]]


class TestElAvisoConSuActo:
    """4251461 (UPD2447021, el operador, 2026-11-24): la notificación por aviso que adjunta la copia del acto va
    con la portada «ANEXO» y la copia, como el reconocimiento con sus anexos."""

    AVISO = (
        "Consecutivo No.A202070000001\nFECHA: 23/12/2020\nNOTIFICACIÓN POR AVISO\nSeñor(a): PEDRO PEREZ\n"
        "por intermedio de este AVISO nos permitimos notificarlo del acto administrativo Consecutivo No. "
        "202070000002 de fecha 14-12-2020. El acto administrativo Consecutivo No. 202070000002, cuya copia "
        "íntegra se adjunta al presente Aviso."
    )
    PORTADA = "Grupo epm\nANEXO: Copia del acto administrativo Consecutivo No. 202070000002 de fecha 14-12-2020\n"
    ACTO = (
        "Consecutivo No. 202070000002\nSANTA ROSA DEL SUR, 2020/12/14\nSeñor PEDRO PEREZ\n"
        "ASUNTO: Recurso de Reposición en subsidio el de apelación No.RE2311202000001\n"
    )
    SEGUNDA = "Por lo anterior, le informamos que Caribe Mar modifica la decisión inicial.\n"
    RECURSO = "Santa Rosa del Sur, noviembre 30 de 2020\nSeñores CARIBEMAR\nRECURSO DE REPOSICIÓN\n"

    def test_reconoce_el_aviso_la_portada_y_el_acto(self):
        from resolutions.domain.asunto_del_documento import (
            acto_que_adjunta,
            consecutivo_de,
            portada_del_anexo,
        )

        assert acto_que_adjunta(self.AVISO) == "202070000002"
        assert portada_del_anexo(self.PORTADA) == "202070000002"
        assert consecutivo_de(self.ACTO) == "202070000002"
        # La notificación que no adjunta nada no se lleva la respuesta.
        assert acto_que_adjunta(self.AVISO.replace("cuya copia íntegra se adjunta al presente Aviso", "")) is None
        assert portada_del_anexo(self.RECURSO) is None

    def test_4251461_el_aviso_se_lleva_su_portada_y_su_acto(self):
        from resolutions.application.anexos_declarados import el_aviso_con_su_acto

        textos = {1: self.AVISO, 2: self.PORTADA, 3: self.ACTO, 4: self.SEGUNDA, 5: self.RECURSO}
        unido = el_aviso_con_su_acto(_grupos([1], [2], [3, 4], [5]), textos, {})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2, 3, 4], [5]]

    def test_sin_portada_el_acto_del_mismo_consecutivo(self):
        from resolutions.application.anexos_declarados import el_aviso_con_su_acto

        textos = {1: self.AVISO, 2: self.ACTO, 3: self.SEGUNDA}
        unido = el_aviso_con_su_acto(_grupos([1], [2, 3]), textos, {})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2, 3]]

    def test_la_respuesta_de_otro_consecutivo_sigue_aparte(self):
        from resolutions.application.anexos_declarados import el_aviso_con_su_acto

        textos = {1: self.AVISO, 2: self.ACTO.replace("202070000002", "202170000009")}
        unido = el_aviso_con_su_acto(_grupos([1], [2]), textos, {})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1], [2]]

    def test_la_auditoria_avisa_el_acto_fuera_de_su_aviso_y_la_portada_sola(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        textos = {1: self.AVISO, 2: self.PORTADA, 3: self.ACTO}
        partido = auditar_los_radicados(
            [
                ArchivoEntregado("01_NOTIFICACION-POR-AVISO.pdf", (1,)),
                ArchivoEntregado("02_ANEXOS.pdf", (2,)),
                ArchivoEntregado("03_RESPUESTA-A-LA-RECLAMACION.pdf", (3,)),
            ],
            textos,
        )
        assert any("la copia salió" in e for e in partido.errores)
        assert any("sólo la portada" in e for e in partido.errores)
        junto = auditar_los_radicados([ArchivoEntregado("01_NOTIFICACION-POR-AVISO.pdf", (1, 2, 3))], textos)
        assert not any("portada" in e or "la copia salió" in e for e in junto.errores)


class TestElSelloAlPieDeOtraRadicacion:
    """4251461 pág. 8: la reclamación manuscrita con su sello al pie del 18-01-2021 («01 folio») iba pegada al
    recurso de la pág. 6, con su sello del 30-11-2020 («02 folios»)."""

    def test_otra_fecha_otro_re_o_fuera_de_los_folios_abre(self):
        from datetime import date

        from resolutions.domain.sello import Sello, al_pie_de_otra_radicacion

        recurso = Sello("tinta", radicado="RE2311202001912", fecha=date(2020, 11, 30), folios=2)
        reclamo = Sello("tinta", radicado="RE2311202100109", fecha=date(2021, 1, 18), folios=1)
        assert set(al_pie_de_otra_radicacion({}, {6: recurso, 8: reclamo})) == {8}
        # Sólo por los folios, sin leer la fecha ni el RE del de detrás.
        assert set(al_pie_de_otra_radicacion({}, {6: recurso, 8: Sello("tinta")})) == {8}
        # Dentro de sus folios, la misma fecha y el mismo RE: el mismo escrito.
        mismo = Sello("tinta", radicado="RE2311202001912", fecha=date(2020, 11, 30))
        assert al_pie_de_otra_radicacion({}, {6: recurso, 7: mismo}) == {}
        # Una cifra mal leída no es otra radicación.
        casi = Sello("tinta", radicado="RE2311202001913")
        assert al_pie_de_otra_radicacion({6: recurso}, {7: casi}) == {}

    def test_la_hoja_muda_se_mira_al_pie_pero_no_en_el_barrido(self):
        from resolutions.application.sellos import se_mira_al_pie

        manuscrita = r"^ fA \ § I Z- ^ ^ ¿s^ev 0, t 'H AQ_"
        assert se_mira_al_pie(manuscrita)
        assert not se_mira_al_pie(manuscrita, mudas=False)


class TestLaCaratulaEnLaAuditoria:
    def test_lo_que_sigue_a_la_caratula_y_salio_aparte_es_duda(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        caratula = (
            "CARIBEMAR DE LA COSTA S.A.S. ESP Numero : 1111111 Fecha 11/11/2020\nNit: 901.380.949-1\n"
            "DISTRITO: Sector Bolívar Sur\nCONSTANCIA DE CONTRATACIÓN DE SERVICIO\nDATOS DE LA OFICINA COMERCIAL\n"
        )
        carta = "Santa Rosa del Sur, 9 de noviembre del 2020\nSeñor: CARIBEMAR\nAsunto: Solicitud de cambio de titular.\n"
        textos = {1: caratula, 2: carta}
        partido = auditar_los_radicados(
            [ArchivoEntregado("01_CONSTANCIA.pdf", (1,)), ArchivoEntregado("02_CAMBIO-DE-TITULAR.pdf", (2,))], textos
        )
        assert any("detrás de la carátula" in d for d in partido.dudas)
        junto = auditar_los_radicados([ArchivoEntregado("01_CONSTANCIA.pdf", (1, 2))], textos)
        assert not any("detrás de la carátula" in d for d in junto.dudas)


class TestElTituloDeLaCaratula:
    """4251482 (el operador, 2026-11-24): «la idea es aplicarle el título que está allí», el subrayado del formato."""

    CONSTANCIA = (
        "CARIBEMAR DE LA COSTA S.A.S. ESP\nNumero ; 1111111\nFecha 11/11/2020\nNit: 901.380.949-1\n"
        "DISTRITO: Sector Bolívar Sur\nCONSTANCIA DE CONTRATACIÓN DE SERVICIO\nDATOS DE LA OFICINA COMERCIAL\n"
        "DATOS DE LOS SERVICIOS CONTRATADOS\nNúmero de Expediente:\n"
    )
    EXPEDIENTE = (
        "CARIBEMAR DE LA COSTA S.A.S. ESP\nNit: 901.380.949-1\nDISTRITO: Sector Bolívar Sur\n"
        "No. Expediente; P00000000000001\nEXPEDIENTE\nFecha de solicitud del Servicio: 11/11/2020\n"
        "Tipo de Solicitud: Aumentos de potencia\n"
    )

    def test_cada_caratula_por_su_titulo_impreso(self):
        from resolutions.domain.asunto_del_documento import titulo_de_la_caratula
        from resolutions.domain.catalogo import POR_NOMBRE

        assert titulo_de_la_caratula(self.CONSTANCIA) == "CONSTANCIA DE CONTRATACION DE SERVICIO"
        # No «AUMENTO DE CARGA» por su casilla, ni el campo «No. Expediente».
        assert titulo_de_la_caratula(self.EXPEDIENTE) == "EXPEDIENTE"
        assert {"CONSTANCIA DE CONTRATACION DE SERVICIO", "EXPEDIENTE"} <= set(POR_NOMBRE)
        assert titulo_de_la_caratula("Santa Rosa, 9 de noviembre\nSeñores CARIBEMAR\nEXPEDIENTE\n") is None

    def test_la_auditoria_avisa_la_caratula_mal_nombrada(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        mal = auditar_los_radicados([ArchivoEntregado("05_AUMENTO-DE-CARGA.pdf", (1,))], {1: self.EXPEDIENTE})
        assert any("EXPEDIENTE y se llama AUMENTO DE CARGA" in d for d in mal.dudas)
        bien = auditar_los_radicados([ArchivoEntregado("05_EXPEDIENTE.pdf", (1,))], {1: self.EXPEDIENTE})
        assert not any("su formato es" in d for d in bien.dudas)


class TestElReQueCitaElExpediente:
    """4251556 (el operador, 2026-11-24): la petición de 2022 salió RE2311202207568 -- el «1» a mano leído «7» -- y la
    de 2023, en otro UPD del mismo NIC, cita «Derecho de Petición numerado según oficio 2311202201568»."""

    CITA = "Solicitud de Cumplimiento acorde a Derecho de Petición numerado según oficio 2311202201568. Quedamos atentos"

    def test_el_candidato_citado_corrige_lo_leido_a_mano(self):
        from resolutions.domain.resolutor_del_re import re_citado_en_el_expediente

        candidatos = ["RE2371202201568", "RE2311202201568", "RE2371202207568"]
        cita = re_citado_en_el_expediente("RE2311202207568", candidatos, {"02_DERECHO-DE-PETICION.pdf": self.CITA})
        assert cita is not None and cita.radicado == "RE2311202201568"
        assert "oficio 2311202201568" in cita.fragmento and cita.fuente == "02_DERECHO-DE-PETICION.pdf"

    def test_lo_que_no_cambia(self):
        from resolutions.domain.resolutor_del_re import re_citado_en_el_expediente

        # Lo leído ya está citado: se queda.
        assert re_citado_en_el_expediente("RE2311202201568", [], {"a": self.CITA}) is None
        # Nadie cita nada parecido.
        assert re_citado_en_el_expediente("RE2311202207568", [], {"a": "sin números"}) is None
        # A dos cifras y sin ser candidato: no basta.
        assert re_citado_en_el_expediente("RE2311202207560", [], {"a": self.CITA}) is None
        # A una cifra, aunque no sea candidato: sí.
        assert re_citado_en_el_expediente("RE2311202207568", [], {"a": self.CITA}).radicado == "RE2311202201568"
        # Dos números posibles: no se adivina.
        dos = self.CITA + " y el oficio 2311202209568"
        assert re_citado_en_el_expediente("RE2311202207568", [], {"a": dos}) is None

    def test_se_corrige_en_lo_entregado(self, tmp_path):
        import pymupdf

        from resolutions.api import constancia as constancias
        from resolutions.api.correccion_del_re import (
            CITADO_EN_EL_EXPEDIENTE,
            corregir_con_el_expediente,
        )

        def pdf(nombre: str, texto: str) -> None:
            documento = pymupdf.open()
            documento.new_page().insert_textbox(pymupdf.Rect(40, 40, 560, 800), texto, fontsize=10)
            documento.save(tmp_path / nombre)
            documento.close()

        pdf("01_DERECHO-DE-PETICION-RE2311202207568.pdf", "Señores AFINIA. Derecho de petición de 2022.")
        pdf("02_DERECHO-DE-PETICION-RE2311202300704.pdf", self.CITA)
        for upd, ruta, hojas, evidencia in (
            (
                "UPD1",
                "01_DERECHO-DE-PETICION-RE2311202207568.pdf",
                [1, 2],
                {
                    "estado": "encontrado",
                    "valor": "RE2311202207568",
                    "metodo": "decidido por el agente: el juez de la IA, mirando el sello, eligió entre lo leído",
                    "candidatos": [{"valor": "RE2311202201568"}, {"valor": "RE2371202207568"}],
                },
            ),
            (
                "UPD2",
                "02_DERECHO-DE-PETICION-RE2311202300704.pdf",
                [1],
                {"estado": "encontrado", "valor": "RE2311202300704", "metodo": "etiqueta impresa"},
            ),
        ):
            constancias.escribir(
                tmp_path / f".bot-entrega-{upd}.json",
                constancias.Constancia(
                    origen=f"1111111/{upd}.pdf",
                    tamano=1,
                    modificado_ns=1,
                    estado=constancias.EstadoDeEntrega.COMPLETA,
                    archivos=[{"ruta": ruta, "bytes": 1}],
                    indice={"filas": [{"nombre": ruta[3:-4].replace("-", " ")}]},
                    evidencia={"re": {"1": evidencia}},
                    documentos=[{"hojas": hojas}],
                ),
            )
        hechos = corregir_con_el_expediente(tmp_path)
        assert len(hechos) == 1 and "RE2311202201568" in hechos[0]
        assert (tmp_path / "01_DERECHO-DE-PETICION-RE2311202201568.pdf").exists()
        assert not (tmp_path / "01_DERECHO-DE-PETICION-RE2311202207568.pdf").exists()
        corregida = constancias.leer(tmp_path / ".bot-entrega-UPD1.json")
        assert corregida.archivos[0]["ruta"] == "01_DERECHO-DE-PETICION-RE2311202201568.pdf"
        assert corregida.evidencia["re"]["1"]["metodo"].startswith(CITADO_EN_EL_EXPEDIENTE)
        assert "oficio 2311202201568" in corregida.evidencia["re"]["1"]["fragmento"]
        # Lo impreso no se toca, y una segunda pasada no cambia nada.
        assert (tmp_path / "02_DERECHO-DE-PETICION-RE2311202300704.pdf").exists()
        assert corregir_con_el_expediente(tmp_path) == []


# -- la notificación personal con su respuesta (el operador, 2026-11-24) ----------------

RE_DE_PEDRO = "RE2310202299901"
NOTIFICACION_DEL_RECLAMO = (
    "Grupo-epm\nNOTIFICACIÓN PERSONAL RECLAMOS\nEn la fecha 12 de octubre de 2022 compareció a las oficinas de "
    "CARIBEMAR DE LA COSTA S.A.S. E.S.P., el (la) señor (a) PEDRO PEREZ PAEZ quien actúa en su nombre propio, a "
    f"notificarse de la respuesta a:\nNúmero de la PQR: {RE_DE_PEDRO}\nTipo de PQR: Reclamo\n"
    "Se entrega copia de la respuesta y para constancia firma:"
)
NOTIFICACION_DEL_RECURSO = (
    "Grupo-epm\nNOTIFICACIÓN PERSONAL\nEn la fecha 23-02-2023 compareció a las oficinas de Caribe Mar, el (la) "
    f"señor (a) PEDRO PEREZ PAEZ a notificarse de la respuesta a:\nNúmero de la POR: {RE_DE_PEDRO}\n"
    "Tipo de POR o Asunto;REC_REPOSICION EN SUBSIDIO DE APELACION\nSe entrega copia de la respuesta"
)
RESPUESTA_AL_RECLAMO = (
    "Grupo-epm\nConsecutivo No.202270000001\nMAGANGUE, 10/10/2022\nSeñor: PEDRO PEREZ PAEZ\nNIC: 1111111\n"
    f"ASUNTO: Reclamación No. {RE_DE_PEDRO}\nEn atención a su escrito presentado, le indicamos lo siguiente:"
)
RESPUESTA_AL_RECURSO = (
    "Grupo-epm\nConsecutivo No. 202370000002\nMAGANGUE, 08/02/2023\nSeñor: PEDRO PEREZ PAEZ\nNIC: 1111111\n"
    f"ASUNTO: Recurso de Reposición en subsidio el de apelación No. {RE_DE_PEDRO}\nEn atención al recurso:"
)
SIGUE_LA_RESPUESTA = "Por lo cual le explicamos la relación de sus consumos anteriores del suministro."


def _nombrados(*documentos: tuple[list[int], str, str | None]) -> GroupingResult:
    """Documentos ya nombrados, con su RE en el código como los deja F6b."""
    return GroupingResult(
        groups=[
            PageGroup(
                code=ResolutionCode(value=f"{i:02d}" + (f" {re_}" if re_ else ""), raw=re_ or f"{i:02d}"),
                page_numbers=list(hojas),
                kind=nombre,
                re_en_el_nombre=bool(re_),
            )
            for i, (hojas, nombre, re_) in enumerate(documentos, start=1)
        ]
    )


class TestLaNotificacionConSuRespuesta:
    """«Si encuentras una notificación personal y una respuesta a la reclamación dentro de un mismo NIC con un RE
    igual, únelos, sólo para esos casos». El PDF se llama como la notificación, con las hojas como en el papel."""

    def test_la_instancia_de_cada_hoja(self):
        from resolutions.domain.asunto_del_documento import (
            INSTANCIA_DEL_RECLAMO,
            INSTANCIA_DEL_RECURSO,
            instancia_de_la_pqr,
        )

        assert instancia_de_la_pqr(NOTIFICACION_DEL_RECLAMO) == INSTANCIA_DEL_RECLAMO
        assert instancia_de_la_pqr(NOTIFICACION_DEL_RECURSO) == INSTANCIA_DEL_RECURSO
        assert instancia_de_la_pqr(RESPUESTA_AL_RECLAMO) == INSTANCIA_DEL_RECLAMO
        assert instancia_de_la_pqr(RESPUESTA_AL_RECURSO) == INSTANCIA_DEL_RECURSO
        assert instancia_de_la_pqr(SIGUE_LA_RESPUESTA) is None

    def test_la_respuesta_de_detras_va_con_su_notificacion(self):
        from resolutions.application.anexos_declarados import (
            la_notificacion_con_su_respuesta,
        )

        textos = {1: CONSTANCIA, 2: NOTIFICACION_DEL_RECLAMO, 3: RESPUESTA_AL_RECLAMO, 4: SIGUE_LA_RESPUESTA}
        cortado = _nombrados(
            ([1], "CONSTANCIA DE RECEPCION DE PETICIONES", "RE2310202200001"),
            ([2], "NOTIFICACION PERSONAL RECLAMOS", RE_DE_PEDRO),
            ([3, 4], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO),
        )
        unido = la_notificacion_con_su_respuesta(cortado, textos, {f"03 {RE_DE_PEDRO}": [4]})
        assert [g.page_numbers for g in unido.grupos.groups] == [[1], [2, 3, 4]]
        junto = unido.grupos.groups[1]
        assert junto.kind == "NOTIFICACION PERSONAL RECLAMOS" and junto.code.value == f"02 {RE_DE_PEDRO}"
        assert junto.orden is None and unido.anexos == {f"02 {RE_DE_PEDRO}": [4]}
        assert unido.parejas[0]["re"] == RE_DE_PEDRO and "justo detrás" in unido.parejas[0]["porque"]
        assert unido.aviso()

    def test_con_la_respuesta_delante_va_como_en_el_papel(self):
        """7740246: la respuesta en las hojas 1-2 y la notificación en la 3; sale con el nombre de la notificación."""
        from resolutions.application.anexos_declarados import (
            la_notificacion_con_su_respuesta,
        )

        textos = {1: RESPUESTA_AL_RECLAMO, 2: SIGUE_LA_RESPUESTA, 3: NOTIFICACION_DEL_RECLAMO}
        cortado = _nombrados(
            ([1, 2], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO), ([3], "NOTIFICACION PERSONAL RECLAMOS", RE_DE_PEDRO)
        )
        unido = la_notificacion_con_su_respuesta(cortado, textos)
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2, 3]]
        assert unido.grupos.groups[0].kind == "NOTIFICACION PERSONAL RECLAMOS"
        assert unido.grupos.groups[0].code.value == f"01 {RE_DE_PEDRO}"

    def test_el_reclamo_y_el_recurso_cada_uno_con_la_suya(self):
        """6834699: notificación del reclamo (1), su respuesta (2-3), el recurso (4), notificación del recurso (5)
        y su respuesta (6). Dos PDF, no uno."""
        from resolutions.application.anexos_declarados import (
            la_notificacion_con_su_respuesta,
        )

        textos = {
            1: NOTIFICACION_DEL_RECLAMO,
            2: RESPUESTA_AL_RECLAMO,
            3: SIGUE_LA_RESPUESTA,
            4: CARTA_DE_PEDRO,
            5: NOTIFICACION_DEL_RECURSO,
            6: RESPUESTA_AL_RECURSO,
        }
        cortado = _nombrados(
            ([1], "NOTIFICACION PERSONAL RECLAMOS", RE_DE_PEDRO),
            ([2, 3], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO),
            ([4], "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION", RE_DE_PEDRO),
            ([5], "NOTIFICACION PERSONAL", RE_DE_PEDRO),
            ([6], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO),
        )
        unido = la_notificacion_con_su_respuesta(cortado, textos)
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2, 3], [4], [5, 6]]
        assert [g.kind for g in unido.grupos.groups] == [
            "NOTIFICACION PERSONAL RECLAMOS",
            "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
            "NOTIFICACION PERSONAL",
        ]

    def test_la_instancia_manda_sobre_estar_al_lado(self):
        """7740476: la notificación del reclamo va lejos de su respuesta, y la del recurso pegada a ella."""
        from resolutions.application.anexos_declarados import (
            la_notificacion_con_su_respuesta,
        )

        textos = {
            1: RESPUESTA_AL_RECLAMO,
            2: CARTA_DE_PEDRO,
            3: NOTIFICACION_DEL_RECLAMO,
            4: NOTIFICACION_DEL_RECURSO,
            5: RESPUESTA_AL_RECURSO,
        }
        cortado = _nombrados(
            ([1], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO),
            ([2], "RECLAMO", "RE2310202299902"),
            ([3], "NOTIFICACION PERSONAL", RE_DE_PEDRO),
            ([4], "NOTIFICACION PERSONAL", RE_DE_PEDRO),
            ([5], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO),
        )
        unido = la_notificacion_con_su_respuesta(cortado, textos)
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 3], [2], [4, 5]]

    @pytest.mark.parametrize(
        "otro",
        [
            ([2], "NOTIFICACION PERSONAL RECLAMOS", "RE2310202299999"),
            ([2], "NOTIFICACION PERSONAL RECLAMOS", None),
            ([2], "NOTIFICACION POR AVISO", RE_DE_PEDRO),
            ([2], "CITACION PARA NOTIFICACION PERSONAL", RE_DE_PEDRO),
        ],
    )
    def test_solo_la_personal_con_el_mismo_re(self, otro):
        from resolutions.application.anexos_declarados import (
            la_notificacion_con_su_respuesta,
        )

        textos = {1: RESPUESTA_AL_RECLAMO, 2: NOTIFICACION_DEL_RECLAMO}
        cortado = _nombrados(([1], "RESPUESTA A LA RECLAMACION", RE_DE_PEDRO), otro)
        unido = la_notificacion_con_su_respuesta(cortado, textos)
        assert [g.page_numbers for g in unido.grupos.groups] == [[1], [2]] and not unido.parejas

    def test_la_fila_lleva_la_fecha_de_la_notificacion(self):
        from resolutions.application.anexos_declarados import la_notificacion_primero

        piezas = [
            {"pages": [1], "archivo": 0, "fecha": "2022-10-01"},
            {"pages": [2, 3], "archivo": 1, "fecha": "2022-10-10"},
            {"pages": [4], "archivo": 1, "fecha": "2022-10-12"},
            {"pages": [5], "archivo": 2, "fecha": "2022-11-01"},
        ]
        ordenadas = la_notificacion_primero(piezas, {4})
        assert [p["pages"] for p in ordenadas] == [[1], [4], [2, 3], [5]]
        assert la_notificacion_primero(piezas, set()) is piezas

    def test_la_auditoria_avisa_la_pareja_partida_y_no_la_unida(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        textos = {1: RESPUESTA_AL_RECLAMO, 2: NOTIFICACION_DEL_RECLAMO}
        partido = auditar_los_radicados(
            [
                ArchivoEntregado(f"01_RESPUESTA-A-LA-RECLAMACION-{RE_DE_PEDRO}.pdf", (1,)),
                ArchivoEntregado(f"02_NOTIFICACION-PERSONAL-RECLAMOS-{RE_DE_PEDRO}.pdf", (2,)),
            ],
            textos,
        )
        assert any("salió aparte de su notificación personal" in e for e in partido.errores)
        junto = auditar_los_radicados(
            [ArchivoEntregado(f"01_NOTIFICACION-PERSONAL-RECLAMOS-{RE_DE_PEDRO}.pdf", (1, 2))], textos
        )
        assert not any("notificación personal" in e for e in junto.errores)
        assert not any("abre con una contestación" in d for d in junto.dudas)


# -- el contrato de transacción nunca lleva pagaré (el operador, 2026-11-24) ------------

CONTRATO = "Grupo-epm\nCONTRATO DE TRANSACCIÓN\nEntre las siguientes partes a saber: CARIBEMAR DE LA COSTA S.A.S."
CLAUSULA_TERCERA = (
    "TERCERO: Para garantizar el pago de las cuotas mensuales de que trata la cláusula segunda, EL CLIENTE "
    "suscribe a favor de CARIBEMAR DE LA COSTA S.A.S E.S.P. un pagaré en blanco con carta de instrucciones."
)
PAGARE = "CARIBEMAR DE LA COSTA S.A.S. ESP\nPAGARE No. 1111111 -2\nFECHA VENCIMIENTO"
CARTA_DE_INSTRUCCIONES = "CARIBEMAR DE LA COSTA S.A.S. ESP\nCARTA DE INSTRUCCIONES ANEXA A PAGARE No. 1111111 2"


class TestElContratoSinPagare:
    def test_el_pagare_sale_del_contrato_con_sus_cartas_y_su_cedula(self):
        """1000478 en la entrega de antes: el contrato (1-3) con pagaré, dos cartas y la cédula (4-7)."""
        from resolutions.application.anexos_declarados import el_contrato_sin_pagare

        textos = {
            1: CONTRATO,
            2: SEGUNDA_HOJA,
            3: CLAUSULA_TERCERA,
            4: PAGARE,
            5: CARTA_DE_INSTRUCCIONES,
            6: CARTA_DE_INSTRUCCIONES,
            7: CEDULA_DE_PEDRO,
            8: CONSTANCIA,
        }
        cortado = _nombrados(
            ([1, 2, 3, 4, 5, 6, 7], "CONTRATO DE TRANSACCION", None),
            ([8], "CONSTANCIA DE RECEPCION DE PETICIONES", "RE2310202200001"),
        )
        limpio = el_contrato_sin_pagare(cortado, textos, {"01": [7]})
        assert [g.page_numbers for g in limpio.grupos.groups] == [[1, 2, 3], [4, 5, 6, 7], [8]]
        assert [g.kind for g in limpio.grupos.groups][:2] == ["CONTRATO DE TRANSACCION", "PAGARE"]
        assert [g.code.value for g in limpio.grupos.groups] == ["01", "02", "03 RE2310202200001"]
        assert limpio.anexos == {"02": [7]} and set(limpio.movidas) == {4, 5, 6, 7}

    def test_el_contrato_limpio_no_se_toca(self):
        """La cláusula TERCERO nombra el pagaré y la carta de instrucciones: no es ninguno de los dos."""
        from resolutions.application.anexos_declarados import el_contrato_sin_pagare

        textos = {1: CONTRATO, 2: CLAUSULA_TERCERA, 3: CEDULA_DE_PEDRO}
        cortado = _nombrados(([1, 2, 3], "CONTRATO DE TRANSACCION", None))
        limpio = el_contrato_sin_pagare(cortado, textos, {"01": [3]})
        assert limpio.grupos is cortado and not limpio.movidas


# -- el paquete de la empresa sin su carátula (el operador, 2026-11-24) -----------------


class TestElPaqueteSinCaratula:
    """«Si la página principal no llega a estar, no importa, que una los demás». 6831824 (UPD2453179): la carta
    «SOLICITUD» con la escritura y la factura (1-11) y la declaración juramentada (12) salían en dos PDF."""

    def test_6831824_la_declaracion_va_con_la_solicitud(self):
        from resolutions.application.anexos_declarados import unir_el_paquete_sin_caratula

        cortado = _grupos(list(range(1, 12)), [12])
        unido = unir_el_paquete_sin_caratula(cortado, {"01": [11]}, anclas={12}, paradas=set())
        assert [g.page_numbers for g in unido.grupos.groups] == [list(range(1, 13))]
        assert unido.anexos == {"01": [11]} and unido.movidas == {12: 1}

    def test_hacia_delante_tambien(self):
        """La declaración delante, la solicitud de servicio y el RETIE detrás: un documento."""
        from resolutions.application.anexos_declarados import unir_el_paquete_sin_caratula

        unido = unir_el_paquete_sin_caratula(_grupos([1], [2, 3], [4]), {}, anclas={1, 2}, paradas=set())
        assert [g.page_numbers for g in unido.grupos.groups] == [[1, 2, 3, 4]]

    @pytest.mark.parametrize("parada", [3, 5])
    def test_la_parada_corta(self, parada):
        """Una constancia (3) delante, o un acuerdo de pago o un sello (5) detrás, no entran."""
        from resolutions.application.anexos_declarados import unir_el_paquete_sin_caratula

        unido = unir_el_paquete_sin_caratula(_grupos([3], [4], [5], [6]), {}, anclas={4}, paradas={parada})
        esperado = [[3], [4, 5, 6]] if parada == 3 else [[3, 4], [5], [6]]
        assert [g.page_numbers for g in unido.grupos.groups] == esperado

    def test_la_declaracion_sola_no_cambia(self):
        from resolutions.application.anexos_declarados import unir_el_paquete_sin_caratula

        cortado = _grupos([1])
        unido = unir_el_paquete_sin_caratula(cortado, {}, anclas={1}, paradas=set())
        assert unido.grupos is cortado and not unido.movidas

    def test_dentro_del_paquete_con_caratula_no_se_toca(self):
        """La declaración que ya va en el paquete de su carátula (1) no arma otro."""
        from resolutions.application.anexos_declarados import unir_el_paquete_sin_caratula

        cortado = _grupos([1, 2, 3], [4])
        unido = unir_el_paquete_sin_caratula(cortado, {}, anclas={2}, paradas={1})
        assert unido.grupos is cortado

    def test_la_auditoria_avisa_la_declaracion_aparte(self):
        from resolutions.application.auditoria_de_la_entrega import auditar_los_radicados
        from resolutions.domain.conciliacion import ArchivoEntregado

        solicitud = (
            "Santa Rosa del Sur, agosto 26 de 2022\nSeñores: GRUPO EPM\nREFERENCIA: SOLICITUD.\n"
            "Yo, ANA MARIA GOMEZ RUIZ, solicito respetuosamente el cambio de nombre del titular del recibo."
        )
        textos = {1: solicitud, 2: DECLARACION_DE_ANA}
        assert formulario_que_abre(DECLARACION_DE_ANA) == DECLARACION_JURAMENTADA
        partido = auditar_los_radicados(
            [ArchivoEntregado("01_SOLICITUD.pdf", (1,)), ArchivoEntregado("02_DECLARACION.pdf", (2,))], textos
        )
        assert any("declaración juramentada salió aparte" in d for d in partido.dudas)
        tras_la_constancia = auditar_los_radicados(
            [ArchivoEntregado("01_CONSTANCIA.pdf", (1,)), ArchivoEntregado("02_DECLARACION.pdf", (2,))],
            {1: CONSTANCIA, 2: DECLARACION_DE_ANA},
        )
        assert not any("declaración juramentada" in d for d in tras_la_constancia.dudas)
