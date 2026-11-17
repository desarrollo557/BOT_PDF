"""El padrón: las personas de la Universidad con su nombre bien escrito.

El operador (2026-11-17), ante los nombres de Enfermería mal leídos: «la idea es
tener los nombres de manera correcta». La letra a mano de una ficha de 1968 no
se lee perfecta ni con la IA; el mismo estudiante aparece, con su cédula, en
documentos que sí se leen bien -- un acta de grado o un diploma a máquina -- o
en un nombre que el operador ya corrigió. El padrón los junta.

De dónde sale cada persona (``fuente``) decide cuánto se le cree:

* **Lo que el operador corrigió o confirmó** en la Revisión es el papel mirado
  por una persona: con la misma cédula, el nombre del padrón se toma tal cual.
* **Lo que el bot leyó en otro documento** también pudo leerse mal: no corrige
  por su cuenta. Se le muestra a la IA que mira el renglón como candidato, y
  ella decide mirando el papel -- la regla de siempre: la lista sólo desempata
  (el operador, 2026-11-03) --.

Sus palabras se suman también a la lista de nombres conocidos que desempata el
voto: TORREGROZA o CAMACHO no estaban en ella.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass

from .historia_academica import plano
from .historia_medicina import mismo_estudiante, nombre_mirado

#: Las personas que una persona miró en el papel: con la misma cédula, mandan.
CORREGIDO_POR_EL_OPERADOR = "corregido por el operador"
CONFIRMADO_POR_EL_OPERADOR = "confirmado por el operador"
DEL_OPERADOR = frozenset({CORREGIDO_POR_EL_OPERADOR, CONFIRMADO_POR_EL_OPERADOR})
#: Las que el bot leyó en documentos con cédula: candidatas para la IA.
ACTA_DE_GRADO = "acta de grado"
DIPLOMA = "libro de diplomas"
CERTIFICADO_DE_TIEMPO = "certificado de tiempo de servicio"

#: Cuántas personas parecidas se le muestran a la IA por estudiante.
CANDIDATOS_PARA_LA_IA = 3
#: Las palabras que no dicen quién es: no sirven para buscar a la persona.
_CONECTORES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VDA", "VIUDA"})


@dataclass(frozen=True, slots=True)
class Persona:
    """Una persona del padrón: su nombre como está escrito, su cédula y de dónde salió."""

    nombre: str
    cedula: str | None = None
    fuente: str = ""
    #: El documento donde se leyó o se corrigió, para quien quiera comprobarlo.
    documento: str | None = None
    fecha: str | None = None

    @property
    def del_operador(self) -> bool:
        return self.fuente in DEL_OPERADOR

    def como_dict(self) -> dict:
        return {clave: valor for clave, valor in asdict(self).items() if valor not in (None, "")}

    @classmethod
    def de_dict(cls, datos: object) -> Persona | None:
        """La persona de una línea del padrón, o ``None`` si la línea no es una."""
        if not isinstance(datos, Mapping):
            return None
        nombre = nombre_de_persona(str(datos.get("nombre") or ""))
        if nombre is None:
            return None
        return cls(
            nombre=nombre,
            cedula=cedula_de_persona(datos.get("cedula")),
            fuente=str(datos.get("fuente") or ""),
            documento=str(datos["documento"]) if datos.get("documento") else None,
            fecha=str(datos["fecha"]) if datos.get("fecha") else None,
        )


def nombre_de_persona(texto: str | None) -> str | None:
    """El nombre en mayúsculas, sin tildes ni puntuación, si tiene forma de nombre: dos palabras de tres letras."""
    palabras = re.findall(r"[A-Z]+", plano(texto or ""))
    plenas = [palabra for palabra in palabras if len(palabra) >= 3 and palabra not in _CONECTORES]
    if len(plenas) < 2 or len(palabras) > 8:
        return None
    return " ".join(palabras)


def cedula_de_persona(texto: object) -> str | None:
    """La cédula sólo con cifras, si tiene forma de cédula: de seis a diez cifras."""
    cifras = re.sub(r"\D", "", str(texto or ""))
    return cifras if 6 <= len(cifras) <= 10 else None


# -- de dónde salen ------------------------------------------------------------------


def _limpia(fila: Mapping) -> bool:
    """Si la fila no trae ninguna duda: lo que va a revisión no entra en el padrón."""
    observaciones = plano(str(fila.get("observaciones") or fila.get("notas") or ""))
    return "REVIS" not in observaciones and "NO SE LEYO" not in observaciones


def personas_del_informe(informe: Mapping, *, documento: str | None = None, fecha: str | None = None) -> list[Persona]:
    """Las personas con nombre y cédula que dejó un trabajo terminado, de lo que se lee a máquina.

    * Las actas de grado individuales (las colectivas van escritas a mano).
    * Los libros de diplomas: el asunto del FUID es «NOMBRE - TÍTULO» y el
      consecutivo, la cédula.
    * Los certificados de tiempo de servicio.

    Ni las historias ni las nóminas: van a mano, y su nombre es justo el que
    hay que asegurar. Sólo las filas sin dudas, y sólo con cédula.
    """
    personas: list[Persona] = []
    tipo = str(informe.get("tipo") or "")
    for fila in informe.get("inventario_actas") or []:
        if not isinstance(fila, Mapping) or not _limpia(fila):
            continue
        if fila.get("tipo") == "ACTA DE GRADO" and not fila.get("acta_colectiva"):
            fuente = ACTA_DE_GRADO
        elif tipo == "certificado-tiempo":
            fuente = CERTIFICADO_DE_TIEMPO
        else:
            continue
        nombre, cedula = nombre_de_persona(fila.get("nombre")), cedula_de_persona(fila.get("cedula"))
        if nombre and cedula:
            personas.append(Persona(nombre, cedula, fuente, documento or fila.get("archivo"), fecha))
    for fila in informe.get("filas_del_fuid") or []:
        if not isinstance(fila, Mapping) or not _limpia(fila):
            continue
        asunto = str(fila.get("asunto") or "")
        inicial, final = fila.get("consecutivo_inicial"), fila.get("consecutivo_final")
        # Un diploma: «NOMBRE - TÍTULO», y el consecutivo es la cédula.
        if " - " not in asunto or inicial != final or not (cedula := cedula_de_persona(inicial)):
            continue
        if str(inicial).strip() != cedula:
            continue
        if nombre := nombre_de_persona(asunto.split(" - ", 1)[0]):
            personas.append(Persona(nombre, cedula, DIPLOMA, documento, fecha))
    return personas


# -- cómo se busca -------------------------------------------------------------------


class IndiceDelPadron:
    """El padrón listo para buscar: por cédula y por cada palabra del nombre."""

    def __init__(self, personas: Iterable[Persona]) -> None:
        self.personas: list[Persona] = list(personas)
        self._por_cedula: dict[str, list[Persona]] = {}
        self._por_palabra: dict[str, list[Persona]] = {}
        for persona in self.personas:
            if persona.cedula:
                self._por_cedula.setdefault(persona.cedula, []).append(persona)
            for palabra in set(persona.nombre.split()):
                if len(palabra) >= 4 and palabra not in _CONECTORES:
                    self._por_palabra.setdefault(palabra, []).append(persona)

    def __len__(self) -> int:
        return len(self.personas)

    @property
    def palabras(self) -> frozenset[str]:
        """Las palabras de nombre del padrón, para la lista que desempata el voto."""
        return frozenset(
            palabra
            for persona in self.personas
            for palabra in persona.nombre.split()
            if len(palabra) >= 3 and palabra not in _CONECTORES
        )

    def por_la_cedula(self, nombre: str | None, cedula: str | None) -> Persona | None:
        """La persona con esa cédula y un nombre del mismo estudiante; la del operador, si la hay.

        Si el padrón trae dos nombres distintos para la misma cédula y ninguno lo
        dio el operador, ninguno: no se sabe cuál es.
        """
        cifras = cedula_de_persona(cedula)
        if not cifras:
            return None
        suyas = [
            persona
            for persona in self._por_cedula.get(cifras, [])
            if not nombre or mismo_estudiante(nombre, persona.nombre)
        ]
        if not suyas:
            return None
        del_operador = [persona for persona in suyas if persona.del_operador]
        if del_operador:
            return del_operador[-1]
        return suyas[-1] if len({persona.nombre for persona in suyas}) == 1 else None

    def parecidos(self, nombre: str | None, cuantos: int = CANDIDATOS_PARA_LA_IA) -> list[Persona]:
        """Las personas del padrón que pueden ser el mismo estudiante, de la más parecida a la menos.

        Se buscan por las palabras que el nombre leído trae bien escritas -- un
        estudiante casi siempre tiene alguna --, y se queda la que
        ``mismo_estudiante`` da por la misma persona. Una por nombre distinto.
        """
        if not nombre:
            return []
        vistas: dict[str, Persona] = {}
        for palabra in set(nombre.split()):
            for persona in self._por_palabra.get(palabra, []):
                actual = vistas.get(persona.nombre)
                if actual is None or (persona.del_operador and not actual.del_operador):
                    vistas[persona.nombre] = persona
        parecidas = [persona for persona in vistas.values() if mismo_estudiante(nombre, persona.nombre)]
        palabras = set(nombre.split())
        parecidas.sort(key=lambda persona: (-len(palabras & set(persona.nombre.split())), not persona.del_operador))
        return parecidas[:cuantos]


def con_la_grafia_de(nombre: str, persona: Persona) -> str | None:
    """El nombre leído con la grafía de la persona del padrón, palabra por palabra y en su orden.

    El padrón puede traer el nombre con los nombres primero -- el diploma dice
    «ETILVIA LEONOR CAMPO TORREGROZA» -- y la historia va con los apellidos
    primero: se corrige cada palabra en su sitio, como lo que mira la IA
    (``nombre_mirado``), y nunca se cambia a la persona.
    """
    return nombre_mirado(nombre, persona.nombre, [nombre, persona.nombre])


def para_la_ia(personas: Sequence[Persona], cedula: str | None = None) -> str:
    """Las personas parecidas del padrón, como se le muestran a la IA que mira el renglón."""
    if not personas:
        return ""
    cifras = cedula_de_persona(cedula)
    renglones = []
    for persona in personas:
        partes = [persona.nombre]
        if persona.cedula:
            partes.append(f"cédula {persona.cedula}" + (" (la misma que la ficha)" if persona.cedula == cifras else ""))
        if persona.fuente:
            partes.append(persona.fuente)
        renglones.append("- " + ", ".join(partes))
    return "Personas de la Universidad con un nombre parecido, de otros documentos:\n" + "\n".join(renglones)
