"""El revisor de cortes: cada PDF que sale, comprobado costura por costura.

Lo pidió el operador el 2026-11-05 ante la caja 1004569 de MAGANGUE
(UPD2437853): el acuerdo de pago se había llevado la última hoja del contrato de
transacción -- cláusulas TERCERO y CUARTO, firmas -- y la cédula de detrás,
saltando la constancia de en medio. Quiso un agente que «verifique y rectifique
todo sin importar la habilidad», «con un margen de error», y que lo que se
salga del margen «se lo envíe a la IA, la IA lo analice y decida», con pocos
tokens. Y que cubra «absolutamente todos los casos que puedan llegar a ocurrir
en medio del procesamiento»: aquí está un escenario por cada uno.

Los textos copian la forma del papel real de 1004569, con otro nombre y otra
cédula.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from resolutions.application.ports import VeredictoDeCostura
from resolutions.application.revisor_de_cortes import (
    COSTURAS_POR_PREGUNTA,
    PREGUNTAS_POR_CAJA,
    Patrones,
    revisar_los_cortes,
)
from resolutions.domain.conciliacion import Huella, comprobar_lo_escrito
from resolutions.domain.grouping import GroupingResult, PageGroup
from resolutions.domain.resolution_code import ResolutionCode
from resolutions.domain.revision_de_cortes import (
    Decision,
    cedulas,
    clausulas,
    frase_partida,
    pagina_declarada,
    primera_clausula,
    revisar_costuras,
)

CONSTANCIA_0503 = (
    "PARA LA EMPRESA\nGrupo-epm\nRecibí constancia del contenido de la reclamación presentada ante "
    "CARIBEMAR DE LA COSTA S.A.S. ESP\nN° PQR: RE2310202300503\nFECHA: 11/01/2023\nCODIGO (NIC): 1004569\n"
    "CAUSA: Información general\n"
)
CONTRATO_1 = (
    "- wW\narinia\nCONTRATO DE TRANSACCIÓN\nCARIBEMAR DE LA COSTA S.A.S. ESP\n"
    "Entre las siguientes partes a saber: CARIBEMAR DE LA COSTA S.A.S E.S.P. sociedad regida de acuerdo\n"
    "con las leyes de la República de Colombia, y la señora Ana Perez en calidad de Usuario.\n"
    "I.-CONSIDERACIONES;\nQue CARIBEMAR DE LA COSTA S.A.S E.S.P. realizó una revisión de las instalaciones.\n"
)
CONTRATO_2 = (
    "añnia\nGrupo«epn9\nEn estos documentos se le indicó al CLIENTE el derecho que tenía de presentar el reclamo y\n"
    "los recursos contra la factura en los términos del artículo 154 de la Ley 142 de 1994.\n"
    "ll.-ACUERDAN:\n"
    "PRIMERO: EL CLIENTE cancelará a CARIBEMAR DE LA COSTA S.A.S E.S.P. la suma de $\n"
    "287410 en los términos y condiciones previstos en la cláusula segunda de este acuerdo.\n"
    "SEGUNDO: El CLIENTE pagará a CARIBEMAR DE LA CQSTA S.A.S E.S.P. de la deuda de\n"
    "($287410) de la siguiente manera: financiado a 11 cuotas de $23008.\nwww.afmia.com.co\n"
)
CONTRATO_3 = (
    "arinia\nGrupo*epno\n"
    "TERCERO: Para garantizar el pago de las cuotas mensuales de que trata la cláusula segunda, EL\n"
    "CLIENTE suscribe a favor de CARIBEMAR DE LA COSTA S.A.S E.S.P. un pagaré en blanco con\n"
    "carta de instrucciones. En el evento en que EL CLIENTE incurra en mora en el pago de alguna de\n"
    "dichas cuotas, se harán exigibles la totalidad de las sumas adeudadas.\n"
    "CUARTO: La presente transacción pone fin al Procedimiento para la Determinación de Consumos.\n"
    "En constancia se suscribe este documento en dos ejemplares de idéntico tenor\n"
    "Ciudad: Magangué , día: 12 mes: 1 del año 2023.\nPor EL CLIENTE:\nNombre: Ana Perez\n"
    "C.C. No: 23000000 expedida en Mompós\n"
)
CEDULA = (
    "REPUBLICA DE COLOMBIA\nIDENTIFICACION PERSONAL\nCEDULA DE CIUDADANIA\n23.000.000\nNUMERO\n"
    "PEREZ\nAPELLIDOS\nANA\nNOMBRES\n"
)
CONSTANCIA_0523 = CONSTANCIA_0503.replace("0503", "0523").replace("11/01", "12/01").replace(
    "Información general", "Gestionar financiación"
)
RECONOCIMIENTO = (
    "Magangué 12 de enero de 2023\nSeñores:\nCARIBE MAR DE LA COSTA S.A. E.S.P.\nLa Ciudad\n"
    "Ref.: Reconocimiento de deuda y propuesta de acuerdo de pago.\n"
    "Yo, Ana Perez identificado como aparece al pie de mi firma, en mi calidad de usuario.\n"
)
PAGARE = "CARIBEMAR DE LA COSTA S.A.S. ESP\nEMPRESA DE SERVICIOS PUBLICOS DOMICILIARIOS\nPAGARE No. 1004569 -3\n"
CARTA_1 = (
    "CARIBEMAR DE LA COSTA S.A.S. ESP\nCARTA DE INSTRUCCIONES ANEXA A PAGARE No. 1004569 3 CON ESPACIOS ABIERTOS\n"
    "identificado como aparece al pie de mi firma, autorizo irrevocablemente.\n"
)
CARTA_2 = CARTA_1 + "5. El monto del pagaré será igual al valor que deba.\n"

#: Las once hojas de UPD2437853, en su orden.
TEXTOS = {
    1: CONSTANCIA_0503,
    2: CONTRATO_1,
    3: CONTRATO_2,
    4: CONTRATO_3,
    5: CEDULA,
    6: CONSTANCIA_0523,
    7: RECONOCIMIENTO,
    8: PAGARE,
    9: CARTA_1,
    10: CARTA_2,
    11: CEDULA,
}
#: Lo que entregó el bot el 27-oct: el acuerdo con las hojas 4 y 5 del contrato.
CORTE_DEL_27_OCT = ([1], [2, 3], [6], [4, 5, 7, 8, 9, 10, 11])
#: Lo correcto, que el operador confirmó.
CORTE_BUENO = ([1], [2, 3, 4, 5], [6], [7, 8, 9, 10, 11])
#: Las constancias van solas: abren por regla.
ABREN = frozenset({1, 6})


def _grupos(*documentos: list[int]) -> GroupingResult:
    return GroupingResult(
        groups=[
            PageGroup(code=ResolutionCode(value=f"{i:02d}", raw=f"{i:02d}"), page_numbers=list(p))
            for i, p in enumerate(documentos, start=1)
        ]
    )


def _paginas(revision) -> list[list[int]]:
    return sorted(g.page_numbers for g in revision.grupos.groups)


class _Juez:
    """Un juez de mentira: contesta lo que se le diga y anota cada pregunta."""

    def __init__(self, decision: str | None = "continua", cita: str = "TERCERO: Para garantizar el pago", falla=None):
        self.decision = decision
        self.cita = cita
        self.falla = falla
        self.preguntas: list[tuple[list, list, str]] = []

    def decidir(self, hojas, costuras, reglas):
        self.preguntas.append((hojas, costuras, reglas))
        if self.falla is not None:
            raise self.falla
        if self.decision is None:
            return None
        return {c: VeredictoDeCostura(self.decision, self.cita) for c in costuras}


class TestLoQueLeeDelPapel:
    def test_las_clausulas_del_contrato(self):
        assert clausulas(CONTRATO_2) == [1, 2]
        assert primera_clausula(CONTRATO_3) == 3

    def test_el_articulo_de_una_resolucion(self):
        assert primera_clausula("RESOLUCION\nARTÍCULO SEGUNDO: Notifíquese.") == 2

    def test_la_paginacion_declarada(self):
        assert pagina_declarada("texto\nPágina 2 de 3") == (2, 3)
        assert pagina_declarada("Pág. 3/3") == (3, 3)
        assert pagina_declarada("sin paginar") is None

    def test_la_frase_partida(self):
        assert frase_partida("renglón largo que se queda colgando de", "y sigue aquí en minúscula esta frase")
        assert not frase_partida("renglón largo que termina bien.", "y sigue aquí en minúscula esta frase")

    def test_las_cedulas(self):
        assert cedulas(CONTRATO_3) == frozenset({"23000000"})
        assert cedulas("C.C. No. 73.195.535 de Cartagena") == frozenset({"73195535"})


class TestLaCajaDel27DeOctubre:
    """El error que dio origen al revisor, visto como lo vería hoy."""

    def test_la_costura_tiene_dos_pruebas_fuertes(self):
        costuras = revisar_costuras(CORTE_DEL_27_OCT, TEXTOS, abren=ABREN)
        costura = next(c for c in costuras if (c.izquierda, c.derecha) == (3, 4))
        assert costura.decision is Decision.CORTE
        assert sum(p.fuerte for p in costura.pruebas) == 2
        assert costura.error_seguro
        assert costura.propuesta.paginas == (4, 5)
        assert costura.propuesta.hacia == 3

    def test_se_corrige_sin_ia_y_queda_lo_que_confirmo_el_operador(self):
        revision = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        assert _paginas(revision) == sorted(CORTE_BUENO)
        assert revision.estado == "corregido"
        assert revision.movimientos[0].paginas == (4, 5)
        assert revision.movimientos[0].por == "dos pruebas del papel"
        assert "TERCERO" in revision.movimientos[0].motivo

    def test_el_corte_bueno_se_valida_sin_gastar(self):
        juez = _Juez()
        revision = revisar_los_cortes(_grupos(*CORTE_BUENO), TEXTOS, Patrones(abren=ABREN), juez=juez)
        assert revision.estado == "validado"
        assert revision.dentro_del_margen == revision.costuras == 10
        assert juez.preguntas == []

    def test_los_codigos_se_renumeran(self):
        revision = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        assert [g.code.value for g in revision.grupos.groups] == ["01", "02", "03", "04"]

    def test_aunque_el_titulo_mal_puesto_la_de_por_cruce_del_acuerdo(self):
        """Medido con el bot del 27-oct de vuelta: la hoja 4 se titulaba CARTA DE
        INSTRUCCIONES y por eso contaba como pieza que cruza. Como sigue por su
        cláusula a la hoja 3, su salto vuelve a ser prueba: dos pruebas, corregida."""
        revision = revisar_los_cortes(
            _grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN, cruces=frozenset({4, 8, 9, 10}))
        )
        assert _paginas(revision) == sorted(CORTE_BUENO)
        assert revision.movimientos[0].por == "dos pruebas del papel"


class TestFueraDelMargenDecideLaIa:
    """El contrato partido sin salto: una sola prueba fuerte."""

    PARTIDO = ([1], [2, 3], [4, 5], [6], [7, 8, 9, 10, 11])

    def test_sin_ia_va_a_revision_y_no_se_mueve(self):
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN))
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert [p for p, _ in revision.en_revision] == [4]
        assert "OCR + IA" in revision.en_revision[0][1]
        # Sin IA no se le preguntó nada: la pantalla no puede decir lo contrario.
        assert revision.preguntadas == 0

    def test_la_ia_decide_y_se_corrige(self):
        juez = _Juez("continua")
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=juez)
        assert _paginas(revision) == sorted(CORTE_BUENO)
        assert revision.movimientos[0].por == "la IA"
        assert len(juez.preguntas) == 1

    def test_la_ia_ve_poco_y_sin_el_titulo_del_bot(self):
        juez = _Juez("continua")
        revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN, reglas="R"), juez=juez)
        hojas, costuras, reglas = juez.preguntas[0]
        assert costuras == [(3, 4)]
        assert reglas == "R"
        # La ventana de la costura y nada más.
        assert [h["p"] for h in hojas] == [2, 3, 4, 5]
        assert all(set(h) <= {"p", "ini", "fin", "es"} for h in hojas)
        assert all(len(str(h.get("ini", ""))) <= 320 for h in hojas)

    def test_la_ia_le_da_la_razon_al_bot(self):
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=_Juez("abre"))
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert revision.confirmadas_por_la_ia == 1
        assert revision.estado == "validado"

    def test_sin_cita_del_papel_no_se_mueve_nada(self):
        revision = revisar_los_cortes(
            _grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=_Juez("continua", cita="  ")
        )
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert [p for p, _ in revision.en_revision] == [4]

    def test_no_se_es_revision(self):
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=_Juez("no_se"))
        assert [p for p, _ in revision.en_revision] == [4]


class TestLoQuePuedePasarEnMedio:
    PARTIDO = TestFueraDelMargenDecideLaIa.PARTIDO

    def test_la_ia_no_responde(self):
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=_Juez(None))
        assert revision.ia_no_respondio
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert "no respondió" in revision.en_revision[0][1]

    def test_la_costura_sin_contestar_se_pregunta_otra_vez(self):
        """Medido con 1004569: la misma pregunta volvió una vez vacía y la
        siguiente con «continua» y su cita."""

        class _Olvidadizo(_Juez):
            def decidir(self, hojas, costuras, reglas):
                self.preguntas.append((hojas, costuras, reglas))
                if len(self.preguntas) == 1:
                    return {}
                return {c: VeredictoDeCostura("continua", "TERCERO: Para garantizar") for c in costuras}

        juez = _Olvidadizo()
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=juez)
        assert len(juez.preguntas) == 2
        assert juez.preguntas[1][1] == [(3, 4)]
        assert _paginas(revision) == sorted(CORTE_BUENO)

    def test_el_juez_revienta_y_la_caja_sigue(self):
        juez = _Juez(falla=RuntimeError("se cayó"))
        revision = revisar_los_cortes(_grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN), juez=juez)
        assert revision.ia_no_respondio
        assert _paginas(revision) == sorted(self.PARTIDO)

    def test_una_hoja_fija_no_se_mueve_ni_se_pregunta(self):
        juez = _Juez("continua")
        revision = revisar_los_cortes(
            _grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN, fijas=frozenset({5})), juez=juez
        )
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert juez.preguntas == []
        assert "fija" in revision.en_revision[0][1]

    def test_el_papel_contra_una_regla_va_a_revision(self):
        """La hoja 4 abre por regla y el papel dice que sigue: manda la regla."""
        juez = _Juez("continua")
        revision = revisar_los_cortes(
            _grupos(*self.PARTIDO), TEXTOS, Patrones(abren=ABREN | {4}), juez=juez
        )
        assert _paginas(revision) == sorted(self.PARTIDO)
        assert juez.preguntas == []
        assert "regla" in revision.en_revision[0][1]

    def test_una_prueba_debil_no_discute_una_regla(self):
        """1000224 pág. 2: la OCR del membrete parece una frase que sigue, y la
        regla dice que la constancia va sola. No es una alarma."""
        textos = {
            1: "PARA LA EMPRESA\nRecibí constancia del contenido\nNombre del cliente que reclama aquí de",
            2: "a la prosperidad de todos los clientes\nTalaigua Nuevo 16 de Mayo de 2021",
        }
        revision = revisar_los_cortes(_grupos([1], [2]), textos, Patrones(abren=frozenset({1, 2})), juez=_Juez())
        assert revision.estado == "validado"
        assert revision.en_revision == ()

    def test_la_habeas_data_que_cruza_por_regla_no_es_sospechosa(self):
        """UPD3102729: la Habeas Data de la hoja 1 con el acuerdo de la 6-14."""
        textos = {1: "ASUNTO: Ley Habeas Data - NIC 1000265\nYo, Sandra", 2: CONSTANCIA_0503, 3: RECONOCIMIENTO, 4: PAGARE}
        revision = revisar_los_cortes(
            _grupos([2], [1, 3, 4]), textos, Patrones(abren=frozenset({2}), cruces=frozenset({1}))
        )
        assert revision.estado == "validado"

    def test_si_la_correccion_perdiera_una_hoja_se_descarta(self, monkeypatch):
        from resolutions.application import revisor_de_cortes as modulo

        def rota(grupos, anexos, decididas):
            perdida = GroupingResult(groups=[g for g in grupos.groups if 4 not in g.page_numbers])
            return perdida, anexos, [modulo.Movimiento((4, 5), (4, 5), (2, 3), "x", "y")]

        monkeypatch.setattr(modulo, "_aplicar", rota)
        revision = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        assert _paginas(revision) == sorted(CORTE_DEL_27_OCT)
        assert revision.movimientos == ()
        assert "perdía o repetía" in revision.en_revision[0][1]

    def test_una_caja_con_muchas_dudas_se_pregunta_en_tandas_y_con_tope(self):
        # Cada hoja par empieza una cláusula que sigue a la de la impar, y el
        # bot las cortó todas: una duda por costura.
        total = (COSTURAS_POR_PREGUNTA * PREGUNTAS_POR_CAJA + 5) * 2
        textos = {
            p: ("PRIMERO: algo del contrato.\n" if p % 2 else "SEGUNDO: lo que sigue del contrato.\n")
            for p in range(1, total + 1)
        }
        documentos = [[p] for p in range(1, total + 1)]
        juez = _Juez("abre")
        revision = revisar_los_cortes(_grupos(*documentos), textos, Patrones(), juez=juez)
        assert len(juez.preguntas) == PREGUNTAS_POR_CAJA
        assert all(len(costuras) <= COSTURAS_POR_PREGUNTA for _, costuras, _ in juez.preguntas)
        assert sum("demasiadas dudas" in motivo for _, motivo in revision.en_revision) == 5

    def test_la_hoja_muda_se_relee_solo_si_cae_en_la_ventana(self):
        releidas = []

        def releer(pagina):
            releidas.append(pagina)
            return "TERCERO: Para garantizar el pago de las cuotas mensuales del contrato de transacción firmado"

        textos = dict(TEXTOS)
        textos[5] = "· ·"
        juez = _Juez("continua")
        revisar_los_cortes(
            _grupos(*TestFueraDelMargenDecideLaIa.PARTIDO), textos, Patrones(abren=ABREN), juez=juez, releer=releer
        )
        assert releidas == [5]

    def test_la_relectura_que_falla_no_rompe(self):
        def releer(_pagina):
            raise OSError("sin red")

        textos = dict(TEXTOS)
        textos[5] = ""
        revision = revisar_los_cortes(
            _grupos(*TestFueraDelMargenDecideLaIa.PARTIDO), textos, Patrones(abren=ABREN), juez=_Juez("continua"), releer=releer
        )
        assert revision.estado == "corregido"


class TestLasOtrasHabilidades:
    def test_dos_personas_en_un_pdf_se_senalan_sin_gastar(self):
        """Diplomas, actas de grado: una persona por PDF. La habilidad no sabe
        nombrar lo partido, así que se señala y a la IA no se le pregunta."""
        textos = {1: "Diploma a Ana Perez C.C. No. 23000000", 2: "Diploma a Luis Gomez C.C. No. 73195535"}
        juez = _Juez("abre")
        revision = revisar_los_cortes(
            _grupos([1, 2]), textos, Patrones(una_persona_por_pdf=True, puede_mover=False), juez=juez
        )
        assert juez.preguntas == []
        assert [p for p, _ in revision.en_revision] == [2]
        assert _paginas(revision) == [[1, 2]]

    def test_partir_un_pdf_que_lleva_dentro_una_hoja_que_abre(self):
        textos = {1: "Señores\nREF: DERECHO DE PETICION", 2: "sigue la petición en esta hoja.", 3: "Señores\nREF: RECLAMO"}
        revision = revisar_los_cortes(
            _grupos([1, 2, 3]), textos, Patrones(abren=frozenset({1, 3})), juez=_Juez("abre", cita="REF: RECLAMO")
        )
        assert _paginas(revision) == [[1, 2], [3]]
        assert revision.movimientos[0].hacia is None


class TestLaComprobacionDelDisco:
    ORIGEN = [Huella(texto="a"), Huella(texto="b"), Huella(imagen="c"), Huella()]

    def test_todo_en_su_sitio(self):
        escritos = {"01.pdf": [Huella(texto="a"), Huella(texto="b")], "02.pdf": [Huella(imagen="c"), Huella()]}
        assert comprobar_lo_escrito(self.ORIGEN, escritos, {"01.pdf": [1, 2], "02.pdf": [3, 4]}) == []

    def test_una_hoja_cambiada_de_puesto(self):
        escritos = {"01.pdf": [Huella(texto="b"), Huella(texto="a")]}
        problemas = comprobar_lo_escrito(self.ORIGEN, escritos, {"01.pdf": [1, 2]})
        assert [p["pagina"] for p in problemas] == [1, 2]

    def test_un_archivo_con_hojas_de_menos(self):
        problemas = comprobar_lo_escrito(self.ORIGEN, {"01.pdf": [Huella(texto="a")]}, {"01.pdf": [1, 2]})
        assert "1 hojas y debía tener 2" in problemas[0]["texto"]

    def test_un_archivo_que_no_se_deja_abrir(self):
        problemas = comprobar_lo_escrito(self.ORIGEN, {"01.pdf": None}, {"01.pdf": [1, 2]})
        assert "no se dejó abrir" in problemas[0]["texto"]

    def test_entregar_comprueba_lo_que_escribio(self, tmp_path):
        pymupdf = pytest.importorskip("pymupdf")
        from resolutions.adapters.huellas_pdf import huellas_de
        from resolutions.adapters.pymupdf_assembler import PyMuPDFAssembler
        from resolutions.application.entrega import Destino, entregar

        origen = tmp_path / "caja.pdf"
        documento = pymupdf.open()
        for texto in ("Primera hoja de la petición del cliente", "Segunda hoja de la petición del cliente", "Respuesta de la empresa a la petición"):
            documento.new_page().insert_text((72, 72), texto)
        documento.save(origen)
        documento.close()
        entregado = entregar(
            _grupos([1, 2], [3]),
            origen=origen,
            nombre="caja.pdf",
            paginas=3,
            destino=Destino(directorio=tmp_path / "salida"),
            assembler=PyMuPDFAssembler(naming_prefix=None),
            huellas=huellas_de,
        )
        assert entregado.comprobacion["comprobada"]
        assert entregado.comprobacion["problemas"] == []
        assert entregado.comprobacion["hojas"] == 3

    def test_la_comprobacion_que_no_puede_leer_no_rompe_la_entrega(self, tmp_path):
        pymupdf = pytest.importorskip("pymupdf")
        from resolutions.adapters.pymupdf_assembler import PyMuPDFAssembler
        from resolutions.application.entrega import Destino, entregar

        origen = tmp_path / "caja.pdf"
        documento = pymupdf.open()
        documento.new_page().insert_text((72, 72), "Una hoja con su texto para la prueba")
        documento.save(origen)
        documento.close()

        def rota(_ruta):
            raise OSError("disco")

        entregado = entregar(
            _grupos([1]),
            origen=origen,
            nombre="caja.pdf",
            paginas=1,
            destino=Destino(directorio=tmp_path / "salida"),
            assembler=PyMuPDFAssembler(naming_prefix=None),
            huellas=rota,
        )
        assert entregado.comprobacion["comprobada"] is False
        assert entregado.salidas


class TestElJuezDeMistral:
    def _respuesta(self, contenido: dict, uso=None) -> io.BytesIO:
        return io.BytesIO(
            json.dumps(
                {"choices": [{"message": {"content": json.dumps(contenido)}}], "usage": uso or {"prompt_tokens": 900, "completion_tokens": 40}}
            ).encode()
        )

    def test_lee_lo_que_se_pregunto_y_nada_mas(self):
        from resolutions.adapters.mistral_revisor import leer_la_respuesta

        texto = json.dumps(
            {
                "costuras": [
                    {"izq": 3, "der": 4, "decision": "Continúa", "cita": "TERCERO"},
                    {"izq": 8, "der": 9, "decision": "continua", "cita": "x"},
                    {"izq": "a", "der": 5},
                    {"izq": 5, "der": 6, "decision": "quizá"},
                ]
            }
        )
        veredictos = leer_la_respuesta(texto, [(3, 4), (5, 6)])
        assert veredictos[(3, 4)].decision == "continua"
        assert veredictos[(5, 6)].decision == "no_se"
        assert (8, 9) not in veredictos

    def test_la_basura_no_se_lee(self):
        from resolutions.adapters.mistral_revisor import leer_la_respuesta

        assert leer_la_respuesta("no es json", [(3, 4)]) == {}
        assert leer_la_respuesta("[1, 2]", [(3, 4)]) == {}

    def test_sin_costuras_no_se_llama(self, monkeypatch):
        from resolutions.adapters import mistral_revisor

        monkeypatch.setattr(mistral_revisor.urllib.request, "urlopen", lambda *a, **k: pytest.fail("llamó"))
        assert mistral_revisor.MistralJuezDeCosturas(api_key="k").decidir([], [], "") == {}

    def test_sin_llave_no_responde(self, monkeypatch):
        from resolutions.adapters import mistral_revisor

        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setattr(mistral_revisor.urllib.request, "urlopen", lambda *a, **k: pytest.fail("llamó"))
        assert mistral_revisor.MistralJuezDeCosturas(api_key="").decidir([{"p": 1}], [(1, 2)], "") is None

    def test_un_429_se_espera_y_se_repite(self, monkeypatch):
        from resolutions.adapters import mistral_revisor
        from resolutions.application.consumo import Consumo

        llamadas = []

        def urlopen(peticion, timeout):
            llamadas.append(json.loads(peticion.data))
            if len(llamadas) == 1:
                raise urllib.error.HTTPError(peticion.full_url, 429, "despacio", {}, io.BytesIO(b""))
            return self._respuesta({"costuras": [{"izq": 3, "der": 4, "decision": "continua", "cita": "TERCERO"}]})

        monkeypatch.setattr(mistral_revisor.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(mistral_revisor.time, "sleep", lambda _s: None)
        consumo = Consumo()
        juez = mistral_revisor.MistralJuezDeCosturas(api_key="k", consumo=consumo)
        veredictos = juez.decidir([{"p": 3}, {"p": 4}], [(3, 4)], "reglas")
        assert veredictos[(3, 4)].decision == "continua"
        assert len(llamadas) == 2
        # La pregunta lleva el modelo pequeño, JSON y temperatura cero.
        assert llamadas[0]["model"] == "mistral-small-latest"
        assert llamadas[0]["response_format"] == {"type": "json_object"}
        assert llamadas[0]["temperature"] == 0

    def test_una_llave_mala_no_se_reintenta(self, monkeypatch):
        from resolutions.adapters import mistral_revisor

        llamadas = []

        def urlopen(peticion, timeout):
            llamadas.append(1)
            raise urllib.error.HTTPError(peticion.full_url, 401, "llave", {}, io.BytesIO(b""))

        monkeypatch.setattr(mistral_revisor.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(mistral_revisor.time, "sleep", lambda _s: None)
        assert mistral_revisor.MistralJuezDeCosturas(api_key="k").decidir([{"p": 1}], [(1, 2)], "") is None
        assert len(llamadas) == 1

    def test_la_red_caida_se_reintenta_y_luego_no_responde(self, monkeypatch):
        from resolutions.adapters import mistral_revisor

        llamadas = []

        def urlopen(peticion, timeout):
            llamadas.append(1)
            raise TimeoutError("lento")

        monkeypatch.setattr(mistral_revisor.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(mistral_revisor.time, "sleep", lambda _s: None)
        assert mistral_revisor.MistralJuezDeCosturas(api_key="k").decidir([{"p": 1}], [(1, 2)], "") is None
        assert len(llamadas) == 3


class TestLoQueVeLaPantalla:
    """Lo que el informe le da a la pantalla para dibujar el trabajo del agente."""

    def test_cada_costura_fuera_del_margen_con_su_resultado(self):
        revision = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        fuera = revision.as_dict()["fuera_del_margen"]
        assert fuera == [
            {
                "izq": 3,
                "der": 4,
                "decision": "corte",
                "confianza": 0.05,
                "resultado": "corregida",
                "motivo": revision.movimientos[0].motivo,
            }
        ]
        assert revision.as_dict()["movimientos"][0]["costura"] == [3, 4]

    def test_la_confirmada_por_la_ia_y_la_de_revision(self):
        partido = TestFueraDelMargenDecideLaIa.PARTIDO
        confirmada = revisar_los_cortes(_grupos(*partido), TEXTOS, Patrones(abren=ABREN), juez=_Juez("abre"))
        assert [c["resultado"] for c in confirmada.as_dict()["fuera_del_margen"]] == ["confirmada"]
        sin_ia = revisar_los_cortes(_grupos(*partido), TEXTOS, Patrones(abren=ABREN))
        assert [c["resultado"] for c in sin_ia.as_dict()["fuera_del_margen"]] == ["revision"]

    def test_la_caja_validada_no_trae_costuras_fuera(self):
        revision = revisar_los_cortes(_grupos(*CORTE_BUENO), TEXTOS, Patrones(abren=ABREN))
        assert revision.as_dict()["fuera_del_margen"] == []


class TestElAgenteDeLaCorrida:
    """La suma de lo que hizo el agente en una corrida de carpeta, para el monitor en vivo."""

    def _informe(self, revision, problemas=()):
        return {
            "revision_de_cortes": revision.as_dict(),
            "comprobacion_de_la_entrega": {"hojas": 11, "problemas": list(problemas), "resumen": "x"},
        }

    def test_suma_cada_pdf_y_cuenta_lo_que_paso(self):
        from resolutions.application.revisor_de_cortes import AgenteDeLaCorrida

        agente = AgenteDeLaCorrida()
        bueno = revisar_los_cortes(_grupos(*CORTE_BUENO), TEXTOS, Patrones(abren=ABREN))
        malo = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        agente.sumar("UPD1.pdf", self._informe(bueno))
        agente.sumar("UPD2437853.pdf", self._informe(malo))
        datos = agente.as_dict()
        assert (datos["pdf"], datos["validados"], datos["corregidos"]) == (2, 1, 1)
        assert datos["costuras"] == 20
        assert datos["dentro_del_margen"] == 19
        assert datos["correcciones"] == 1
        assert datos["hojas_comprobadas"] == 22
        # Sólo lo que merece contarse llega al registro en vivo: la corrección.
        assert [s["pdf"] for s in datos["sucesos"]] == ["UPD2437853.pdf"]
        assert datos["sucesos"][0]["texto"] == "hojas 4-5 con las hojas 2-3, por dos pruebas del papel"

    def test_un_problema_en_el_disco_se_cuenta_y_se_dice(self):
        from resolutions.application.revisor_de_cortes import AgenteDeLaCorrida

        agente = AgenteDeLaCorrida()
        bueno = revisar_los_cortes(_grupos(*CORTE_BUENO), TEXTOS, Patrones(abren=ABREN))
        agente.sumar("UPD9.pdf", self._informe(bueno, [{"texto": "la hoja 2 de 01.pdf no es la hoja 2 del original"}]))
        datos = agente.as_dict()
        assert datos["problemas_de_entrega"] == 1
        assert datos["sucesos"][0]["estado"] == "problema"

    def test_lo_que_no_parte_pdf_no_cuenta_y_el_que_no_corrio_si(self):
        from resolutions.application.revisor_de_cortes import AgenteDeLaCorrida

        agente = AgenteDeLaCorrida()
        agente.sumar("inventario.pdf", {"document_type": "diploma"})
        assert agente.as_dict()["pdf"] == 0
        agente.sumar("roto.pdf", {"revision_de_cortes": {"estado": "no corrió", "resumen": "El revisor falló"}})
        assert agente.as_dict()["sin_revisar"] == 1
        assert agente.as_dict()["sucesos"][0]["texto"] == "El revisor falló"

    def test_el_registro_en_vivo_guarda_los_ultimos(self):
        from resolutions.application.revisor_de_cortes import (
            SUCESOS_EN_VIVO,
            AgenteDeLaCorrida,
        )

        agente = AgenteDeLaCorrida()
        malo = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        for numero in range(SUCESOS_EN_VIVO + 3):
            agente.sumar(f"UPD{numero}.pdf", self._informe(malo))
        sucesos = agente.as_dict()["sucesos"]
        assert len(sucesos) == SUCESOS_EN_VIVO
        assert sucesos[0]["pdf"] == f"UPD{SUCESOS_EN_VIVO + 2}.pdf"


class TestElAcuerdoTrasElRevisor:
    def test_la_hoja_que_sale_del_acuerdo_deja_de_ser_suya(self):
        from resolutions.api.worker.correspondencia import revisados_del_acuerdo

        revision = revisar_los_cortes(_grupos(*CORTE_DEL_27_OCT), TEXTOS, Patrones(abren=ABREN))
        assert revisados_del_acuerdo({4, 5, 7, 8, 9, 10, 11}, revision) == {7, 8, 9, 10, 11}
