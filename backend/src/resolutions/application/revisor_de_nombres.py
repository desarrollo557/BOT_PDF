"""El revisor de nombres: el nombre de la persona de cada documento, asegurado contra su papel.

El operador, 2026-11-17: «usar estas herramientas muy bien creadas para todas
las habilidades… centralizarlas y conectarlas a todas las habilidades». Es el
gemelo del revisor de fechas (``application/revisor_de_fechas.py``): una sola
pieza que usan todas las habilidades con persona, cada una con lo suyo -- de
dónde salen sus lecturas, cómo vuelve a mirar el renglón y qué imagen recorta
--, y la misma decisión para todas (``domain/revision_de_nombres.py``).

De lo barato a lo caro:

1. **Las lecturas votan** palabra por palabra; la lista de nombres conocidos y
   las palabras del padrón sólo desempatan (``nombre_por_consenso``).
2. **Lo dudoso se vuelve a mirar** con otro recorte y más zoom (``releer``, el
   de cada habilidad), y esa lectura vota también.
3. **La IA mira la imagen del renglón de cada persona** con todas sus lecturas
   y los candidatos del padrón al lado -- a todas, siempre, por decisión del
   operador (2026-11-17) --, y sólo se acepta una corrección de letras
   (``nombre_mirado``). Sin imagen, la IA de texto corrige comparando las
   lecturas lo que nada confirma.
4. **Lo que ni así se confirma** va a Revisión con todas sus lecturas, donde lo
   mira una persona con la imagen delante.

Medido en las fichas de Enfermería (UPD3859718, 29 contra el papel): de 16 a 25
nombres exactos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..domain.historia_medicina import NombreVotado, nombre_por_consenso
from ..domain.padron import IndiceDelPadron, para_la_ia
from ..domain.revision_de_nombres import (
    A_REVISION,
    CONFIRMADO,
    CORREGIDO,
    ESTADO_DE_LA_FILA,
    SIN_DATO,
    corregida_comparando,
    decidir_el_nombre,
)
from .control import Cancelled

logger = logging.getLogger(__name__)

#: La clave del informe donde queda lo que hizo el revisor de nombres en un trabajo.
CLAVE_DEL_INFORME = "revision_de_nombres"
#: Cuántas personas se le preguntan a la IA a la vez.
LECTORES = 4


@dataclass(frozen=True, slots=True)
class PorRevisar:
    """Una persona de un documento, con lo que se leyó de su nombre."""

    clave: Hashable
    lecturas: Sequence[str | None]
    cedula: str | None = None
    #: La imagen de donde está escrito su nombre, recortada al pedirla: sólo si hay IA.
    imagen: Callable[[], bytes | None] | None = None
    #: La página donde está escrito, para la cola de Revisión.
    pagina: int | None = None
    #: El nombre que ya votó la habilidad con su propio voto (las actas de
    #: grado, con ``consenso``): el revisor no lo vuelve a votar ni lo relee, y
    #: pone lo demás -- la IA que mira, el padrón, la decisión, la cola --.
    votado: NombreVotado | None = None


@dataclass(frozen=True, slots=True)
class NombreRevisado:
    """Lo que el revisor decidió del nombre de una persona."""

    estado: str
    nombre: str | None
    #: Lo que se leyó antes de votar y corregir.
    leido: str | None
    lecturas: tuple[str, ...] = ()
    motivo: str | None = None
    #: Lo que contestó la IA mirando el renglón, tal cual.
    de_la_ia: str | None = None
    #: Las personas parecidas del padrón que se le mostraron a la IA.
    candidatos: tuple[str, ...] = ()
    pagina: int | None = None
    preguntado_a_la_ia: bool = False
    por_la_ia: bool = False

    @property
    def cambio(self) -> bool:
        return bool(self.nombre and self.leido and self.nombre != self.leido)

    @property
    def detalle(self) -> dict:
        """Lo que la fila lleva para la pantalla de Revisión (``revision_del_nombre``)."""
        return {
            "estado": ESTADO_DE_LA_FILA.get(self.estado, self.estado),
            "pagina_de_la_ficha": self.pagina,
            "leido": self.leido,
            "lecturas": list(self.lecturas),
            **({"de_la_ia": self.de_la_ia} if self.de_la_ia is not None else {}),
            **({"padron": list(self.candidatos)} if self.candidatos else {}),
        }


@dataclass
class _Estado:
    lecturas: list[str | None] = field(default_factory=list)


def revisar_los_nombres(
    personas: Sequence[PorRevisar],
    *,
    conocidas=(),
    padron: IndiceDelPadron | None = None,
    juez=None,
    corrector=None,
    releer: Callable[[list[Hashable]], Mapping[Hashable, Sequence[str]]] | None = None,
    a_revision: bool = True,
    control=None,
    lectores: int = LECTORES,
    documento: str = "",
) -> dict[Hashable, NombreRevisado]:
    """El nombre de cada persona, votado, vuelto a mirar si hace falta y mirado por la IA.

    ``juez`` mira la imagen (``resumir(texto, imagen=)``); ``corrector`` compara
    lecturas en texto (``resumir(texto)``). ``releer`` es la otra mirada de la
    habilidad: de las claves dudosas, sus lecturas nuevas. Nada de esto tumba
    el trabajo: lo que falla queda votado. Cancelar sí corta.
    """
    lecturas = {persona.clave: list(persona.lecturas) for persona in personas}
    por_clave = {persona.clave: persona for persona in personas}
    votados = {
        clave: por_clave[clave].votado or nombre_por_consenso(lecturas[clave], conocidas) for clave in lecturas
    }

    # Lo que ya votó la habilidad no se vuelve a mirar aquí: lo hizo ella.
    dudosos = [
        clave
        for clave, votado in votados.items()
        if por_clave[clave].votado is None and (votado.sin_confirmar or not votado.nombre)
    ]
    if dudosos and releer is not None:
        try:
            nuevas = releer(dudosos)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - sin la otra mirada queda lo votado
            logger.warning("no se pudo volver a mirar el nombre de %s", documento, exc_info=True)
            nuevas = {}
        for clave in dudosos:
            if suyas := [lectura for lectura in nuevas.get(clave, []) if lectura]:
                lecturas[clave].extend(suyas)
                votados[clave] = nombre_por_consenso(lecturas[clave], conocidas)

    candidatos: dict[Hashable, list] = {}
    if padron is not None and len(padron):
        for clave, votado in votados.items():
            suyos = padron.parecidos(votado.nombre)
            cedula = por_clave[clave].cedula
            if (misma := padron.por_la_cedula(votado.nombre, cedula)) is not None and misma not in suyos:
                suyos = [misma, *suyos]
            if suyos:
                candidatos[clave] = suyos

    miradas = _mirar(personas, votados, lecturas, candidatos, juez, control, lectores, documento) if juez else {}

    revisados: dict[Hashable, NombreRevisado] = {}
    for clave, votado in votados.items():
        persona = por_clave[clave]
        suyas = lecturas[clave]
        corregida = None
        if votado.nombre and clave not in miradas and votado.sin_confirmar and corrector is not None:
            todas = [votado.nombre, *[lectura for lectura in suyas if lectura != votado.nombre]]
            try:
                respuesta = corrector.resumir("\n".join(f"- {lectura}" for lectura in todas if lectura))
            except Cancelled:
                raise
            except Exception:  # noqa: BLE001 - sin la IA queda lo votado
                logger.warning("la IA no corrigió un nombre de %s", documento, exc_info=True)
            else:
                corregida = corregida_comparando(votado, respuesta, todas)
        nombres_de_candidatos = [persona_del_padron.nombre for persona_del_padron in candidatos.get(clave, [])]
        decision = decidir_el_nombre(
            votado,
            suyas,
            mirada=miradas.get(clave),
            candidatos=nombres_de_candidatos,
            corregida=corregida,
            a_revision=a_revision,
        )
        revisados[clave] = NombreRevisado(
            estado=decision.estado,
            nombre=decision.nombre,
            leido=votado.leido,
            lecturas=tuple(dict.fromkeys(lectura for lectura in suyas if lectura)),
            motivo=decision.motivo,
            de_la_ia=miradas.get(clave),
            candidatos=tuple(nombres_de_candidatos),
            pagina=persona.pagina,
            preguntado_a_la_ia=clave in miradas or corregida is not None,
            por_la_ia=decision.por_la_ia,
        )
    return revisados


def zona_para_mirar(source, pagina: int, regla, *, dpi: int = 200) -> bytes | None:
    """La primera zona de la regla del nombre en la hoja ``pagina``, en JPEG, para la IA que mira el nombre.

    Para los lectores de la aplicación (libros de diplomas, legajos de
    matrículas), que no ubican su renglón: la regla de su perfil dice en qué
    parte de la hoja escribe su papel el nombre.
    """
    from .ports import Band

    if regla is None or not regla.zonas:
        return None
    arriba, abajo = regla.zonas[0]
    try:
        return source.render(pagina, Band(0.0, arriba, 1.0, abajo), dpi, formato="jpeg")
    except TypeError:
        # Una fuente que no sabe de formatos: el PNG de siempre.
        return source.render(pagina, Band(0.0, arriba, 1.0, abajo), dpi)
    except Exception:  # noqa: BLE001 - sin imagen, el nombre queda como se leyó
        logger.debug("no se pudo recortar el nombre de la página %s", pagina, exc_info=True)
        return None


def de_la_habilidad(habilidad: str):
    """La regla del nombre del perfil de la habilidad; ``None`` si no tiene una persona por documento."""
    from .perfiles_de_revision import perfil_de

    try:
        return perfil_de(habilidad).regla_del_nombre
    except Exception:  # noqa: BLE001 - sin perfil, sin regla
        return None


def _mirar(personas, votados, lecturas, candidatos, juez, control, lectores, documento) -> dict[Hashable, str]:
    """Lo que contesta la IA de cada persona, mirando su renglón con sus lecturas y sus candidatos al lado.

    Las imágenes se recortan de a una, en este hilo: el documento no se lee
    desde dos. Las preguntas van de a ``lectores``.
    """
    imagenes: dict[Hashable, bytes] = {}
    for persona in personas:
        if not votados[persona.clave].nombre or persona.imagen is None:
            continue
        if control is not None:
            control.check()
        try:
            imagen = persona.imagen()
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - sin imagen, su nombre queda votado
            logger.debug("no se pudo recortar el nombre de %s en %s", persona.clave, documento, exc_info=True)
            imagen = None
        if imagen:
            imagenes[persona.clave] = imagen

    def preguntar(clave: Hashable) -> tuple[Hashable, str | None]:
        suyas = list(dict.fromkeys(lectura for lectura in [votados[clave].nombre, *lecturas[clave]] if lectura))
        texto = "\n".join(f"- {lectura}" for lectura in suyas)
        if pista := para_la_ia(candidatos.get(clave, []), next((p.cedula for p in personas if p.clave == clave), None)):
            texto = f"{texto}\n\n{pista}"
        try:
            return clave, juez.resumir(texto, imagen=imagenes[clave])
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - sin el juez queda lo votado
            logger.warning("la IA no miró el nombre de %s en %s", clave, documento, exc_info=True)
            return clave, None

    if not imagenes:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, lectores)) as pool:
        respuestas = dict(pool.map(preguntar, list(imagenes)))
    return {clave: respuesta for clave, respuesta in respuestas.items() if respuesta}


def anotar_en_el_informe(
    report: dict, revisados: Mapping[Hashable, NombreRevisado], documento: str, *, a_la_cola: bool = True
) -> None:
    """Lo que el revisor decidió de los nombres de un trabajo, en su informe: la misma forma en todas las habilidades.

    - las cuentas, en ``report["revision_de_nombres"]`` (la pantalla en vivo, el
      Excel de procesos y la auditoría);
    - un aviso con lo corregido y lo que va a Revisión, en ``notices``;
    - con ``a_la_cola``, lo que va a Revisión en ``review_queue`` con su página
      y su motivo (la habilidad que ya lleva sus dudas a la cola no lo pide).
    """
    resumen = report.setdefault(
        CLAVE_DEL_INFORME,
        {"revisados": 0, CONFIRMADO: 0, CORREGIDO: 0, A_REVISION: 0, SIN_DATO: 0, "preguntadas_a_la_ia": 0, "detalle": []},
    )
    corregidos = a_revision = 0
    for revisado in revisados.values():
        resumen["revisados"] += 1
        resumen[revisado.estado] = resumen.get(revisado.estado, 0) + 1
        resumen["preguntadas_a_la_ia"] += int(revisado.preguntado_a_la_ia)
        if revisado.estado in (CORREGIDO, A_REVISION):
            resumen["detalle"].append(
                {
                    "documento": documento,
                    "pagina": revisado.pagina,
                    "estado": revisado.estado,
                    "nombre": revisado.nombre,
                    "leido": revisado.leido,
                    **({"motivo": revisado.motivo} if revisado.motivo else {}),
                }
            )
        if revisado.estado == CORREGIDO:
            corregidos += 1
        if revisado.estado == A_REVISION:
            a_revision += 1
            if a_la_cola:
                report.setdefault("review_queue", []).append(
                    {"page": revisado.pagina or 1, "reason": f"revisor de nombres, {documento}: {revisado.motivo}"}
                )
    if corregidos or a_revision:
        partes = [
            *([f"{corregidos} corregidos"] if corregidos else []),
            *([f"{a_revision} a Revisión"] if a_revision else []),
        ]
        report.setdefault("notices", []).append(f"Nombres de {documento}: {', '.join(partes)}.")
