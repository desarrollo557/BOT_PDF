"""Cada anexo con su documento: la secuencia del PDF, y la persona que lo hace suyo.

Lo pidió el operador el 2026-11-23: «necesito que el bot tenga la habilidad de
razonar, de acuerdo al orden de secuencia en el PDF, cuál es anexo de cada
página principal… se los estás asignando a páginas que no corresponden». Y
después: «si ve que la página principal es la carta y la segunda también, pero
la tercera es una cédula que no pertenece a la hoja…», y «aproxima la unión de
páginas por razonamiento también, con IA: hay veces que los PDF fuentes vienen
con las páginas muy mal organizadas».

Lo que decidió:

- **La secuencia.** Un anexo -- la cédula, la factura, el recibo, el
  certificado, el contrato, las fotos, el estado de cuenta, y el reverso mudo
  de cualquiera de ellos -- va con la página principal anterior en el PDF, sea
  la que sea: también una constancia, una notificación o una respuesta. Los
  anexos con que empieza el PDF, antes de toda principal, van con la primera
  principal, detrás de ella.
- **La persona.** Antes de unirlo se mira de quién es: la persona de la
  cédula, el titular de la factura. Si la principal anterior la nombra, se
  queda; si no, y otro documento de la caja la nombra con prueba suficiente
  (su número, o dos pares de palabras de su nombre), va con ése: primero el
  siguiente, si no el más cercano.
- **La IA.** Si nada de eso decide -- no se lee de quién es, o ningún
  documento lo nombra --, y se eligió «OCR + IA», un juez mira el anexo y la
  lista de documentos de la caja y elige uno de ellos o ninguno. Nunca
  inventa: sólo vale una de las opciones.
- **Sin nada de eso**, la secuencia, con un aviso en la auditoría.

La fecha, el trámite y el RE no mueven un anexo. Aquí no se lee papel: entran
los textos y las identidades ya leídas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .tramites import donde_aparece_la_persona, prueba_suficiente

#: Las reglas con que un anexo queda en su documento, como se dicen en la auditoría.
CON_SU_PRINCIPAL = "con su principal anterior"
AL_INICIO = "al inicio del PDF: con la primera principal, detrás de ella"
DE_SU_PERSONA = "es de la persona que nombra ese documento"
POR_LA_IA = "lo eligió la IA entre los documentos de la caja"
CONFIRMADO_POR_LA_IA = "confirmado por la IA"
#: La constancia de reclamación va sola, sin ningún anexo (el operador,
#: 2026-11-24): lo que la sigue va con el documento siguiente, salvo que sea de
#: la persona del de antes.
TRAS_LA_CONSTANCIA = "tras la constancia, que va sin anexos: con el documento siguiente"
TRAS_LA_CONSTANCIA_AL_ANTERIOR = "tras la constancia, que va sin anexos: es de la persona del documento de antes"

#: Los avisos, informativos: el anexo se queda en su secuencia.
NO_SE_LEYO = "no se pudo leer de quién es; va con su principal anterior"
NADIE_LO_NOMBRA = "ningún documento de la caja nombra a su persona; va con su principal anterior"
NO_SE_CONFIRMO = "no se pudo confirmar de quién es; va con su principal anterior"


@dataclass(frozen=True, slots=True)
class Dueno:
    """El documento de un anexo y por qué."""

    #: El documento, por su posición en la lista de documentos.
    documento: int
    #: Una hoja principal de ese documento: la que el anexo acompaña.
    ancla: int | None
    regla: str
    pruebas: tuple[str, ...] = ()
    aviso: str | None = None
    confianza: str = "alta"
    #: Si la regla no lo pudo probar: con «OCR + IA» lo mira el juez (el
    #: operador, 2026-11-24: «que el bot sepa razonar con la ayuda de la IA
    #: cuándo una cédula pertenece a un grupo de páginas y cuándo no»).
    dudoso: bool = False


def duenos_por_secuencia(
    orden: Sequence[int],
    anexos: set[int] | frozenset[int],
    documento_de: Mapping[int, int],
    sin_anexos: set[int] | frozenset[int] = frozenset(),
) -> dict[int, tuple[int, int | None]]:
    """Por cada anexo, su documento por la secuencia y la hoja principal que lo lleva.

    ``orden`` son las hojas en el orden del PDF; ``documento_de``, el documento
    de cada hoja. La principal de un anexo es la hoja no anexo más cercana
    antes de él; si no la hay, la primera después. Un PDF hecho sólo de
    anexos los deja donde están.

    ``sin_anexos`` son los documentos que no reciben ninguno -- la constancia
    de reclamación --: el anexo que va detrás de uno va con el documento
    siguiente que sí los recibe; si no hay, con el de antes.
    """

    def recibe(q: int) -> bool:
        return q not in anexos and documento_de[q] not in sin_anexos

    salida: dict[int, tuple[int, int | None]] = {}
    for i, pagina in enumerate(orden):
        if pagina in anexos:
            antes = next((q for q in reversed(orden[:i]) if q not in anexos), None)
            if antes is not None and documento_de[antes] not in sin_anexos:
                salida[pagina] = (documento_de[antes], antes)
                continue
            despues = next((q for q in orden[i + 1 :] if recibe(q)), None)
            if despues is None:
                despues = next((q for q in reversed(orden[:i]) if recibe(q)), None)
            if despues is not None:
                salida[pagina] = (documento_de[despues], despues)
            else:
                salida[pagina] = (documento_de[antes], antes) if antes is not None else (documento_de[pagina], None)
    return salida


def dueno_tras_la_constancia(
    siguiente: tuple[int, int] | None,
    anterior: tuple[int, int] | None,
    identidad: str | None,
    principales: Mapping[int, str],
) -> Dueno:
    """El anexo detrás de una constancia: con el documento siguiente, salvo que sea de la persona del de antes.

    ``siguiente`` y ``anterior`` son ``(documento, hoja principal)`` de los
    documentos que lo pueden recibir a un lado y a otro de la constancia. Va
    con el de antes sólo si éste nombra a su persona con prueba suficiente y
    el siguiente no la nombra. Si no se sabe de quién es, o ninguno la nombra,
    es dudoso: con la IA lo mira el juez.
    """
    if siguiente is None and anterior is None:
        raise ValueError("un anexo sin ningún documento que lo reciba")
    if siguiente is None or anterior is None:
        documento, ancla = siguiente or anterior
        return Dueno(documento, ancla, TRAS_LA_CONSTANCIA)
    if identidad is None or not identidad.strip():
        return Dueno(*siguiente, TRAS_LA_CONSTANCIA, aviso=NO_SE_LEYO, confianza="media", dudoso=True)
    del_siguiente = donde_aparece_la_persona(identidad, {siguiente[0]: principales.get(siguiente[0], "")})
    del_anterior = donde_aparece_la_persona(identidad, {anterior[0]: principales.get(anterior[0], "")})
    if del_siguiente:
        return Dueno(*siguiente, TRAS_LA_CONSTANCIA, tuple(del_siguiente[siguiente[0]]))
    pruebas = del_anterior.get(anterior[0], [])
    if prueba_suficiente(pruebas):
        return Dueno(*anterior, TRAS_LA_CONSTANCIA_AL_ANTERIOR, tuple(pruebas), confianza="media")
    return Dueno(*siguiente, TRAS_LA_CONSTANCIA, tuple(pruebas), confianza="media", dudoso=True)


def dueno_razonado(
    por_secuencia: tuple[int, int | None],
    regla_de_la_secuencia: str,
    identidad: str | None,
    principales: Mapping[int, str],
    anclas: Mapping[int, int],
    *,
    siguiente: int | None = None,
    distancia: Mapping[int, int] | None = None,
) -> Dueno:
    """De quién es el anexo: la secuencia, salvo que otro documento de la caja nombre a su persona y el suyo no.

    ``identidad`` es lo que dice de quién es -- el texto de la cédula, el
    titular de la factura --, o ``None`` si no se leyó. ``principales`` es el
    texto de las hojas principales de cada documento, sin sus anexos;
    ``anclas``, una hoja principal de cada uno. ``siguiente`` es el documento
    que sigue al anexo en el PDF; ``distancia``, cuántas hojas separan al
    anexo de cada documento.
    """
    documento, ancla = por_secuencia
    quedarse = Dueno(documento, ancla, regla_de_la_secuencia)
    if len(principales) < 2:
        return quedarse
    if identidad is None or not identidad.strip():
        return Dueno(documento, ancla, regla_de_la_secuencia, aviso=NO_SE_LEYO, confianza="media", dudoso=True)
    suyas = donde_aparece_la_persona(identidad, {documento: principales.get(documento, "")}).get(documento, [])
    if prueba_suficiente(suyas):
        return Dueno(documento, ancla, regla_de_la_secuencia, tuple(suyas))
    # Que su principal no la nombre no basta para sacarlo: el pagaré, la
    # declaración y la carta de instrucciones se llenan a mano y la capa no
    # deja leer el nombre (1000186 hoja 7, 1000265 hoja 7, 4251565 hoja 3, en
    # la repetición del 2026-11-23). La regla sólo lo aparta si su principal no
    # la nombra ni a medias y nombra con su cédula a otra persona; si no, se
    # queda, pero es dudoso: con la IA lo mira el juez.
    if suyas or not nombra_a_otra_persona(identidad, principales.get(documento, "")):
        return Dueno(documento, ancla, regla_de_la_secuencia, tuple(suyas), confianza="media", dudoso=True)
    # Cada documento por separado: si dos la nombran, va al más cercano. Lo que
    # nombran todos -- el titular del servicio -- ya lo nombra también su
    # principal, y se quedó arriba.
    fuertes = {
        d: pruebas
        for d, texto in principales.items()
        if d != documento
        and prueba_suficiente(pruebas := donde_aparece_la_persona(identidad, {d: texto}).get(d, []))
    }
    if fuertes:
        distancia = distancia or {}
        elegido = (
            siguiente
            if siguiente in fuertes
            else min(fuertes, key=lambda d: (distancia.get(d, 10**6), 0 if d == siguiente else 1, d))
        )
        return Dueno(elegido, anclas.get(elegido), DE_SU_PERSONA, tuple(fuertes[elegido]), confianza="media")
    # Su principal nombra a otra persona y ningún documento a la suya.
    return Dueno(documento, ancla, regla_de_la_secuencia, aviso=NADIE_LO_NOMBRA, confianza="media", dudoso=True)


def nombra_a_otra_persona(identidad: str, principal: str) -> bool:
    """Si la principal nombra con claridad, por su cédula, a una persona que no es la del anexo.

    Sólo la cédula rotulada («C.C. 12.345.678», ``persona_de_la_hoja``): el
    nombre tras «Yo,» que deja la capa de una letra a mano -- «RVG GCIJQRDO
    ENO» por Eduardo Gutiérrez Moreno (6833800 hoja 15, 2026-11-23) -- no
    prueba que sea otra persona. Si la principal no trae cédula, no hay
    contradicción y el anexo sigue su secuencia.
    """
    from .persona_de_la_hoja import persona_de_la_hoja
    from .tramites import numeros_de

    cedulas = persona_de_la_hoja(principal).cedulas
    if not cedulas:
        return False
    numeros = numeros_de(identidad)
    return not numeros or not any(_misma_cifra_a_cifra(a, b) for a in cedulas for b in numeros)


def _misma_cifra_a_cifra(una: str, otra: str) -> bool:
    """El mismo número, con una cifra de holgura o sin sus últimas cifras."""
    una, otra = una.lstrip("0"), otra.lstrip("0")
    if len(una) == len(otra):
        return sum(a != b for a, b in zip(una, otra, strict=True)) <= 1
    corta, larga = sorted((una, otra), key=len)
    return len(corta) >= 6 and larga.startswith(corta)


# -- el juez de la IA ------------------------------------------------------------

#: Lo que se le pide al juez: mira el anexo y elige uno de los documentos.
INSTRUCCIONES_PARA_UBICAR_EL_ANEXO = (
    "Eres archivista. En la imagen está una hoja que es un anexo -- una cédula, una factura, un recibo, "
    "un certificado, un contrato, unas fotos, un estado de cuenta -- dentro de un expediente escaneado "
    "con las hojas a veces desordenadas. Te doy la lista de los documentos de ese expediente, cada uno "
    "con una letra, sus hojas y el comienzo de su texto; el que va justo antes del anexo en el PDF está "
    "marcado. Di a cuál pertenece el anexo por la persona (nombre, cédula), el titular, la dirección, el "
    "NIC, la fecha o el tema. Si nada indica con claridad otro documento, elige el que va justo antes. "
    "Contesta SÓLO la letra de la opción, o NINGUNO si no se puede saber con certeza. No inventes ni expliques."
)
#: El encabezado de las opciones en el pedido.
ENCABEZADO_DE_LAS_OPCIONES = "Los documentos del expediente"
#: Cuánto texto de cada documento va en su opción.
LARGO_DE_LA_OPCION = 320
_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def opciones_para_el_juez(documentos: Sequence[tuple[Sequence[int], str]], antes: int | None = None) -> list[str]:
    """Una opción por documento: «A) hojas 1-2: SEÑORES CARIBEMAR… REF. RECLAMO…», hasta 26.

    ``antes`` es la posición del documento que va justo antes del anexo en el
    PDF -- el de su secuencia --: va marcado para que el juez lo prefiera si
    nada indica otro.
    """
    opciones = []
    for posicion, (letra, (hojas, texto)) in enumerate(zip(_LETRAS, documentos, strict=False)):
        hojas = sorted(hojas)
        donde = f"hoja {hojas[0]}" if len(hojas) == 1 else f"hojas {hojas[0]}-{hojas[-1]}"
        marca = " (va justo antes del anexo)" if posicion == antes else ""
        opciones.append(f"{letra}) {donde}{marca}: {' '.join((texto or '').split())[:LARGO_DE_LA_OPCION]}")
    return opciones


_LA_LETRA = re.compile(r"^\W*(?:OPCI[OÓ]N\s+)?([A-Z])\b\W*", re.IGNORECASE)
_NINGUNO = re.compile(r"\bNINGUN[OA]?\b|NO\s+SE\s+PUEDE", re.IGNORECASE)


def eleccion_del_juez_de_anexos(respuesta: str | None, opciones: int) -> int | None:
    """La opción que eligió el juez, por su posición; ``None`` si no eligió una de la lista.

    Sólo una letra de las que se dieron: «B», «B)», «Opción B». «NINGUNO», una
    letra que no está o una respuesta larga que no empieza por la letra, nada.
    """
    texto = (respuesta or "").strip()
    if not texto or _NINGUNO.search(texto):
        return None
    hallado = _LA_LETRA.match(texto)
    if hallado is None:
        return None
    posicion = _LETRAS.find(hallado.group(1).upper())
    return posicion if 0 <= posicion < opciones else None


# -- la auditoría ------------------------------------------------------------------


def auditar_la_secuencia(documentos: Sequence[Sequence[int]], duenos: Mapping[int, int | None]) -> list[int]:
    """Los anexos que no quedaron con su ancla: deberían ser ninguno.

    ``duenos`` es, por cada anexo, la hoja principal con que se decidió que va.
    Se comprueba sobre los documentos finales: el anexo y su ancla, en el mismo.
    """
    de_cada_hoja = {pagina: i for i, hojas in enumerate(documentos) for pagina in hojas}
    return sorted(
        anexo
        for anexo, ancla in duenos.items()
        if ancla is not None and anexo in de_cada_hoja and de_cada_hoja.get(ancla) != de_cada_hoja[anexo]
    )
