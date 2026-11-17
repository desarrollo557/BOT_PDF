"""El revisor de nombres: lo que se decide del nombre de la persona de un documento, sin E/S.

El operador (2026-11-17): «usar estas herramientas muy bien creadas para todas
las habilidades… centralizarlas y conectarlas a todas las habilidades para que
puedan hacer un mejor trabajo». Es el gemelo del revisor de fechas
(``domain/fechas_extremas.py``): cada habilidad declara cómo es el nombre de su
papel (``ReglaDelNombre``, en su perfil), y la decisión es una para todas.

La decisión reutiliza lo que ya se midió en las historias:

* el voto entre lecturas, palabra por palabra, donde la lista sólo desempata
  (``nombre_por_consenso``);
* lo que la IA vio en el renglón, que sólo vale como corrección de letras
  (``nombre_mirado``);
* el padrón: lo del operador manda con su cédula y lo leído en otro documento
  es candidato (``domain/padron.py``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .historia_academica import plano
from .historia_medicina import NombreVotado, corregir_con_la_ia, nombre_mirado

#: Cómo está escrito el nombre: a mano, el OCR se equivoca igual en todas sus
#: lecturas (CORTEZ en la página y en el renglón), y la IA tiene que mirarlos todos.
A_MANO = "a mano"
A_MAQUINA = "a máquina"
MIXTA = "mixta"
#: En qué orden lo escribe el papel; el FUID lo lleva como lo escribe.
APELLIDOS_PRIMERO = "apellidos"
NOMBRES_PRIMERO = "nombres"

#: Cómo quedó el nombre de una persona.
CONFIRMADO = "confirmado"
CORREGIDO = "corregido"
A_REVISION = "a revisión"
SIN_DATO = "sin dato"
#: Lo que dice la fila para la pantalla de Revisión (``revision_del_nombre.estado``).
ESTADO_DE_LA_FILA = {CONFIRMADO: "confirmado", CORREGIDO: "corregido", A_REVISION: "duda", SIN_DATO: "sin dato"}

#: El motivo de lo que va a Revisión: lo busca también quien lo saca de la cola al corregirlo.
SE_LEYO_DISTINTO = "el nombre se leyó distinto en cada zona"


@dataclass(frozen=True, slots=True)
class ReglaDelNombre:
    """Cómo es el nombre de la persona en el papel de una habilidad: lo que declara su perfil."""

    #: La clave de la fila donde queda.
    campo: str = "nombre"
    orden: str = APELLIDOS_PRIMERO
    escritura: str = A_MANO
    #: Dónde está escrito en la hoja que abre el documento, en fracción de su
    #: alto (arriba, abajo): es lo que se recorta para la Revisión y para la IA.
    zonas: tuple[tuple[float, float], ...] = ((0.02, 0.26),)
    #: Y en la hoja que sigue, si lo repite (el pie de la hoja de notas).
    zonas_de_la_siguiente: tuple[tuple[float, float], ...] = ()


def palabras(texto: str | None) -> list[str]:
    """Las palabras del nombre, en mayúsculas y sin tildes."""
    return re.findall(r"[A-Z]+", plano(texto or ""))


def dice_lo_mismo(respuesta: str | None, nombre: str | None) -> bool:
    """Si la respuesta de la IA es el mismo nombre, palabra por palabra: eso lo confirma."""
    return bool(nombre) and " ".join(palabras(respuesta)) == " ".join(palabras(nombre))


@dataclass(frozen=True, slots=True)
class Decision:
    """Lo que se decide del nombre de una persona."""

    estado: str
    nombre: str | None
    #: La IA, mirando o comparando, dijo algo que se aceptó o que lo confirmó.
    por_la_ia: bool = False
    motivo: str | None = None


def decidir_el_nombre(
    votado: NombreVotado,
    lecturas: Sequence[str | None],
    *,
    mirada: str | None = None,
    candidatos: Sequence[str] = (),
    corregida: str | None = None,
    del_operador: str | None = None,
    a_revision: bool = True,
) -> Decision:
    """El nombre que queda y su estado, con lo que dijeron las lecturas, la IA y el padrón.

    * Lo que el operador ya dio para esa persona (``del_operador``) manda: lo
      miró una persona.
    * Lo que la IA vio en el renglón (``mirada``) vale si es una corrección de
      letras de lo leído o de un candidato del padrón (``nombre_mirado``); si
      dice lo mismo, lo confirma. Sin imagen, lo que corrigió comparando las
      lecturas (``corregida``).
    * Lo que ni así se confirma, si las lecturas no dicen igual, va a Revisión
      con todas (``a_revision``).
    """
    leido = votado.leido
    final = votado.nombre
    if not final:
        return Decision(SIN_DATO, None)
    if del_operador:
        estado = CORREGIDO if del_operador != leido else CONFIRMADO
        return Decision(estado, del_operador, motivo="el nombre que dio el operador para esa cédula")
    por_la_ia = False
    if mirada is not None:
        todas = [final, *[lectura for lectura in lecturas if lectura and lectura != final], *candidatos]
        if aceptada := nombre_mirado(final, mirada, todas):
            final, por_la_ia = aceptada, True
        elif dice_lo_mismo(mirada, final):
            por_la_ia = True
    elif corregida:
        final, por_la_ia = corregida, True
    distintas = list(dict.fromkeys(lectura for lectura in lecturas if lectura))
    if a_revision and votado.sin_confirmar and not por_la_ia and len(distintas) > 1:
        leidas = " / ".join(f"«{lectura}»" for lectura in distintas)
        return Decision(A_REVISION, final, motivo=f"{SE_LEYO_DISTINTO}: {leidas}")
    estado = CORREGIDO if leido and final != leido else CONFIRMADO
    return Decision(estado, final, por_la_ia=por_la_ia)


def con_el_nombre_cambiado(texto: str | None, viejo: str | None, nuevo: str | None) -> str | None:
    """El texto -- el nombre de un PDF, un asunto -- con el nombre viejo cambiado por el nuevo; ``None`` si no lo trae.

    Cada habilidad escribe el nombre a su modo: con guiones en el PDF de una
    historia o de una nómina («03_CASTELLAR-MEZA-TULIO-9064111.pdf»), con
    espacios en el asunto («NOMINAS - CASTELLAR MEZA TULIO») o tal cual. Se
    cambia en la forma en que esté, una vez.
    """
    if not texto or not viejo or not nuevo:
        return None
    formas = [
        ("-".join(palabras(viejo)), "-".join(palabras(nuevo))),
        (" ".join(palabras(viejo)), " ".join(palabras(nuevo))),
        (viejo, nuevo),
    ]
    for antes, despues in formas:
        if antes and antes in texto:
            return texto.replace(antes, despues, 1)
    return None


def corregida_comparando(votado: NombreVotado, respuesta: str, lecturas: Sequence[str | None]) -> str | None:
    """Lo que la IA de texto corrigió comparando las lecturas, sólo en las palabras sin confirmar."""
    return corregir_con_la_ia(votado, respuesta, lecturas)
