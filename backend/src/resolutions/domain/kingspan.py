"""La fila del inventario oficial de Kingspan que le toca a una UPD.

El inventario de Kingspan no tiene una fila por documento ni una por tramo de
numeración: tiene **una por UPD**. Medido sobre el oficial
(«1. INVENTARIO DOCUMENTAL KINGSPAN.xlsx», 1.517 filas): 1.515 UPD distintas, y
la única que repite es la que traía dos asuntos -- notas bancarias y egresos --,
con una fila por asunto.

En esa fila, «No. DOCUMENTO DESDE / HASTA» es el primer y el último documento del
paquete, y «FECHAS EXTREMAS INICIAL / FINAL» la fecha de **esos dos**, no la más
antigua y la más reciente: el oficial tiene 65 filas con la final anterior a la
inicial, que sólo salen así.

Lo que se cuenta es la serie del paquete: las notas internas de una UPD de notas
internas. Las causaciones, órdenes de servicio y documentos soporte que van
grapados detrás de cada nota también llevan número impreso, pero son sus
anexos, y meterlos en el rango lo desfiguraría.

El paquete puede llegar escaneado al revés. La UPD3869754 empieza en la nota
14368 y termina en la 14161, y su portada dice «14161 - 14368»: el primer y el
último documento son los de las puntas, ordenados de menor a mayor.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from .fechas import fechas_de

#: El número impreso junto a «Número:»: el consecutivo de la compañía, las
#: letras del tipo y el correlativo -- «001-NI-00014368». La capa de texto que
#: traen estos escaneos confunde la O con el cero y la l con el uno, y a veces
#: parte el correlativo con un espacio: «OOl-NI-00014417», «001-NI-OOO14189»,
#: «001-NI-OOOl424 6» son todos números reales de la UPD3869754.
_NUMERO = re.compile(
    r"[O0][O0C]\s*[l1I]\s*-\s*([A-Z]{2,4})\s*-\s*([0-9OoIl]{3,8})(?:[ ]([0-9OoIl]{1,3}))?"
)

#: El documento soporte en adquisiciones no sigue ese patrón: «Número DSS 1747».
_DSS = re.compile(r"\bDSS\s*(\d{2,7})\b")

#: Lo que delata que un número está en el encabezado y no citado en el cuerpo:
#: el rótulo «Número», que la capa de texto también lee mal («Ntímero»,
#: «Niimero»), así que basta con su final.
_ROTULO = re.compile(r"mero\s*[:;]?\s*$", re.IGNORECASE)

#: Cuántos caracteres antes del número se busca el rótulo.
ANTES_DEL_NUMERO = 40

#: Cuántos caracteres después del número se busca su fecha. El «Fecha:» va en
#: el renglón de abajo; más allá ya se está leyendo el cuerpo del documento.
DESPUES_DEL_NUMERO = 220

#: Cifras del correlativo como las escribe el sistema que emite estos papeles.
CIFRAS = 8

#: El nombre de cada serie como lo escribe el inventario oficial, que es el que
#: el archivo va a ordenar y buscar. Se tomó la forma más repetida de cada una.
ASUNTOS: dict[str, str] = {
    "NI": "NOTAS INTERNAS",
    "CEE": "COMPROBANTES DE EGRESO ELECTRONICO",
    "CE": "COMPROBANTES DE EGRESO",
    "CEC": "COMPROBANTES DE EGRESO CHEQUES",
    "RC": "RECIBOS DE CAJA",
    "NB": "NOTAS BANCARIAS",
    "NA": "NOTAS DE AJUSTE",
    "NR": "NOTAS Y RECLASIFICACIONES CARTERA",
    "NCE": "NOTAS CREDITO ELECTRONICA DE VENTA",
    "NCV": "NOTAS CREDITO",
    "OS": "ORDENES DE SERVICIO",
    "CCF": "COMPROBANTES CAUSACION FINANCIERA",
    "PN": "PAGOS DE NOMINA",
    "DSS": "DOCUMENTOS SOPORTE EN ADQUISICIONES",
}

#: Qué parte de los documentos de la serie principal tiene que tener otra serie
#: para ser un asunto propio y no anexos. En la UPD3869754 hay 62 notas
#: internas, 7 causaciones y 7 documentos soporte: anexos. En la UPD1923787 del
#: oficial, dos asuntos de unos 80 documentos cada uno: dos filas.
PROPORCION_DE_ASUNTO = 1 / 3

#: Y un mínimo absoluto, para que tres anexos en una UPD de seis notas no se
#: vuelvan un asunto.
MINIMO_DE_ASUNTO = 3

#: Cuántos números fuera de rango se escriben en NOTAS antes de resumir.
NUMEROS_EN_LA_NOTA = 15

NO_APLICA = "N/A"


@dataclass(frozen=True, slots=True)
class Documento:
    """Un documento numerado, donde empieza dentro del PDF."""

    pagina: int
    serie: str
    numero: int
    fecha: date | None = None

    @property
    def codigo(self) -> str:
        """El número como lo escribe el inventario: «001-NI-00014161», «DSS 1747»."""
        if self.serie == "DSS":
            return f"DSS {self.numero}"
        return f"001-{self.serie}-{self.numero:0{CIFRAS}d}"


@dataclass(frozen=True, slots=True)
class FilaKingspan:
    """Lo que el papel dice de una fila: asunto, rango, fechas y lo que no cuadra."""

    asunto: str
    desde: str = NO_APLICA
    hasta: str = NO_APLICA
    fecha_inicial: date | None = None
    fecha_final: date | None = None
    notas: str = ""
    #: Los documentos de la serie, en orden de página: dónde cortar al dividir.
    documentos: tuple[Documento, ...] = ()


def _cifras(texto: str) -> str:
    return texto.translate(str.maketrans("OoIl", "0011"))


def leer_numero(texto: str) -> tuple[str, int, int] | None:
    """El número de documento que encabeza una página: (serie, número, dónde acaba).

    Si la página trae varios, manda el que va detrás del rótulo «Número»: los
    demás son referencias del cuerpo -- el «D.Cruce» de una nota cita otros
    documentos con la misma forma --. Sin rótulo legible, el primero.
    """
    candidatos: list[tuple[bool, int, str, int, int]] = []
    for hallazgo in _NUMERO.finditer(texto):
        primero, resto = hallazgo.group(2), hallazgo.group(3) or ""
        # El espacio dentro del correlativo sólo se junta si no lo alarga más
        # de la cuenta: «OOOl424 6» es un número partido, «00014417 1» no.
        cifras = primero + resto if len(primero) + len(resto) <= CIFRAS else primero
        try:
            numero = int(_cifras(cifras))
        except ValueError:
            continue
        fin = hallazgo.end() if cifras != primero else hallazgo.end(2)
        rotulado = bool(_ROTULO.search(texto[max(0, hallazgo.start() - ANTES_DEL_NUMERO) : hallazgo.start()]))
        candidatos.append((rotulado, -hallazgo.start(), hallazgo.group(1).upper(), numero, fin))
    dss = _DSS.search(texto)
    if dss:
        rotulado = bool(_ROTULO.search(texto[max(0, dss.start() - ANTES_DEL_NUMERO) : dss.start()]))
        candidatos.append((rotulado, -dss.start(), "DSS", int(dss.group(1)), dss.end()))
    if not candidatos:
        return None
    _, _, serie, numero, fin = max(candidatos)
    return serie, numero, fin


_ANIO_MES_DIA = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")


def fecha_tras(texto: str, desde: int, *, hoy: date | None = None) -> date | None:
    """La fecha que acompaña al número: la primera que aparece detrás de él.

    Es la del «Fecha:» del encabezado. Si detrás no hay ninguna -- la capa de
    texto a veces pone la fecha antes que el número --, la primera de la página.
    """
    def primera(trozo: str) -> date | None:
        trozo = _ANIO_MES_DIA.sub(r"\3/\2/\1", trozo)
        encontradas = fechas_de(trozo, hoy=hoy)
        return encontradas[0] if encontradas else None

    return primera(texto[desde : desde + DESPUES_DEL_NUMERO]) or primera(texto)


def documento_de(texto: str, pagina: int, *, hoy: date | None = None) -> Documento | None:
    """El documento que abre esta página, o ``None`` si no abre ninguno."""
    leido = leer_numero(texto)
    if leido is None:
        return None
    serie, numero, fin = leido
    return Documento(pagina=pagina, serie=serie, numero=numero, fecha=fecha_tras(texto, fin, hoy=hoy))


def _series_con_asunto(documentos: list[Documento]) -> list[str]:
    """Las series que son asunto de la UPD, en el orden en que aparecen."""
    cuantos = Counter(documento.serie for documento in documentos)
    principal = max(cuantos.values())
    umbral = max(MINIMO_DE_ASUNTO, principal * PROPORCION_DE_ASUNTO)
    orden: list[str] = []
    for documento in documentos:
        serie = documento.serie
        if serie in orden:
            continue
        if cuantos[serie] == principal or cuantos[serie] >= umbral:
            orden.append(serie)
    return orden


def _nota_fuera_de_rango(fuera: list[Documento], desde: Documento, hasta: Documento) -> str:
    numeros = sorted(documento.numero for documento in fuera)
    lista = ", ".join(str(numero) for numero in numeros[:NUMEROS_EN_LA_NOTA])
    if len(numeros) > NUMEROS_EN_LA_NOTA:
        lista += f" y {len(numeros) - NUMEROS_EN_LA_NOTA} más"
    return (
        f"{len(numeros)} documento(s) fuera del rango {desde.numero}-{hasta.numero} "
        f"dentro de la UPD: {lista}"
    )


def filas_de(documentos: list[Documento]) -> list[FilaKingspan]:
    """Las filas del inventario de una UPD a partir de sus documentos numerados.

    ``documentos`` va en el orden de las páginas. Un número repetido -- la misma
    nota leída en dos hojas -- cuenta una vez, donde apareció primero.
    """
    unicos: list[Documento] = []
    vistos: set[tuple[str, int]] = set()
    for documento in documentos:
        clave = (documento.serie, documento.numero)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(documento)
    if not unicos:
        return []

    filas: list[FilaKingspan] = []
    for serie in _series_con_asunto(unicos):
        de_la_serie = [documento for documento in unicos if documento.serie == serie]
        desde, hasta = de_la_serie[0], de_la_serie[-1]
        if desde.numero > hasta.numero:
            # Escaneado al revés: el paquete se lee desde la otra punta.
            desde, hasta = hasta, desde
        notas: list[str] = []
        fuera = [d for d in de_la_serie if not desde.numero <= d.numero <= hasta.numero]
        if fuera:
            notas.append(_nota_fuera_de_rango(fuera, desde, hasta))
        sin_fecha = [d.codigo for d in (desde, hasta) if d.fecha is None]
        if sin_fecha:
            notas.append("no se leyó la fecha de " + " ni de ".join(dict.fromkeys(sin_fecha)))
        filas.append(
            FilaKingspan(
                asunto=ASUNTOS.get(serie, f"DOCUMENTOS {serie}"),
                desde=desde.codigo,
                hasta=hasta.codigo,
                fecha_inicial=desde.fecha,
                fecha_final=hasta.fecha,
                notas="; ".join(notas),
                documentos=tuple(de_la_serie),
            )
        )
    return filas


#: Las entidades remitente y productora van fijas: lo pidió el operador el
#: 2026-10-26, «son campos que van quemados». Es la forma con razón social que
#: más usa el oficial.
ENTIDAD = "KINGSPAN SAS"

#: Los números de acta de transferencia que el operador elige en el asistente
#: antes de procesar. Los seis primeros son los del oficial; la 169 la añadió
#: el operador el 2026-10-27.
ACTAS_DE_TRANSFERENCIA: tuple[str, ...] = ("012", "015", "070", "088", "092", "094", "169")

#: La fecha de transferencia que va con cada acta. Las seis del oficial son las
#: que trae: cada acta lleva siempre la misma en todas sus filas (la 092, el
#: 11-10-2022 en las 1.156). La de la 169 la dictó el operador el 2026-10-27.
FECHAS_DE_TRANSFERENCIA: dict[str, date] = {
    "012": date(2024, 2, 2),
    "015": date(2024, 2, 21),
    "070": date(2024, 8, 1),
    "088": date(2023, 8, 9),
    "092": date(2022, 10, 11),
    "094": date(2026, 5, 12),
    "169": date(2026, 7, 31),
}
