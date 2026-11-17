"""El revisor de nombres, la pieza común a todas las habilidades (2026-11-17).

El operador: «usar estas herramientas muy bien creadas para todas las
habilidades… centralizarlas y conectarlas a todas las habilidades». Es el gemelo
del revisor de fechas: el voto, la otra mirada de lo dudoso, la IA que mira el
renglón, el padrón y lo que va a Revisión, con la misma decisión para todas.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resolutions.application.control import Cancelled
from resolutions.application.revisor_de_nombres import (
    CLAVE_DEL_INFORME,
    PorRevisar,
    anotar_en_el_informe,
    revisar_los_nombres,
)
from resolutions.domain.historia_medicina import nombre_por_consenso
from resolutions.domain.padron import ACTA_DE_GRADO, IndiceDelPadron, Persona
from resolutions.domain.revision_de_nombres import (
    A_REVISION,
    CONFIRMADO,
    CORREGIDO,
    SE_LEYO_DISTINTO,
    SIN_DATO,
    decidir_el_nombre,
)

CAMPO = ["CAMPO TERNEGROZA ETDRIA LEONOR", "CAMPO TORREGROZA SILVIA", "SAMPO TORREGROZA ETDIVIA LEONOR"]


class Juez:
    """La IA que mira el renglón: contesta por la primera palabra de lo que se le pregunta."""

    def __init__(self, respuestas: dict[str, str], falla: str | None = None):
        self.respuestas, self.falla, self.preguntas = respuestas, falla, []

    def resumir(self, texto, imagen=None):
        self.preguntas.append((texto, imagen))
        clave = texto.split("\n", 1)[0].removeprefix("- ").split()[0]
        if clave == self.falla:
            raise RuntimeError("se cayó la red")
        return self.respuestas[clave]


# -- la decisión ---------------------------------------------------------------------


def test_lo_que_mira_la_ia_corrige_letras_o_confirma():
    votado = nombre_por_consenso(CAMPO)
    decision = decidir_el_nombre(votado, CAMPO, mirada="CAMPO TORREGROZA ETILVIA LEONOR")
    assert (decision.estado, decision.nombre, decision.por_la_ia) == (CORREGIDO, "CAMPO TORREGROZA ETILVIA LEONOR", True)
    # La IA lee lo mismo que se votó: queda lo votado, confirmado por la IA.
    decision = decidir_el_nombre(votado, CAMPO, mirada=votado.nombre)
    assert (decision.nombre, decision.por_la_ia) == (votado.nombre, True)
    unanime = nombre_por_consenso(["ACUNA MEZA PEDRO", "PEDRO ACUNA MEZA"])
    decision = decidir_el_nombre(unanime, ["ACUNA MEZA PEDRO"], mirada="ACUÑA MEZA PEDRO")
    assert (decision.estado, decision.por_la_ia) == (CONFIRMADO, True)


def test_lo_que_nada_confirma_va_a_revision_con_sus_lecturas():
    lecturas = ["LOPEZ GOMEZ ANA", "LOPES GOMEZ ANA"]
    votado = nombre_por_consenso(lecturas)
    # La IA dice otra persona: no se acepta, y a Revisión.
    decision = decidir_el_nombre(votado, lecturas, mirada="PEREZ GOMEZ ANA")
    assert decision.estado == A_REVISION and decision.motivo.startswith(SE_LEYO_DISTINTO)
    assert "LOPES GOMEZ ANA" in decision.motivo
    # Sin pedir Revisión, queda como se votó.
    assert decidir_el_nombre(votado, lecturas, mirada="PEREZ GOMEZ ANA", a_revision=False).estado == CONFIRMADO


def test_lo_del_operador_manda_y_sin_nombre_no_hay_dato():
    votado = nombre_por_consenso(CAMPO)
    decision = decidir_el_nombre(votado, CAMPO, del_operador="CAMPO TORREGROZA ETILVIA LEONOR")
    assert (decision.estado, decision.nombre) == (CORREGIDO, "CAMPO TORREGROZA ETILVIA LEONOR")
    assert decidir_el_nombre(nombre_por_consenso([]), []).estado == SIN_DATO


# -- el revisor ----------------------------------------------------------------------


def test_la_ia_mira_a_todos_con_sus_lecturas_y_los_candidatos_del_padron():
    padron = IndiceDelPadron([Persona("ETILVIA LEONOR CAMPO TORREGROZA", "49731465", ACTA_DE_GRADO)])
    juez = Juez({"CAMPO": "CAMPO TORREGROZA ETILVIA LEONOR", "CORTEZ": "CORTES RIVERA ESPERANZA"})
    personas = [
        PorRevisar(1, CAMPO, cedula="49731465", imagen=lambda: b"campo", pagina=23),
        # Confirmado por dos lecturas, y mal: la IA lo mira igual.
        PorRevisar(2, ["CORTEZ RIVERA ESPERANZA", "ESPERANZA CORTEZ RIVERA"], imagen=lambda: b"cortez", pagina=31),
    ]
    revisados = revisar_los_nombres(personas, padron=padron, juez=juez)
    assert revisados[1].nombre == "CAMPO TORREGROZA ETILVIA LEONOR" and revisados[1].estado == CORREGIDO
    assert revisados[1].candidatos == ("ETILVIA LEONOR CAMPO TORREGROZA",)
    assert revisados[2].nombre == "CORTES RIVERA ESPERANZA"
    assert {imagen for _, imagen in juez.preguntas} == {b"campo", b"cortez"}
    texto_de_campo = next(texto for texto, imagen in juez.preguntas if imagen == b"campo")
    assert "la misma que la ficha" in texto_de_campo
    # Lo que la pantalla de Revisión necesita.
    assert revisados[1].detalle["estado"] == "corregido" and revisados[1].detalle["pagina_de_la_ficha"] == 23


def test_lo_dudoso_se_vuelve_a_mirar_y_esa_lectura_vota():
    vistos = []

    def releer(claves):
        vistos.extend(claves)
        return {1: ["ALVAREZ LONDONO OLGA"]}

    personas = [
        PorRevisar(1, ["ALVAREZ LONDONO OLEA", "OLGA ALVAREZ LONDONO"]),
        PorRevisar(2, ["ACUNA MEZA PEDRO", "PEDRO ACUNA MEZA"]),
    ]
    revisados = revisar_los_nombres(personas, conocidas={"ALVAREZ", "OLEA", "OLGA"}, releer=releer)
    # Sólo el dudoso se vuelve a mirar.
    assert vistos == [1]
    assert revisados[1].nombre == "ALVAREZ LONDONO OLGA" and revisados[1].estado == CORREGIDO
    assert revisados[2].estado == CONFIRMADO


def test_sin_imagen_la_ia_de_texto_compara_lo_que_nada_confirma():
    corrector = SimpleNamespace(resumir=lambda texto: "VELASQUEZ CANO RAFAEL")
    revisados = revisar_los_nombres([PorRevisar(1, ["VELESEUZ CANO RAFAEL", "CANO RAFAEL"])], corrector=corrector)
    assert revisados[1].nombre == "VELASQUEZ CANO RAFAEL" and revisados[1].por_la_ia


def test_lo_que_falla_queda_votado_y_cancelar_corta():
    juez = Juez({"CAMPO": "CAMPO TORREGROZA ETILVIA LEONOR"}, falla="CAMPO")
    revisados = revisar_los_nombres([PorRevisar(1, CAMPO, imagen=lambda: b"x")], juez=juez)
    assert revisados[1].nombre == nombre_por_consenso(CAMPO).nombre and revisados[1].de_la_ia is None

    def cancelado(claves):
        raise Cancelled()

    with pytest.raises(Cancelled):
        revisar_los_nombres([PorRevisar(1, ["LOPEZ GOMEZ ANA", "LOPES GOMEZ ANA"])], releer=cancelado)


def test_lo_revisado_queda_en_el_informe_con_la_misma_forma_que_las_fechas():
    juez = Juez({"CAMPO": "CAMPO TORREGROZA ETILVIA LEONOR", "LOPEZ": "PEREZ GOMEZ ANA"})
    revisados = revisar_los_nombres(
        [
            PorRevisar(1, CAMPO, imagen=lambda: b"a", pagina=23),
            PorRevisar(2, ["LOPEZ GOMEZ ANA", "LOPES GOMEZ ANA"], imagen=lambda: b"b", pagina=5),
        ],
        juez=juez,
    )
    informe: dict = {}
    anotar_en_el_informe(informe, revisados, "UPD3859718.pdf")
    resumen = informe[CLAVE_DEL_INFORME]
    assert (resumen["revisados"], resumen[CORREGIDO], resumen[A_REVISION], resumen["preguntadas_a_la_ia"]) == (2, 1, 1, 2)
    assert informe["notices"] == ["Nombres de UPD3859718.pdf: 1 corregidos, 1 a Revisión."]
    (entrada,) = informe["review_queue"]
    assert entrada["page"] == 5 and "revisor de nombres" in entrada["reason"]
    # La habilidad que ya lleva sus dudas a la cola no las repite.
    otro: dict = {}
    anotar_en_el_informe(otro, revisados, "UPD3859718.pdf", a_la_cola=False)
    assert "review_queue" not in otro


# -- la capa común y el perfil -------------------------------------------------------


def test_el_revisor_nunca_tumba_el_trabajo():
    from resolutions.api.worker.nombres_asegurados import asegurar_los_nombres

    def se_cae():
        raise RuntimeError("sin IA")

    taller = SimpleNamespace(juez_del_nombre=se_cae, corrector_de_nombres=se_cae, control=None, settings={})
    informe: dict = {}
    revisados = asegurar_los_nombres(informe, [PorRevisar(1, CAMPO)], taller=taller, documento="x.pdf")
    # Sin IA, el voto: el nombre sale igual.
    assert revisados[1].nombre and informe[CLAVE_DEL_INFORME]["revisados"] == 1
    # Con «Solo OCR» no se prepara ninguna IA.
    from resolutions.api.worker.nombres_asegurados import jueces_del_trabajo

    assert jueces_del_trabajo(taller, de_pago=False) == (None, None)


def test_cada_habilidad_declara_su_nombre_en_su_perfil():
    from resolutions.application.perfiles_de_revision import perfil_de
    from resolutions.domain.revision_de_nombres import A_MANO

    historias = perfil_de("historias")
    assert historias.regla_del_nombre.escritura == A_MANO
    assert historias.as_dict()["nombre_de_persona"] == A_MANO
    # Una habilidad sin persona por documento no lo declara.
    assert perfil_de("correspondencia").regla_del_nombre is None


# -- fase 2: nóminas y certificados --------------------------------------------------


def test_las_nominas_y_los_certificados_usan_el_revisor_comun(tmp_path):
    """Cada hoja de la persona es una lectura; la IA mira su cabecera, y el nombre llega al PDF y a la fila."""
    from resolutions.api.worker.nominas import (
        asegurar_los_nombres_de,
        con_lo_revisado,
        nombre_del_pdf,
    )
    from resolutions.domain import nomina as n

    tulio = n.Documento(
        clase=n.PERSONA, plantilla=n.TARJETA, paginas=[3, 4],
        lecturas=[n.DatosDeLaHoja(nombre="CASTELLAR AGUA TULIO", cedula="9064111"), n.DatosDeLaHoja(nombre="CASTELLAR MEZA TULIO")],
    )
    listado = n.Documento(clase=n.PAQUETE, plantilla=None, paginas=[5])
    recortadas = []

    def recorte(documento):
        recortadas.append(documento.paginas[0])
        return b"cabecera"

    juez = Juez({"CASTELLAR": "CASTELLAR MEZA TULIO"})
    taller = SimpleNamespace(
        juez_del_nombre=lambda: juez, corrector_de_nombres=lambda: None, control=None, settings={}
    )
    documentos = [tulio, listado]
    revisados = asegurar_los_nombres_de(documentos, taller=taller, de_pago=object(), nombre="NOMINA 1975.pdf", recorte=recorte)
    # Sólo la persona: el listado no tiene nombre que asegurar.
    assert list(revisados) == [0] and recortadas == [3]
    assert tulio.nombre == "CASTELLAR MEZA TULIO" and revisados[0].estado == CORREGIDO
    assert nombre_del_pdf(1, tulio, carpeta=tmp_path).startswith("01_CASTELLAR-MEZA-TULIO")

    filas = [{"nombre": tulio.nombre, "observaciones": ""}, {"nombre": None, "observaciones": ""}]
    informe: dict = {}
    con_lo_revisado(informe, filas, revisados, "NOMINA 1975.pdf")
    assert filas[0]["revision_del_nombre"]["estado"] == "corregido"
    assert "se leyó «CASTELLAR AGUA TULIO»" in filas[0]["observaciones"]
    assert informe[CLAVE_DEL_INFORME]["revisados"] == 1


def test_nominas_y_certificados_declaran_su_nombre():
    from resolutions.application.perfiles_de_revision import perfil_de
    from resolutions.domain.revision_de_nombres import A_MANO, A_MAQUINA

    assert perfil_de("nominas").regla_del_nombre.escritura == A_MANO
    assert perfil_de("certificados").regla_del_nombre.escritura == A_MAQUINA
