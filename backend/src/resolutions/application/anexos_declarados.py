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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

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
from ..domain.tramites import es_cedula, radicado_de

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
        # Con todo lo demás del grupo: rehecho a mano perdía que lleva el RE de
        # su propio sello (``re_en_el_nombre``) y el recurso de 1005117 salía
        # sin él al numerarse por fecha (UPD2437857 p5, 2026-11-18).
        nuevos.append(
            replace(grupo, code=ResolutionCode(value=valor, raw=grupo.code.raw if resto.strip() else valor))
        )
    return nuevos, renombrados


# -- la cédula y la factura nunca van solas ----------------------------------------

#: Lo que nunca es un documento por sí mismo: la fotocopia de una cédula y la
#: factura (o su estado de cuenta). Lo dictó el operador sin excepciones: «una
#: cédula nunca podrá ir sola en el inventario o en la división, siempre será
#: acompañada o inventariada dentro del PDF de la página anterior».
DOCUMENTO_DE_IDENTIDAD = "documento de identidad"
SOPORTES = frozenset({DOCUMENTO_DE_IDENTIDAD, "factura"})

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


def es_anexo_por_secuencia(texto: str) -> str | None:
    """La clase de anexo de una hoja para la secuencia, o ``None`` si es una principal.

    La cédula -- también la que el OCR rompe: «CEBULABÉ ClUDi^DANiA» --, la
    factura o el recibo, el estado de cuenta, y los soportes de cabecera
    (certificados, contrato, escritura, fotos, comprobante). La hoja muda no:
    sólo es anexo detrás de otro anexo, y eso lo decide quien recorre.
    """
    texto = texto or ""
    if es_cedula(texto) or clase_de_la_hoja(texto) == DOCUMENTO_DE_IDENTIDAD:
        return DOCUMENTO_DE_IDENTIDAD
    clase = clase_de_soporte(texto)
    return clase if clase is not None and clase != HOJA_MUDA else None


def los_anexos_detras(
    grupos: GroupingResult, textos: Mapping[int, str], *, abren: set[int] | frozenset[int] = frozenset()
) -> GroupingResult:
    """Ningún PDF empieza por un anexo: va detrás de su principal (el operador, 2026-11-23).

    «Una cédula siempre será un anexo, nunca debería ir de primero en un PDF»
    (4132540), y desde el mismo día todo anexo: la factura, el recibo, el
    certificado, con sus reversos mudos. Pasa con los anexos con que empieza el
    PDF -- van con la primera principal -- y con el anexo que la persona llevó
    al documento siguiente. Sólo cambia el orden en que se escriben las hojas
    (``PageGroup.orden``); el inventario y la fecha siguen con el del papel. Un
    PDF que es sólo anexos no se toca, ni la hoja que abre por otra regla
    (``abren``: el sello, la etiqueta).
    """
    salida: list[PageGroup] = []
    cambio = False
    for grupo in grupos.groups:
        hojas = grupo.en_el_pdf
        delante = 0
        con_anexo = False
        while delante < len(hojas):
            pagina = hojas[delante]
            texto = textos.get(pagina, "") or ""
            if pagina not in abren and es_anexo_por_secuencia(texto):
                con_anexo = True
            elif not (con_anexo and pagina not in abren and clase_de_la_hoja(texto) == HOJA_MUDA):
                break
            delante += 1
        if not con_anexo or delante == len(hojas):
            salida.append(grupo)
            continue
        orden = (*hojas[delante:], *hojas[:delante])
        salida.append(replace(grupo, orden=None if list(orden) == sorted(grupo.page_numbers) else orden))
        cambio = True
    return replace(grupos, groups=salida) if cambio else grupos


#: El nombre de antes: la cédula fue la primera (4132540).
la_cedula_detras = los_anexos_detras


# -- cada anexo con su documento: la secuencia, la persona y la IA (F5g) ---------------

#: Cuántos anexos por caja se le enseñan al juez de la IA, como mucho.
ANEXOS_AL_JUEZ_POR_CAJA = 20


@dataclass(frozen=True, slots=True)
class AnexosEnSuDocumento:
    """Los documentos con cada anexo en el suyo, y por qué está ahí cada uno."""

    grupos: GroupingResult
    anexos: dict[str, list[int]]
    #: Las hojas que cambiaron de documento: hoja → ancla del documento al que fueron.
    movidas: dict[int, int] = field(default_factory=dict)
    #: Una por hoja de anexo, para la auditoría.
    decisiones: list[dict] = field(default_factory=list)

    def duenos(self) -> dict[int, int | None]:
        """Por cada anexo, la hoja principal con que va: lo que comprueba ``auditar_la_secuencia``."""
        return {int(d["pagina"]): d.get("ancla") for d in self.decisiones}


def asignar_por_secuencia(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
    *,
    fijas: set[int] | frozenset[int] = frozenset(),
    sin_anexos: set[int] | frozenset[int] = frozenset(),
    identidad_de=None,
    juez=None,
) -> AnexosEnSuDocumento:
    """F5g: cada anexo en el documento que le toca, después de todos los cortes.

    El seguro final que pidió el operador el 2026-11-23 («que te asegures…
    para evitar un anexo a una página que no corresponda»): corre después del
    último filtro que cambia qué hojas van en cada documento, y antes de
    nombrarlos. La regla la dice :mod:`~resolutions.domain.secuencia_de_anexos`:
    la secuencia del PDF, salvo que la persona del anexo lo haga de otro
    documento de la caja; si nada decide y hay IA, la IA elige entre ellos.

    - ``fijas``: hojas que no se mueven aunque parezcan anexo -- las que abren
      por sello, etiqueta o folio, lo que retuvo la lista de ANEXOS o los
      folios del sello, las copias aportadas como prueba --. Cuentan como
      principales para la secuencia.
    - ``identidad_de(pagina, clase)``: ``(texto que dice de quién es, lector)``
      o ``(None, None)``; sólo para la cédula y la factura.
    - ``sin_anexos``: las hojas de los documentos que no reciben ningún anexo
      -- la constancia de reclamación (el operador, 2026-11-24: «las constancias
      van solas, no deberían llevar ningún anexo») --. Lo que va detrás de una
      va con el documento siguiente, salvo que sea de la persona del de antes.
    - ``juez(pagina, opciones)``: la posición de la opción que eligió la IA, o
      ``None``. Mira todo anexo que la regla no pudo probar (``Dueno.dudoso``):
      «que el bot sepa razonar con la ayuda de la IA cuándo una cédula
      pertenece a un grupo de páginas y cuándo no» (2026-11-24).
    """
    from ..domain.secuencia_de_anexos import (
        AL_INICIO,
        CON_SU_PRINCIPAL,
        CONFIRMADO_POR_LA_IA,
        NO_SE_CONFIRMO,
        POR_LA_IA,
        Dueno,
        dueno_razonado,
        dueno_tras_la_constancia,
        duenos_por_secuencia,
        opciones_para_el_juez,
    )

    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    documentos = [list(g.page_numbers) for g in grupos.groups]
    orden = sorted(p for hojas in documentos for p in hojas)
    if not orden:
        return AnexosEnSuDocumento(grupos=grupos, anexos=anexos)
    documento_de = {p: i for i, hojas in enumerate(documentos) for p in hojas}
    clases = {p: es_anexo_por_secuencia(textos.get(p, "") or "") for p in orden}
    # El reverso mudo sigue a su anexo, pero sólo el que ya va con él: una hoja
    # sin texto legible en otro documento puede ser una carta con la capa rota
    # que otro filtro decidió que abre, y el seguro no se la lleva.
    mudas: set[int] = set()
    for pagina in orden:
        anterior = pagina - 1
        if (
            (clases.get(anterior) or anterior in mudas)
            and documento_de.get(anterior) == documento_de[pagina]
            and clase_de_la_hoja(textos.get(pagina, "") or "") == HOJA_MUDA
        ):
            mudas.add(pagina)
    # Y el documento hecho sólo de hojas sin texto legible: eso no es un
    # documento, sigue su secuencia (6833917 hoja 9, el reverso de la cédula
    # detrás de la Habeas Data, 2026-11-23). Si trae un anexo, la hoja muda
    # puede ser su carta llenada a mano, con la capa rota: se queda.
    # Salvo que alguna de sus hojas diga qué es: la notificación por aviso de
    # poco texto también cuenta como hoja muda, y se iba con la respuesta de
    # delante (test_segment_task, desde f8b1fb8; 2026-11-24).
    from ..domain.asunto_del_documento import titulo_del_documento as _titulo_de

    for hojas in documentos:
        if all(not clases[p] and clase_de_la_hoja(textos.get(p, "") or "") == HOJA_MUDA for p in hojas) and all(
            _titulo_de(textos.get(p, "") or "") == "DOCUMENTO" for p in hojas
        ):
            mudas.update(hojas)
    movibles = {p for p in orden if (clases[p] or p in mudas) and p not in fijas}
    if not movibles:
        return AnexosEnSuDocumento(grupos=grupos, anexos=anexos)
    # Los documentos que no reciben anexos: los de la constancia.
    documentos_sin_anexos = {documento_de[p] for p in sin_anexos if p in documento_de}
    por_secuencia = duenos_por_secuencia(orden, movibles, documento_de, documentos_sin_anexos)
    # Lo que dice cada documento de sí mismo: sus hojas principales, sin anexos.
    # La constancia no es candidata: nombra al cliente, pero no recibe nada.
    principales: dict[int, str] = {}
    anclas: dict[int, int] = {}
    for i, hojas in enumerate(documentos):
        propias = [p for p in hojas if not clases[p] and p not in mudas]
        if propias and i not in documentos_sin_anexos:
            principales[i] = "\n".join(textos.get(p, "") or "" for p in propias)
            anclas[i] = propias[0]

    def recibe(q: int) -> bool:
        return q not in movibles and documento_de[q] not in documentos_sin_anexos
    al_juez = 0
    decididos: dict[int, Dueno] = {}
    decisiones: list[dict] = []
    for pagina in sorted(movibles):
        if pagina in mudas and (pagina - 1) in decididos:
            # El reverso, con su anverso.
            del_anverso = decididos[pagina - 1]
            decididos[pagina] = del_anverso
            decisiones.append(
                {
                    "pagina": pagina,
                    "clase": HOJA_MUDA,
                    "ancla": del_anverso.ancla,
                    "regla": "el reverso, con su anverso",
                    "confianza": del_anverso.confianza,
                    "movida_desde": None,
                    "documento_antes": documento_de[pagina],
                    "documento": del_anverso.documento,
                }
            )
            continue
        documento, ancla = por_secuencia[pagina]
        regla = AL_INICIO if ancla is not None and ancla > pagina else CON_SU_PRINCIPAL
        clase = clases[pagina] or HOJA_MUDA
        identidad = lector = None
        de_antes = next((q for q in reversed(orden) if q < pagina and q not in movibles), None)
        tras_la_constancia = de_antes is not None and documento_de[de_antes] in documentos_sin_anexos
        if tras_la_constancia:
            # La constancia no lleva anexos: el siguiente, salvo que sea de la
            # persona del de antes.
            siguiente_que_recibe = next((q for q in orden if q > pagina and recibe(q)), None)
            anterior_que_recibe = next((q for q in reversed(orden) if q < pagina and recibe(q)), None)
            if clase in (DOCUMENTO_DE_IDENTIDAD, "factura") and identidad_de is not None:
                identidad, lector = identidad_de(pagina, clase)
            if siguiente_que_recibe is None and anterior_que_recibe is None:
                dueno = Dueno(documento, ancla, regla)
            else:
                dueno = dueno_tras_la_constancia(
                    (documento_de[siguiente_que_recibe], siguiente_que_recibe) if siguiente_que_recibe else None,
                    (documento_de[anterior_que_recibe], anterior_que_recibe) if anterior_que_recibe else None,
                    identidad if clase in (DOCUMENTO_DE_IDENTIDAD, "factura") else None,
                    principales,
                )
        elif clase in (DOCUMENTO_DE_IDENTIDAD, "factura") and identidad_de is not None and len(principales) >= 2:
            identidad, lector = identidad_de(pagina, clase)
            siguiente = next((documento_de[q] for q in orden if q > pagina and q not in movibles), None)
            distancia = {
                i: min(abs(p - pagina) for p in hojas if not clases[p] and p not in mudas)
                for i, hojas in enumerate(documentos)
                if i in principales
            }
            dueno = dueno_razonado(
                (documento, ancla), regla, identidad, principales, anclas, siguiente=siguiente, distancia=distancia
            )
        else:
            dueno = Dueno(documento, ancla, regla)
        if (
            (dueno.dudoso or dueno.aviso)
            and juez is not None
            and len(principales) >= 2
            and al_juez < ANEXOS_AL_JUEZ_POR_CAJA
        ):
            al_juez += 1
            candidatos = sorted(principales)
            opciones = opciones_para_el_juez(
                [(documentos[i], principales[i]) for i in candidatos],
                antes=candidatos.index(dueno.documento) if dueno.documento in candidatos else None,
            )
            try:
                elegida = juez(pagina, opciones)
            except Exception:  # noqa: BLE001 - sin el juez, la secuencia
                elegida = None
            if elegida is not None and 0 <= elegida < len(candidatos):
                elegido = candidatos[elegida]
                dueno = (
                    Dueno(dueno.documento, dueno.ancla, f"{dueno.regla}, {CONFIRMADO_POR_LA_IA}", dueno.pruebas,
                          confianza="media")
                    if elegido == dueno.documento
                    else Dueno(elegido, anclas.get(elegido), POR_LA_IA, confianza="baja")
                )  # fmt: skip
            elif dueno.dudoso and not dueno.aviso:
                dueno = Dueno(dueno.documento, dueno.ancla, dueno.regla, dueno.pruebas, aviso=NO_SE_CONFIRMO,
                              confianza=dueno.confianza)  # fmt: skip
        decididos[pagina] = dueno
        decisiones.append(
            {
                "pagina": pagina,
                "clase": clase,
                "de_quien": " ".join((identidad or "").split())[:160] or None,
                "leido_por": lector,
                "ancla": dueno.ancla,
                "regla": dueno.regla,
                "pruebas": list(dueno.pruebas),
                "aviso": dueno.aviso,
                "confianza": dueno.confianza,
                "documento_antes": documento_de[pagina],
                "documento": dueno.documento,
            }
        )
    # Rehacer los documentos: lo principal donde estaba, cada anexo con su dueño.
    nuevas: list[list[int]] = [[p for p in hojas if p not in movibles] for hojas in documentos]
    for pagina, dueno in decididos.items():
        nuevas[dueno.documento].append(pagina)
    movidas = {
        pagina: dueno.ancla
        for pagina, dueno in decididos.items()
        if dueno.documento != documento_de[pagina] and dueno.ancla is not None
    }
    for decision in decisiones:
        antes = decision.pop("documento_antes")
        despues = decision.pop("documento")
        decision["movida_desde"] = documentos[antes][0] if antes != despues else None
    if not movidas:
        return AnexosEnSuDocumento(grupos=grupos, anexos=anexos, decisiones=decisiones)
    salida: list[PageGroup] = []
    for grupo, hojas in zip(grupos.groups, nuevas, strict=True):
        if not hojas:
            anexos.pop(grupo.code.value, None)
            continue
        hojas = sorted(hojas)
        if hojas == list(grupo.page_numbers):
            salida.append(grupo)
            continue
        suyos = [p for p in anexos.get(grupo.code.value, []) if p in hojas]
        suyos += [p for p in hojas if p in movidas and p not in grupo.page_numbers]
        if suyos:
            anexos[grupo.code.value] = sorted(set(suyos))
        else:
            anexos.pop(grupo.code.value, None)
        if hojas[0] == grupo.page_numbers[0]:
            # Conserva su primera hoja: conserva su nombre.
            salida.append(replace(grupo, page_numbers=hojas, orden=None))
        else:
            # Empieza por otra hoja: se nombra después (F6), como las piezas nuevas.
            salida.append(PageGroup(code=grupo.code, page_numbers=hojas))
    if len(salida) < len(grupos.groups):
        salida, anexos = _renumerar(salida, anexos)
    return AnexosEnSuDocumento(
        grupos=GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos=anexos,
        movidas=movidas,
        decisiones=decisiones,
    )


def unir_el_paquete_de_la_empresa(
    grupos: GroupingResult,
    anexos: dict[str, list[int]] | None = None,
    *,
    abren_paquete: set[int] | frozenset[int],
    paradas: set[int] | frozenset[int],
) -> SoportesUnidos:
    """El formato con membrete de la empresa abre un paquete con todo lo que lo sigue (el operador, 2026-11-24).

    La CONSTANCIA DE CONTRATACIÓN DE SERVICIO y el EXPEDIENTE de una solicitud
    son la carátula de un trámite de servicio: detrás van la carta del usuario
    que lo pide, su cédula, la declaración juramentada, la solicitud de
    servicio, la factura, el certificado de tradición, el RETIE con la cédula
    y la matrícula del electricista. Todo eso es UN documento, hasta la
    siguiente carátula. En 4251482 (UPD2447022) el operador lo dictó así: «de
    la página 1 a la 7, y el otro grupo de la 8 a la 18»; salía en siete PDF,
    porque la carta, la declaración y la solicitud abrían cada una el suyo.

    ``abren_paquete`` son las hojas de la carátula; ``paradas``, las que cierran
    un paquete: otra carátula, la constancia de reclamación, la notificación,
    la respuesta de la empresa, el acuerdo de pago, un sello o una etiqueta,
    el folio 1, el escrito de un trámite (reclamo, recurso, petición). Un
    documento entra en el paquete si todas sus hojas caen dentro y no empieza
    en una parada; el que cruza la parada se queda como está.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    lista = list(grupos.groups)
    todas = sorted({p for g in lista for p in g.page_numbers})
    cierran = set(paradas) | set(abren_paquete)
    destino_de: dict[int, int] = {}
    for caratula in sorted(abren_paquete):
        if caratula not in todas:
            continue
        fin = next((p for p in todas if p > caratula and p in cierran), todas[-1] + 1)
        dentro = {p for p in todas if caratula <= p < fin}
        suyo = next((k for k, g in enumerate(lista) if caratula in g.page_numbers), None)
        if suyo is None:
            continue
        for k, grupo in enumerate(lista):
            if k == suyo or k in destino_de or not grupo.page_numbers:
                continue
            if grupo.page_numbers[0] in cierran or not set(grupo.page_numbers) <= dentro:
                continue
            destino_de[k] = suyo
    if not destino_de:
        return SoportesUnidos(grupos=grupos, anexos=anexos)
    movidas: dict[int, int] = {}
    juntos: dict[int, list[int]] = {}
    for origen, destino in destino_de.items():
        juntos.setdefault(destino, []).append(origen)
    salida: list[PageGroup] = []
    for k, grupo in enumerate(lista):
        if k in destino_de:
            continue
        if k not in juntos:
            salida.append(grupo)
            continue
        miembros = [lista[o] for o in juntos[k]]
        paginas = sorted({*grupo.page_numbers, *(p for g in miembros for p in g.page_numbers)})
        propios = anexos.pop(grupo.code.value, []) + [p for g in miembros for p in anexos.pop(g.code.value, [])]
        for g in miembros:
            for pagina in g.page_numbers:
                movidas[pagina] = grupo.page_numbers[0]
        # En el orden del papel: la carátula delante y lo demás como viene.
        unido = replace(grupo, page_numbers=paginas, orden=None)
        salida.append(unido)
        if propios:
            anexos[unido.code.value] = sorted(set(propios))
    salida, anexos = _renumerar(salida, anexos)
    return SoportesUnidos(
        grupos=GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos=anexos,
        movidas=movidas,
    )


def el_aviso_con_su_acto(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
) -> SoportesUnidos:
    """La notificación por aviso que adjunta la copia del acto se la lleva, con su portada (el operador, 2026-11-24).

    En 4251461 (UPD2447021) el aviso de la hoja 2 dice que la copia íntegra del
    acto «Consecutivo No. 202070083927» «se adjunta al presente Aviso»; la hoja
    3 es la portada «ANEXO: Copia del acto administrativo…» y las 4-5 son la
    copia. Salían tres PDF: el aviso, «ANEXOS» con la portada sola, y la
    respuesta. El operador eligió el aviso con su anexo, como el reconocimiento
    de deuda se lleva sus anexos.

    Se une lo que va justo detrás del aviso: la portada del anexo y la carta
    cuyo consecutivo es el del acto que el aviso nombra (sin número, la que va
    tras la portada). La notificación que no dice adjuntar nada sigue sola, y
    la respuesta, aparte (2026-10-26).
    """
    from ..domain.asunto_del_documento import (
        acto_que_adjunta,
        consecutivo_de,
        portada_del_anexo,
    )

    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    lista = sorted(grupos.groups, key=lambda g: min(g.page_numbers) if g.page_numbers else 0)
    del_grupo = {p: k for k, g in enumerate(lista) for p in g.page_numbers}
    destino_de: dict[int, int] = {}
    for k, grupo in enumerate(lista):
        if not grupo.page_numbers or k in destino_de:
            continue
        acto = acto_que_adjunta(textos.get(grupo.page_numbers[0], "") or "")
        if acto is None:
            continue
        ultima, tras_la_portada = max(grupo.page_numbers), False
        while (siguiente := del_grupo.get(ultima + 1)) is not None and siguiente != k and siguiente not in destino_de:
            otra = lista[siguiente]
            primera = otra.page_numbers[0]
            if primera != ultima + 1:
                break
            texto = textos.get(primera, "") or ""
            portada = portada_del_anexo(texto)
            es_su_portada = portada is not None and (not acto or not portada or portada == acto)
            # La portada también trae el consecutivo: el acto es la hoja que no es portada.
            es_su_acto = portada is None and (consecutivo_de(texto) == acto if acto else tras_la_portada)
            if not (es_su_portada or es_su_acto):
                break
            destino_de[siguiente] = k
            tras_la_portada = es_su_portada
            ultima = max(otra.page_numbers)
            if es_su_acto:
                break
    if not destino_de:
        return SoportesUnidos(grupos=grupos, anexos=anexos)
    movidas: dict[int, int] = {}
    salida: list[PageGroup] = []
    en_la_lista = {id(g): k for k, g in enumerate(lista)}
    # En el orden en que venían los documentos, no en el del papel.
    for grupo in grupos.groups:
        k = en_la_lista[id(grupo)]
        if k in destino_de:
            continue
        suyos = [lista[o] for o, d in destino_de.items() if d == k]
        if not suyos:
            salida.append(grupo)
            continue
        paginas = sorted({*grupo.page_numbers, *(p for g in suyos for p in g.page_numbers)})
        propios = anexos.pop(grupo.code.value, []) + [p for g in suyos for p in anexos.pop(g.code.value, [])]
        propios += [p for g in suyos for p in g.page_numbers]
        for g in suyos:
            for pagina in g.page_numbers:
                movidas[pagina] = grupo.page_numbers[0]
        unido = replace(grupo, page_numbers=paginas, orden=None)
        salida.append(unido)
        anexos[unido.code.value] = sorted(set(propios))
    salida, anexos = _renumerar(salida, anexos)
    return SoportesUnidos(
        grupos=GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos=anexos,
        movidas=movidas,
    )


def constancias_solas(
    grupos: GroupingResult,
    textos: Mapping[int, str],
    anexos: dict[str, list[int]] | None = None,
    *,
    constancias: Mapping[int, str | None],
) -> SoportesUnidos:
    """Cada constancia del contenido de la reclamación en su PDF, sola, siempre.

    Lo dictó el operador el 2026-11-20 («una constancia del contenido de la
    reclamación siempre va sola»; «siempre un documento así va solo»). Va al
    final de los cortes: el filtro de formularios la dejaba con su anexo
    evidente, y después los soportes, lo que no abre y el revisor le volvían a
    pegar la cédula o la carta de detrás (1005652, UPD2437864).

    ``constancias`` dice, de cada hoja de constancia, su RE: dos hojas seguidas
    con el mismo RE son la misma constancia. Lo que tenía detrás en su
    documento se queda aparte, y si es sólo soporte -- la cédula, la factura,
    el reverso mudo -- va con el documento siguiente, que es del mismo cliente;
    si no hay, con el anterior. Nunca con otra constancia.

    El operador lo confirmó el 2026-11-24: «las constancias van solas, no
    deberían llevar ningún anexo». Es el único documento que va sin anexos; el
    EXPEDIENTE, la constancia de contratación y la declaración van solos con
    los suyos. Si la cédula es de la persona del documento de antes y no del
    siguiente, F5g (``asignar_por_secuencia``) la lleva a ése.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    if not any(p in constancias for g in grupos.groups for p in g.page_numbers):
        return SoportesUnidos(grupos=grupos, anexos=anexos)
    # 1. Partir: lo de antes, cada constancia, lo de detrás.
    piezas: list[dict] = []
    for grupo in grupos.groups:
        tramos: list[list[int]] = []
        claves: list[tuple[str | None] | None] = []
        for pagina in grupo.page_numbers:
            clave = (constancias[pagina],) if pagina in constancias else None
            sigue = tramos and clave == claves[-1] and (clave is None or clave[0] is not None)
            if not sigue:
                tramos.append([])
                claves.append(clave)
            tramos[-1].append(pagina)
        for indice, (tramo, clave) in enumerate(zip(tramos, claves, strict=True)):
            piezas.append(
                {
                    "grupo": grupo,
                    "paginas": tramo,
                    "propio": indice == 0,
                    "constancia": clave is not None,
                    "tras": indice > 0 and claves[indice - 1] is not None and clave is None,
                    "anexos": [p for p in anexos.get(grupo.code.value, []) if p in tramo],
                }
            )
    if len(piezas) == len(grupos.groups):
        return SoportesUnidos(grupos=grupos, anexos=anexos)

    def soporte(pagina: int) -> bool:
        texto = textos.get(pagina, "") or ""
        return clase_de_soporte(texto) is not None or es_cedula(texto)

    # 2. Lo de detrás que es sólo soporte, con el siguiente; si no, con el anterior.
    movidas: dict[int, int] = {}
    i = 0
    while i < len(piezas):
        pieza = piezas[i]
        if not (pieza["tras"] and all(soporte(p) for p in pieza["paginas"])):
            i += 1
            continue
        siguiente = next((j for j in range(i + 1, len(piezas)) if not piezas[j]["constancia"]), None)
        anterior = next((j for j in range(i - 1, -1, -1) if not piezas[j]["constancia"]), None)
        destino = siguiente if siguiente is not None else anterior
        if destino is None:
            i += 1
            continue
        otra = piezas[destino]
        otra["paginas"] = (
            [*pieza["paginas"], *otra["paginas"]] if destino > i else [*otra["paginas"], *pieza["paginas"]]
        )
        otra["anexos"] = [*otra["anexos"], *pieza["anexos"], *pieza["paginas"]]
        for pagina in pieza["paginas"]:
            movidas[pagina] = min(p for p in otra["paginas"] if p not in pieza["paginas"])
        del piezas[i]
    # 3. Numerar otra vez. La pieza que conserva la primera hoja de su documento
    # conserva su nombre y su código; las nuevas se nombran después (F6).
    ancho = max(2, len(re.match(r"^(\d*)", grupos.groups[0].code.value).group(1)))
    salida: list[PageGroup] = []
    nuevos: dict[str, list[int]] = {}
    for puesto, pieza in enumerate(piezas, start=1):
        grupo = pieza["grupo"]
        numero = re.match(r"^\d+(.*)$", grupo.code.value)
        resto = numero.group(1) if pieza["propio"] and numero else ""
        valor = f"{puesto:0{ancho}d}{resto}"
        codigo = ResolutionCode(value=valor, raw=grupo.code.raw if resto.strip() else valor)
        paginas = sorted(pieza["paginas"])
        if pieza["propio"]:
            salida.append(replace(grupo, code=codigo, page_numbers=paginas))
        else:
            salida.append(PageGroup(code=codigo, page_numbers=paginas))
        if pieza["anexos"]:
            nuevos[valor] = sorted(set(pieza["anexos"]))
    return SoportesUnidos(
        grupos=GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        anexos=nuevos,
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
    persona_de=None,
    fecha_de=None,
    reconocimientos_que_abren: set[int] | frozenset[int] = frozenset(),
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

    Con dos o más reconocimientos, la Habeas Data va con el acuerdo de **su
    persona** (``persona_de(pagina)``: el nombre y la cédula de quien firma la
    hoja), no con el que tenga al lado: en 4100921 (UPD2985187, 2026-11-18) las
    dos Habeas iban juntas encima del acuerdo de Luis Alfonso Velilla Arias, y
    el de Alfonso Velilla Corrales se quedaba sin la suya. Sin persona que lo
    decida, el más cercano, como antes.

    Y la fecha primero (el operador, ese mismo día: «las Habeas Data y los
    reconocimientos que van juntos la mayoría de veces llevan las mismas
    fechas, y cuando las fechas no cuadren, valida por el nombre»): la Habeas
    va con el único acuerdo cuyo reconocimiento lleva su fecha (``fecha_de``);
    la persona la valida y, si la contradice o la fecha no decide, manda ella.

    ``reconocimientos_que_abren`` son las hojas del reconocimiento de deuda que
    abren su documento como carta o por el folio 1 de su esquina, sin sello ni
    etiqueta: siguen siendo la pieza que hace el acuerdo, y empiezan el suyo
    (7740523, UPD3128421 pág. 11, 2026-11-24: sin él, sus pagarés y su Habeas
    Data se quedaban sin acuerdo).

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
        return (primera not in abren or primera in reconocimientos_que_abren) and titulo_del_documento(
            textos.get(primera, "") or ""
        ) in PIEZAS_DEL_ACUERDO

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
            # Sólo es el acuerdo si trae el reconocimiento de deuda (lo dictó el
            # operador el 2026-10-26: «para que sea nombrado reconocimiento de
            # deuda, debe haber el documento»). Sin él, los pagarés con sus
            # cartas son un documento, pero se llaman por lo que son.
            primero = racha[0]
            paginas = [p for g in racha for p in g.page_numbers]
            propios = [p for g in racha for p in anexos.pop(g.code.value, [])]
            salida.append(
                PageGroup(
                    code=primero.code,
                    page_numbers=paginas,
                    title=primero.title,
                    kind=ACUERDO_DE_PAGO if reconocimiento else None,
                )
            )
            if propios:
                anexos[primero.code.value] = propios
        if reconocimiento:
            del_acuerdo.update(p for g in racha for p in g.page_numbers)
        racha.clear()

    for grupo in grupos.groups:
        if es_pieza(grupo):
            # El reconocimiento que abre su documento empieza su acuerdo: lo de
            # delante no se le une por estar al lado (sí, más abajo, por ser el
            # único reconocimiento del PDF).
            if grupo.page_numbers[0] in reconocimientos_que_abren:
                cerrar()
            racha.append(grupo)
        else:
            cerrar()
            salida.append(grupo)
    cerrar()

    # Con varios reconocimientos y la persona de cada hoja, la Habeas Data no
    # se pega por estar al lado: la reparte su persona, más abajo.
    por_su_persona = persona_de is not None and sum(1 for g in salida if tiene_reconocimiento(g)) > 1

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
        return es_habeas(grupo) and not por_su_persona

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
                """El acuerdo más cercano; para el pagaré, el más cercano que ningún escrito radicado le corta.

                En 6833800 (UPD2994692, 2026-11-24) el pagaré de 2023 quedaba a
                dos hojas del acuerdo de 2022, con un recurso con sello en medio,
                y a cinco del de 2023, con sólo una constancia en medio: se
                quedaba sin ninguno. La Habeas Data cruza lo que sea: la reparten
                su persona y su fecha.
                """
                centro = salida[k].page_numbers[0]
                posibles = con_reconocimiento
                if not es_habeas(salida[k]):
                    posibles = [a for a in con_reconocimiento if not cortado(k, a)] or con_reconocimiento
                return min(posibles, key=lambda a: min(abs(p - centro) for p in salida[a].page_numbers))

            from ..domain.persona_de_la_hoja import de_quien_es, la_persona_del_grupo

            def reconocimientos_de(a: int) -> list[int]:
                return [
                    p
                    for p in salida[a].page_numbers
                    if titulo_del_documento(textos.get(p, "") or "") == ACUERDO_DE_PAGO
                ]

            def de_su_persona(k: int) -> int | None:
                """El acuerdo de la Habeas Data: el de su misma fecha, validado por la persona que la firma."""
                if persona_de is None or not es_habeas(salida[k]):
                    return None
                por_la_persona = None
                suya = la_persona_del_grupo(salida[k].page_numbers[:1], persona_de)
                if not suya.vacia:
                    por_la_persona = de_quien_es(
                        suya,
                        {a: la_persona_del_grupo(reconocimientos_de(a), persona_de) for a in con_reconocimiento},
                    )
                por_la_fecha = None
                if fecha_de is not None and (fecha := fecha_de(salida[k].page_numbers[0])) is not None:
                    iguales = [
                        a for a in con_reconocimiento if any(fecha_de(p) == fecha for p in reconocimientos_de(a))
                    ]
                    por_la_fecha = iguales[0] if len(iguales) == 1 else None
                # La persona valida la fecha: si la contradice, manda la persona.
                return por_la_persona if por_la_persona is not None else por_la_fecha

            candidatos = {}
            for k in sueltas:
                suyo = de_su_persona(k)
                candidatos[k] = suyo if suyo is not None else mas_cercano(k)
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
    # o la carta de instrucciones sola va con el acuerdo de al lado, el
    # siguiente primero. Sin un acuerdo al lado no se pega a ningún otro
    # documento: va solo, con sus cartas y la cédula de detrás, y se llama por
    # lo que es, «PAGARE» (1000186 págs. 4-7). Hasta el 2026-11-24 iba con el
    # documento de antes, y el operador lo encontró pegado a un contrato de
    # transacción (1000478, UPD2437820: «pegaste unos pagarés a donde no
    # corresponde»); en la misma corrida, a un recurso (6833800) y a la
    # constancia de contratación (7740523).
    i = 0
    while len(salida) > 1 and i < len(salida):
        suelta = salida[i]
        if suelta.kind == ACUERDO_DE_PAGO or not es_pieza(suelta):
            i += 1
            continue
        al_lado = [j for j in (i + 1, i - 1) if 0 <= j < len(salida) and salida[j].kind == ACUERDO_DE_PAGO]
        if not al_lado:
            i += 1
            continue
        j = al_lado[0]
        con_el_siguiente = j == i + 1
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


#: Las partes del acuerdo de pago, por su lugar en el PDF.
RECONOCIMIENTO, PAGARES, HABEAS, ANEXOS_DEL_ACUERDO = "reconocimiento", "pagares", "habeas", "anexos"
#: Un escrito de otro formato dentro del acuerdo -- la autorización para la
#: financiación, una carta del usuario --: va detrás de la Habeas Data y antes
#: de los anexos (el operador, 2026-11-23, 1000258).
OTRO_DOCUMENTO = "otro documento"


def partes_del_acuerdo(paginas: Sequence[int], textos: Mapping[int, str]) -> list[tuple[str, list[int]]]:
    """Las hojas de un acuerdo de pago en sus partes, en el orden del papel.

    Cada hoja con título abre su parte: el reconocimiento de deuda, el pagaré o
    su carta de instrucciones (pagarés), la Ley Habeas Data. La hoja sin título
    sigue a la de delante -- la segunda hoja del pagaré es del pagaré --, salvo
    el soporte -- la cédula, la factura -- y lo que no es de ninguna, que son
    anexos; también el simulador de la financiación.

    La hoja que abre un escrito propio sin ser ninguna de esas -- «Señores
    AFINIA… AUTORIZACION», «REF: AUTORIZACION PARA FINANCIACION» -- es otro
    documento (``OTRO_DOCUMENTO``): antes se pegaba al reconocimiento o al
    pagaré de delante (1000258, 2026-11-23).
    """
    from ..domain.asunto_del_documento import (
        ACUERDO_DE_PAGO,
        LEY_HABEAS_DATA,
        PIEZAS_DEL_ACUERDO,
        titulo_del_documento,
    )

    partes: list[tuple[str, list[int]]] = []
    for pagina in sorted(paginas):
        texto = textos.get(pagina, "") or ""
        # «DOCUMENTO» es el título de lo que no dice ninguno.
        titulo = None if (leido := titulo_del_documento(texto)) == SIN_TIPO else leido
        if titulo == ACUERDO_DE_PAGO:
            parte = RECONOCIMIENTO
        elif titulo in PIEZAS_DEL_ACUERDO and titulo != "SIMULADOR DE NEGOCIACION Y FINANCIACION":
            parte = PAGARES
        elif titulo == LEY_HABEAS_DATA:
            parte = HABEAS
        elif es_cedula(texto) or (soporte := clase_de_soporte(texto)) not in (None, HOJA_MUDA, DOCUMENTO_DE_IDENTIDAD):
            # La tarjeta con sus rótulos, la factura, el certificado: anexos.
            parte = ANEXOS_DEL_ACUERDO
        elif soporte != HOJA_MUDA and _ABRE.search(plano(texto)[:CABEZA_QUE_ABRE]):
            # Abre un escrito -- «Señores…», «REF:» -- aunque nombre la cédula
            # de quien firma: es otro documento, no la fotocopia de la cédula.
            parte = OTRO_DOCUMENTO
        elif (
            titulo
            or clase_de_la_hoja(texto) in SOPORTES
            or es_cedula(texto)
            or not partes
            # El reconocimiento y la Habeas Data son de una hoja: la foto de
            # la cédula que la capa no deja leer, detrás, es un anexo y va al
            # final, no pegada a él (1005114, UPD2973876 pág. 6, 2026-11-18).
            or (partes[-1][0] in (RECONOCIMIENTO, HABEAS) and clase_de_la_hoja(texto) == HOJA_MUDA)
        ):
            parte = ANEXOS_DEL_ACUERDO
        else:
            # Sin título: sigue a la de delante.
            partes[-1][1].append(pagina)
            continue
        partes.append((parte, [pagina]))
    return partes


def reconocimientos_del_acuerdo(paginas: Sequence[int], textos: Mapping[int, str]) -> list[list[int]]:
    """Las hojas de cada reconocimiento de deuda del acuerdo, en el orden del papel.

    Casi siempre uno; a veces dos -- el acuerdo renegociado trae el nuevo y el
    anterior -- y entonces el más reciente va primero (``orden_del_acuerdo``).
    """
    return [hojas for parte, hojas in partes_del_acuerdo(paginas, textos) if parte == RECONOCIMIENTO]


def orden_del_acuerdo(
    paginas: Sequence[int],
    textos: Mapping[int, str],
    *,
    reconocimiento_fechado: bool,
    fechas_del_reconocimiento: Mapping[int, date] | None = None,
) -> tuple[int, ...]:
    """Las hojas de un acuerdo de pago en el orden en que van en su PDF.

    Lo dictó el operador el 2026-11-12: «cuando encuentres un reconocimiento de
    deuda y acuerdo de pago, si la página principal tiene fecha, agregarla de
    primero, luego los pagarés si tiene, luego Ley Habeas Data, y luego los
    anexos; pero cuando no tenga fecha, colócalo de último: pagarés, Ley Habeas
    Data, anexos, reconocimiento de deuda y acuerdo de pago». Dentro de cada
    parte, el orden del papel. Lo que no trae reconocimiento queda como estaba.

    Con dos reconocimientos (el operador, 2026-11-20: «coloca el más
    reciente»), el más reciente primero y el anterior justo detrás, antes de
    los pagarés; el que no tiene fecha, detrás de los fechados.
    ``fechas_del_reconocimiento`` va por la primera hoja de cada uno. Una hoja
    con el título que sigue a otra del reconocimiento sin fecha propia es su
    continuación -- el encabezado repetido -- y va con ella.
    """
    partes = partes_del_acuerdo(paginas, textos)
    if not any(parte == RECONOCIMIENTO for parte, _ in partes):
        return tuple(sorted(paginas))
    fechas = fechas_del_reconocimiento or {}
    reconocimientos: list[list[int]] = []
    anterior = None
    for parte, hojas in partes:
        if parte == RECONOCIMIENTO:
            if anterior == RECONOCIMIENTO and hojas[0] not in fechas:
                reconocimientos[-1].extend(hojas)
            else:
                reconocimientos.append(list(hojas))
        anterior = parte
    fechados = sorted((r for r in reconocimientos if r[0] in fechas), key=lambda r: fechas[r[0]], reverse=True)
    reconocimientos = [*fechados, *(r for r in reconocimientos if r[0] not in fechas)]
    del_reconocimiento = [p for hojas in reconocimientos for p in hojas]
    puestos = (
        (RECONOCIMIENTO, PAGARES, HABEAS, OTRO_DOCUMENTO, ANEXOS_DEL_ACUERDO)
        if reconocimiento_fechado
        else (PAGARES, HABEAS, OTRO_DOCUMENTO, ANEXOS_DEL_ACUERDO, RECONOCIMIENTO)
    )
    return tuple(
        p
        for puesto in puestos
        for p in (
            del_reconocimiento
            if puesto == RECONOCIMIENTO
            else [p for parte, hojas in partes if parte == puesto for p in hojas]
        )
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
