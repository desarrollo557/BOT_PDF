"""El padrón de personas de la Universidad (2026-11-17).

El operador, ante los nombres de Enfermería mal leídos: «la idea es tener los
nombres de manera correcta». Lo que una persona corrigió manda con su cédula; lo
que el bot leyó en otro documento sólo es candidato para la IA que mira el renglón.
"""

from __future__ import annotations

import json

from resolutions.adapters.padron_jsonl import PadronEnArchivo
from resolutions.domain.padron import (
    ACTA_DE_GRADO,
    CORREGIDO_POR_EL_OPERADOR,
    DIPLOMA,
    IndiceDelPadron,
    Persona,
    cedula_de_persona,
    con_la_grafia_de,
    nombre_de_persona,
    para_la_ia,
    personas_del_informe,
)


def test_el_nombre_y_la_cedula_de_una_persona():
    assert nombre_de_persona("Campo Torregroza, Etilvia Leonor.") == "CAMPO TORREGROZA ETILVIA LEONOR"
    assert nombre_de_persona("Dueñas Suárez Irina del Carmen") == "DUENAS SUAREZ IRINA DEL CARMEN"
    # Una palabra sola, o basura, no es una persona.
    assert nombre_de_persona("REGINA") is None
    assert nombre_de_persona("") is None
    assert cedula_de_persona("49.731.465") == "49731465"
    # Ni la tarjeta de identidad de once cifras ni un número corto.
    assert cedula_de_persona("57052007471") is None
    assert cedula_de_persona("820") is None


def test_de_lo_escrito_a_maquina_y_sin_dudas():
    informe = {
        "tipo": "acta",
        "inventario_actas": [
            {"tipo": "ACTA DE GRADO", "nombre": "ETILVIA LEONOR CAMPO TORREGROZA", "cedula": "49731465"},
            # La colectiva va a mano.
            {"tipo": "ACTA DE GRADO", "nombre": "OLGA ALVAREZ LONDONO", "cedula": "22123456", "acta_colectiva": "ACTA 7"},
            # Lo que va a revisión no entra.
            {
                "tipo": "ACTA DE GRADO", "nombre": "IRINA DUENAS SUAREZ", "cedula": "45474260",
                "observaciones": "la cédula se leyó distinto: revísela",
            },
            # Sin cédula, no.
            {"tipo": "ACTA DE GRADO", "nombre": "SOFIA CAMARGO PEREZ", "cedula": None},
        ],
        "filas_del_fuid": [
            {"asunto": "JOAN BOLIVAR BARRETO LUNA - ENFERMERO", "consecutivo_inicial": "78106659", "consecutivo_final": "78106659"},
            # Una resolución no es una persona.
            {"asunto": "RESOLUCION 042 - RESUELVE", "consecutivo_inicial": "042-2005", "consecutivo_final": "042-2005"},
        ],
    }
    personas = personas_del_informe(informe, documento="UPD1.pdf", fecha="2026-11-17")
    assert [(p.nombre, p.cedula, p.fuente) for p in personas] == [
        ("ETILVIA LEONOR CAMPO TORREGROZA", "49731465", ACTA_DE_GRADO),
        ("JOAN BOLIVAR BARRETO LUNA", "78106659", DIPLOMA),
    ]
    # Las historias van a mano: su nombre es justo el que hay que asegurar.
    historia = {"tipo": "historia-academica", "inventario_actas": [
        {"tipo": "HISTORIA ACADEMICA", "nombre": "CAMPO TERNEGROZA ETDRIA LEONOR", "cedula": "49751465"},
    ]}
    assert personas_del_informe(historia) == []


def test_lo_del_operador_manda_con_la_misma_cedula():
    padron = IndiceDelPadron([
        Persona("CAMPO TORREGROSA ETILVIA LEONOR", "49731465", ACTA_DE_GRADO),
        Persona("CAMPO TORREGROZA ETILVIA LEONOR", "49731465", CORREGIDO_POR_EL_OPERADOR),
    ])
    persona = padron.por_la_cedula("CAMPO TERNEGROZA ETDRIA LEONOR", "49.731.465")
    assert persona is not None and persona.del_operador and persona.nombre == "CAMPO TORREGROZA ETILVIA LEONOR"
    # Otra persona con la misma cédula -- un número mal leído --: ninguna.
    assert padron.por_la_cedula("GOMEZ RODRIGUEZ VALIA ESTHER", "49731465") is None
    # Dos nombres distintos para una cédula, y ninguno del operador: no se sabe cuál.
    dudoso = IndiceDelPadron([
        Persona("ARIZA TORRES LASTENIA", "30768934", ACTA_DE_GRADO),
        Persona("ARIZA TORRES LASTERNIA", "30768934", DIPLOMA),
    ])
    assert dudoso.por_la_cedula("ARIZA TORRES LASTERNE", "30768934") is None


def test_las_personas_parecidas_son_candidatas_para_la_ia():
    padron = IndiceDelPadron([
        Persona("ETILVIA LEONOR CAMPO TORREGROZA", "49731465", ACTA_DE_GRADO),
        Persona("CAMPO PEREZ LUIS", "73111222", DIPLOMA),
        Persona("CAMACHO RODRIGUEZ REGINA", None, CORREGIDO_POR_EL_OPERADOR),
    ])
    assert [p.nombre for p in padron.parecidos("CAMPO TERNEGROZA ETDRIA LEONOR")] == ["ETILVIA LEONOR CAMPO TORREGROZA"]
    assert [p.nombre for p in padron.parecidos("IANACHO RODRIGUEZ REGINA")] == ["CAMACHO RODRIGUEZ REGINA"]
    assert padron.parecidos("ACUNA MEZA PEDRO") == []
    # Sus palabras desempatan el voto.
    assert {"TORREGROZA", "CAMACHO"} <= padron.palabras
    texto = para_la_ia(padron.parecidos("CAMPO TERNEGROZA ETDRIA LEONOR"), "49731465")
    assert "ETILVIA LEONOR CAMPO TORREGROZA" in texto and "la misma que la ficha" in texto


def test_la_grafia_del_padron_en_el_orden_de_la_historia():
    """El diploma va con los nombres primero; la historia, con los apellidos."""
    persona = Persona("ETILVIA LEONOR CAMPO TORREGROSA", "49731465", DIPLOMA)
    assert con_la_grafia_de("CAMPO TORREGROZA ETILVIA LEONOR", persona) == "CAMPO TORREGROSA ETILVIA LEONOR"
    # Nunca otra persona.
    assert con_la_grafia_de("GOMEZ RODRIGUEZ VALIA ESTHER", persona) is None


def test_el_padron_en_su_archivo(tmp_path):
    ruta = tmp_path / "padron.jsonl"
    padron = PadronEnArchivo(ruta)
    assert padron.personas() == []
    campo = Persona("CAMPO TORREGROZA ETILVIA LEONOR", "49731465", ACTA_DE_GRADO, "UPD1.pdf", "2026-11-17")
    assert padron.anotar([campo, campo]) == 1
    # La misma persona de la misma fuente no se repite.
    assert padron.anotar([campo]) == 0
    # Lo del operador se anota siempre: la última corrección manda.
    corregida = Persona("CAMPO TORREGROZA ETILVIA LEONOR", "49731465", CORREGIDO_POR_EL_OPERADOR)
    assert padron.anotar([corregida]) == 1 and padron.anotar([corregida]) == 1
    # Una línea rota no tumba el padrón.
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write("{esto no es JSON\n" + json.dumps({"nombre": "X"}) + "\n")
    personas = padron.personas()
    assert len(personas) == 3 and personas[0] == campo


def test_el_trabajo_terminado_anota_sus_personas(tmp_path):
    from types import SimpleNamespace

    from resolutions.api.ejecucion import _anotar_en_el_padron

    padron = PadronEnArchivo(tmp_path / "padron.jsonl")
    ctx = SimpleNamespace(padron=padron)
    job = SimpleNamespace(filename="UPD3859810.pdf")
    informe = {"tipo": "acta", "inventario_actas": [
        {"tipo": "ACTA DE GRADO", "nombre": "ETILVIA LEONOR CAMPO TORREGROZA", "cedula": "49731465"},
    ]}
    _anotar_en_el_padron(ctx, job, informe)
    (persona,) = padron.personas()
    assert (persona.nombre, persona.documento) == ("ETILVIA LEONOR CAMPO TORREGROZA", "UPD3859810.pdf")
    # Sin padrón, o con un informe que no es un informe, no pasa nada.
    _anotar_en_el_padron(SimpleNamespace(padron=None), job, informe)
    _anotar_en_el_padron(ctx, job, None)


def test_el_nombre_que_dio_el_operador_se_toma_tal_cual():
    """La historia con la cédula que el operador ya corrigió: su nombre, y fuera de la cola."""
    from resolutions.api.worker.historias import _nombres_del_operador
    from resolutions.domain.historia_academica import Expediente, Ficha

    padron = IndiceDelPadron([
        Persona("CAMPO TORREGROZA ETILVIA LEONOR", "49731465", CORREGIDO_POR_EL_OPERADOR, "UPD3859718.pdf"),
        Persona("CAMACHO RODRIGUEZ REGINA", "22111333", ACTA_DE_GRADO),
    ])
    campo = Expediente(
        paginas=[23, 24], ficha=Ficha(nombre="CAMPO TERNEGROZA ETDRIA LEONOR", cedula="49731465"),
        pagina_de_la_ficha=23, dudas=["el nombre se leyó distinto en cada zona: «A» / «B»"],
    )
    camacho = Expediente(paginas=[19, 20], ficha=Ficha(nombre="IANACHO RODRIGUEZ REGINA", cedula="22111333"))
    notas, detalle = {}, {}
    _nombres_del_operador([campo, camacho], padron, notas, detalle)
    assert campo.ficha.nombre == "CAMPO TORREGROZA ETILVIA LEONOR" and not campo.dudas
    assert "corregido por el operador" in notas[23] and detalle[23]["estado"] == "padron"
    # Lo que el bot leyó en otro documento no corrige por su cuenta.
    assert camacho.ficha.nombre == "IANACHO RODRIGUEZ REGINA"
