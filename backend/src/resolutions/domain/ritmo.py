"""La velocidad real de la red o del disco y cuánto le falta a una corrida.

Lo pidió el operador el 2026-11-05: «que si es por red el bot me diga y estime
en realidad cuánto es la velocidad de la red y cuánto podría demorar, cuando es
por red y cuando es por local». Eligió una prueba corta al empezar y la medida
en vivo después, con el acceso -- red o local -- del origen y del destino, los
MB/s reales, el tiempo restante separado en red y proceso, y las mismas cifras
en el inventario general de procesos.

Aquí sólo la cuenta, sin tocar la red ni el disco: las medidas las toma quien
copia (``adapters/acceso.py``, ``api/folders.py``) y las suma a un ``Ritmo``.

* La velocidad es la **real**: bytes movidos entre segundos que tardó, con la
  latencia dentro. Un PDF pequeño por la red tarda más de lo que diría su
  tamaño, y eso es justo lo que cuesta. Se mira sólo lo reciente -- las últimas
  ``MUESTRAS`` medidas --, porque la red de una oficina cambia en el día.
* Lo que falta sale del ritmo al que la corrida va terminando PDF (con el OCR,
  la IA y la red dentro), y la parte de la red, de los bytes que quedan por
  traer y llevar entre la velocidad medida.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

#: Cuántas medidas recientes cuentan para la velocidad.
MUESTRAS = 30
#: Un MB, como lo cuenta el Explorador de Windows.
MB = 1024 * 1024
#: Cuántos PDF terminados hacen falta para estimar lo que falta: con uno solo,
#: el primero -- el que espera al OCR en frío -- daría una cifra absurda.
TERMINADOS_PARA_ESTIMAR = 3
#: Cuántos terminados recientes miden el ritmo de la corrida.
VENTANA_DE_TERMINADOS = 40


@dataclass(frozen=True, slots=True)
class Medida:
    """Una copia medida: cuántos bytes, de cuándo a cuándo (reloj monótono, en segundos)."""

    bytes: int
    inicio: float
    fin: float


def tiempo_ocupado(tramos: Sequence[tuple[float, float]]) -> float:
    """Cuánto tiempo hubo al menos una copia en marcha: los tramos solapados cuentan una vez."""
    total = 0.0
    hasta = float("-inf")
    for inicio, fin in sorted(tramos):
        if fin <= hasta:
            continue
        total += fin - max(inicio, hasta)
        hasta = fin
    return total


class Ritmo:
    """Las medidas recientes de un sentido -- leer del origen o escribir en el destino --.

    Con varias copias a la vez -- la carpeta baja hasta tres PDF de un mismo
    servidor en paralelo --, cada una va a un tercio de la red. La velocidad de
    la red es la del conjunto: los bytes de todas entre el tiempo en que hubo
    alguna en marcha (``tiempo_ocupado``). Así tampoco cuentan los ratos en que
    la red estuvo quieta porque la corrida estaba haciendo OCR.
    """

    def __init__(self, muestras: int = MUESTRAS) -> None:
        self._medidas: deque[Medida] = deque(maxlen=muestras)
        self.total_bytes = 0

    def sumar(self, bytes_: int, inicio: float, fin: float) -> None:
        """Anota una copia. Las vacías o sin tiempo no dicen nada y no cuentan."""
        if bytes_ <= 0 or fin <= inicio:
            return
        self._medidas.append(Medida(int(bytes_), float(inicio), float(fin)))
        self.total_bytes += int(bytes_)

    @property
    def medidas(self) -> int:
        return len(self._medidas)

    def mb_por_segundo(self) -> float | None:
        """La velocidad de lo reciente, en MB/s; ``None`` sin medidas."""
        recientes = tuple(self._medidas)
        ocupado = tiempo_ocupado([(m.inicio, m.fin) for m in recientes])
        if not recientes or ocupado <= 0:
            return None
        return sum(m.bytes for m in recientes) / MB / ocupado


def mb_por_segundo(bytes_: int, segundos: float) -> float | None:
    """La velocidad de una sola medida, en MB/s."""
    if bytes_ <= 0 or segundos <= 0:
        return None
    return bytes_ / MB / segundos


@dataclass(frozen=True, slots=True)
class Estimacion:
    """Cuánto le falta a la corrida y cuánto de eso es la red, en segundos.

    ``total`` es ``None`` mientras no hay ritmo con qué estimar; ``al_menos``
    dice que el recorrido del origen no ha terminado y pueden aparecer más PDF.
    """

    total: float | None
    red: float | None
    al_menos: bool


def estimar(
    *,
    pendientes: int,
    terminados_en: Sequence[float],
    ahora: float,
    bytes_pendientes: int,
    lectura_mb_s: float | None,
    escritura_mb_s: float | None,
    origen_de_red: bool,
    destino_de_red: bool,
    recorrido_terminado: bool,
) -> Estimacion:
    """Lo que falta, del ritmo de los últimos PDF terminados, y la parte de la red.

    ``terminados_en`` son los instantes (reloj monótono) en que fue terminando
    cada PDF. El ritmo es el de los últimos ``VENTANA_DE_TERMINADOS``, medido
    hasta ``ahora``: si la corrida se atasca, el ritmo baja y lo que falta sube,
    en vez de quedarse en la cifra de cuando iba bien.

    La red: lo que queda por traer del origen y por llevar al destino, cada
    uno con su velocidad, sólo si ese lado es de red. Lo que sale pesa como lo
    que entra: un libro partido en cien PDF ocupa lo mismo que el libro.
    """
    red: float | None = None
    partes = []
    if origen_de_red and lectura_mb_s:
        partes.append(bytes_pendientes / MB / lectura_mb_s)
    if destino_de_red and escritura_mb_s:
        partes.append(bytes_pendientes / MB / escritura_mb_s)
    if partes:
        red = sum(partes)

    total: float | None = None
    if pendientes <= 0:
        total = 0.0
    else:
        recientes = list(terminados_en)[-VENTANA_DE_TERMINADOS:]
        if len(recientes) >= TERMINADOS_PARA_ESTIMAR:
            transcurrido = ahora - recientes[0]
            if transcurrido > 0:
                # n terminados en lo que va del primero de la ventana hasta ahora.
                por_segundo = (len(recientes) - 1) / transcurrido
                if por_segundo > 0:
                    total = pendientes / por_segundo
    if total is not None and red is not None:
        # La red no puede tardar más que todo: si la corrida va más rápido de lo
        # que diría la red, es que la red se solapa con el proceso.
        red = min(red, total)
    return Estimacion(total=total, red=red, al_menos=not recorrido_terminado)


def duracion_legible(segundos: float | None) -> str:
    """«3 h 10 min», «12 min», «menos de 1 min»; «—» si no se sabe."""
    if segundos is None:
        return "—"
    minutos = round(segundos / 60)
    if minutos < 1:
        return "menos de 1 min"
    horas, minutos = divmod(minutos, 60)
    if horas >= 24:
        dias, horas = divmod(horas, 24)
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    return f"{minutos} min"


def velocidad_legible(mb_s: float | None) -> str:
    """«4,2 MB/s», «850 KB/s»; «—» si no se midió. Con coma decimal, como en Colombia."""
    if mb_s is None:
        return "—"
    if mb_s < 1:
        return f"{mb_s * 1024:.0f} KB/s"
    texto = f"{mb_s:.1f}" if mb_s < 100 else f"{mb_s:.0f}"
    return f"{texto.replace('.', ',')} MB/s"


# -- el avance de un PDF que se baja de la red ---------------------------------------------
#
# El operador, 2026-11-09: «cuando esté un archivo o un PDF a procesar en la red
# y se esté bajando, que se muestre el progreso de descarga, el tamaño del
# archivo, esos detallitos». Un PDF de 400 MB a 4 MB/s pasaba casi dos minutos
# diciendo «Bajando el PDF de la red», sin cifras.

#: Lo que se espera entre un aviso y el siguiente: la pantalla se repinta cuatro
#: veces por segundo, y con bloques de 1 MiB una red local daría cien avisos.
AVISO_DE_LA_DESCARGA = 0.25
#: Los segundos recientes que cuentan para la velocidad de una descarga: la del
#: principio, con la sesión abriéndose, no dice cómo va ahora.
VENTANA_DE_LA_DESCARGA = 2.0

ESPERANDO = "esperando"
BAJANDO = "bajando"


@dataclass
class AvanceDeLaDescarga:
    """La cuenta de una descarga, y cuándo avisar de ella.

    ``avanzar(bytes, ahora)`` recibe lo copiado hasta ahora -- en cada bloque,
    desde el hilo que copia -- y devuelve lo que hay que decir a la pantalla, o
    ``None`` si no toca todavía: como mucho cada ``intervalo`` segundos, y
    siempre al empezar y al acabar. Si lo copiado vuelve atrás es un intento
    nuevo -- la red se cortó y la copia empezó de cero --, y se cuenta de nuevo.
    """

    #: El tamaño del archivo en el origen; 0 si no se supo.
    total: int = 0
    intervalo: float = AVISO_DE_LA_DESCARGA
    ventana: float = VENTANA_DE_LA_DESCARGA
    intento: int = 1
    copiados: int = 0
    _muestras: deque = field(default_factory=deque, repr=False)
    _ultimo_aviso: float | None = None

    def esperando(self) -> dict:
        """Lo que se dice mientras espera su turno de descarga: el tamaño, sin avance."""
        return self._datos(ESPERANDO, None)

    def avanzar(self, copiados: int, ahora: float, total: int | None = None) -> dict | None:
        if total:
            self.total = total
        if copiados < self.copiados:
            # La copia volvió a empezar: otro intento, otra velocidad.
            self.intento += 1
            self._muestras.clear()
            self._ultimo_aviso = None
        self.copiados = copiados
        self._muestras.append((ahora, copiados))
        while len(self._muestras) > 2 and ahora - self._muestras[0][0] > self.ventana:
            self._muestras.popleft()
        acabo = bool(self.total) and copiados >= self.total
        if (
            self._ultimo_aviso is not None
            and not acabo
            and ahora - self._ultimo_aviso < self.intervalo
        ):
            return None
        self._ultimo_aviso = ahora
        return self._datos(BAJANDO, self._mb_s())

    def _mb_s(self) -> float | None:
        if len(self._muestras) < 2:
            return None
        (desde, antes), (hasta, ahora) = self._muestras[0], self._muestras[-1]
        if hasta <= desde:
            return None
        return max(0.0, (ahora - antes) / MB / (hasta - desde))

    def _datos(self, estado: str, mb_s: float | None) -> dict:
        falta = None
        if mb_s and self.total and self.total > self.copiados:
            falta = round((self.total - self.copiados) / MB / mb_s, 1)
        return {
            "estado": estado,
            "bytes": self.copiados,
            "total": self.total,
            "mb_s": round(mb_s, 2) if mb_s is not None else None,
            "velocidad": velocidad_legible(mb_s) if mb_s is not None else "",
            "falta_s": falta,
            "intento": self.intento,
        }


def tamano_legible(bytes_: int) -> str:
    """«410 MB», «2,4 MB», «1,6 GB», «850 KB»: base 1024 y coma decimal, como la velocidad."""
    if round(bytes_ / 1024) < 1024:
        return f"{bytes_ / 1024:.0f} KB"
    mb = bytes_ / MB
    if round(mb) >= 1024:
        return f"{mb / 1024:.1f} GB".replace(".", ",")
    # «9,96» redondea a «10»: sin decimal, como lo de diez para arriba.
    return (f"{mb:.1f}" if round(mb, 1) < 10 else f"{mb:.0f}").replace(".", ",") + " MB"


def _de(copiados: int, total: int) -> str:
    """«123 de 410 MB»; con unidades distintas, «850 KB de 410 MB»."""
    hecho, todo = tamano_legible(copiados), tamano_legible(total)
    cifra, unidad = hecho.rsplit(" ", 1)
    return f"{cifra} de {todo}" if todo.endswith(" " + unidad) else f"{hecho} de {todo}"


def frase_de_la_descarga(datos: dict | None) -> str:
    """La línea de la descarga en palabras, para quien no sabe pintar la barra.

    «Bajando de la red · 123 de 410 MB · 3,5 MB/s», «Esperando turno para
    bajar de la red · 410 MB». La pantalla de la corrida pinta además la barra
    con los datos sueltos.
    """
    if not datos:
        return ""
    total = int(datos.get("total") or 0)
    if datos.get("estado") == ESPERANDO:
        return "Esperando turno para bajar de la red" + (f" · {tamano_legible(total)}" if total else "")
    partes = ["Bajando de la red"]
    copiados = int(datos.get("bytes") or 0)
    partes.append(_de(copiados, total) if total else tamano_legible(copiados))
    if datos.get("velocidad"):
        partes.append(str(datos["velocidad"]))
    return " · ".join(partes)
