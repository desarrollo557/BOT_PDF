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
