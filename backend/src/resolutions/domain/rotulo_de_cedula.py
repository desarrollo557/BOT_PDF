"""Un número es una cédula sólo si su rótulo va justo a su izquierda.

Lo dictó el operador el 2026-11-03: «lo importante es que sepamos que al lado
izquierdo del primer número de la cédula tan siquiera estemos seguros que diga
cédula, o TI, o CC… ahora lo usaremos para estar seguros». Un número con cara
de cédula pero sin su rótulo pegado -- escrito encima del renglón, unos
renglones más abajo, con puntos de miles en la casilla de al lado -- puede ser
un folio, un teléfono, la cédula del acudiente o la del padre, y un archivo
nombrado con la cédula de otra persona es peor que uno sin ella.

Vale para todas las habilidades que leen la cédula de una persona: historias
académicas, actas de grado, diplomas.
"""

from __future__ import annotations

import re

#: El rótulo, al final de lo que va a la izquierda del número: «CÉDULA», «C.C.»,
#: «CC», «C. de C.», «CIUDADANÍA», «TARJETA», «IDENTIDAD», «Tde. Identi.»,
#: «T.I.», con su «No.», «N°» o «#» y la puntuación de en medio. Se compara en
#: mayúsculas y sin tildes.
_ROTULO = re.compile(
    r"(?:CEDULA|CIUDADANIA|TARJETA|IDENTIDAD|IDENTI|\bC\s?\.?\s?C\b|\bC\.?\s?DE\s?C\b|\bT\s?\.?\s?I\b)"
    r"[\s.:\-]*(?:DE\s+(?:CIUDADANIA|IDENTIDAD)[\s.:\-]*)?(?:(?:N[O0°º]?|#)[\s.:\-°º]*)?$"
)
#: Cuánto texto a la izquierda del número se mira.
ALCANCE = 40


def tiene_rotulo(izquierda: str) -> bool:
    """Si lo que va a la izquierda del número termina en el rótulo de una cédula o una tarjeta.

    ``izquierda`` en mayúsculas y sin tildes. «… Cédula - Tarjeta No. » sí;
    «… Firma » o «… PEREZ REYES No » no.
    """
    return bool(_ROTULO.search(izquierda[-ALCANCE:].rstrip()))
