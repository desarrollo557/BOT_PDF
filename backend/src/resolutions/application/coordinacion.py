"""Lo que deciden varios equipos que procesan la misma carpeta, sin tocar el disco.

El operador, 2026-11-25: «correr 4 PC al mismo tiempo sin que ninguno se pise
los procesos, consumiendo de la misma fuente y llevando al mismo destino», por
carpetas compartidas de red. Aquí está la parte que no lee ni escribe nada --
la clave de cada PDF, a qué equipo le toca primero cada carpeta y quién sigue
vivo --; el disco lo pone ``adapters.coordinacion_en_disco``.

Nada de esto se fía del reloj de pared de otro equipo: dos PC de la red pueden
llevar la hora con minutos de diferencia. Un equipo está vivo mientras el
contador de su latido cambia, medido con el reloj monótono de quien lo mira.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

#: Cada cuánto escribe su latido un equipo.
SEGUNDOS_DEL_LATIDO = 10.0
#: Sin que su contador cambie durante esto, medido por quien mira, un equipo
#: está caído y lo que tenía reclamado se puede tomar.
SEGUNDOS_PARA_DARLO_POR_CAIDO = 90.0
#: Y el propio equipo deja de entregar si lleva esto sin poder escribir su
#: latido: antes de que los demás lo den por caído (90 s), con margen.
SEGUNDOS_SIN_LATIDO_PROPIO = 45.0

#: Las opciones de la corrida que tienen que ser las mismas en todos los
#: equipos: con otra lectura o con otra habilidad, la mitad de la carpeta
#: saldría de una forma y la otra mitad de otra.
OPCIONES_QUE_DEBEN_COINCIDIR = (
    "task",
    "tipo",
    "tipo_documento",
    "lectura",
    "corte",
    "agrupar",
    "oracle",
    "retomar",
    "territorial",
    "acta",
    "oficina",
)

#: Cómo se llama cada opción en la pantalla, para explicar la diferencia.
NOMBRE_DE_LA_OPCION = {
    "task": "tarea",
    "tipo": "tipo de documento",
    "tipo_documento": "tipo documental",
    "lectura": "lectura (Solo OCR / OCR + IA)",
    "corte": "criterio de corte",
    "agrupar": "agrupar",
    "oracle": "verificador",
    "retomar": "retomar",
    "territorial": "territorial",
    "acta": "acta",
    "oficina": "oficina",
}


def ruta_canonica(relativa: str) -> str:
    """La ruta de un PDF desde la raíz del origen, igual se lea por unidad o por SMB.

    Sin distinguir mayúsculas -- Windows no las distingue --, con «/», en NFC
    y sin espacios en los bordes de cada tramo: «UPD1.PDF» y «upd1.pdf» son el
    mismo archivo para el servidor, y tienen que ser el mismo reclamo.
    """
    plano = unicodedata.normalize("NFC", str(relativa)).replace("\\", "/")
    tramos = [t.strip() for t in plano.split("/") if t.strip() and t.strip() != "."]
    return "/".join(tramos).casefold()


def clave_de(relativa: str) -> str:
    """El nombre del reclamo de un PDF: corto, sin caracteres raros y siempre el mismo."""
    return hashlib.sha1(ruta_canonica(relativa).encode("utf-8")).hexdigest()


def carpeta_de(relativa: str) -> str:
    """La carpeta del PDF dentro del origen (su NIC), o el propio PDF si está en la raíz."""
    canonica = ruta_canonica(relativa)
    return canonica.rsplit("/", 1)[0] if "/" in canonica else canonica


def equipo_preferido(carpeta: str, equipos: Iterable[str]) -> str | None:
    """A qué equipo le toca primero una carpeta: hash de encuentro (rendezvous).

    Cada equipo calcula lo mismo sin hablar con los demás, y la carpeta entera
    -- todos los UPD de un NIC -- cae en el mismo equipo. Si entra o sale un
    equipo, sólo cambian de dueño las carpetas de ese equipo.
    """
    canonica = ruta_canonica(carpeta)

    def peso(equipo: str) -> bytes:
        return hashlib.sha1(f"{equipo}\0{canonica}".encode()).digest()

    return max(sorted(set(equipos)), key=peso, default=None)


def opciones_distintas(propias: Mapping[str, object], de_la_corrida: Mapping[str, object]) -> list[str]:
    """Las opciones en que este equipo no coincide con la corrida, en palabras."""
    distintas = []
    for clave in OPCIONES_QUE_DEBEN_COINCIDIR:
        una, otra = propias.get(clave), de_la_corrida.get(clave)
        if (una or None) != (otra or None):
            distintas.append(f"{NOMBRE_DE_LA_OPCION.get(clave, clave)}: aquí «{una or '—'}», en la corrida «{otra or '—'}»")
    return distintas


@dataclass
class Vida:
    """Quién sigue vivo, por el contador de su latido y el reloj monótono propio.

    Un equipo que nunca se ha visto no cuenta como caído hasta que pasen
    ``caido`` segundos desde que se le vio por primera vez. Y nadie se da por
    caído si este equipo no ha podido mirar los latidos de seguido durante ese
    mismo tiempo: con la red propia cortada, todos los demás parecerían
    muertos al volver, y se le quitarían sus PDF a equipos que siguen leyendo.
    """

    caido: float = SEGUNDOS_PARA_DARLO_POR_CAIDO
    _vistos: dict[str, tuple[object, float]] = field(default_factory=dict)
    _mirando_desde: float | None = None

    def mirada(self, ahora: float, *, bien: bool) -> None:
        """Una vuelta mirando los latidos: si salió bien, la cuenta de mirar seguido sigue."""
        if not bien:
            self._mirando_desde = None
        elif self._mirando_desde is None:
            self._mirando_desde = ahora

    def observar(self, equipo: str, contador: object, ahora: float) -> None:
        anterior = self._vistos.get(equipo)
        if anterior is None or anterior[0] != contador:
            self._vistos[equipo] = (contador, ahora)

    def vivo(self, equipo: str, ahora: float) -> bool:
        """Si sigue vivo. Ante la duda -- sin mirar de seguido, o recién visto --, sí."""
        visto = self._vistos.get(equipo)
        if visto is None:
            # Nunca visto: se empieza a contar desde ahora.
            self._vistos[equipo] = (None, ahora)
            return True
        if self._mirando_desde is None or ahora - self._mirando_desde < self.caido:
            return True
        return ahora - visto[1] < self.caido

    def vivos(self, ahora: float) -> list[str]:
        return sorted(equipo for equipo in list(self._vistos) if self.vivo(equipo, ahora))
