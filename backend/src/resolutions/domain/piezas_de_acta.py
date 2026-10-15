"""Las piezas de una sesión de consejo: citación, asistencia, acta y anexos.

Un libro de actas de consejo no es una pila de actas sueltas. Cada sesión llega
como un expediente: la portada que la separa de la anterior, la citación con su
orden del día, el registro de asistencia, el acta, y detrás los soportes de lo
que se trató -- los oficios que se leyeron, los formatos de corrección de notas,
las resoluciones, los microcurrículos que se aprobaron --. Lo que se ha visto en
los libros escaneados:

* el orden de las piezas **no es fijo** -- en varias sesiones la citación y la
  asistencia van detrás del acta --, así que cada pieza se reconoce por lo que
  es y no por dónde está;
* cada pieza se reconoce por su **primera línea útil**, quitado el membrete de
  la universidad. El cuerpo del acta menciona «microcurrículos», «convocatoria»
  y numerales del orden del día («3. SOLICITUD CONVOCATORIA …»), y una palabra
  suelta en mitad de la hoja no abre nada;
* una hoja sin nada que la abra sigue la pieza anterior: es su continuación, o
  un manuscrito sin texto, y ante la duda se une.

Sólo texto: lo que el escaneo ya trae en su capa, o lo que dejó el OCR de casa.
Ninguna regla de aquí cuesta una página facturada.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

#: Los tipos de pieza, con el nombre que lleva el archivo.
PORTADA = "PORTADA"
CITACION = "CITACION"
ASISTENCIA = "REGISTRO DE ASISTENCIA"
ACTA = "ACTA"
OFICIO = "OFICIO"
FORMATO_DE_NOTAS = "FORMATO DE CORRECCION DE NOTAS"
RESOLUCION = "RESOLUCION"
MICROCURRICULO = "MICROCURRICULO"
CRONOGRAMA = "CRONOGRAMA"
CONVOCATORIA = "CONVOCATORIA"
CONSTANCIA = "CONSTANCIA"
ANEXO = "ANEXO"
#: Lo que va delante de la primera sesión del libro: no es de ninguna.
SIN_SESION = "SIN SESION"

#: Cómo se lee cada tipo en el inventario.
NOMBRES = {
    PORTADA: "Portada",
    CITACION: "Citación",
    ASISTENCIA: "Registro de asistencia",
    ACTA: "Acta",
    OFICIO: "Oficio",
    FORMATO_DE_NOTAS: "Formato de corrección de notas",
    RESOLUCION: "Resolución",
    MICROCURRICULO: "Microcurrículo",
    CRONOGRAMA: "Cronograma",
    CONVOCATORIA: "Convocatoria",
    CONSTANCIA: "Constancia",
    ANEXO: "Anexo",
    SIN_SESION: "Páginas previas",
}

#: Los que, repetidos uno detrás de otro, son el mismo documento partido. Es la
#: regla del operador -- «no quiero ver un documento dividido con dos tipos
#: iguales» -- con su excepción: dos oficios seguidos son dos cartas distintas,
#: y lo que las distingue es su propia fecha y su destinatario.
_SE_JUNTAN_SEGUIDOS = frozenset(
    {PORTADA, CITACION, ASISTENCIA, ACTA, RESOLUCION, MICROCURRICULO, CRONOGRAMA, CONVOCATORIA}
)

#: Una hoja de continuación del acta: su encabezado corrido, «Acta No. 014-2012».
#: No abre pieza nueva si el acta ya está abierta.
_ACTA_SIGUE = "ACTA (sigue)"

_SIN_TILDES = str.maketrans("áéíóúüÁÉÍÓÚÜñÑ", "aeiouuAEIOUUnN")

_MESES = (
    "ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|OCTUBRE|"
    "NOVIEMBRE|DICIEMBRE"
)

#: El membrete de la universidad y de la facultad, con lo que el OCR deja de él.
#: Se quita antes de mirar la primera línea porque es igual en todas las hojas.
_MEMBRETE = re.compile(
    r"FACULTAD\s+DE\s+ODONTOL|DEPARTAMENTO\s+ACAD|DIRECCI|TELE.?ONOS|"
    r"CARTAGENA\s*[-~]?\s*COLOMBIA|UNIVERSIDAD|FUNDADA|NIT\.?\s*\d|APROBADA\s+SEGUN|"
    r"DEL\s+6\s+DE\s+OCTUBRE|SIEMPRE\s+A\s+LA|DE\s+LOS\s+TIEMPOS|ISO\s*9001|^1827$|^DE\s+CARTAGENA$"
)

#: La portada separadora: «No. 017 - 16 DE AGOSTO DE 2012», sola en la hoja.
_PORTADA = re.compile(rf"\b\d{{1,3}}\s*[-–]\s*\d{{1,2}}\s+(?:DE\s+)?(?:{_MESES})\b")
PORTADA_MAXIMA = 80

#: El encabezado que abre el acta: «ACTA ORDINARIA No. 002», «ACTA EXTRAORDINARIA
#: No. 017», al principio del renglón.
_ACTA_ABRE = re.compile(r"^\W{0,6}ACTA\s+(?:EXTRA)?ORDINARIA\s+N", re.MULTILINE)
#: Su encabezado corrido en las hojas siguientes: «Acta No. 014-2012», «ActaNo.
#: 001-2012», «Acta No, 012-2012».
_ACTA_CORRIDA = re.compile(r"ACTA\s*N\s*[O0°º]?\s*[.,:]?\s*\d{1,3}\s*-\s*(?:19|20)\d\d")
#: La segunda hoja de un acta sin encabezado corrido: «Consejo de Facultad /
#: 23 de abril de 2012 / ORDEN DEL DÍA», con la sesión ya empezada.
_ACTA_ORDEN_DEL_DIA = re.compile(r"^CONSEJO DE FACULTAD\s*$", re.MULTILINE)

_SESION = re.compile(r"\bSESION\s+(?:EXTRA)?ORDINARIA\b")
_ASISTENCIA_PLANILLA = re.compile(r"REGISTRO\s+DE\s+ASISTENCIA|FO-?\s*DA\s*-?\s*002")
_ASISTENCIA_FIRMAS = re.compile(r"CONSEJO\s+DE\s+FACULTAD\s+(?:EXTRA)?ORDINARIO\b")
#: El formulario del Centro de Admisiones, con lo que el OCR hace de su código:
#: «FO-DO/AD-005», «FO-OO/AD-OOS», «FO-DO/AR-005».
_FORMATO_DE_NOTAS = re.compile(r"FO-?\s*[DO0]{2}\s*/\s*A[DR]\s*-?\s*[0O]{2}")
_RESOLUCION = re.compile(r"^RESOLUCI[O0]N\s+N", re.MULTILINE)

#: La fecha con que abre una carta: «Cartagena de Indias, 23 de enero de 2012»,
#: «Cartagena, Junio 25 de 2012», «Cartagena Enero 20 de 2.012».
_FECHA_DE_CARTA = re.compile(
    rf"^CARTAGENA[^\n]{{0,25}}?(?:\d{{1,2}}\s+DE\s+(?:{_MESES})|(?:{_MESES})\s+\d{{1,2}})",
    re.MULTILINE,
)
#: A quién va, o cómo saluda.
_DESTINATARIO = re.compile(
    r"^(?:DOCTORA?|DRA?\b\.?|SRA?\b\.?|SE[NÑ]OR(?:ES|A)?|HONORABLES|RESPETAD[OA]|ATT?\b\.?)",
    re.MULTILINE,
)
_SALUDO = re.compile(r"CORDIAL\s*SALUDO|RESPETAD[OA]S?\s|APRECIAD[OA]S?\s")

#: Las piezas que se reconocen por cómo empieza su primera línea.
_POR_SU_TITULO = (
    (re.compile(r"^MICROCURRICULO|^NOMBRE\s+DE.{0,4}CURSO"), MICROCURRICULO),
    (re.compile(r"^CRONOGRAMA"), CRONOGRAMA),
    (re.compile(r"^(?:CONVOCATORIA|INSCRIPCIONES\s+ABIERTAS|CALENDARIO\s+PARA)"), CONVOCATORIA),
    (re.compile(r"^A\s+QUIEN\s+(?:LE\s+)?INTERES"), CONSTANCIA),
)

#: Cuántas líneas útiles del principio de la hoja cuentan como su cabecera.
LINEAS_DE_CABECERA = 8
LINEAS_DEL_TITULO = 3


def _plano(texto: str) -> str:
    return texto.translate(_SIN_TILDES).upper()


def renglones_utiles(texto: str) -> list[str]:
    """Las líneas de la hoja sin el membrete y sin lo que el OCR deja de los bordes."""
    utiles: list[str] = []
    for renglon in _plano(texto).splitlines():
        limpio = renglon.strip()
        if sum(caracter.isalpha() for caracter in limpio) < 3:
            continue
        if _MEMBRETE.search(limpio):
            continue
        utiles.append(limpio)
    return utiles


def tipo_de_pagina(texto: str) -> str | None:
    """Qué pieza **abre** esta hoja, o ``None`` si continúa la anterior."""
    plano = _plano(texto)
    if len(plano.strip()) <= PORTADA_MAXIMA and _PORTADA.search(plano):
        return PORTADA

    utiles = renglones_utiles(texto)
    cabeza = "\n".join(utiles[:LINEAS_DE_CABECERA])
    titulo = utiles[:LINEAS_DEL_TITULO]

    # El encabezado corrido va antes que todo lo demás: una hoja del acta lista
    # a los representantes y cita oficios, y no por eso es otra cosa.
    if _ACTA_CORRIDA.search(cabeza):
        return _ACTA_SIGUE
    if _ACTA_ABRE.search(cabeza):
        return ACTA
    if _ASISTENCIA_PLANILLA.search(plano) or _ASISTENCIA_FIRMAS.search(cabeza):
        return ASISTENCIA
    if _SESION.search(cabeza) and re.search(r"\bLUGAR\b|\bFECHA\b", plano):
        return CITACION
    if _ACTA_ORDEN_DEL_DIA.search(cabeza) and "ORDEN DEL DIA" in cabeza:
        return _ACTA_SIGUE
    if _FORMATO_DE_NOTAS.search(plano):
        return FORMATO_DE_NOTAS
    if _RESOLUCION.search(cabeza) and re.search(r"POR\s+LA\s+CUAL|EN\s+USO\s+DE\s+SUS", plano):
        return RESOLUCION
    for patron, tipo in _POR_SU_TITULO:
        if any(patron.search(renglon) for renglon in titulo):
            return tipo
    if _FECHA_DE_CARTA.search(cabeza) and (
        _DESTINATARIO.search(cabeza) or _SALUDO.search(plano)
    ):
        return OFICIO
    return None


@dataclass(frozen=True, slots=True)
class PiezaDeActa:
    """Las páginas de una pieza de la sesión, contadas desde 1 en el PDF."""

    tipo: str
    desde: int
    hasta: int

    @property
    def paginas(self) -> list[int]:
        return list(range(self.desde, self.hasta + 1))

    @property
    def nombre(self) -> str:
        return NOMBRES.get(self.tipo, self.tipo.capitalize())

    @property
    def rango(self) -> str:
        """«p. 43» o «pp. 46-48»."""
        if self.desde == self.hasta:
            return f"p. {self.desde}"
        return f"pp. {self.desde}-{self.hasta}"


def piezas_de_la_sesion(paginas: Sequence[str], desde: int = 1) -> list[PiezaDeActa]:
    """Las piezas de una sesión, en el orden del PDF y sin dejar una hoja fuera.

    ``paginas`` es el texto de las hojas de la sesión y ``desde`` el número que
    tiene la primera en el PDF. Toda hoja acaba en exactamente una pieza: lo que
    no se reconoce sigue la pieza anterior, y si no hay anterior es un anexo.

    * Un formato de corrección de notas detrás de un oficio es su soporte: el
      oficio lo remite. Va con él.
    * Dos piezas seguidas del mismo tipo son una, salvo los oficios: cada carta
      lleva su fecha y su destinatario, y eso es lo que las separa.
    * El encabezado corrido del acta sigue el acta abierta; si aparece detrás de
      un anexo intercalado, vuelve a abrir el acta.
    """
    piezas: list[PiezaDeActa] = []
    for indice, texto in enumerate(paginas):
        numero = desde + indice
        tipo = tipo_de_pagina(texto)
        actual = piezas[-1] if piezas else None

        if tipo == _ACTA_SIGUE:
            tipo = None if actual is not None and actual.tipo == ACTA else ACTA
        if tipo == FORMATO_DE_NOTAS and actual is not None and actual.tipo in (
            OFICIO,
            FORMATO_DE_NOTAS,
        ):
            tipo = None
        if tipo is not None and actual is not None and actual.tipo == tipo and tipo in (
            _SE_JUNTAN_SEGUIDOS
        ):
            tipo = None

        if tipo is None:
            # La portada es una sola hoja: lo que venga detrás sin reconocerse
            # no es su continuación, es otra cosa.
            if actual is None or actual.tipo == PORTADA:
                piezas.append(PiezaDeActa(ANEXO, numero, numero))
            else:
                piezas[-1] = replace(actual, hasta=numero)
            continue
        piezas.append(PiezaDeActa(tipo, numero, numero))
    return piezas


def resumen_de_piezas(piezas: Sequence[PiezaDeActa]) -> str:
    """Las piezas de una sesión dichas en una línea, para el inventario.

    «Portada p. 42 · Citación p. 43 · Registro de asistencia p. 44 · …».
    """
    return " · ".join(f"{pieza.nombre} {pieza.rango}" for pieza in piezas)
