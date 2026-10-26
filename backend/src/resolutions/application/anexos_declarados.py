"""Retener con su escrito los anexos que el escrito enumera, y verificarlos.

Lo acordó el operador: la lista de «ANEXOS» de un escrito **retiene y
verifica**. Retiene: lo que la lista nombra y aparece detrás va en el mismo
documento que el escrito -- y, al agrupar por trámite, en su trámite --, aunque
el corte lo hubiera separado porque la hoja se titula «CONTRATO DE
ARRENDAMIENTO». Verifica: si la lista dice tres y aparecen dos, o aparece algo
que no dice, se declara.

Y nada más. La lista no parte: una hoja que no es de la lista no se separa por
eso, se queda donde la dejó el corte. Es evidencia para unir, como todo lo
demás en esta caja (ante la duda, se une).

Cómo se recorre: el documento que trae la lista se queda abierto mientras los
que le siguen sean anexos de ella. Una cédula o una hoja muda entre dos anexos
declarados no cortan la cadena -- la fotocopia de una cédula siempre soporta
algo --; pero sólo se retienen si detrás vuelve a aparecer uno de la lista. El
primer documento que abre un escrito propio, o que no es ningún anexo, cierra
la cadena.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from ..domain.anexos_declarados import (
    HOJA_MUDA,
    SIEMPRE_ANEXO,
    AnexoDeclarado,
    ListaDeAnexos,
    clase_de_la_hoja,
    corresponde,
    leer_lista_de_anexos,
    plano,
)
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.resolution_code import ResolutionCode
from ..domain.tramites import radicado_de

#: Lo que en la cabecera de una hoja dice que abre un escrito propio: a quién
#: va, bajo qué referencia, con qué radicado o consecutivo. Un documento que
#: empieza así no es el anexo de nadie, aunque traiga una factura dentro.
_ABRE = re.compile(
    r"\bSENOR(?:ES|A)?\b|\bREF\W|\bREFERENCIA\b|\bASUNTO\b|DERECHO\s+DE\s+PETICION"
    r"|RECURSO\s+DE\s+REPOSICION|\bCONSECUTIVO\b|\bCITACION\b|NOTIFICACION\s+PERSONAL"
    r"|CORDIAL\s+SALUDO|RADICADO|\bPQR\b"
)
#: Cuánto de la cabecera se mira para eso.
CABEZA_QUE_ABRE = 600


def _abre_un_escrito(texto: str) -> bool:
    return bool(_ABRE.search(plano(texto)[:CABEZA_QUE_ABRE])) or radicado_de(texto) is not None


@dataclass(frozen=True, slots=True)
class AnexoHallado:
    """Un anexo que se encontró detrás del escrito: qué es y en qué hojas."""

    clase: str
    paginas: list[int]
    #: El renglón de la lista que lo nombra, o ``None`` si no estaba en ella.
    declarado: str | None = None


@dataclass(frozen=True, slots=True)
class AnexosDelEscrito:
    """Lo que un escrito dijo que traía, contra lo que se encontró."""

    #: La hoja donde está la lista.
    pagina: int
    lista: ListaDeAnexos
    hallados: list[AnexoHallado] = field(default_factory=list)
    #: Los renglones de la lista que no aparecieron detrás.
    faltan: list[AnexoDeclarado] = field(default_factory=list)
    #: Los renglones que no se pueden buscar: copias de un reclamo, de una
    #: respuesta, o lo que no se reconoció.
    sin_verificar: list[AnexoDeclarado] = field(default_factory=list)
    #: Las hojas que se unieron al escrito por la lista, que el corte había
    #: dejado en otro documento.
    retenidas: list[int] = field(default_factory=list)
    #: Los que la lista nombra, que no aparecen y que en su mismo renglón
    #: alguien anotó a mano que no se aportaron: no faltan, no se entregaron.
    no_aportados: list[AnexoDeclarado] = field(default_factory=list)

    @property
    def declarados(self) -> int:
        return self.lista.cantidad

    @property
    def no_declarados(self) -> list[AnexoHallado]:
        return [hallado for hallado in self.hallados if hallado.declarado is None]

    def observacion(self) -> str:
        """Lo que va a las observaciones del índice: «Anexos declarados: 3…»."""
        if self.lista.sin_detalle and not self.lista.anexos:
            partes = [f"Anexos declarados sin detallar (pág. {self.pagina})"]
            if self.hallados:
                partes.append("hallados: " + ", ".join(h.clase for h in self.hallados))
            return "; ".join(partes)
        partes = [
            f"Anexos declarados: {self.declarados} (pág. {self.pagina})",
            f"hallados: {len(self.hallados) - len(self.no_declarados)}",
        ]
        if self.faltan:
            partes.append("faltan: " + ", ".join(anexo.texto for anexo in self.faltan))
        if self.no_declarados:
            partes.append("no declarados: " + ", ".join(h.clase for h in self.no_declarados))
        if self.sin_verificar:
            partes.append("sin verificar: " + ", ".join(anexo.texto for anexo in self.sin_verificar))
        if self.no_aportados:
            partes.append(
                "no aportados (anotado a mano al radicar): "
                + ", ".join(anexo.texto for anexo in self.no_aportados)
            )
        return "; ".join(partes)

    def motivo_de_revision(self) -> str | None:
        """Por qué alguien tiene que mirarlo, o ``None`` si cuadra."""
        if not self.faltan:
            return None
        return (
            f"el escrito declara {self.declarados} anexo(s) y no aparece: "
            + ", ".join(f"«{anexo.texto}»" for anexo in self.faltan)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "pagina": self.pagina,
            "encabezado": self.lista.encabezado,
            "sin_detalle": self.lista.sin_detalle,
            "declarados": [
                {"texto": a.texto, "clase": a.clase, "cantidad": a.cantidad} for a in self.lista.anexos
            ],
            "hallados": [
                {"clase": h.clase, "paginas": h.paginas, "declarado": h.declarado} for h in self.hallados
            ],
            "faltan": [a.texto for a in self.faltan],
            "sin_verificar": [a.texto for a in self.sin_verificar],
            "no_aportados": [a.texto for a in self.no_aportados],
            "retenidas": self.retenidas,
            "observacion": self.observacion(),
        }


@dataclass(frozen=True, slots=True)
class Retencion:
    """Los documentos con los anexos ya retenidos, y lo que se verificó."""

    grupos: GroupingResult
    anexos: dict[str, list[int]]
    escritos: list[AnexosDelEscrito]

    @property
    def retenidas(self) -> dict[int, int]:
        """Cada hoja retenida por una lista, con la hoja de la lista que la retuvo."""
        return {pagina: escrito.pagina for escrito in self.escritos for pagina in escrito.retenidas}

    def aviso(self) -> str | None:
        if not self.escritos:
            return None
        retenidas = sum(len(escrito.retenidas) for escrito in self.escritos)
        faltan = sum(len(escrito.faltan) for escrito in self.escritos)
        texto = f"{len(self.escritos)} escrito(s) enumeran sus anexos"
        if retenidas:
            texto += f"; se unieron {retenidas} hoja(s) a su escrito por esa lista"
        if faltan:
            texto += f"; {faltan} anexo(s) declarado(s) no aparecen y van a revisión"
        return texto


class _Pendientes:
    """Lo que la lista declaró y todavía no apareció."""

    def __init__(self, lista: ListaDeAnexos) -> None:
        self.sin_detalle = lista.sin_detalle and not lista.anexos
        self.buscables = [a for a in lista.anexos if a.clase and a.clase != "copia de reclamo o respuesta"]
        self.sin_verificar = [a for a in lista.anexos if a not in self.buscables]
        self.quedan = {id(a): a.cantidad for a in self.buscables}

    def busca(self, clase: str | None) -> AnexoDeclarado | None:
        """El renglón de la lista que es esta clase, si aún falta."""
        return next(
            (a for a in self.buscables if self.quedan[id(a)] > 0 and corresponde(a.clase, clase)),
            None,
        )

    def consume(self, anexo: AnexoDeclarado) -> None:
        self.quedan[id(anexo)] -= 1

    @property
    def vacia(self) -> bool:
        return not self.sin_detalle and all(n <= 0 for n in self.quedan.values())

    def faltan(self) -> list[AnexoDeclarado]:
        return [a for a in self.buscables if self.quedan[id(a)] > 0]


def _tramos(paginas: list[int], clases: Mapping[int, str | None]) -> list[tuple[str | None, list[int]]]:
    """Las hojas en tramos de un mismo anexo: una hoja sin clase sigue al anterior.

    El contrato de dos hojas es un anexo, no dos: su segunda hoja no dice
    «CONTRATO DE ARRENDAMIENTO», dice «DÉCIMA NOVENA: CLÁUSULA PENAL». Y el
    reverso mudo de una cédula es la misma cédula.
    """
    tramos: list[tuple[str | None, list[int]]] = []
    for pagina in paginas:
        clase = clases[pagina]
        anterior = tramos[-1][0] if tramos else None
        if tramos and (clase is None or clase == anterior or (clase == HOJA_MUDA and anterior)):
            tramos[-1][1].append(pagina)
        else:
            tramos.append((clase, [pagina]))
    return tramos


def _anota(
    tramos: list[tuple[str | None, list[int]]],
    pendientes: _Pendientes,
    hallados: list[AnexoHallado],
) -> bool:
    """Anota los anexos de unos tramos; si alguno era de la lista."""
    alguno = False
    for clase, paginas in tramos:
        if clase is None:
            continue
        anexo = pendientes.busca(clase)
        if anexo is not None:
            pendientes.consume(anexo)
            hallados.append(AnexoHallado(clase, list(paginas), declarado=anexo.texto))
            alguno = True
        elif pendientes.sin_detalle and clase != HOJA_MUDA:
            hallados.append(AnexoHallado(clase, list(paginas)))
            alguno = True
        elif clase in SIEMPRE_ANEXO or clase == HOJA_MUDA:
            hallados.append(AnexoHallado(clase, list(paginas)))
    return alguno


def retener_anexos(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
    *,
    abren: set[int] | frozenset[int] = frozenset(),
) -> Retencion:
    """Une a cada escrito los documentos que su lista de anexos nombra.

    ``anexos`` son las hojas que el corte ya marcó como anexo, por código de
    documento: se reindexan con la unión. ``abren`` son las hojas que abren un
    documento sí o sí -- un sello, una etiqueta de envío --: no se unen a nadie.

    Y la hoja que trae la lista **cierra** su escrito: si el corte la dejó
    abriendo un documento y ella no abre nada -- ni sello, ni encabezado, ni
    radicado --, es la última hoja del escrito anterior y vuelve a él. En
    UPD2326319 la hoja 3 -- «NOTIFICACIONES… ANEXO: Certificado de defunción,
    Factura NIC…, Denuncia por hurto» -- salía como un documento aparte con los
    anexos detrás, separada de la petición de las hojas 1 y 2.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    # La hoja con sello o con la etiqueta de LECTA abre su documento aunque
    # parezca un soporte: nunca se mueve.
    clases = {
        pagina: None if pagina in abren else clase_de_soporte(textos.get(pagina, "") or "")
        for grupo in grupos.groups
        for pagina in grupo.page_numbers
    }
    listas = {
        pagina: leer_lista_de_anexos(textos.get(pagina, "") or "")
        for grupo in grupos.groups
        for pagina in grupo.page_numbers
    }
    documentos = list(grupos.groups)
    salida: list[PageGroup] = []
    escritos: list[AnexosDelEscrito] = []
    i = 0
    while i < len(documentos):
        grupo = documentos[i]
        con_lista = [(p, listas[p]) for p in grupo.page_numbers if listas[p] is not None]
        if not con_lista:
            salida.append(grupo)
            i += 1
            continue
        primera = grupo.page_numbers[0]
        if (
            salida
            and con_lista[0][0] == primera
            and primera not in abren
            and not _abre_un_escrito(textos.get(primera, "") or "")
        ):
            # La hoja de la lista cierra el escrito anterior: vuelve a él.
            anterior = salida.pop()
            grupo = PageGroup(
                code=anterior.code,
                page_numbers=anterior.page_numbers + grupo.page_numbers,
                title=anterior.title,
                kind=anterior.kind,
                fecha=anterior.fecha,
            )
            suyos = anexos.pop(documentos[i].code.value, [])
            if suyos:
                anexos.setdefault(anterior.code.value, []).extend(suyos)
            documentos[i] = grupo
        # La última lista del documento es la que mira hacia delante: lo que
        # trae detrás. Las anteriores -- un escrito que enumera en «PRUEBAS» y
        # otra vez en «ANEXOS» -- son la misma promesa.
        pagina, lista = con_lista[-1]
        pendientes = _Pendientes(lista)
        hallados: list[AnexoHallado] = []
        # Lo que ya está dentro del documento, detrás de la lista.
        _anota(
            _tramos([p for p in grupo.page_numbers if p > pagina], clases),
            pendientes,
            hallados,
        )
        # Y lo que viene en los documentos siguientes, mientras sean anexos.
        unidos: list[PageGroup] = []
        en_espera: list[tuple[PageGroup, list[AnexoHallado]]] = []
        j = i + 1
        while j < len(documentos) and not pendientes.vacia:
            siguiente = documentos[j]
            primera = siguiente.page_numbers[0]
            if primera in abren:
                # Un sello o una etiqueta: ese documento es otro.
                break
            if clases[primera] is None and _abre_un_escrito(textos.get(primera, "") or ""):
                break
            if any(listas[p] for p in siguiente.page_numbers):
                # Otro escrito con su propia lista: lo suyo es suyo.
                break
            suyos: list[AnexoHallado] = []
            de_la_lista = _anota(_tramos(siguiente.page_numbers, clases), pendientes, suyos)
            if de_la_lista:
                for espera, sus_hallados in en_espera:
                    unidos.append(espera)
                    hallados.extend(sus_hallados)
                en_espera = []
                unidos.append(siguiente)
                hallados.extend(suyos)
            elif suyos and all(h.clase in SIEMPRE_ANEXO or h.clase == HOJA_MUDA for h in suyos):
                # Una cédula suelta entre anexos: espera a ver si detrás vuelve
                # la lista. Si no vuelve, se queda donde estaba.
                en_espera.append((siguiente, suyos))
            else:
                break
            j += 1

        retenidas = [p for unido in unidos for p in unido.page_numbers]
        if retenidas:
            grupo = PageGroup(
                code=grupo.code,
                page_numbers=grupo.page_numbers + retenidas,
                title=grupo.title,
                kind=grupo.kind,
                fecha=grupo.fecha,
            )
            propios = anexos.setdefault(grupo.code.value, [])
            for unido in unidos:
                anexos.pop(unido.code.value, None)
            propios.extend(retenidas)
            anexos[grupo.code.value] = sorted(set(propios))
        salida.append(grupo)
        escritos.append(
            AnexosDelEscrito(
                pagina=pagina,
                lista=lista,
                hallados=hallados,
                faltan=pendientes.faltan(),
                sin_verificar=pendientes.sin_verificar,
                retenidas=retenidas,
            )
        )
        i = i + 1 + len(unidos)

    if len(salida) < len(documentos):
        salida, anexos = _renumerar(salida, anexos)
    return Retencion(
        grupos=GroupingResult(
            groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)
        ),
        anexos=anexos,
        escritos=escritos,
    )


def _renumerar(
    grupos: list[PageGroup], anexos: dict[str, list[int]]
) -> tuple[list[PageGroup], dict[str, list[int]]]:
    """01, 02, 03… otra vez, si los documentos se numeraban por su puesto.

    El número de orden va delante del nombre del archivo y del índice; tras
    unir el contrato a su escrito, la carpeta saltaba del 01 al 03 y parecía
    que faltaba un archivo.
    """
    # «01», o «01 RE3110202030638» por trámite: se renumera el puesto y se
    # conserva el radicado. Sin esto la caja por trámite saltaba del 02 al 04
    # (UPD2326321).
    partes = [re.match(r"^(\d+)(.*)$", grupo.code.value) for grupo in grupos]
    if not all(partes):
        return grupos, anexos
    ancho = len(partes[0].group(1)) if partes else 2
    nuevos: list[PageGroup] = []
    renombrados: dict[str, list[int]] = {}
    for puesto, (grupo, parte) in enumerate(zip(grupos, partes, strict=True), start=1):
        resto = parte.group(2)
        valor = f"{puesto:0{ancho}d}{resto}"
        if grupo.code.value in anexos:
            renombrados[valor] = anexos[grupo.code.value]
        nuevos.append(
            PageGroup(
                code=ResolutionCode(value=valor, raw=grupo.code.raw if resto.strip() else valor),
                page_numbers=grupo.page_numbers,
                title=grupo.title,
                kind=grupo.kind,
                fecha=grupo.fecha,
            )
        )
    return nuevos, renombrados


# -- la cédula y la factura nunca van solas ----------------------------------------

#: Lo que nunca es un documento por sí mismo: la fotocopia de una cédula y la
#: factura (o su estado de cuenta). Lo dictó el operador sin excepciones: «una
#: cédula nunca podrá ir sola en el inventario o en la división, siempre será
#: acompañada o inventariada dentro del PDF de la página anterior».
SOPORTES = frozenset({"documento de identidad", "factura"})

#: Los demás soportes que tampoco abren un documento -- revisando la caja
#: 108C000033 salían como documentos propios: el certificado de tradición
#: partido hoja por hoja aunque todas llevan el mismo PIN, el contrato de
#: arrendamiento, el certificado catastral, los comprobantes de pago --. Se
#: reconocen sólo en la cabecera de la hoja: un escrito que cita la
#: «matrícula inmobiliaria» en su cuerpo no es un certificado.
SOPORTES_DE_CABEZA = frozenset(
    {
        "certificado de tradición",
        "certificado catastral",
        "contrato de arrendamiento",
        "comprobante de pago",
        "escritura pública",
        "certificado de existencia",
        "fotografías",
    }
)
#: Cuánto texto es la cabecera de una hoja, para esos soportes.
CABEZA_DEL_SOPORTE = 700


def clase_de_soporte(texto: str) -> str | None:
    """La clase de soporte de una hoja, si es un soporte; la muda, si es muda."""
    clase = clase_de_la_hoja(texto)
    if clase in SOPORTES or clase == HOJA_MUDA:
        return clase
    if clase in SOPORTES_DE_CABEZA and clase_de_la_hoja(texto[:CABEZA_DEL_SOPORTE]) == clase:
        return clase
    return None


@dataclass(frozen=True, slots=True)
class SoportesUnidos:
    """Los documentos después de devolver cada soporte a su anterior."""

    grupos: GroupingResult
    anexos: dict[str, list[int]]
    #: Las hojas que se movieron, con la hoja del documento al que se unieron.
    movidas: dict[int, int] = field(default_factory=dict)

    def aviso(self) -> str | None:
        if not self.movidas:
            return None
        return (
            f"{len(self.movidas)} hoja(s) de soporte (cédula, factura, certificado, contrato…) "
            "que el corte dejaba aparte se unieron al documento anterior: un soporte nunca es "
            "un documento por sí mismo"
        )


def _soporte_que_abre(paginas: list[int], clases: Mapping[int, str | None]) -> list[int]:
    """Las hojas de soporte con que empieza un documento, con sus reversos mudos."""
    tramo: list[int] = []
    for pagina in paginas:
        clase = clases[pagina]
        if (clase is not None and clase != HOJA_MUDA) or (tramo and clase == HOJA_MUDA):
            tramo.append(pagina)
        else:
            break
    return tramo


def unir_soportes(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
    *,
    solo_si_queda_solo: bool = False,
    abren: set[int] | frozenset[int] = frozenset(),
) -> SoportesUnidos:
    """Devuelve cada cédula y cada factura al documento de la página anterior.

    Un documento que **empieza** por una cédula o una factura empieza mal: esas
    hojas -- y el reverso mudo que las siga -- pasan al final del documento
    anterior, y lo que quede detrás se queda donde estaba. Si no queda nada, el
    documento desaparece. El primero de la caja no tiene anterior: lo suyo se
    une al documento siguiente, que es el único que lo puede acompañar.

    ``solo_si_queda_solo`` es para los trámites: ahí un trámite que empieza por
    una cédula puede estar bien -- la comprobación la llevó al trámite que
    nombra a esa persona --, así que sólo se mueve el trámite hecho entero de
    soportes, que es justo el que iría solo.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    # La hoja con sello o con la etiqueta de LECTA abre su documento aunque
    # parezca un soporte: nunca se mueve.
    clases = {
        pagina: None if pagina in abren else clase_de_soporte(textos.get(pagina, "") or "")
        for grupo in grupos.groups
        for pagina in grupo.page_numbers
    }
    salida: list[PageGroup] = []
    movidas: dict[int, int] = {}
    pendientes: list[int] = []  # lo del primer documento, a la espera del siguiente
    for grupo in grupos.groups:
        paginas = pendientes + list(grupo.page_numbers)
        if pendientes:
            anexos.setdefault(grupo.code.value, []).extend(pendientes)
            pendientes = []
        soporte = _soporte_que_abre([p for p in paginas if p in grupo.page_numbers], clases)
        if solo_si_queda_solo and len(soporte) < len(grupo.page_numbers):
            soporte = []
        resto = [p for p in paginas if p not in soporte]
        if soporte and salida:
            anterior = salida[-1]
            salida[-1] = PageGroup(
                code=anterior.code,
                page_numbers=anterior.page_numbers + soporte,
                title=anterior.title,
                kind=anterior.kind,
                fecha=anterior.fecha,
            )
            suyos = anexos.setdefault(anterior.code.value, [])
            suyos.extend(soporte)
            for pagina in soporte:
                movidas[pagina] = anterior.page_numbers[0]
        elif soporte and not resto:
            # El primero de la caja, todo soporte: espera al siguiente.
            pendientes = soporte
            anexos.pop(grupo.code.value, None)
            continue
        else:
            resto = paginas
        if not resto:
            anexos.pop(grupo.code.value, None)
            continue
        if resto == list(grupo.page_numbers):
            salida.append(grupo)
        else:
            salida.append(
                PageGroup(
                    code=grupo.code,
                    page_numbers=resto,
                    title=grupo.title,
                    kind=grupo.kind,
                    fecha=grupo.fecha,
                )
            )
            propios = [p for p in anexos.get(grupo.code.value, []) if p in resto]
            if propios:
                anexos[grupo.code.value] = propios
            else:
                anexos.pop(grupo.code.value, None)
    if pendientes:
        # Una caja hecha sólo de soportes: no hay a quién unirlos.
        salida.append(PageGroup(code=grupos.groups[0].code, page_numbers=pendientes))
    anexos = {codigo: sorted(set(paginas)) for codigo, paginas in anexos.items() if paginas}
    if len(salida) < len(grupos.groups):
        salida, anexos = _renumerar(salida, anexos)
    return SoportesUnidos(
        grupos=GroupingResult(
            groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)
        ),
        anexos=anexos,
        movidas=movidas,
    )


# -- y un documento nunca se llama como su anexo -----------------------------------

#: Los tipos del catálogo que nombran un soporte. Un documento de la caja que
#: no empieza por uno no puede llamarse así: el catálogo lo dice cuando el
#: escrito menciona «identificado con CC No.» y la OCR le rompió el «REF:».
TIPOS_DE_SOPORTE = frozenset(
    {"DOCUMENTO DE IDENTIDAD", "FACTURA", "ESTADO DE CUENTA DEL SERVICIO", "RECIBO"}
)
#: Lo que la cabecera de un escrito dice de sí mismo, para cuando el catálogo
#: sólo ve el soporte. En orden: el recurso cita la petición que recurre.
_TIPO_DEL_ESCRITO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RECURSO DE REPOSICION", re.compile(r"RECURSO\s+DE\s+REPOSICION|REC\W?REPOSICION")),
    ("DERECHO DE PETICION", re.compile(r"DERECHO\s+DE\s+PETICI")),
    ("RECLAMO", re.compile(r"\bR[CE]CLAMO\b|\bRECLAMACION\b")),
)
#: Cuánto de la cabecera se mira.
CABEZA_DEL_ESCRITO = 1500
#: El tipo de lo que nadie reconoció.
SIN_TIPO = "DOCUMENTO"


def nombrar_sin_soporte(grupos: GroupingResult, textos: Mapping[int, str]) -> GroupingResult:
    """Quita el nombre de un soporte al documento que no es ese soporte.

    Se fija el tipo sólo en esos documentos; los demás siguen sin él y los
    clasifica la entrega como siempre.
    """
    from .clasificacion import tipo_de

    def texto_de(pagina: int) -> str:
        return textos.get(pagina, "") or ""

    salida: list[PageGroup] = []
    for grupo in grupos.groups:
        tipo = grupo.kind or tipo_de(grupo.page_numbers, texto_de)
        primera = grupo.page_numbers[0]
        if tipo not in TIPOS_DE_SOPORTE or clase_de_la_hoja(texto_de(primera)) in SOPORTES:
            salida.append(grupo)
            continue
        propias = [
            p for p in grupo.page_numbers if clase_de_la_hoja(texto_de(p)) not in (*SOPORTES, HOJA_MUDA)
        ]
        nuevo = tipo_de(propias, texto_de) if propias else None
        if nuevo is None or nuevo in TIPOS_DE_SOPORTE:
            cabeza = plano(texto_de(primera))[:CABEZA_DEL_ESCRITO]
            nuevo = next((nombre for nombre, patron in _TIPO_DEL_ESCRITO if patron.search(cabeza)), SIN_TIPO)
        salida.append(
            PageGroup(
                code=grupo.code,
                page_numbers=grupo.page_numbers,
                title=grupo.title,
                kind=nuevo,
                fecha=grupo.fecha,
            )
        )
    return GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs))


# -- el acuerdo de pago es un solo documento -----------------------------------------


def unir_el_acuerdo_de_pago(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
    *,
    abren: set[int] | frozenset[int] = frozenset(),
    cruzan: set[int] | frozenset[int] = frozenset(),
) -> tuple[GroupingResult, dict[str, list[int]], set[int]]:
    """Junta en un documento las piezas seguidas de un acuerdo de pago.

    Lo decidió el operador ante UPD2326302: los pagarés, sus cartas de
    instrucciones, el reconocimiento de deuda y el simulador de la financiación
    -- de la hoja 5 a la 13, con la cédula del deudor -- son un solo documento,
    «RECONOCIMIENTO DE DEUDA Y ACUERDO DE PAGO», y no cinco. Ninguna pieza lleva
    sello ni RE: es lo que la empresa le hace firmar al usuario, no un escrito
    radicado. Un sello o una etiqueta de envío cortan la racha.

    Y se lleva lo que se firmó con él (lo dictó el operador el 2026-10-22 ante
    UPD3102729: «la Ley Habeas Data siempre irá anexada a su respectivo
    reconocimiento de deuda y propuesta de acuerdo de pago… este documento
    parece ser uno solo»): la autorización de Habeas Data. Lo que abre su
    propio documento -- un sello, una carta del cliente -- corta.

    Las constancias de PQR de esa misma visita ya **no** entran: el 2026-10-26
    el operador dictó que «una constancia de reclamación siempre va sola», y
    sobre la misma UPD3102729 eligió las constancias de las hojas 2 a 5 aparte
    del acuerdo.

    Y es **un solo acuerdo por PDF** cuando hay un solo reconocimiento (lo
    dictó el operador el 2026-10-26): sus pagarés -- «Pagaré No. 1000265 2» y
    «… 3» -- y la Habeas Data van juntos aunque haya otros documentos en medio.
    En UPD3102729 la Habeas Data es la hoja 1 y el acuerdo va de la 6 a la 14:
    el PDF del acuerdo es 1, 6-14. Con varios reconocimientos, cada uno es su
    acuerdo y la Habeas Data suelta va con el más cercano.

    ``cruzan`` son las hojas que abren su documento pero no cortan el acuerdo:
    la constancia, la notificación y la respuesta que quedan en medio. Lo que
    sí lo corta es lo demás que abre -- un sello, una etiqueta de envío, la
    carta de un cliente --: es otro escrito radicado, y el pagaré de antes no
    es de este acuerdo.

    Devuelve los documentos, sus anexos y las hojas del acuerdo.
    """
    from ..domain.asunto_del_documento import (
        ACUERDO_DE_PAGO,
        LEY_HABEAS_DATA,
        PIEZAS_DEL_ACUERDO,
        titulo_del_documento,
    )
    from ..domain.fechas import fecha_de_la_pagina

    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}

    def es_pieza(grupo: PageGroup) -> bool:
        primera = grupo.page_numbers[0]
        return primera not in abren and titulo_del_documento(textos.get(primera, "") or "") in PIEZAS_DEL_ACUERDO

    def es_habeas(grupo: PageGroup) -> bool:
        primera = grupo.page_numbers[0]
        return primera not in abren and titulo_del_documento(textos.get(primera, "") or "") == LEY_HABEAS_DATA

    def tiene_reconocimiento(grupo: PageGroup) -> bool:
        return any(
            titulo_del_documento(textos.get(p, "") or "") == ACUERDO_DE_PAGO for p in grupo.page_numbers
        )

    salida: list[PageGroup] = []
    del_acuerdo: set[int] = set()
    racha: list[PageGroup] = []

    def cerrar() -> None:
        if not racha:
            return
        reconocimiento = any(
            titulo_del_documento(textos.get(p, "") or "") == ACUERDO_DE_PAGO for g in racha for p in g.page_numbers
        )
        if len(racha) == 1 and not reconocimiento:
            salida.append(racha[0])
        else:
            primero = racha[0]
            paginas = [p for g in racha for p in g.page_numbers]
            propios = [p for g in racha for p in anexos.pop(g.code.value, [])]
            salida.append(
                PageGroup(code=primero.code, page_numbers=paginas, title=primero.title, kind=ACUERDO_DE_PAGO)
            )
            if propios:
                anexos[primero.code.value] = propios
        del_acuerdo.update(p for g in racha for p in g.page_numbers)
        racha.clear()

    for grupo in grupos.groups:
        if es_pieza(grupo):
            racha.append(grupo)
        else:
            cerrar()
            salida.append(grupo)
    cerrar()

    # Lo que se firmó con el acuerdo, pegado a él por arriba o por abajo.
    def fecha_del_acuerdo(grupo: PageGroup):
        for p in grupo.page_numbers:
            texto = textos.get(p, "") or ""
            if titulo_del_documento(texto) == ACUERDO_DE_PAGO:
                return fecha_de_la_pagina(texto)
        return None

    def va_con_el_acuerdo(grupo: PageGroup, fecha) -> bool:
        primera = grupo.page_numbers[0]
        if primera in abren or grupo.kind == ACUERDO_DE_PAGO:
            return False
        return es_habeas(grupo)

    i = 0
    while i < len(salida):
        acuerdo = salida[i]
        if acuerdo.kind != ACUERDO_DE_PAGO:
            i += 1
            continue
        fecha = fecha_del_acuerdo(acuerdo)
        desde, hasta = i, i
        while desde > 0 and va_con_el_acuerdo(salida[desde - 1], fecha):
            desde -= 1
        while hasta + 1 < len(salida) and va_con_el_acuerdo(salida[hasta + 1], fecha):
            hasta += 1
        if (desde, hasta) != (i, i):
            juntos = salida[desde : hasta + 1]
            primero = juntos[0]
            paginas = [p for g in juntos for p in g.page_numbers]
            propios = [p for g in juntos for p in anexos.pop(g.code.value, [])]
            # Lo que no era pieza del acuerdo va como su anexo.
            propios += [p for g in juntos if g.kind != ACUERDO_DE_PAGO for p in g.page_numbers]
            salida[desde : hasta + 1] = [
                PageGroup(code=primero.code, page_numbers=paginas, title=primero.title, kind=ACUERDO_DE_PAGO)
            ]
            anexos[primero.code.value] = sorted(set(propios))
            del_acuerdo.update(paginas)
            i = desde
        i += 1

    # Un solo acuerdo por PDF cuando hay un solo reconocimiento, con la Habeas
    # Data aunque no esté pegada; con varios, la Habeas Data suelta va con el
    # acuerdo más cercano.
    acuerdos = [k for k, g in enumerate(salida) if g.kind == ACUERDO_DE_PAGO]
    if acuerdos:
        sueltas = [
            k for k, g in enumerate(salida) if g.kind != ACUERDO_DE_PAGO and (es_habeas(g) or es_pieza(g))
        ]
        con_reconocimiento = [k for k in acuerdos if tiene_reconocimiento(salida[k])]

        def cortado(desde: int, hasta: int) -> bool:
            """Si entre los dos hay un documento que corta el acuerdo."""
            lo, hi = min(desde, hasta), max(desde, hasta)
            return any(
                salida[x].page_numbers[0] in abren and salida[x].page_numbers[0] not in cruzan
                for x in range(lo + 1, hi)
            )

        if len(con_reconocimiento) <= 1:
            principal = con_reconocimiento[0] if con_reconocimiento else acuerdos[0]
            candidatos = {k: principal for k in acuerdos + sueltas if k != principal}
        else:

            def mas_cercano(k: int) -> int:
                centro = salida[k].page_numbers[0]
                return min(con_reconocimiento, key=lambda a: min(abs(p - centro) for p in salida[a].page_numbers))

            candidatos = {k: mas_cercano(k) for k in sueltas}
            candidatos.update({k: mas_cercano(k) for k in acuerdos if k not in con_reconocimiento})
        destinos = {
            k: d for k, d in candidatos.items() if es_habeas(salida[k]) or not cortado(k, d)
        }
        if destinos:
            juntos: dict[int, list[int]] = {}
            for origen, destino in destinos.items():
                juntos.setdefault(destino, []).append(origen)
            nueva: list[PageGroup] = []
            for k, grupo in enumerate(salida):
                if k in destinos:
                    continue
                if k in juntos:
                    miembros = [grupo, *(salida[o] for o in juntos[k])]
                    paginas = sorted({p for g in miembros for p in g.page_numbers})
                    propios = [p for g in miembros for p in anexos.pop(g.code.value, [])]
                    # La Habeas Data va como anexo del acuerdo; los pagarés son sus piezas.
                    propios += [p for g in miembros if es_habeas(g) for p in g.page_numbers]
                    unido = PageGroup(
                        code=grupo.code, page_numbers=paginas, title=grupo.title, kind=ACUERDO_DE_PAGO, fecha=grupo.fecha
                    )
                    if propios:
                        anexos[unido.code.value] = sorted(set(propios))
                    del_acuerdo.update(paginas)
                    nueva.append(unido)
                else:
                    nueva.append(grupo)
            # El acuerdo se queda en el puesto de sus pagarés, no en el de la
            # Habeas Data que se le unió desde arriba: lo que viene detrás del
            # reconocimiento -- la cédula, la autorización -- se une después al
            # documento de delante, y ése tiene que ser el acuerdo y no la
            # constancia que quedó en medio (1000483 págs. 12-15, 1001381 pág. 9).
            salida = nueva
    # Ninguna pieza suelta (lo dictó el operador el 2026-10-22: «ningún pagaré
    # puede ir suelto, siempre anexado a un reconocimiento de deuda»): el pagaré
    # o la carta de instrucciones sola va con el acuerdo de al lado y, si no hay
    # ninguno, con el documento de antes -- o el de después, si es el primero --.
    i = 0
    while len(salida) > 1 and i < len(salida):
        suelta = salida[i]
        if suelta.kind == ACUERDO_DE_PAGO or not es_pieza(suelta):
            i += 1
            continue
        siguiente = salida[i + 1] if i + 1 < len(salida) else None
        con_el_siguiente = i == 0 or (siguiente is not None and siguiente.kind == ACUERDO_DE_PAGO)
        j = i + 1 if con_el_siguiente else i - 1
        # Nunca con un formulario que va solo -- la constancia, la notificación,
        # la respuesta --: con el otro vecino, o se queda como su acuerdo
        # (1000186: el pagaré sin reconocimiento detrás de una constancia).
        if salida[j].page_numbers[0] in cruzan:
            otro = i - 1 if j == i + 1 else i + 1
            if 0 <= otro < len(salida) and salida[otro].page_numbers[0] not in cruzan:
                j, con_el_siguiente = otro, otro == i + 1
            else:
                salida[i] = replace(suelta, kind=ACUERDO_DE_PAGO)
                del_acuerdo.update(suelta.page_numbers)
                i += 1
                continue
        destino = salida[j]
        paginas = (
            list(suelta.page_numbers) + list(destino.page_numbers)
            if con_el_siguiente
            else list(destino.page_numbers) + list(suelta.page_numbers)
        )
        primero = suelta if con_el_siguiente else destino
        unido = PageGroup(
            code=primero.code, page_numbers=paginas, title=destino.title, kind=destino.kind, fecha=destino.fecha
        )
        propios = anexos.pop(suelta.code.value, []) + anexos.pop(destino.code.value, []) + list(suelta.page_numbers)
        if destino.kind != ACUERDO_DE_PAGO:
            # Con un documento que no es el acuerdo: su nombre es el de ese
            # documento, y sus hojas dejan de ser «del acuerdo».
            del_acuerdo.difference_update(suelta.page_numbers)
        lo, hi = min(i, j), max(i, j)
        salida[lo : hi + 1] = [unido]
        anexos[unido.code.value] = sorted(set(propios))
        i = lo

    if len(salida) < len(grupos.groups):
        salida, anexos = _renumerar(salida, anexos)
    return (
        GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos,
        del_acuerdo,
    )


def verificar_en_el_documento(
    escritos: list[AnexosDelEscrito],
    grupos: GroupingResult,
    textos: Mapping[int, str],
    *,
    abren: set[int] | frozenset[int] = frozenset(),
) -> list[AnexosDelEscrito]:
    """La lista de anexos de cada escrito, verificada contra su PDF final.

    `retener_anexos` mira hacia delante en el momento del corte; después los
    soportes, los folios del sello y lo que no abre nada todavía se unen al
    escrito, y un anexo que sí acabó en su PDF salía como faltante (UPD2326310:
    el contrato de las hojas 6 y 7). Aquí se mira lo que quedó detrás de la
    lista dentro del mismo PDF.

    Y la hoja que la lectura no sabe qué es -- la foto de una cédula, un
    escaneo ilegible -- puede ser lo que falta: mientras haya tantas como
    anexos sin hallar, éstos quedan «sin verificar» y no «faltan» (UPD2326319:
    el certificado de defunción y la factura, ilegibles, estaban detrás).
    """
    from dataclasses import replace as _reemplazar

    de_quien = {p: g for g in grupos.groups for p in g.page_numbers}
    salida: list[AnexosDelEscrito] = []
    for escrito in escritos:
        grupo = de_quien.get(escrito.pagina)
        if grupo is None:
            salida.append(escrito)
            continue
        detras = [p for p in grupo.page_numbers if p > escrito.pagina]
        clases = {
            p: None if p in abren else clase_de_la_hoja(textos.get(p, "") or "") for p in detras
        }
        pendientes = _Pendientes(escrito.lista)
        hallados: list[AnexoHallado] = []
        for clase, paginas in _tramos(detras, clases):
            if clase is None:
                continue
            # Las facturas y las cédulas van a dos caras: un tramo de cuatro
            # hojas de factura son dos facturas («dos (2) facturas», UPD2326323).
            ejemplares = -(-len(paginas) // 2) if clase in SOPORTES else 1
            for _ in range(ejemplares):
                anexo = pendientes.busca(clase)
                if anexo is None:
                    break
                pendientes.consume(anexo)
                hallados.append(AnexoHallado(clase, list(paginas), declarado=anexo.texto))
            else:
                continue
            if not any(h.paginas == list(paginas) for h in hallados):
                hallados.append(AnexoHallado(clase, list(paginas)))
        faltan = pendientes.faltan()
        # El que no aparece y al que en su mismo renglón le anotaron a mano que
        # no se aportó -- «No aporta documento», en ventanilla al radicar --
        # no falta: se declaró y no se entregó, y eso ya quedó escrito. Se omite
        # de la verificación y se dice, sin pedir revisión (UPD2326315 p2).
        no_aportados = [a for a in faltan if a.anotado_no_aporta]
        faltan = [a for a in faltan if not a.anotado_no_aporta]
        # Las hojas que nadie reconoció y que tampoco se atribuyeron a un anexo.
        atribuidas = {p for h in hallados if h.clase != HOJA_MUDA for p in h.paginas}
        sin_saber = [
            p for p in detras if p not in atribuidas and clases[p] in (None, HOJA_MUDA)
        ]
        probables = faltan[: len(sin_saber)]
        salida.append(
            _reemplazar(
                escrito,
                hallados=hallados,
                faltan=faltan[len(probables) :],
                sin_verificar=list(escrito.sin_verificar) + probables,
                no_aportados=no_aportados,
            )
        )
    return salida
