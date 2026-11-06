"""Los patrones de cada habilidad, en un solo sitio: con ellos revisan el agente y la auditoría.

Lo pidió el operador el 2026-11-05: «centralizar el agente de revisión y el de
auditoría, estandarizarlos para todas las habilidades, ya que nos guiaremos del
margen de error, y cada habilidad tiene sus patrones: allí sabremos cómo crear
el margen de error».

Un **perfil** por habilidad dice lo que el agente necesita saber de su papel:

- sus **reglas**, dichas a la IA en pocas líneas, que mandan sobre lo que la IA
  crea ver;
- si va **una persona por PDF** -- dos cédulas en un PDF son dos personas --;
- si el agente **corrige** al procesar o sólo **señala**: corrige sólo la
  habilidad que sabe volver a nombrar y fechar lo que se mueve (la caja de
  correspondencia); en las demás el nombre y la fila del FUID salen de leer
  cada documento, y mover una hoja los dejaría mal. En todas, lo que sale del
  margen lo decide la IA si se eligió «OCR + IA»: donde no se corrige, lo que
  la IA confirma como error va a revisión con su cita, y lo que desmiente no;
- lo que **cruza por regla** -- la Habeas Data y las piezas del acuerdo de
  pago, lejos de su documento a propósito --;
- su **margen de error aceptable**, contra el que la auditoría juzga la muestra;
- los **datos que espera** de cada documento (2026-11-06): de una historia, el
  nombre, la cédula -- o la tarjeta, o la libreta militar --, el código y las
  fechas extremas (``integridad_de_los_datos``).

El revisor de cortes al procesar (``revisor_de_cortes``) y la auditoría de cierre
(``auditoria_de_la_entrega``) los leen de aquí: una habilidad nueva se revisa y
se audita con sólo añadir su perfil.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..domain.auditoria import MARGEN_ACEPTABLE
from .integridad_de_los_datos import DE_UNA_HISTORIA, DatosEsperados
from .revisor_de_cortes import REGLAS_DE_LA_CORRESPONDENCIA, Patrones


@dataclass(frozen=True, slots=True)
class PerfilDeRevision:
    """Lo que el agente revisor y la auditoría saben del papel de una habilidad."""

    clave: str
    nombre: str
    reglas: str
    una_persona_por_pdf: bool = False
    #: Si el agente corrige al procesar; si no, señala y no le pregunta a la IA.
    corrige: bool = False
    #: Si las piezas del acuerdo de pago y la Habeas Data cruzan por regla.
    cruces_del_acuerdo: bool = False
    #: El error que se acepta en una corrida de esta habilidad.
    margen_aceptable: float = MARGEN_ACEPTABLE
    #: Cómo se la nombra en la constancia, el informe o la petición.
    alias: tuple[str, ...] = field(default=())
    #: Los datos que se esperan de cada documento -- el nombre, la cédula, las
    #: fechas extremas --, que el agente revisa al procesar y la auditoría
    #: contra el FUID entregado (2026-11-06). ``None``: sólo se revisan los cortes.
    datos: DatosEsperados | None = None

    @property
    def margen(self) -> float:
        """El margen aceptable, o el de ``BOTPDF_MARGEN_ACEPTABLE_<CLAVE>`` (en por ciento)."""
        variable = "BOTPDF_MARGEN_ACEPTABLE_" + self.clave.upper().replace("-", "_")
        for nombre in (variable, "BOTPDF_MARGEN_ACEPTABLE"):
            try:
                valor = float(os.environ.get(nombre, "").replace(",", ".")) / 100
            except ValueError:
                continue
            if 0 < valor < 1:
                return valor
        return self.margen_aceptable

    def patrones(self, textos: Mapping[int, str], **de_la_ruta) -> Patrones:
        """Los patrones de esta habilidad para un PDF, con lo que la ruta sepa además.

        ``de_la_ruta`` son los que sólo sabe quien procesa -- las hojas que
        abren por una regla, las fijas, los cruces que ya calculó -- y ganan
        sobre los del perfil. Sin ellos -- la auditoría, que no ve las reglas
        de la corrida -- los cruces salen del título de cada hoja.
        """
        valores: dict[str, object] = {
            "una_persona_por_pdf": self.una_persona_por_pdf,
            "puede_mover": self.corrige,
            "puede_partir": self.corrige,
            "reglas": self.reglas,
        }
        if self.cruces_del_acuerdo and "cruces" not in de_la_ruta:
            valores["cruces"] = _cruces_del_acuerdo(textos)
        valores.update(de_la_ruta)
        return Patrones(**valores)

    def as_dict(self) -> dict[str, object]:
        """Lo que el informe y la pantalla dicen del perfil con que se revisó."""
        return {
            "clave": self.clave,
            "nombre": self.nombre,
            "una_persona_por_pdf": self.una_persona_por_pdf,
            "corrige": self.corrige,
            "margen_aceptable": self.margen,
            "datos": list(self.datos.campos) if self.datos else [],
        }


def _cruces_del_acuerdo(textos: Mapping[int, str]) -> frozenset[int]:
    """Las hojas que por su propio título son piezas del acuerdo de pago o su Habeas Data."""
    from ..domain.asunto_del_documento import (
        LEY_HABEAS_DATA,
        PIEZAS_DEL_ACUERDO,
        titulo_del_documento,
    )

    return frozenset(
        pagina
        for pagina, texto in textos.items()
        if titulo_del_documento(texto or "") in (*PIEZAS_DEL_ACUERDO, LEY_HABEAS_DATA)
    )


PERFILES: tuple[PerfilDeRevision, ...] = (
    PerfilDeRevision(
        clave="correspondencia",
        nombre="Caja de correspondencia",
        reglas=REGLAS_DE_LA_CORRESPONDENCIA,
        corrige=True,
        cruces_del_acuerdo=True,
        alias=("caja de correspondencia", "correspondencia", "segment"),
    ),
    PerfilDeRevision(
        clave="diplomas",
        nombre="Libro de diplomas",
        reglas=(
            "Libro de registro de diplomas: cada diploma es de un graduado. El encabezado impreso abre un diploma; "
            "la cara vacía o el reverso van con el de delante. Dos cédulas o dos nombres distintos son dos graduados."
        ),
        una_persona_por_pdf=True,
        alias=("libro de diplomas", "diploma", "diplomas", "registro de diplomas"),
    ),
    PerfilDeRevision(
        clave="actas-de-grado",
        nombre="Actas de grado",
        reglas=(
            "Libro de actas de grado: una por graduado, con su número de acta, su nombre, su título y su cédula. "
            "La hoja con el encabezado del acta abre; lo que sigue sin encabezado es de la misma. "
            "Dos graduados distintos nunca van en el mismo PDF."
        ),
        una_persona_por_pdf=True,
        alias=("actas de grado", "acta de grado", "acta"),
    ),
    PerfilDeRevision(
        clave="actas-de-consejo",
        nombre="Actas de consejo",
        reglas=(
            "Libro de actas de consejo: un PDF por sesión, con su portada separadora, su citación, su asistencia, "
            "su acta y sus anexos. La portada o la citación de otra sesión abre la siguiente; lo que sigue a un "
            "acta sin portada nueva es suyo."
        ),
        alias=("actas de consejo", "acta de consejo", "acta-consejo"),
    ),
    PerfilDeRevision(
        clave="historias",
        nombre="Historias académicas",
        reglas=(
            "Historias académicas: un expediente por estudiante. Su ficha abre; las notas, certificados y "
            "recibos que siguen son suyos hasta la ficha de otro estudiante. Dos estudiantes nunca van juntos."
        ),
        una_persona_por_pdf=True,
        alias=("historias academicas", "historia academica", "historia-academica", "historias"),
        datos=DE_UNA_HISTORIA,
    ),
    PerfilDeRevision(
        clave="matriculas",
        nombre="Legajo de matrículas",
        reglas=(
            "Legajo de matrículas: un expediente por persona, abierto por su carátula. Lo que sigue sin "
            "carátula nueva es suyo. Dos cédulas o dos nombres distintos son dos personas."
        ),
        una_persona_por_pdf=True,
        alias=("legajo de matriculas", "matricula", "matriculas"),
    ),
    PerfilDeRevision(
        clave="resoluciones",
        nombre="Legajo de resoluciones",
        reglas=(
            "Legajo de resoluciones: un PDF por resolución. Su número impreso en el encabezado abre; sus "
            "considerandos y su RESUELVE siguen; la copia de otra resolución que trae va dentro de ella."
        ),
        alias=("legajo de resoluciones", "resolucion", "resoluciones"),
    ),
    PerfilDeRevision(
        clave="kingspan",
        nombre="Kingspan",
        reglas=(
            "Inventario de Kingspan: un PDF por documento de la serie (001-XX-NNNNNNNN), con las facturas y "
            "causaciones grapadas detrás; lo que hay antes del primero, la portada, va con el primero."
        ),
        alias=("kingspan",),
    ),
    PerfilDeRevision(
        clave="archivos-separados",
        nombre="Archivos ya separados",
        reglas="PDF que ya son un documento cada uno: no se dividen.",
        alias=("archivos ya separados", "inventory", "inventario"),
    ),
)

#: El de lo que no se reconoce: los patrones de cualquier papel.
GENERICO = PerfilDeRevision(clave="generico", nombre="Sin habilidad reconocida", reglas="")


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().replace("_", " ").split())


def perfil_de(habilidad: str | None) -> PerfilDeRevision:
    """El perfil de una habilidad, por como la nombre la constancia, el informe o la petición."""
    buscado = _plano(habilidad or "")
    if not buscado:
        return GENERICO
    for perfil in PERFILES:
        if buscado == perfil.clave or buscado in (_plano(alias) for alias in perfil.alias):
            return perfil
    for perfil in PERFILES:
        if any(_plano(alias) in buscado for alias in perfil.alias if len(alias) > 6):
            return perfil
    return GENERICO
