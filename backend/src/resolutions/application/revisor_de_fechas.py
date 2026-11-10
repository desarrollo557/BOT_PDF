"""El revisor de fechas: la fecha inicial y la final de un documento, aseguradas contra su papel.

Lo pidió el operador el 2026-11-10: «necesito estar muy seguro de cada fecha en
cada documento, sin importar la habilidad», con los dos agentes -- al procesar,
cada documento; al cerrar, la muestra -- y «corregir sólo con prueba». Y que los
auditores cubran «todas las habilidades, todos los documentos, todos los
patrones, todo el margen de errores, de una manera muy optimizada y súper
estructurada».

Una sola pieza para los dos agentes y todas las habilidades:

1. **La regla de la habilidad** sale de su perfil (``perfil.regla_de_fechas``):
   la sesión, el grado, la expedición, la firma, los años, los extremos.
2. **De lo barato a lo caro**: el contraste con el texto ya leído
   (``domain/fechas_extremas.py``), gratis; y sólo lo dudoso, a la IA, **en una
   pregunta por documento**, si la corrida se hizo con ella.
3. **Una decisión**: ``CONFIRMADA``, ``CORREGIDA`` (dos pruebas del papel, o la
   IA citándolo) o ``A_REVISION`` con su motivo. Lo que no tiene fechas en su
   fila, o páginas sin texto, es ``SIN_DATO``: ni bien ni mal.

El margen de error es el de ``contrastar_las_fechas``: lo que se aparta como lo
aparta el OCR, o sólo por la precisión, es duda y no error.

Tras la revisión adversarial del 2026-11-10 (la IA corregía la historia de
1977 a 1958 citando «1958», el año de nacimiento): la cita de la IA vale con
al menos ``CITA_MINIMA`` caracteres y conteniendo la fecha; su corrección cae
en los años del libro -- y en el del encabezado de una resolución -- y nunca
va hacia una lectura que la fila ya descartó; y lo que el contraste manda
derecho a Revisión (fuera de la ventana) no se le pregunta: se paga por
documento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from ..domain.fechas_extremas import (
    ANIO,
    Correccion,
    FechasDeLaFila,
    RevisionDeFechas,
    anios_del_texto,
    contrastar_las_fechas,
    dentro,
    difiere_como_el_ocr,
    en_el_papel,
    fechas_escritas,
    mes_y_anio_en,
)
from .control import Cancelled
from .ports import JuezDeDatos

CONFIRMADA = "confirmada"
CORREGIDA = "corregida"
A_REVISION = "a revisión"
SIN_DATO = "sin dato"

#: Cuánto texto de un documento se le manda a la IA: se paga por tokens.
TEXTO_PARA_LA_IA = 30_000
#: Cuántos caracteres (del texto plano) tiene que tener la cita de la IA para
#: valer: «1958» sola está en cualquier historia y no dice de qué es la fecha.
CITA_MINIMA = 12


@dataclass(frozen=True, slots=True)
class FechasRevisadas:
    """Lo que el revisor decidió de las fechas de un documento."""

    estado: str
    #: Las fechas que quedan: las de la fila, o las corregidas.
    inicial: date | None
    final: date | None
    precision: str
    #: Lo que se corrigió, con su prueba; lo que va a Revisión, con su motivo.
    correcciones: tuple[Correccion, ...] = ()
    motivos: tuple[str, ...] = ()
    #: Cuántas fechas contestó la IA citando el papel.
    preguntadas_a_la_ia: int = 0
    confirmadas: tuple[str, ...] = field(default=())

    @property
    def nota(self) -> str:
        """Lo que se dice en las observaciones de la fila y en el informe."""
        if self.estado == CORREGIDA:
            return "; ".join(
                f"{c.campo.replace('_', ' ')} corregida: {_escrita(c.dice_la_fila, self.precision)} → "
                f"{_escrita(c.dice_el_papel, self.precision)} ({c.prueba})"
                for c in self.correcciones
            )
        if self.estado == A_REVISION:
            return "fechas: " + "; ".join(self.motivos)
        return ""


def revisar_las_fechas(
    fechas: FechasDeLaFila | None,
    textos: Sequence[str],
    *,
    regla: str,
    juez: JuezDeDatos | None = None,
    ventana: tuple[int, int] | None = None,
    contraste: RevisionDeFechas | None = None,
) -> FechasRevisadas:
    """Las fechas de un documento contra su papel, con la IA para lo dudoso: confirmadas, corregidas o a revisión.

    ``contraste`` es el de ``contrastar_las_fechas`` con estas mismas fechas,
    textos, regla y ventana, si quien llama ya lo hizo: la auditoría lo
    necesita antes, para saber qué preguntar, y contrastaba cada documento dos
    veces (2026-11-10).
    """
    if fechas is None:
        return FechasRevisadas(SIN_DATO, None, None, "dia", motivos=("la fila no trae fechas",))
    revision = contraste if contraste is not None else contrastar_las_fechas(fechas, textos, regla=regla, ventana=ventana)
    correcciones = list(revision.correcciones)
    # Lo que el contraste manda derecho a Revisión no se le pregunta a la IA.
    motivos: list[str] = [p.duda for p in revision.preguntas if not p.para_la_ia]
    preguntadas = 0
    confirmadas = list(revision.confirmadas)
    pendientes = [p for p in revision.preguntas if p.para_la_ia]
    if pendientes and juez is not None:
        pendientes, de_la_ia, preguntadas, confirmo = _con_la_ia(
            fechas, pendientes, textos, juez, ventana=revision.ventana
        )
        correcciones.extend(de_la_ia)
        # Lo que la IA confirmó citando el papel es tan confirmado como lo que
        # confirmó el texto: sin esto, una fila cuyas dos fechas confirmó la IA
        # salía «sin dato» (las pruebas del 2026-11-10).
        confirmadas.extend(confirmo)
    motivos.extend(p.duda for p in pendientes)
    inicial, final = fechas.inicial, fechas.final
    for correccion in correcciones:
        if correccion.campo == "fecha_inicial":
            inicial = correccion.dice_el_papel
        else:
            final = correccion.dice_el_papel
    if inicial and final and final < inicial:
        motivos.append(f"la fecha final {_escrita(final, fechas.precision)} es anterior a la inicial")
    if motivos:
        estado = A_REVISION
    elif correcciones:
        estado = CORREGIDA
    elif confirmadas:
        estado = CONFIRMADA
    else:
        estado = SIN_DATO
        motivos.extend(revision.sin_dato)
    return FechasRevisadas(
        estado,
        inicial if estado == CORREGIDA else fechas.inicial,
        final if estado == CORREGIDA else fechas.final,
        fechas.precision,
        tuple(correcciones) if estado == CORREGIDA else (),
        tuple(motivos),
        preguntadas,
        tuple(confirmadas),
    )


#: La clave del informe donde queda lo que hizo el revisor de fechas en un trabajo.
CLAVE_DEL_INFORME = "revision_de_fechas"


def anotar_en_el_informe(report: dict, documento: str, pagina: int | None, revisadas: FechasRevisadas) -> None:
    """Lo que el revisor decidió de un documento, en el informe del trabajo: la misma forma en todas las habilidades.

    - las cuentas, en ``report["revision_de_fechas"]`` (para la pantalla en vivo,
      el Excel de procesos y la auditoría);
    - una corrección, en ``notices`` («Fecha corregida: …»);
    - lo que va a Revisión, en ``review_queue`` con su página y su motivo.
    """
    resumen = report.setdefault(
        CLAVE_DEL_INFORME,
        {"revisados": 0, CONFIRMADA: 0, CORREGIDA: 0, A_REVISION: 0, SIN_DATO: 0, "preguntadas_a_la_ia": 0, "detalle": []},
    )
    resumen["revisados"] += 1
    resumen[revisadas.estado] = resumen.get(revisadas.estado, 0) + 1
    resumen["preguntadas_a_la_ia"] += revisadas.preguntadas_a_la_ia
    if revisadas.estado == CORREGIDA:
        report.setdefault("notices", []).append(f"Fecha corregida en {documento}: {revisadas.nota}")
    if revisadas.estado in (CORREGIDA, A_REVISION):
        resumen["detalle"].append({"documento": documento, "pagina": pagina, "estado": revisadas.estado, "nota": revisadas.nota})
    if revisadas.estado == A_REVISION:
        report.setdefault("review_queue", []).append(
            {"page": pagina or 1, "reason": f"revisor de fechas, {documento}: {revisadas.nota}"}
        )


def _con_la_ia(
    fechas: FechasDeLaFila,
    preguntas,
    textos: Sequence[str],
    juez: JuezDeDatos,
    *,
    ventana: tuple[int, int] | None = None,
):
    """Lo dudoso, en una pregunta a la IA: lo que queda, lo que corrige citando, cuántas contestó y cuáles confirmó.

    ``ventana``: los años en que puede caer una fecha corregida (los del libro
    y, en una resolución, el de su encabezado), como los dice el contraste.
    """
    from ..domain.auditoria_de_filas import plano

    texto = "\n".join(textos)
    # El texto plano, una vez por documento y no una por cada cita.
    texto_plano = plano(texto)
    try:
        respuesta = juez.verificar(
            texto[:TEXTO_PARA_LA_IA],
            [{"campo": p.campo, "valor": p.valor} for p in preguntas],
        )
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - una respuesta rara deja la duda, no tumba el documento
        respuesta = None
    if not respuesta:
        return [_sin_respuesta(p) for p in preguntas], [], 0, []
    quedan, correcciones, contestadas, confirmadas = [], [], 0, []
    for pregunta in preguntas:
        dicho = respuesta.get(pregunta.campo)
        if dicho is None or not _cita_del_papel(dicho.cita, texto_plano):
            quedan.append(pregunta)
            continue
        contestadas += 1
        citadas = _fechas_de_la_cita(dicho.cita, fechas.precision)
        de_la_fila = _de_la_fila(fechas, pregunta.campo)
        if dicho.decision == "esta" and de_la_fila and _en(de_la_fila, citadas, fechas.precision):
            confirmadas.append("la fecha inicial" if pregunta.campo == "fecha_inicial" else "la fecha final")
            continue
        if dicho.decision == "no_esta" and de_la_fila and len(citadas) == 1:
            otra = citadas[0]
            if fechas.precision == ANIO and pregunta.campo == "fecha_final":
                # La final de un año es su 31 de diciembre, como la escribe la
                # fila («01/01/1972-31/12/1972»), no su primero de enero.
                otra = date(otra.year, 12, 31)
            # Corregir sólo si la cita trae otra fecha, que no se aparta como el
            # OCR, -- si el lector de la regla dijo algo -- es la misma que él, y
            # la de la fila no es un día que el OCR deshizo: sin escribir entera,
            # con su mes y su año escritos. «I3DF, DICIEMBRE DE 2007» es el 13
            # aunque la IA cite una fecha de respaldo del 17/11 (el mismo margen
            # que el contraste, 2026-11-10). La de la plantilla o la de la
            # próxima reunión, escritas enteras, sí las corrige la IA.
            dia_deshecho = not en_el_papel(de_la_fila, fechas.precision, textos) and mes_y_anio_en(
                de_la_fila, fechas.precision, textos
            )
            de_acuerdo = pregunta.dice_el_papel is None or _iguales(otra, pregunta.dice_el_papel, fechas.precision)
            # Y la corregida cae en los años del libro (y en el del encabezado
            # de una resolución) y no es una lectura que la fila ya descartó
            # («el OCR leyó X y la IA Y»): la IA corregía 1977 → 1958, el
            # nacimiento (2026-11-10).
            cabe = dentro(otra, ventana) and otra not in fechas.rechazadas
            if not difiere_como_el_ocr(de_la_fila, otra, fechas.precision) and de_acuerdo and not dia_deshecho and cabe:
                correcciones.append(
                    Correccion(pregunta.campo, de_la_fila, otra, f"la IA lo cita del papel: «{dicho.cita.strip()[:100]}»")
                )
                continue
        quedan.append(pregunta)
    return quedan, correcciones, contestadas, confirmadas


def _sin_respuesta(pregunta):
    from ..domain.fechas_extremas import PreguntaDeFecha

    return PreguntaDeFecha(pregunta.campo, pregunta.valor, f"{pregunta.duda} (la IA no respondió)", pregunta.dice_el_papel)


def _de_la_fila(fechas: FechasDeLaFila, campo: str) -> date | None:
    return fechas.inicial if campo == "fecha_inicial" else fechas.final


def _fechas_de_la_cita(cita: str, precision: str) -> list[date]:
    if precision == ANIO:
        return [date(a, 1, 1) for a in sorted(anios_del_texto(cita))]
    # La cita la escribe la IA: con el costo acotado, como el texto del documento.
    return sorted(fechas_escritas(cita))


def _en(fecha: date, citadas: Sequence[date], precision: str) -> bool:
    return any(_iguales(fecha, c, precision) for c in citadas)


def _iguales(una: date, otra: date, precision: str) -> bool:
    return una.year == otra.year if precision == ANIO else una == otra


def _cita_del_papel(cita: str, texto_plano: str) -> bool:
    """Si la cita está en el papel (``texto_plano``, ya pasado por ``plano``) y es larga para decir algo."""
    from ..domain.auditoria_de_filas import plano

    buscada = plano(cita)
    return len(buscada) >= CITA_MINIMA and buscada in texto_plano


def _escrita(fecha: date | None, precision: str) -> str:
    if fecha is None:
        return "N/A"
    return str(fecha.year) if precision == ANIO else fecha.strftime("%d/%m/%Y")
