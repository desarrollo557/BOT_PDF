"""El agente revisor también en los datos: cada documento contra lo que su habilidad espera de él.

Lo pidió el operador el 2026-11-06, antes de procesar Enfermería por segunda
vez: que los dos agentes «se aseguren de que lo que esperemos sea íntegro en
todas las habilidades» -- el nombre, la cédula, la tarjeta o la libreta
militar, el código, las fechas extremas -- «y que los documentos cumplan su
margen de error». Empezó por las historias académicas.

Dos momentos, con la misma regla (``domain/datos_esperados.py``):

- **Al procesar** (``revisar_los_datos``): las filas que salieron de leer cada
  documento, antes de entregarlas. Lo que no cuadra va a la cola de revisión y
  al informe (``integridad_de_los_datos``); nada se inventa ni se corrige aquí:
  lo que había que leer ya se leyó -- con la IA si se eligió --.
- **Al auditar** (``auditar_los_datos``): cada PDF entregado contra **su fila
  del FUID entregado**, leída del disco: que la tenga, que se llame como ella
  y que sus datos estén completos y en orden.

Un perfil de habilidad dice qué espera con un ``DatosEsperados``; el que no
tiene ninguno no revisa datos.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from ..domain.auditoria import MARGEN_ACEPTABLE, margen_de_error
from ..domain.datos_esperados import (
    CAMPOS_DE_UNA_HISTORIA,
    CAMPOS_DE_UNA_NOMINA,
    DUDA,
    ERROR,
    VERIFICADO_EN_BLANCO,
    DatosDeUnaHistoria,
    Hallazgo,
    cifras,
    plano,
    revisar_entre_documentos,
    revisar_nominas_entre_si,
    revisar_una_historia,
    revisar_una_nomina,
)
from ..domain.historia_academica import CEDULA, HISTORIA_ACADEMICA, Ficha
from .fuid import FuidRow

#: Lo que se espera de un documento, leído de una fila del informe o del FUID.
Lector = Callable[[Mapping[str, object]], DatosDeUnaHistoria | None]


@dataclass(frozen=True, slots=True)
class DatosEsperados:
    """Qué datos espera una habilidad de cada documento, y cómo se leen y se revisan."""

    campos: tuple[str, ...]
    #: De una fila del informe del trabajo; ``None`` si la fila no es de un documento (la portada).
    de_la_fila: Lector
    #: De una fila del FUID entregado.
    del_fuid: Callable[[FuidRow], DatosDeUnaHistoria | None]
    revisar: Callable[[DatosDeUnaHistoria], list[Hallazgo]]
    #: Lo que no cuadra entre los documentos de un PDF o una caja: por posición, sus hallazgos.
    entre_documentos: Callable[[Sequence[DatosDeUnaHistoria], Sequence[str]], dict[int, list[Hallazgo]]] | None = None
    #: Si un PDF entregado no es de nadie y no lleva fila con datos: las hojas
    #: de antes de la primera ficha, un listado de nómina, el índice del libro.
    sin_datos: Callable[[str], bool] = lambda pdf: "SIN-FICHA" in pdf.upper()


@dataclass(frozen=True, slots=True)
class IntegridadDeLosDatos:
    """Cómo salieron los datos de los documentos de un PDF."""

    documentos: int
    completos: int
    con_dudas: int
    con_errores: int
    #: Por campo: en cuántos documentos está bien, en cuántos para mirar, en
    #: cuántos con error y en cuántos el papel lo trae en blanco (verificado).
    por_campo: dict[str, dict[str, int]]
    #: Lo que no cuadra, documento por documento: {documento, pagina, campo, gravedad, texto}.
    hallazgos: tuple[dict[str, object], ...] = ()
    aceptable: float = MARGEN_ACEPTABLE
    #: Los completos a los que alguna casilla les falta en el papel: buscada
    #: otra vez, está en blanco (2026-11-06).
    con_en_blanco: int = 0

    @property
    def estado(self) -> str:
        if self.con_errores:
            return "con errores"
        if self.con_dudas:
            return "en revisión"
        return "validado"

    def resumen(self) -> str:
        partes = [f"{self.completos} de {self.documentos} completos"]
        if self.con_errores:
            partes.append(f"{self.con_errores} con error")
        if self.con_dudas:
            partes.append(f"{self.con_dudas} para mirar")
        if self.con_en_blanco:
            partes.append(f"{self.con_en_blanco} con casillas en blanco en el papel")
        return f"Datos de cada documento: {self.estado} ({'; '.join(partes)})"

    def as_dict(self) -> dict[str, object]:
        return {
            "estado": self.estado,
            "resumen": self.resumen(),
            "documentos": self.documentos,
            "completos": self.completos,
            "con_dudas": self.con_dudas,
            "con_errores": self.con_errores,
            "con_en_blanco": self.con_en_blanco,
            "por_campo": {campo: dict(cuentas) for campo, cuentas in self.por_campo.items()},
            "hallazgos": [dict(h) for h in self.hallazgos],
            "margen": margen_de_error(self.con_errores, self.documentos, aceptable=self.aceptable).as_dict(),
        }


def revisar_los_datos(
    filas: Sequence[Mapping[str, object]],
    esperados: DatosEsperados,
    *,
    aceptable: float = MARGEN_ACEPTABLE,
) -> IntegridadDeLosDatos:
    """Los datos de cada fila del informe contra lo que espera la habilidad, y entre ellas."""
    suyas = [(fila, datos) for fila in filas if (datos := esperados.de_la_fila(fila)) is not None]
    rotulos = [str(fila.get("archivo_generado") or "") or _paginas(fila) for fila, _ in suyas]
    entre = esperados.entre_documentos([datos for _, datos in suyas], rotulos) if esperados.entre_documentos else {}
    completos = con_dudas = con_errores = con_en_blanco = 0
    por_campo = {campo: {"bien": 0, "dudas": 0, "errores": 0, "en_blanco": 0} for campo in esperados.campos}
    hallazgos: list[dict[str, object]] = []
    for indice, ((fila, datos), documento) in enumerate(zip(suyas, rotulos, strict=True)):
        suyos = [*esperados.revisar(datos), *entre.get(indice, [])]
        gravedades = {h.gravedad for h in suyos}
        if ERROR in gravedades:
            con_errores += 1
        elif DUDA in gravedades:
            con_dudas += 1
        else:
            completos += 1
            con_en_blanco += VERIFICADO_EN_BLANCO in gravedades
        for campo, cuentas in por_campo.items():
            del_campo = {h.gravedad for h in suyos if h.campo == campo}
            if ERROR in del_campo:
                cuentas["errores"] += 1
            elif DUDA in del_campo:
                cuentas["dudas"] += 1
            elif VERIFICADO_EN_BLANCO in del_campo:
                cuentas["en_blanco"] += 1
            else:
                cuentas["bien"] += 1
        hallazgos.extend(
            {"documento": documento, "pagina": fila.get("pagina_inicial"), **h.as_dict()} for h in suyos
        )
    return IntegridadDeLosDatos(
        documentos=len(suyas),
        completos=completos,
        con_dudas=con_dudas,
        con_errores=con_errores,
        por_campo=por_campo,
        hallazgos=tuple(hallazgos),
        aceptable=aceptable,
        con_en_blanco=con_en_blanco,
    )


def auditar_los_datos(
    entregados: Sequence[str],
    filas_del_fuid: Sequence[FuidRow] | None,
    esperados: DatosEsperados,
    *,
    verificados: Mapping[str, Mapping[str, str]] | None = None,
    tipos: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Cada PDF entregado contra su fila del FUID entregado: los errores y las dudas, dichos para el operador.

    Sin FUID en su carpeta no hay con qué comprobar: es un error, porque toda
    habilidad de la Universidad entrega el suyo. El PDF que no es de ningún
    estudiante -- las hojas de antes de la primera ficha -- no lleva fila.
    ``verificados`` dice, por PDF, cómo quedó cada casilla que el agente buscó
    otra vez al procesar (de la constancia): la que está en blanco en el papel
    no es una duda. ``tipos``, también de la constancia, si su identificación
    es una cédula, una tarjeta o una libreta: el FUID sólo trae las cifras. Y las filas del FUID se cruzan entre sí: la misma cédula en
    dos estudiantes es un error.
    """
    de_estudiante = [pdf for pdf in entregados if not esperados.sin_datos(pdf)]
    if not de_estudiante:
        return [], []
    if filas_del_fuid is None:
        return ["su carpeta no tiene FUID con que comprobar los datos"], []
    candidatas = [(fila, datos) for fila in filas_del_fuid if (datos := esperados.del_fuid(fila)) is not None]
    entre = (
        esperados.entre_documentos(
            [datos for _, datos in candidatas], [datos.nombre or f"la fila {fila.orden}" for fila, datos in candidatas]
        )
        if esperados.entre_documentos
        else {}
    )
    usadas: set[int] = set()
    errores: list[str] = []
    dudas: list[str] = []
    for pdf in de_estudiante:
        suya = _la_fila_de(pdf, candidatas, usadas)
        archivo = pdf.rsplit("/", 1)[-1]
        if suya is None:
            errores.append(f"«{archivo}» no tiene su fila en el FUID (ni por su identificación ni por su nombre)")
            continue
        usadas.add(suya)
        datos = replace(candidatas[suya][1], archivo=archivo, verificado=dict((verificados or {}).get(archivo) or {}))
        if datos.identificacion and (tipo := (tipos or {}).get(archivo)):
            # El FUID sólo trae las cifras; la constancia dice si son de una
            # cédula: «415467824» no lo es (PAJARO MARTINEZ, 2026-11-06).
            datos = replace(datos, tipo_de_identificacion=tipo)
        for hallazgo in [*esperados.revisar(datos), *entre.get(suya, [])]:
            if hallazgo.gravedad == ERROR:
                errores.append(f"«{archivo}»: {hallazgo.texto}")
            elif hallazgo.gravedad == DUDA:
                dudas.append(f"«{archivo}»: {hallazgo.texto}")
    return errores, dudas


def _la_fila_de(pdf: str, candidatas: list, usadas: set[int]) -> int | None:
    """La fila del FUID de un PDF: por su identificación y su nombre, por uno de los dos, o la sin nombre.

    Primero la que coincide en las dos cosas: con la misma cédula en dos filas
    -- la de VILLALOBOS GARI también en CONDE DIAZ, 2026-11-06 -- el PDF de
    CONDE se casaba con la fila de VILLALOBOS.
    """
    base = re.sub(r"^\d{1,4}_", "", pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]).upper()
    numero = hallado.group(1) if (hallado := re.search(r"-(\d{4,})$", base)) else ""
    nombre = base.removesuffix(f"-{numero}") if numero else base
    libres = [i for i in range(len(candidatas)) if i not in usadas]

    def por_nombre(i: int) -> bool:
        esperado = plano(candidatas[i][1].nombre or "")
        return bool(esperado) and (esperado.startswith(nombre) or nombre.startswith(esperado))

    def por_numero(i: int) -> bool:
        return bool(numero) and cifras(candidatas[i][1].identificacion) == numero

    for prueba in (lambda i: por_numero(i) and por_nombre(i), por_numero, por_nombre):
        if (suya := next((i for i in libres if prueba(i)), None)) is not None:
            return suya
    if _SIN_NOMBRE.match(nombre):
        # El PDF que salió sin nombre -- «PAGINAS-5-6», «NOMBRE-POR-REVISAR» --
        # es una fila sin nombre («N/A») del FUID, en el mismo orden: su
        # hallazgo es que no se leyó el nombre, no que no tenga fila
        # (Enfermería, 2026-11-06).
        for i in libres:
            datos = candidatas[i][1]
            if not datos.nombre and (not numero or cifras(datos.identificacion) in ("", numero)):
                return i
    return None


#: Cómo se llama el PDF de un estudiante cuyo nombre no se leyó (``historias._nombre_del_pdf``).
_SIN_NOMBRE = re.compile(r"^(?:PAGINAS-\d+-\d+|NOMBRE-POR-REVISAR)$")


def _paginas(fila: Mapping[str, object]) -> str:
    desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
    if desde is None:
        return str(fila.get("archivo") or "")
    return f"págs. {desde}-{hasta}" if hasta and hasta != desde else f"pág. {desde}"


# -- las historias académicas -------------------------------------------------------


def _anio(valor: object) -> int | None:
    """El año de un número o de una fecha escrita («01/01/1993», «26/03/1992»)."""
    if isinstance(valor, int):
        return valor
    hallado = re.search(r"\b(1[89]\d\d|20\d\d)\b", str(valor or ""))
    return int(hallado.group(1)) if hallado else None


def historia_de_la_fila(fila: Mapping[str, object]) -> DatosDeUnaHistoria | None:
    """Los datos de un estudiante tal como salieron de leer su historia; ``None`` si la fila no es de un estudiante."""
    if fila.get("tipo") != HISTORIA_ACADEMICA:
        return None
    identificacion = Ficha(
        cedula=_texto(fila.get("cedula")), tarjeta=_texto(fila.get("tarjeta")), libreta=_texto(fila.get("libreta"))
    ).identificacion
    inicial = _anio(fila.get("anio_inicial")) or _anio(fila.get("fecha_exacta"))
    final = _anio(fila.get("anio_final")) or _anio(fila.get("fecha_exacta"))
    return DatosDeUnaHistoria(
        nombre=_texto(fila.get("nombre")),
        identificacion=identificacion[1] if identificacion else None,
        tipo_de_identificacion=identificacion[0] if identificacion else None,
        codigo=_texto(fila.get("codigo")),
        anio_inicial=inicial,
        anio_final=final,
        hoja_suelta=bool(fila.get("clase")),
        archivo=_texto(fila.get("archivo_generado")),
        verificado=dict(fila.get("verificado") or {}),
    )


def historia_del_fuid(fila: FuidRow) -> DatosDeUnaHistoria | None:
    """Los datos de un estudiante tal como quedaron en el FUID entregado.

    El asunto es el nombre; las hojas sueltas de Medicina lo llevan seguido del
    tipo de hoja («… - RECIBO DE CAJA»), y los FUID de antes del 2026-11-06,
    de «- HISTORIA ACADEMICA». El consecutivo inicial es la identificación y el
    final, el código; «N/A» es que no se leyó.
    """
    asunto = (fila.asunto or "").strip()
    if not asunto:
        return None
    nombre, _, tipo = asunto.partition(" - ")
    tipo = tipo.strip().upper()
    return DatosDeUnaHistoria(
        nombre=_texto(nombre),
        identificacion=cifras(str(fila.consecutivo_inicial)) or None,
        codigo=cifras(str(fila.consecutivo_final)) or None,
        anio_inicial=_anio(fila.fecha_inicial),
        anio_final=_anio(fila.fecha_final),
        hoja_suelta=bool(tipo) and tipo != HISTORIA_ACADEMICA,
    )


def _texto(valor: object) -> str | None:
    texto = " ".join(str(valor or "").split())
    return texto if texto and texto.upper() != "N/A" else None


def _revisar_una_historia(datos: DatosDeUnaHistoria) -> list[Hallazgo]:
    return revisar_una_historia(datos, este_anio=date.today().year)


#: Lo que se espera de una historia académica: nombre, cédula -- o tarjeta, o
#: libreta militar --, código y fechas extremas.
DE_UNA_HISTORIA = DatosEsperados(
    campos=CAMPOS_DE_UNA_HISTORIA,
    de_la_fila=historia_de_la_fila,
    del_fuid=historia_del_fuid,
    revisar=_revisar_una_historia,
    entre_documentos=revisar_entre_documentos,
)


# -- las nóminas ------------------------------------------------------------------------


#: Los asuntos que no son de una persona: el listado, el hablador y el índice.
_DE_NADIE = ("NOMINA", "INDICE")
_DEL_HABLADOR = "LISTADO DE NOMINA PERSONAL"


def nomina_de_la_fila(fila: Mapping[str, object]) -> DatosDeUnaHistoria | None:
    """Los datos de una persona de un libro de nómina; ``None`` si la fila es un paquete o el índice."""
    from ..domain.nomina import NOMINA, PERSONA

    if fila.get("tipo") != NOMINA or fila.get("clase") != PERSONA:
        return None
    return DatosDeUnaHistoria(
        nombre=_texto(fila.get("nombre")),
        identificacion=cifras(str(fila.get("cedula") or "")) or None,
        tipo_de_identificacion=CEDULA,
        anio_inicial=_anio(fila.get("fecha_inicial")),
        anio_final=_anio(fila.get("fecha_final")),
        # Su hoja no trae cédula (el libro de anotaciones de 1972): no se pide.
        hoja_suelta=not fila.get("pide_cedula"),
        archivo=_texto(fila.get("archivo_generado")),
    )


def nomina_del_fuid(fila: FuidRow) -> DatosDeUnaHistoria | None:
    """Los datos de una persona tal como quedaron en el FUID: «NOMINAS - NOMBRE», la cédula, los años.

    El listado («NOMINA»), lo que abre el hablador y el índice no son de una
    persona: ``None``. Una persona sin nombre leído queda con sólo el tipo
    («NOMINAS»), y es la fila del PDF que se llama por sus páginas.
    """
    asunto = " ".join((fila.asunto or "").split()).upper()
    if not asunto or asunto in _DE_NADIE or asunto.startswith(_DEL_HABLADOR):
        return None
    tipo, _, nombre = asunto.partition(" - ")
    return DatosDeUnaHistoria(
        nombre=_texto(nombre),
        identificacion=cifras(str(fila.consecutivo_inicial)) or None,
        tipo_de_identificacion=CEDULA,
        anio_inicial=_anio(fila.fecha_inicial),
        anio_final=_anio(fila.fecha_final),
        # Al auditar no se sabe si su hoja la traía: sólo la tarjeta y el certificado la piden.
        hoja_suelta=not (tipo.startswith("NOMINAS") or tipo.startswith("CERTIFICADO")),
    )


def _sin_datos_de_nomina(pdf: str) -> bool:
    """El PDF de un listado, de un año del hablador o del índice: no es de una persona."""
    base = re.sub(r"^\d{1,4}_", "", pdf.rsplit("/", 1)[-1]).upper()
    return base.startswith(("NOMINA-", "LISTADO-DE-NOMINA", "INDICE"))


def _revisar_una_nomina(datos: DatosDeUnaHistoria) -> list[Hallazgo]:
    return revisar_una_nomina(datos, este_anio=date.today().year)


#: Lo que se espera de una persona de un libro de nómina: nombre, cédula si su
#: hoja la trae, y fechas extremas (2026-11-06).
DE_UNA_NOMINA = DatosEsperados(
    campos=CAMPOS_DE_UNA_NOMINA,
    de_la_fila=nomina_de_la_fila,
    del_fuid=nomina_del_fuid,
    revisar=_revisar_una_nomina,
    entre_documentos=revisar_nominas_entre_si,
    sin_datos=_sin_datos_de_nomina,
)
