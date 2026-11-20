"""La evidencia de cada valor extraído: qué se leyó, dónde, quién lo leyó y si se cree.

Lo pidió el operador el 2026-11-18, en su segunda ejecución integral: «NUNCA
INVENTAR INFORMACIÓN… No quiero que el sistema diga que encontró un parámetro:
quiero que pueda demostrar exactamente dónde, cómo y por qué lo encontró».

Y decidió dos reglas:

* **Lo que otro documento sugiere se propone, no se pone.** Un RE que sólo
  existe porque se corrigió una lectura -- la oficina a una cifra, una cifra de
  más, el RE impreso en otra hoja de la caja, el de su trámite -- es un
  *candidato*: va a la Revisión con su motivo, nunca al nombre.
* **La letra a mano, con un lector que nadie contradiga.** Un RE escrito a
  mano en un sello entra al nombre si un lector -- el OCR de pago o el modelo
  con visión -- lo lee tal cual y válido, y el otro no lee un RE distinto
  (el operador lo ajustó el mismo día: con dos lectores obligatorios, siete
  RE buenos iban a Revisión porque el otro lector no leía nada). Si los dos
  lo leen igual, queda verificado; si leen RE distintos, va a Revisión. Lo impreso
  -- la etiqueta, el PQR de la constancia, el radicado que cita una
  notificación -- basta con que una lectura lo traiga literal.

«Literal» es la única transformación permitida: las trece cifras seguidas en
la lectura, con a lo sumo un blanco, un punto o un guion entre ellas, como los
mete el escáner. Ni una letra leída por cifra, ni una cifra de más o de menos.
El prefijo «RE», que es el mismo en todos, se reconoce aunque la letra a mano
deje su E en un signo o sin trazar -- «R$2320202301449», 4100974;
«R2810202402908», 1005122; 2026-11-18 --: no cambia ninguna cifra.

Y lo leído va tal cual, también la oficina que no está en la lista de las que
radican, si dos lectores distintos la leen igual con su año (el operador ante
1005122: «si es el que está allí, es el que debes colocar tal cual»). Lo
corregido -- la oficina a una cifra de una que radica -- es sólo un candidato,
detrás de lo leído.

Aquí no se lee papel: entran las lecturas tal como las dejó cada lector.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Estado(StrEnum):
    """Lo que se sabe de un valor extraído."""

    #: Dos lectores distintos lo leyeron igual, o lo confirmó un revisor con su cita.
    VERIFICADO = "verificado"
    #: Una lectura lo trae literal en una fuente impresa: se cree.
    ENCONTRADO = "encontrado"
    #: Hay candidatos, pero ninguno con la evidencia que exige su fuente.
    REQUIERE_VALIDACION = "requiere validación"
    #: Se buscó y no hay nada que proponer.
    NO_ENCONTRADO = "no encontrado"
    #: Dos valores propios distintos, los dos con evidencia.
    CONTRADICTORIO = "contradictorio"


#: Los estados con los que el valor va al nombre y al índice.
SE_CREE = frozenset({Estado.VERIFICADO, Estado.ENCONTRADO})


@dataclass(frozen=True, slots=True)
class Candidato:
    """Un valor posible que no se pone solo: lo confirma una persona."""

    valor: str
    #: Por qué no se cree: «una sola lectura de letra a mano», «corregido: la
    #: oficina a una cifra», «el de su trámite»…
    motivo: str
    pagina: int | None = None

    def as_dict(self) -> dict:
        return {"valor": self.valor, "motivo": self.motivo, "pagina": self.pagina}


@dataclass(frozen=True, slots=True)
class Hallazgo:
    """Un parámetro de un documento con su evidencia."""

    #: «re», «fecha», «tipo» o «corte».
    parametro: str
    estado: Estado
    #: El valor normalizado que va al nombre, o ``None`` si no se cree ninguno.
    valor: str | None = None
    #: Lo que el lector dejó, tal cual.
    valor_original: str | None = None
    pagina: int | None = None
    #: El trozo de la lectura donde está, para verlo sin abrir el PDF.
    fragmento: str | None = None
    #: De dónde salió: «etiqueta impresa», «PQR de la constancia», «sello de tinta»…
    metodo: str | None = None
    #: Quién lo leyó: «capa», «tesseract», «ocr de pago», «visión».
    lectores: tuple[str, ...] = ()
    #: «alta», «media» o «baja».
    confianza: str | None = None
    candidatos: tuple[Candidato, ...] = ()
    #: Qué se intentó, cuando no se encontró.
    buscado: str | None = None
    #: Lo que dijo el verificador, si bajó el estado.
    motivo: str | None = None

    @property
    def se_cree(self) -> bool:
        return self.estado in SE_CREE

    def as_dict(self) -> dict:
        return {
            "parametro": self.parametro,
            "estado": str(self.estado),
            "valor": self.valor,
            "valor_original": self.valor_original,
            "pagina": self.pagina,
            "fragmento": self.fragmento,
            "metodo": self.metodo,
            "lectores": list(self.lectores),
            "confianza": self.confianza,
            "candidatos": [c.as_dict() for c in self.candidatos],
            "buscado": self.buscado,
            "motivo": self.motivo,
        }


# -- el RE ----------------------------------------------------------------------

#: Un RE entero, como va al nombre.
_RE_ENTERO = re.compile(r"RE\d{13}")
#: Lo que puede ir entre dos cifras de una lectura sin cambiar el valor: el
#: blanco, el punto o el guion que mete el escáner o la letra a mano.
_SEPARADOR = r"[ \t.\-]?"
#: Cuánto texto se guarda alrededor del valor, a cada lado.
ALCANCE_DEL_FRAGMENTO = 30

#: Cada lector, por la familia que lo hace independiente de otro: la relectura
#: y el renglón son Tesseract otra vez; no confirman a Tesseract.
FAMILIA_DEL_LECTOR = {
    "capa": "capa",
    "tesseract": "tesseract",
    "relectura": "tesseract",
    "renglon": "tesseract",
    "ocr de pago": "ocr de pago",
    "vision": "visión",
    "visión": "visión",
}
#: Las fuentes impresas: basta una lectura literal.
FUENTES_IMPRESAS = frozenset(
    {"etiqueta impresa", "sello impreso", "PQR de la constancia", "citado en su texto"}
)
#: Cuántos lectores distintos hacen falta para dar la letra a mano por verificada.
#: Con uno solo se cree si ningún otro lector la contradice (2026-11-18).
LECTORES_PARA_LA_LETRA_A_MANO = 2
#: El RE que el agente propone para una oficina leída a una cifra: «…: sería RE2320202301449».
#: El año de un RE que puede serlo: el número interno con «RE» delante,
#: «RE2024600387419», trae «6003».
_ANO_POSIBLE = re.compile(r"(?:199\d|20\d\d)")
_SERIA = re.compile(r"sería (RE\d{13})")


def es_re_entero(valor: str | None) -> bool:
    return bool(valor) and _RE_ENTERO.fullmatch(valor.upper()) is not None


def aparece_literal(radicado: str, texto: str | None) -> str | None:
    """El fragmento de ``texto`` donde están las trece cifras del RE seguidas, o ``None``.

    Con a lo sumo un blanco, un punto o un guion entre dos cifras, y sin otra
    cifra pegada delante ni detrás: «RE28102024102908» no trae el
    «2810202410290» que lleva dentro. Ni letras por cifras ni cifras de más.
    """
    if not es_re_entero(radicado) or not texto:
        return None
    cifras = radicado.upper()[2:]
    patron = r"(?<!\d)" + _SEPARADOR.join(cifras) + rf"(?!{_SEPARADOR}\d)"
    hallado = re.search(patron, texto)
    if hallado is None:
        return None
    inicio = max(0, hallado.start() - ALCANCE_DEL_FRAGMENTO)
    fin = min(len(texto), hallado.end() + ALCANCE_DEL_FRAGMENTO)
    # Cada renglón con su corte, « / »: unidos con un blanco, el «1 Folio» del
    # renglón de abajo parecía una cifra pegada al RE y el fragmento ya no lo
    # probaba (1004833, la prueba de humo del 2026-11-18).
    return " / ".join(" ".join(renglon.split()) for renglon in texto[inicio:fin].splitlines() if renglon.strip())


def familia(lector: str) -> str:
    return FAMILIA_DEL_LECTOR.get(lector, lector)


#: Un RE en una lectura, tal cual: «RE», a lo sumo dos signos, y trece cifras
#: con sus separadores; ni una cifra más ni una menos. La E del prefijo, que
#: la letra a mano deja a veces en un signo -- «R$2320202301449» (4100974,
#: UPD2985240 pág. 2, 2026-11-18) --: el prefijo es el mismo en todo RE y las
#: cifras siguen siendo las leídas.
#: Y la E sin trazar: «R2810202402908» (1005122).
_PREFIJO_DEL_RE = r"R(?:\W?E|[$€£&§])?"
_RE_EN_LA_LECTURA = re.compile(
    r"(?<![A-Z0-9])" + _PREFIJO_DEL_RE + r"\W{0,2}((?:\d" + _SEPARADOR + r"){12}\d)(?!" + _SEPARADOR + r"\d)"
)


def oficina_confirmada(valor: str, lecturas: Iterable[tuple[str, str]]) -> bool:
    """Si dos lectores distintos leen tal cual la oficina y el año del RE, justo detrás de su «RE».

    Para la oficina que no está en la lista de las que radican: no se corrige,
    se cree si la leen igual dos lectores (1005122, UPD3102765 pág. 1,
    2026-11-18: la visión leyó «R2810202402908» y el OCR de pago
    «RE28102024102908»; el papel dice RE2810202402908). Una oficina que lee un
    solo lector -- la visión, «RE2020202301449» en 4100974, donde el papel dice
    2320 -- es sólo un candidato.
    """
    if not es_re_entero(valor):
        return False
    cabeza = re.compile(r"(?<![A-Z0-9])" + _PREFIJO_DEL_RE + r"\W{0,2}" + _SEPARADOR.join(valor.upper()[2:10]))
    familias = {familia(lector) for lector, texto in lecturas if cabeza.search((texto or "").upper())}
    return len(familias) >= LECTORES_PARA_LA_LETRA_A_MANO


def res_en_la_lectura(texto: str | None) -> list[str]:
    """Los RE que una lectura trae tal cual, normalizados: «RE 2310 2024 03286» es RE2310202403286."""
    return [
        "RE" + re.sub(r"\D", "", hallado.group(1))
        for hallado in _RE_EN_LA_LECTURA.finditer((texto or "").upper())
    ]


@dataclass(frozen=True, slots=True)
class EvidenciaDeRE:
    """Lo que una hoja propia del documento ofrece como su RE."""

    pagina: int
    #: «etiqueta impresa», «sello impreso», «sello de tinta», «sello al pie»,
    #: «PQR de la constancia», «citado en su texto».
    fuente: str
    #: El valor que propuso quien la leyó, ya con sus correcciones si las hizo.
    propuesto: str | None
    #: Cada lectura cruda: (lector, texto).
    lecturas: tuple[tuple[str, str], ...] = ()
    #: Por qué el valor propuesto se corrigió, si lo dijo quien lo corrigió.
    correccion: str | None = None
    #: Si el RE salió de cruzar la letra a mano del sello con el RE que su
    #: trámite trae impreso (``re_impreso_que_casa``), por qué: se cree aunque
    #: ninguna lectura lo traiga tal cual (el operador, 2026-11-20).
    cruce: str | None = None


#: Lo que la letra a mano deja leer en vez de cada cifra (2026-11-20, sobre las
#: lecturas del sello de 1000690 pág. 3 y las de 4100974 y 1005122).
CONFUSIONES_DE_LA_MANO: dict[str, str] = {
    "0": "ODQU",
    "1": "IL|/T",
    "2": "Z",
    "5": "S",
    "6": "G",
    "7": "PDT",
    "8": "B",
}
_LETRAS_DE_LA_MANO = "".join(sorted(set("".join(CONFUSIONES_DE_LA_MANO.values()))))
#: Lo que cuesta, en el cruce, cada diferencia entre lo leído y lo impreso.
COSTO_DE_UNA_CONFUSION = 0.5
#: La «D» que es un «10» escrito junto: «RE23D2021…» por RE2310 2021….
COSTO_DE_LA_D_POR_10 = 0.5
COSTO_DE_OTRA_CIFRA = 1.0
#: Hasta dónde se parece lo leído a un impreso para casarlo, y cuánto más lejos
#: tiene que quedar el siguiente para que no haya duda.
DISTANCIA_PARA_CASAR = 2.0
VENTAJA_SOBRE_EL_SIGUIENTE = 1.5
#: Cuántas lecturas tienen que casar con el mismo impreso.
LECTURAS_QUE_CASAN = 2
#: Cuántas cifras de verdad trae, como poco, lo leído tras su «RE».
CIFRAS_DE_LO_LEIDO = 8
_LO_LEIDO_TRAS_EL_RE = re.compile(
    r"(?<![A-Z0-9])R(?:\W?E|[$€£&§3])\W{0,2}((?:[0-9" + re.escape(_LETRAS_DE_LA_MANO) + r"][ .\-]?){9,18})"
)


def lo_leido_tras_el_re(texto: str | None) -> list[str]:
    """Lo que cada «RE» de una lectura trae detrás, cifras y letras que la mano confunde: «23D20210565»."""
    leidos = []
    for hallado in _LO_LEIDO_TRAS_EL_RE.finditer((texto or "").upper()):
        # La barra suelta tras un blanco separa renglones («… 0565 / NIC»): no es un «1».
        token = re.sub(r"[ .\-]", "", re.split(r"[ .\-][/|]", hallado.group(1))[0])
        if sum(c.isdigit() for c in token) >= CIFRAS_DE_LO_LEIDO:
            leidos.append(token)
    return leidos


def distancia_de_la_mano(leido: str, cifras: str) -> float:
    """Cuánto se aparta lo leído a mano de las cifras de un RE impreso, con las confusiones de la letra a mano."""

    def sustituir(a: str, b: str) -> float:
        if a == b:
            return 0.0
        if not a.isdigit() and a in CONFUSIONES_DE_LA_MANO.get(b, ""):
            return COSTO_DE_UNA_CONFUSION
        return COSTO_DE_OTRA_CIFRA

    n, m = len(leido), len(cifras)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * COSTO_DE_OTRA_CIFRA
    for j in range(1, m + 1):
        d[0][j] = j * COSTO_DE_OTRA_CIFRA
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            mejor = min(
                d[i - 1][j] + COSTO_DE_OTRA_CIFRA,
                d[i][j - 1] + COSTO_DE_OTRA_CIFRA,
                d[i - 1][j - 1] + sustituir(leido[i - 1], cifras[j - 1]),
            )
            if j >= 2 and leido[i - 1] == "D" and cifras[j - 2 : j] == "10":
                mejor = min(mejor, d[i - 1][j - 2] + COSTO_DE_LA_D_POR_10)
            d[i][j] = mejor
    return d[n][m]


@dataclass(frozen=True, slots=True)
class Cruce:
    """El RE impreso de su trámite con el que casa la letra a mano de un sello."""

    valor: str
    #: Lo leído, dónde está impreso y por qué casa.
    porque: str
    #: Si se cree; si no, sólo se propone en la Revisión.
    se_cree: bool


def re_impreso_que_casa(
    lecturas: Iterable[tuple[str, str]],
    impresos: Mapping[str, Sequence[tuple[int, date | None]]],
    *,
    fecha_del_sello: date | None,
    valido: Callable[[str], str | None] | None = None,
) -> Cruce | None:
    """El RE de su trámite que la letra a mano del sello quiso escribir, si lo impreso de la caja lo dice sin duda.

    Lo dictó el operador el 2026-11-20 ante 1000690 (UPD2437824 pág. 3): doce
    lecturas del sello -- OCR de pago y visión, en tres zonas -- leen
    «RE23D20210565», «RE23D20210565P» o «RE23020210565», el «10» hecho una «D»
    y el «7» perdido, y la respuesta del 18-06-2021 dice impreso «Reclamación
    No. RE2310202105657». «Ponerlo si el agente lo cruza»:

    - lo leído tras el «RE» casa con un impreso a ``DISTANCIA_PARA_CASAR`` o
      menos, con las confusiones de la mano (``distancia_de_la_mano``), y el
      siguiente impreso queda ``VENTAJA_SOBRE_EL_SIGUIENTE`` más lejos;
    - lo dicen ``LECTURAS_QUE_CASAN`` lecturas, y ninguna casa con otro;
    - ``valido`` -- la oficina y el año del sello -- lo admite;
    - alguna hoja que lo imprime es del mismo día del sello o posterior: es su
      trámite -- la respuesta, la notificación --, no un escrito anterior.

    ``impresos`` va por RE, con las hojas que lo imprimen y su fecha. Si casa
    pero falta algo de lo demás, el impreso se propone (``se_cree=False``).
    """
    if not impresos:
        return None
    votos: dict[str, list[str]] = {}
    #: Los RE que alguna lectura trae enteros, trece cifras: si no es el
    #: impreso, la lectura lo contradice -- no lo leyó mal, leyó otro --.
    enteros: set[str] = set()
    for _lector, texto in lecturas:
        for leido in lo_leido_tras_el_re(texto):
            if leido.isdigit() and len(leido) == 13:
                enteros.add(f"RE{leido}")
            distancias = sorted((distancia_de_la_mano(leido, impreso[2:]), impreso) for impreso in impresos)
            mejor, impreso = distancias[0]
            if mejor > DISTANCIA_PARA_CASAR:
                continue
            claro = len(distancias) == 1 or distancias[1][0] >= mejor + VENTAJA_SOBRE_EL_SIGUIENTE
            votos.setdefault(impreso if claro else "?", []).append(leido)
    candidatos = [impreso for impreso in votos if impreso != "?"]
    if not candidatos:
        return None
    impreso = max(candidatos, key=lambda i: len(votos[i]))
    leidos = votos[impreso]
    hojas = impresos[impreso]
    despues = [
        (pagina, fecha) for pagina, fecha in hojas if fecha and fecha_del_sello and fecha >= fecha_del_sello
    ]
    donde = ", ".join(
        f"pág. {pagina}" + (f" del {fecha:%d-%m-%Y}" if fecha else "") for pagina, fecha in (despues or hojas)
    )
    vistos = ", ".join(f"RE{v} (×{leidos.count(v)})" for v in dict.fromkeys(leidos))
    porque = f"leído {vistos} en el sello; casa con {impreso}, impreso en la {donde}"
    faltas = []
    if len(leidos) < LECTURAS_QUE_CASAN:
        faltas.append("lo lee una sola lectura")
    if len(candidatos) > 1 or "?" in votos:
        faltas.append("otras lecturas casan con otro impreso")
    if enteros - {impreso}:
        faltas.append(f"una lectura trae entero otro RE: {', '.join(sorted(enteros - {impreso}))}")
    if not despues:
        faltas.append("ninguna hoja que lo imprime es del día del sello o posterior")
    if valido is not None and (motivo := valido(impreso)):
        faltas.append(motivo)
    if faltas:
        return Cruce(impreso, f"{porque}; sin certeza: {'; '.join(faltas)}", se_cree=False)
    return Cruce(impreso, porque, se_cree=True)


@dataclass(frozen=True, slots=True)
class _Visto:
    valor: str
    evidencia: EvidenciaDeRE
    lectores: tuple[str, ...]
    fragmento: str | None
    original: str | None


def _lectores_literales(valor: str, lecturas: Iterable[tuple[str, str]]) -> tuple[tuple[str, ...], str | None, str | None]:
    """Las familias de lectores que traen el valor literal, el primer fragmento y su lectura."""
    familias: list[str] = []
    fragmento = original = None
    for lector, texto in lecturas:
        trozo = aparece_literal(valor, texto)
        if trozo is None:
            continue
        if familia(lector) not in familias:
            familias.append(familia(lector))
        if fragmento is None:
            fragmento, original = trozo, texto
    return tuple(familias), fragmento, original


def decidir_el_re(
    evidencias: Sequence[EvidenciaDeRE],
    *,
    del_tramite: str | None = None,
    valido: Callable[[str, EvidenciaDeRE], str | None] | None = None,
    buscado: str | None = None,
) -> Hallazgo:
    """El RE del documento con su evidencia, o los candidatos que una persona confirma.

    ``evidencias`` van en el orden de sus hojas: manda la primera que se cree.
    ``valido(valor, evidencia)`` devuelve por qué un valor no puede ser un RE de
    verdad -- una oficina que no radica, un año imposible -- o ``None``.
    ``del_tramite`` es el RE de su trámite: si ninguna hoja propia lo prueba,
    es sólo un candidato.
    """
    creidos: list[_Visto] = []
    candidatos: list[Candidato] = []

    def proponer(valor: str, motivo: str, pagina: int | None) -> None:
        if not any(c.valor == valor for c in candidatos):
            candidatos.append(Candidato(valor, motivo, pagina))

    for evidencia in evidencias:
        impresa = evidencia.fuente in FUENTES_IMPRESAS
        propio = (evidencia.propuesto or "").upper()
        valores = [propio]
        if not impresa:
            # Del recorte de un sello, también lo que cada lector leyó tal cual,
            # aunque quien lo leyó lo corrigiera o lo rechazara. De la lectura
            # de una carta nunca: cita los RE de otros trámites. Lo leído antes
            # que lo corregido (1005122: «tal cual»).
            leidos = [v for _, texto in evidencia.lecturas for v in res_en_la_lectura(texto)]
            valores = [*leidos, propio] if evidencia.correccion else [propio, *leidos]
        valores = list(dict.fromkeys(v for v in valores if es_re_entero(v)))
        por_que_no = {v: (valido(v, evidencia) if valido is not None else None) for v in valores}
        # Lo que cada lector leyó tal cual y puede ser un RE: si dos lectores leen
        # RE distintos, se contradicen.
        leidos_validos = {
            v for v in valores if not por_que_no[v] and _lectores_literales(v, evidencia.lecturas)[0]
        }
        for propuesto in valores:
            lectores, fragmento, original = _lectores_literales(propuesto, evidencia.lecturas)
            if por_que_no[propuesto] and propuesto != propio:
                # Lo que un lector leyó suelto y no puede ser un RE -- el número
                # interno con «RE» delante, «RE2024600387419», un año imposible --
                # no es evidencia de nada. Si lo único extraño es la oficina, lo
                # leído se propone tal cual (1005122) y, detrás, la oficina a una
                # cifra de una que radica, si la hay (4100974, «RE2020202301449»
                # por RE2320202301449, 2026-11-18).
                motivo = str(por_que_no[propuesto])
                if "oficina" in motivo and lectores and _ANO_POSIBLE.fullmatch(propuesto[6:10]):
                    proponer(propuesto, f"leído tal cual: {motivo}", evidencia.pagina)
                if corregido := _SERIA.search(motivo):
                    proponer(corregido.group(1), f"leído {propuesto}: {motivo}", evidencia.pagina)
                continue
            if not lectores and evidencia.cruce and propuesto == propio and not por_que_no[propuesto]:
                # La letra a mano que todos los lectores leen igual de mal,
                # casada con el único RE que su trámite trae impreso.
                creidos.append(_Visto(propuesto, evidencia, ("cruce con lo impreso",), evidencia.cruce, None))
                continue
            if not lectores:
                motivo = f"corregido: {evidencia.correccion}" if evidencia.correccion else "ninguna lectura lo trae tal cual"
                proponer(propuesto, motivo, evidencia.pagina)
                continue
            if por_que_no[propuesto]:
                proponer(propuesto, str(por_que_no[propuesto]), evidencia.pagina)
                if corregido := _SERIA.search(str(por_que_no[propuesto])):
                    proponer(corregido.group(1), f"leído {propuesto}: {por_que_no[propuesto]}", evidencia.pagina)
                continue
            if not impresa and len(lectores) < LECTORES_PARA_LA_LETRA_A_MANO:
                # La letra a mano con un solo lector se cree si ningún otro lector
                # la contradice con otro RE (el operador, 2026-11-18: en siete
                # casos un lector leía el RE bueno y el otro no leía nada).
                contradicen = sorted(leidos_validos - {propuesto})
                if contradicen:
                    proponer(
                        propuesto,
                        f"los lectores leen RE distintos: {', '.join([propuesto, *contradicen])}",
                        evidencia.pagina,
                    )
                    continue
            creidos.append(_Visto(propuesto, evidencia, lectores, fragmento, original))

    if del_tramite and es_re_entero(del_tramite) and not any(v.valor == del_tramite.upper() for v in creidos):
        proponer(del_tramite.upper(), "el de su trámite: ninguna hoja suya lo trae", None)

    if creidos:
        primero = creidos[0]
        otros = [v for v in creidos[1:] if v.valor != primero.valor]
        for otro in otros:
            proponer(otro.valor, f"otro RE propio, en la pág. {otro.evidencia.pagina}", otro.evidencia.pagina)
        verificado = len(primero.lectores) >= LECTORES_PARA_LA_LETRA_A_MANO
        return Hallazgo(
            parametro="re",
            estado=Estado.VERIFICADO if verificado else Estado.ENCONTRADO,
            valor=primero.valor,
            valor_original=_lo_leido(primero.original, primero.valor),
            pagina=primero.evidencia.pagina,
            fragmento=primero.fragmento,
            metodo=primero.evidencia.fuente,
            lectores=primero.lectores,
            confianza="alta" if verificado or primero.evidencia.fuente in FUENTES_IMPRESAS else "media",
            candidatos=tuple(c for c in candidatos if c.valor != primero.valor),
        )
    if candidatos:
        return Hallazgo(
            parametro="re",
            estado=Estado.REQUIERE_VALIDACION,
            metodo="candidatos",
            confianza="baja",
            candidatos=tuple(candidatos),
            buscado=buscado,
        )
    return Hallazgo(parametro="re", estado=Estado.NO_ENCONTRADO, buscado=buscado)


def _lo_leido(texto: str | None, valor: str) -> str | None:
    """Lo que el lector escribió para ese valor, con sus blancos: «RE 2310 2024 03286»."""
    if not texto:
        return None
    cifras = valor.upper()[2:]
    hallado = re.search(r"(?:" + _PREFIJO_DEL_RE + r"\W{0,2})?" + _SEPARADOR.join(cifras), texto, re.IGNORECASE)
    return hallado.group(0) if hallado else None


def candidatos_legibles(hallazgo: Hallazgo) -> str:
    """Los candidatos dichos para el aviso de Revisión: «RE… (el de su trámite); RE… (…)»."""
    return "; ".join(f"{c.valor} ({c.motivo})" for c in hallazgo.candidatos)


# -- la fecha y el tipo -------------------------------------------------------------

#: Cuánto texto se mira alrededor de un año para encontrar la fecha entera.
_VENTANA_DE_LA_FECHA = 40
#: Dónde se busca el renglón del título: la cabeza de la hoja, en renglones cortos.
RENGLONES_DEL_TITULO = 40
LARGO_DEL_RENGLON_DEL_TITULO = 80


def fragmento_de_la_fecha(texto: str | None, fecha_iso: str) -> str | None:
    """El trozo del texto donde está escrita la fecha, tal como se escribió, o ``None``."""
    from datetime import date

    from .fechas import _normalizar, fechas_de

    if not texto or not fecha_iso:
        return None
    try:
        buscada = date.fromisoformat(fecha_iso)
    except ValueError:
        return None
    plano = " ".join(texto.split())
    for hallado in re.finditer(str(buscada.year), plano):
        inicio = max(0, hallado.start() - _VENTANA_DE_LA_FECHA)
        trozo = plano[inicio : hallado.end() + 5]
        if buscada in fechas_de(_normalizar(trozo)):
            return trozo
    return None


def hallazgo_de_la_fecha(pieza: dict, texto_de: Callable[[int], str | None]) -> Hallazgo:
    """La fecha de un documento con su evidencia, de lo que dejó su pieza (``describir_piezas``).

    ``texto_de(pagina)`` da lo leído de la hoja de su fecha: la capa, o lo que
    leyó el sello o la IA. Sin fecha, «no encontrado» con dónde se buscó.
    """
    paginas = [int(p) for p in pieza.get("pages") or []]
    if not pieza.get("fecha"):
        donde = pieza.get("donde_buscar") or paginas
        return Hallazgo(
            parametro="fecha",
            estado=Estado.NO_ENCONTRADO,
            buscado=(
                "la estructura de la hoja (sello, encabezado, firma, casillas) y la relectura con Tesseract"
                f"{' y con la IA' if pieza.get('con_ia') else ''} en las hojas {', '.join(map(str, donde))}"
            ),
        )
    pagina = pieza.get("fecha_pagina")
    fragmento = fragmento_de_la_fecha(texto_de(int(pagina)) if pagina else None, str(pieza["fecha"]))
    return Hallazgo(
        parametro="fecha",
        estado=Estado.ENCONTRADO,
        valor=str(pieza["fecha"]),
        valor_original=fragmento,
        pagina=int(pagina) if pagina else None,
        fragmento=fragmento,
        metodo=pieza.get("fecha_por"),
        lectores=(str(pieza.get("fecha_via")),) if pieza.get("fecha_via") else (),
        confianza="alta" if pieza.get("fecha_via") in ("texto", "sello", "guia") else "media",
    )


def hallazgo_del_tipo(pieza: dict, texto_de: Callable[[int], str | None]) -> Hallazgo:
    """El tipo del documento -- lo que su primera hoja dice ser -- con el renglón donde lo dice."""
    paginas = [int(p) for p in pieza.get("pages") or []]
    tipo = str(pieza.get("titulo") or pieza.get("type") or "").strip()
    if not tipo or tipo.upper() == "DOCUMENTO":
        return Hallazgo(parametro="tipo", estado=Estado.NO_ENCONTRADO, buscado="el título de su primera hoja")
    import unicodedata

    def sin_tildes(texto: str) -> str:
        return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().upper()

    primera = paginas[0] if paginas else None
    renglon = None
    palabras = [p for p in re.findall(r"[A-Z]{4,}", sin_tildes(tipo))][:2]
    # Sólo los renglones cortos de la cabeza: el título, su REF o su ASUNTO; no
    # la prosa que nombra el tipo de pasada («…para el reclamo RE…»).
    for linea in (texto_de(primera) or "").splitlines()[:RENGLONES_DEL_TITULO] if primera else ():
        plano = sin_tildes(linea)
        if len(plano.strip()) > LARGO_DEL_RENGLON_DEL_TITULO:
            continue
        if palabras and all(p in plano for p in palabras):
            renglon = " ".join(linea.split())[:120]
            break
    return Hallazgo(
        parametro="tipo",
        estado=Estado.ENCONTRADO,
        valor=tipo,
        pagina=primera,
        fragmento=renglon,
        metodo="título de su primera hoja" if renglon else "su asunto, su formato o su catálogo",
        confianza="alta" if renglon else "media",
    )


@dataclass(slots=True)
class Evidencias:
    """Los hallazgos de un trabajo, por documento (su primera hoja)."""

    por_documento: dict[int, list[Hallazgo]] = field(default_factory=dict)

    def anotar(self, primera: int, hallazgo: Hallazgo) -> None:
        self.por_documento.setdefault(primera, [])
        self.por_documento[primera] = [
            h for h in self.por_documento[primera] if h.parametro != hallazgo.parametro
        ] + [hallazgo]

    def as_dict(self) -> dict[str, list[dict]]:
        return {str(p): [h.as_dict() for h in hs] for p, hs in sorted(self.por_documento.items())}
