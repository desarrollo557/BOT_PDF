"""Cuánto se fía el bot de cada costura de lo que va a entregar, sin preguntarle a nadie.

Lo pidió el operador el 2026-11-05 ante la caja 1004569 de MAGANGUE: el acuerdo
de pago se había llevado la última hoja del contrato de transacción -- la de las
cláusulas TERCERO y CUARTO y las firmas -- con la cédula de detrás, saltando la
constancia de en medio. Pidió un agente que «verifique y rectifique todo sin
importar la habilidad, haciendo valer que se cumpla cada patrón y con un margen
de error», y que «cuando un caso se salga del margen se lo envíe a la IA, la IA
lo analice y decida», gastando pocos tokens.

Esto es la parte que no cuesta nada. Cada **costura** -- dos hojas seguidas del
original -- tiene la decisión que tomó el bot, cortar o unir, y una
**confianza** en esa decisión a la luz de lo que dice el papel:

- **Contra un corte**: el texto sigue de una hoja a la otra -- la cláusula
  TERCERO detrás de la SEGUNDO, «página 3 de 3» detrás de «2 de 3» (fuerte), la
  frase partida a media línea (débil) --, o la hoja derecha está en un documento
  lejano, saltando otro de por medio (fuerte).
- **Contra una unión**: la hoja de la derecha abre documento por una regla del
  operador (fuerte), o es de otra persona en las habilidades de una persona por
  PDF (débil: la OCR cambia una cifra de la cédula).

Con **dos pruebas fuertes** que apuntan a lo mismo el error es seguro y el
revisor lo corrige solo. Con menos, la costura queda **fuera del margen** y la
decide la IA, si el operador la eligió; sin IA va a revisión. Lo demás queda
**dentro del margen**: validado sin gastar un token.

Nada aquí abre un PDF ni pregunta a un modelo: entra el texto de las hojas y
cómo quedaron repartidas, y salen las costuras con su confianza.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .foliacion_del_escrito import foliacion_del_escrito
from .sello import SELLOS_PARA_AVISAR, res_del_documento

#: Por debajo de esta confianza la costura sale del margen de error y la decide
#: la IA (o va a revisión, sin ella). Una prueba fuerte sola la deja en 0,3 y
#: una débil en 0,45: las dos quedan fuera, y es a propósito -- una prueba
#: sola es lo que tuvo el bot para equivocarse en 1004569.
MARGEN_DE_ERROR = 0.6
#: A esta confianza o menos el error es seguro -- dos pruebas fuertes que
#: apuntan a lo mismo -- y el revisor lo corrige sin preguntarle a nadie.
CERTEZA_DEL_ERROR = 0.1
#: La costura sin nada en contra.
SIN_NADA_EN_CONTRA = 0.95

#: Cuánto del principio y del final de cada hoja ve la IA. Lo justo para
#: reconocer un encabezado, una cláusula o unas firmas: la huella de una caja
#: de diez hojas cabe en unos mil quinientos tokens.
LARGO_DEL_PRINCIPIO = 320
LARGO_DEL_FINAL = 160
#: En cuántos renglones del principio se busca la cláusula con que abre una hoja.
RENGLONES_DEL_PRINCIPIO = 12

_ORDINALES = (
    "PRIMER",
    "SEGUND",
    "TERCER",
    "CUART",
    "QUINT",
    "SEXT",
    "SEPTIM",
    "OCTAV",
    "NOVEN",
    "DECIM",
)
#: «TERCERO:», «CUARTO.-», «PRIMERA -», «ARTÍCULO SEGUNDO:» al principio del
#: renglón: la cláusula de un contrato, el artículo de una resolución.
_CLAUSULA = re.compile(r"^\W{0,3}(?:ARTICULO\s+)?(" + "|".join(_ORDINALES) + r")[OA]?\s*[:.\-–]")
#: «Página 2 de 3», «Pág. 2/3».
_PAGINA_DE = re.compile(r"\bPAG(?:INA)?\.?\s*(\d{1,3})\s*(?:DE|/)\s*(\d{1,3})\b")
#: Cómo se dice cada cláusula, para el motivo que lee el operador.
_NOMBRES = ("PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO", "SEXTO", "SÉPTIMO", "OCTAVO", "NOVENO", "DÉCIMO")
#: La cédula de una persona: «C.C. No. 23.007.523», «C.C. No: 23007523»,
#: «cédula de ciudadanía No. 23007523».
_CEDULA = re.compile(
    r"(?:\bC\.?\s?C\.?|CEDULA\s+DE\s+CIUDADANIA)\s*(?:NO|N[°º])?\s*[.:]?\s*([\d][\d.\s]{5,13}\d)"
)
#: Un renglón que no es texto corrido: el membrete, un número suelto.
_CORTO = 15


class Decision(StrEnum):
    """Lo que el bot hizo con dos hojas seguidas."""

    CORTE = "corte"
    UNION = "union"


@dataclass(frozen=True, slots=True)
class Prueba:
    """Algo del papel que contradice lo que hizo el bot."""

    motivo: str
    fuerte: bool


@dataclass(frozen=True, slots=True)
class Propuesta:
    """Lo que habría que hacer si el bot se equivocó.

    ``paginas`` es el bloque que se mueve; ``hacia``, una hoja del documento al
    que iría, o ``None`` si el bloque abre su propio documento.
    """

    paginas: tuple[int, ...]
    hacia: int | None


@dataclass(frozen=True, slots=True)
class Costura:
    izquierda: int
    derecha: int
    decision: Decision
    pruebas: tuple[Prueba, ...] = ()
    propuesta: Propuesta | None = None
    #: Una regla del operador decidió esta costura y el papel la contradice: no
    #: la corrige nadie, ni la IA, y va a revisión.
    contra_una_regla: bool = False

    @property
    def confianza(self) -> float:
        """Cuánto se fía el revisor de lo que hizo el bot, de 0 a 1."""
        fuertes = sum(1 for p in self.pruebas if p.fuerte)
        debiles = len(self.pruebas) - fuertes
        if fuertes >= 2:
            return 0.05
        if fuertes == 1:
            return 0.15 if debiles else 0.3
        if debiles:
            return 0.45
        return SIN_NADA_EN_CONTRA

    @property
    def fuera_del_margen(self) -> bool:
        return self.confianza < MARGEN_DE_ERROR

    @property
    def error_seguro(self) -> bool:
        return self.confianza <= CERTEZA_DEL_ERROR and self.propuesta is not None

    @property
    def motivo(self) -> str:
        return "; ".join(p.motivo for p in self.pruebas)


def plano(texto: str) -> str:
    """Mayúsculas y sin tildes, renglón por renglón."""
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return sin_tildes.upper()


def _renglones(texto: str) -> list[str]:
    return [r.strip() for r in (texto or "").splitlines() if r.strip()]


def clausulas(texto: str) -> list[int]:
    """Las cláusulas ordinales con que empiezan renglones de la hoja, en orden: TERCERO = 3."""
    halladas = []
    for renglon in _renglones(plano(texto)):
        encontrada = _CLAUSULA.match(renglon)
        if encontrada:
            halladas.append(_ORDINALES.index(encontrada.group(1)) + 1)
    return halladas


def primera_clausula(texto: str) -> int | None:
    """La cláusula con que abre la hoja, si abre con una en sus primeros renglones."""
    for renglon in _renglones(plano(texto))[:RENGLONES_DEL_PRINCIPIO]:
        encontrada = _CLAUSULA.match(renglon)
        if encontrada:
            return _ORDINALES.index(encontrada.group(1)) + 1
    return None


def pagina_declarada(texto: str) -> tuple[int, int] | None:
    """La paginación que el papel dice de sí mismo: «Página 2 de 3» = (2, 3)."""
    encontrada = _PAGINA_DE.search(plano(texto))
    if encontrada is None:
        return None
    numero, total = int(encontrada.group(1)), int(encontrada.group(2))
    return (numero, total) if 0 < numero <= total else None


def cedulas(texto: str) -> frozenset[str]:
    """Las cédulas que nombra la hoja, sólo cifras."""
    return frozenset(
        cifras
        for hallada in _CEDULA.finditer(plano(texto))
        if 6 <= len(cifras := re.sub(r"\D", "", hallada.group(1))) <= 10
    )


def frase_partida(izquierda: str, derecha: str) -> bool:
    """Si la hoja de la izquierda termina a media frase y la derecha la retoma en minúscula."""
    final = [r for r in _renglones(izquierda) if len(r) >= _CORTO]
    principio = [r for r in _renglones(derecha) if len(r) >= _CORTO]
    if not final or not principio:
        return False
    ultimo = final[-1]
    return ultimo[-1].isalpha() and ultimo[-1].islower() and principio[0][0].islower()


def _pruebas_de_continuidad(izquierda: str, derecha: str) -> list[Prueba]:
    pruebas = []
    antes = clausulas(izquierda)
    abre = primera_clausula(derecha)
    if antes and abre is not None and abre == antes[-1] + 1:
        pruebas.append(
            Prueba(
                f"la cláusula {_NOMBRES[abre - 1]} de la hoja derecha sigue a la "
                f"{_NOMBRES[antes[-1] - 1]} de la izquierda",
                fuerte=True,
            )
        )
    de_izquierda, de_derecha = pagina_declarada(izquierda), pagina_declarada(derecha)
    if (
        de_izquierda
        and de_derecha
        and de_derecha[1] == de_izquierda[1]
        and de_derecha[0] == de_izquierda[0] + 1
    ):
        pruebas.append(
            Prueba(
                f"«página {de_derecha[0]} de {de_derecha[1]}» sigue a «página {de_izquierda[0]} de {de_izquierda[1]}»",
                fuerte=True,
            )
        )
    if frase_partida(izquierda, derecha):
        pruebas.append(Prueba("la frase sigue de una hoja a la otra", fuerte=False))
    return pruebas


def _tramos(paginas: Sequence[int]) -> list[list[int]]:
    """Las hojas de un documento en tramos seguidos: [4, 5, 7, 8] → [[4, 5], [7, 8]]."""
    tramos: list[list[int]] = []
    for pagina in sorted(paginas):
        if tramos and pagina == tramos[-1][-1] + 1:
            tramos[-1].append(pagina)
        else:
            tramos.append([pagina])
    return tramos


#: Con el segundo RE en un sello al pie, en cuántas costuras -- las que siguen a
#: la hoja del sello anterior -- puede empezar su documento: la firma con el
#: sello va al final del escrito, no donde empieza.
COSTURAS_POR_SELLO_AL_PIE = 4


def costuras_de_los_sellos(
    documentos: Sequence[Sequence[int]],
    sellos: Mapping[int, str],
    al_pie: frozenset[int] | set[int] = frozenset(),
) -> dict[int, str]:
    """Las costuras de unión que dos sellos con RE distinto en un documento ponen en duda.

    Lo pidió el operador el 2026-11-12: un PDF con dos o más sellos de RE
    distinto se avisa y lo revisa el agente. Por la hoja derecha de cada
    costura, el motivo. Desde el segundo RE (hoja ``s``):

    - con el sello en la cabeza, la costura ``s-1|s``: ahí empieza su escrito;
    - con el sello al pie, su escrito empieza antes: las costuras que siguen a
      la hoja del sello anterior, como mucho ``COSTURAS_POR_SELLO_AL_PIE``.
    """
    marcadas: dict[int, str] = {}
    for paginas in documentos:
        orden = sorted(paginas)
        suyas = set(orden)
        res = res_del_documento(orden, sellos)
        if len(res) < SELLOS_PARA_AVISAR:
            continue
        for (anterior, su_re), (hoja, otro_re) in zip(res, res[1:], strict=False):
            motivo = f"la hoja {hoja} trae el sello {otro_re} y este PDF ya lleva el {su_re} de la hoja {anterior}"
            if hoja in al_pie:
                candidatas = [p for p in orden if anterior < p <= hoja][:COSTURAS_POR_SELLO_AL_PIE]
            else:
                candidatas = [hoja]
            for derecha in candidatas:
                if derecha - 1 in suyas:
                    marcadas.setdefault(derecha, motivo)
    return marcadas


def revisar_costuras(
    documentos: Sequence[Sequence[int]],
    textos: Mapping[int, str],
    *,
    abren: frozenset[int] | set[int] = frozenset(),
    cruces: frozenset[int] | set[int] = frozenset(),
    una_persona_por_pdf: bool = False,
    sellos: Mapping[int, str] | None = None,
    al_pie: frozenset[int] | set[int] = frozenset(),
    folios: Mapping[int, int] | None = None,
) -> list[Costura]:
    """Cada costura de la entrega, con lo que el papel dice en contra.

    - ``abren``: las hojas que abren documento por una regla del operador -- el
      sello, la constancia, la carta --. Una unión que las deja dentro de otro
      documento va contra la regla; un corte delante de ellas lo decidió la
      regla, y el papel no lo deshace.
    - ``cruces``: las hojas que por regla van lejos de su documento -- la Habeas
      Data con su acuerdo de pago --. Su salto no es una prueba.
    - ``una_persona_por_pdf``: en los diplomas, las actas de grado y las
      historias, dos cédulas distintas en un PDF son dos personas.
    - ``sellos``: por hoja, el RE de su sello que se cree; ``al_pie``, las que
      lo llevan junto a la firma. Dos RE distintos en un documento son una
      prueba débil contra la unión donde empieza el segundo
      (``costuras_de_los_sellos``, 2026-11-12): la decide la IA o va a revisión.
    - ``folios``: el folio escrito a mano en la esquina de cada hoja. El que
      sigue al de la anterior es prueba fuerte contra un corte; el 1 detrás de
      un folio mayor, contra una unión (``foliacion_del_escrito``, 2026-11-12).
    """
    por_los_sellos = costuras_de_los_sellos(documentos, sellos or {}, al_pie)
    foliacion = foliacion_del_escrito(folios or {}, [p for paginas in documentos for p in paginas])
    de: dict[int, int] = {}
    for indice, paginas in enumerate(documentos):
        for pagina in paginas:
            de[pagina] = indice
    tramos_de = [_tramos(paginas) for paginas in documentos]

    def texto(pagina: int) -> str:
        return textos.get(pagina, "") or ""

    def bloque_desde(pagina: int) -> tuple[int, ...]:
        """Las hojas seguidas de su documento a partir de ésta, hasta la que abre otra cosa."""
        suyo = de[pagina]
        bloque = [pagina]
        while (siguiente := bloque[-1] + 1) in de and de[siguiente] == suyo and siguiente not in abren:
            bloque.append(siguiente)
        return tuple(bloque)

    def salta(pagina: int, *, sigue_a_la_de_delante: bool = False) -> bool:
        """Si la hoja abre un tramo de su documento separado del grueso por otro documento.

        El cruce que manda una regla -- la Habeas Data con su acuerdo -- no
        cuenta, salvo que la hoja siga por su numeración a la de delante: una
        pieza suelta del acuerdo no continúa la cláusula de otro documento. Sin
        esto, el título mal puesto que causó el error de 1004569 lo tapaba
        también aquí, porque «cruces» sale de los títulos.
        """
        if pagina in cruces and not sigue_a_la_de_delante:
            return False
        tramos = tramos_de[de[pagina]]
        if len(tramos) < 2:
            return False
        mayor = max(tramos, key=len)
        return any(t[0] == pagina for t in tramos if t is not mayor)

    costuras: list[Costura] = []
    for izquierda in sorted(de):
        derecha = izquierda + 1
        if derecha not in de:
            continue
        if de[izquierda] != de[derecha]:
            pruebas = _pruebas_de_continuidad(texto(izquierda), texto(derecha))
            if derecha in foliacion.continua:
                pruebas.append(Prueba(foliacion.motivo(derecha), fuerte=True))
            if salta(derecha, sigue_a_la_de_delante=any(p.fuerte for p in pruebas)):
                grueso = max(tramos_de[de[derecha]], key=len)
                pruebas.append(
                    Prueba(
                        f"la hoja {derecha} va con las hojas {grueso[0]}-{grueso[-1]}, "
                        "saltando otro documento de por medio",
                        fuerte=True,
                    )
                )
            contra = False
            if derecha in abren:
                # La regla manda. Una prueba débil -- la «frase que sigue»,
                # que la OCR fabrica con un membrete mal leído -- no la discute
                # (1000224 y 1000265 pág. 2, medido sobre las 26 de MAGANGUE);
                # una fuerte sí, y va a revisión.
                pruebas = [p for p in pruebas if p.fuerte]
                contra = bool(pruebas)
            costuras.append(
                Costura(
                    izquierda,
                    derecha,
                    Decision.CORTE,
                    tuple(pruebas),
                    Propuesta(bloque_desde(derecha), hacia=izquierda) if pruebas else None,
                    contra_una_regla=contra,
                )
            )
            continue
        pruebas = []
        if derecha in abren:
            pruebas.append(Prueba(f"la hoja {derecha} abre documento por una regla y quedó dentro de otro", fuerte=True))
        if una_persona_por_pdf:
            antes, despues = cedulas(texto(izquierda)), cedulas(texto(derecha))
            if antes and despues and not antes & despues:
                pruebas.append(
                    Prueba(
                        f"la hoja {derecha} es de otra persona (C.C. {', '.join(sorted(despues))})",
                        fuerte=False,
                    )
                )
        if derecha in por_los_sellos and derecha not in foliacion.continua:
            pruebas.append(Prueba(por_los_sellos[derecha], fuerte=False))
        if derecha in foliacion.abre:
            pruebas.append(Prueba(foliacion.motivo(derecha), fuerte=True))
        costuras.append(
            Costura(
                izquierda,
                derecha,
                Decision.UNION,
                tuple(pruebas),
                Propuesta(bloque_desde(derecha), hacia=None) if pruebas else None,
            )
        )
    return costuras


def huella_para_la_ia(
    pagina: int, texto: str, clase: str | None = None, marcas: str | None = None
) -> dict[str, object]:
    """Lo poco que la IA necesita de una hoja: cómo empieza, cómo termina y qué marcas trae.

    Nunca el título que le puso el bot: el error de 1004569 nació de un título
    mal puesto, y un juez que lo ve tiende a darle la razón. Sí lo que el papel
    dice de sí mismo fuera del texto (2026-11-12: «que el bot y los agentes
    tengan la capacidad de razonar»): el folio escrito a mano en la esquina y
    el sello de radicación con su RE, su fecha y sus folios (``marcas``).
    """
    limpio = " ".join((texto or "").split())
    if clase:
        huella: dict[str, object] = {"p": pagina, "es": clase, "ini": limpio[:120]}
    elif not limpio:
        huella = {"p": pagina, "es": "sin texto legible"}
    else:
        huella = {"p": pagina, "ini": limpio[:LARGO_DEL_PRINCIPIO]}
        if len(limpio) > LARGO_DEL_PRINCIPIO:
            huella["fin"] = limpio[-LARGO_DEL_FINAL:]
    if marcas:
        huella["marcas"] = marcas
    return huella
