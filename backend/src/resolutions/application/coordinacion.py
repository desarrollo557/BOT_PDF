"""Lo que deciden varios equipos que procesan la misma carpeta, sin tocar el disco.

El operador, 2026-11-25: «correr 4 PC al mismo tiempo sin que ninguno se pise
los procesos, consumiendo de la misma fuente y llevando al mismo destino», por
carpetas compartidas de red. Aquí está la parte que no lee ni escribe nada --
la clave de cada PDF, a qué equipo le toca primero cada carpeta y quién sigue
vivo --; el disco lo pone ``adapters.coordinacion_en_disco``.

Nada de esto se fía del reloj de pared de otro equipo: dos PC de la red pueden
llevar la hora con minutos de diferencia. Un equipo está vivo mientras el
contador de su latido cambia, medido con el reloj monótono de quien lo mira.

Desde el 2026-11-27 la corrida tiene un **principal** (``principal_de``): el
equipo que la empezó, o quien le sigue si se cae o se retira. Hace las tareas
pesadas -- los Excel generales de a mitad de corrida, el cierre y la auditoría
final --, y el monitoreo enseña la velocidad en PDF por minuto y los recursos
de cada PC.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

#: Cada cuánto escribe su latido un equipo.
SEGUNDOS_DEL_LATIDO = 10.0
#: Sin que su contador cambie durante esto, medido por quien mira, un equipo
#: está caído y lo que tenía reclamado se puede tomar.
SEGUNDOS_PARA_DARLO_POR_CAIDO = 90.0
#: Y el propio equipo deja de entregar si lleva esto sin poder escribir su
#: latido: antes de que los demás lo den por caído (90 s), con margen.
SEGUNDOS_SIN_LATIDO_PROPIO = 45.0
#: Si la última vez que este equipo pudo mirar los latidos de los demás fue
#: hace más que esto, no juzga a nadie: su propia mirada está atrasada -- el
#: hilo esperando a un servidor que no contesta, una lectura de 467 s medida
#: el 2026-11-25 --, y vería caídos a todos los que siguen latiendo.
SEGUNDOS_DE_MIRADA_ATRASADA = 60.0

#: Cómo se le ordena parar a un equipo desde el monitoreo (2026-11-26):
#: «calma» termina lo que tiene en curso y no toma nada nuevo; «ya» es
#: «Detener», y lo que estaba leyendo lo retoman los demás. «ya» manda sobre
#: «calma».
MODOS_DE_PARAR = ("calma", "ya")
#: Desde cuántos minutos unido se da el ritmo de un equipo: antes, con el
#: arranque dentro (de 3 a 28 min de «se unió» a «reclamó» el 2026-11-26), la
#: cifra no dice nada. Vale también para su velocidad acumulada en PDF por
#: minuto (``pdf_por_minuto_promedio``, 2026-11-27).
MINUTOS_PARA_EL_RITMO = 5.0

# -- la velocidad en PDF por minuto (2026-11-27) ------------------------------
#
# El operador: «llevar un promedio de velocidad de procesamiento de archivos por
# minuto contando los PC activos, y un promedio uniéndolo a los PC que están».
# Hasta aquí sólo había ``pdf_por_hora``, acumulado desde que se unió y con lo
# reclamado que ya estaba entregado dentro.

#: La velocidad de ahora de un equipo: lo que entregó en los últimos diez
#: minutos, contado por él con su reloj monótono. Un PDF largo no la hunde ni
#: el arranque la infla.
MINUTOS_DE_LA_VENTANA = 10.0
#: Y desde cuántos minutos unido se da: con uno o dos PDF entregados la cifra
#: salta de cero a mucho.
MINUTOS_PARA_LA_VELOCIDAD = 2.0

# -- los recursos de cada PC (2026-11-27) --------------------------------------

#: Lo que lleva cada latido en ``recursos`` y lo que enseña la pantalla, en el
#: orden del contrato de ``GET /api/folder-runs/{id}/equipos``. Lo mide
#: ``adapters.recursos_del_equipo``: núcleos, CPU en %, carga, memoria y disco
#: en bytes, y qué disco se midió («/equipo/c» en Docker).
CLAVES_DE_LOS_RECURSOS = (
    "nucleos",
    "cpu",
    "carga",
    "memoria_usada",
    "memoria_total",
    "disco_libre",
    "disco_total",
    "disco",
)
#: Cuánta RAM de más tiene que tener otro PC para avisar que el principal es el
#: de menos recursos: dos PC iguales no dan la misma memoria total -- lo que se
#: reservan el sistema y la tarjeta de video --, y un aviso permanente por cien
#: megas sería ruido. De núcleos, cualquiera de más cuenta.
RAM_QUE_CUENTA = 1024**3

#: Lo que se le dice al operador cuando no se puede parar un equipo. Los mismos
#: textos en la respuesta del POST y en el «por qué no» de cada fila.
CORRIDA_TERMINADA = "Ese proceso ya había terminado"
NO_ES_COMPARTIDA = "Esta corrida no es compartida: para detenerla use «Detener»."
NO_ESTA_EN_LA_CORRIDA = "Ese equipo no está en esta corrida."

#: Lo que dice el latido de un equipo mientras se une: todavía sin corrida.
UNIENDOSE = "uniéndose"


class OrdenNoPermitida(ValueError):
    """A ese equipo no se le puede ordenar parar ahora; el motivo va en palabras, para el operador.

    Aquí y no en la API: la lanza también la coordinación, que al escribir la
    orden ve en el destino que el equipo ya se retiró (2026-11-26).
    """

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
    #: Sin una mirada buena en este tiempo, nadie cae (``SEGUNDOS_DE_MIRADA_ATRASADA``).
    atrasada: float = SEGUNDOS_DE_MIRADA_ATRASADA
    _vistos: dict[str, tuple[object, float]] = field(default_factory=dict)
    _mirando_desde: float | None = None
    _ultima_mirada: float | None = None

    def mirada(self, ahora: float, *, bien: bool) -> None:
        """Una vuelta mirando los latidos: si salió bien, la cuenta de mirar seguido sigue."""
        if not bien:
            self._mirando_desde = None
            return
        if self._mirando_desde is None:
            self._mirando_desde = ahora
        self._ultima_mirada = ahora

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
        if self._ultima_mirada is None or ahora - self._ultima_mirada > self.atrasada:
            # La mirada propia se quedó atrás (el hilo esperando a la red): lo
            # que no se ha podido ver no es que el otro haya muerto.
            return True
        return ahora - visto[1] < self.caido

    def vivos(self, ahora: float) -> list[str]:
        return sorted(equipo for equipo in list(self._vistos) if self.vivo(equipo, ahora))

    def muerto_hace(self, equipo: str, ahora: float) -> float | None:
        """Cuánto lleva caído un equipo según esta mirada; ``None`` si vive o no se le puede juzgar."""
        if self.vivo(equipo, ahora):
            return None
        visto = self._vistos.get(equipo)
        return None if visto is None else ahora - visto[1]

    def quieto_hace(self, equipo: str, ahora: float) -> float | None:
        """Cuántos segundos lleva su contador sin cambiar, según esta mirada; ``None`` si nunca se le vio.

        Para el monitoreo (2026-11-26). A diferencia de ``vivo``, no apunta a
        nadie: preguntar por un equipo nunca observado no lo cuenta entre los
        vivos de ``equipos_vivos`` ni en el reparto.
        """
        visto = self._vistos.get(equipo)
        return None if visto is None else max(0.0, ahora - visto[1])


# -- el monitoreo de equipos (2026-11-26) -------------------------------------
#
# El operador: «un monitoreo para ver los que están conectados y poder
# desconectarlos». Hasta aquí la pantalla sólo sabía cuántos equipos latían.


def la_orden_que_manda(una: object, otra: object) -> dict | None:
    """De dos órdenes de parar, la que manda: «ya» sobre «calma»; entre dos iguales, la primera.

    ``None`` si ninguna es una orden. Lo que no es «calma» ni «ya» no cuenta.
    """

    def fuerza(orden: object) -> int:
        if not isinstance(orden, Mapping):
            return 0
        return {"calma": 1, "ya": 2}.get(str(orden.get("modo")), 0)

    elegida = una if fuerza(una) >= fuerza(otra) else otra
    return dict(elegida) if isinstance(elegida, Mapping) and fuerza(elegida) else None


def _segundos_unido(unido: str | None, escrito: str | None) -> float | None:
    """Los segundos entre ``unido`` y ``escrito``, dos horas que escribe el propio equipo; ``None`` sin ellas."""
    if not unido or not escrito:
        return None
    try:
        return (datetime.fromisoformat(escrito) - datetime.fromisoformat(unido)).total_seconds()
    except (TypeError, ValueError):
        # Una hora que no se entiende, o una con zona y otra sin ella.
        return None


def pdf_por_hora(hechos: int, unido: str | None, escrito: str | None) -> float | None:
    """El ritmo de un equipo desde que se unió: ``hechos`` ÷ (``escrito`` − ``unido``), en PDF por hora.

    Las dos horas las escribe el propio equipo en su latido, así que la
    diferencia de hora entre PC no entra. ``None`` sin datos, o con menos de
    ``MINUTOS_PARA_EL_RITMO`` unido. Se queda por compatibilidad: la pantalla
    de 2026-11-27 enseña ``pdf_por_minuto`` y ``pdf_por_minuto_promedio``.
    """
    segundos = _segundos_unido(unido, escrito)
    if segundos is None or segundos < MINUTOS_PARA_EL_RITMO * 60:
        return None
    return round(max(0, hechos) * 3600 / segundos, 1)


def pdf_por_minuto(entregas: Iterable[float], *, ahora: float, unido: float | None) -> float | None:
    """La velocidad de ahora de un equipo, en PDF por minuto (2026-11-27).

    ``entregas`` son los instantes del reloj monótono del propio equipo en que
    entregó un PDF que procesó él -- no lo reclamado que ya estaba entregado --,
    y ``unido`` el instante en que se unió, con el mismo reloj. Lo entregado en
    la ventana ÷ los minutos de la ventana, que son los últimos
    ``MINUTOS_DE_LA_VENTANA`` o lo que lleva unido si es menos: recién unido,
    diez minutos enteros la hundirían. ``None`` con menos de
    ``MINUTOS_PARA_LA_VELOCIDAD`` unido. Con dos decimales.
    """
    if unido is None:
        return None
    ventana = min(MINUTOS_DE_LA_VENTANA * 60, ahora - unido)
    if ventana < MINUTOS_PARA_LA_VELOCIDAD * 60:
        return None
    cuantas = sum(1 for instante in entregas if 0 <= ahora - instante <= ventana)
    return round(cuantas * 60 / ventana, 2)


def pdf_por_minuto_promedio(entregados: int, unido: str | None, escrito: str | None) -> float | None:
    """La velocidad acumulada de un equipo: ``entregados`` ÷ (``escrito`` − ``unido``), en PDF por minuto (2026-11-27).

    Las dos horas, como en ``pdf_por_hora``, las escribe el propio equipo en su
    latido. Cuenta sólo lo que procesó y entregó él (``entregados``). ``None``
    sin datos o con menos de ``MINUTOS_PARA_EL_RITMO`` unido. Con dos decimales.
    """
    segundos = _segundos_unido(unido, escrito)
    if segundos is None or segundos < MINUTOS_PARA_EL_RITMO * 60:
        return None
    return round(max(0, entregados) * 60 / segundos, 2)


def _es_cifra(valor: object) -> bool:
    """Un número de verdad: ni ``bool``, ni NaN, ni infinito."""
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _cifra(valor: object, decimales: int) -> float | None:
    """Una velocidad del latido de otro equipo: un número no negativo, redondeado; si no, ``None``."""
    return round(float(valor), decimales) if _es_cifra(valor) and valor >= 0 else None


# -- el principal (2026-11-27) ----------------------------------------------------
#
# El operador: «necesito que desde el PC principal, que donde se ejecute primero
# sea el principal, obviamente el principal deberá tener más capacidad de
# recursos, RAM, disco». Hasta aquí no había principal: los Excel generales de a
# mitad de corrida los escribía el primero que tomaba el rol «generales» -- que
# nunca se soltaba --, y cerraba el primero que acababa.


def equipo_en_palabras(id_: str) -> str:
    """«SIAR (ad21be)» para el id «SIAR-ad21be»: el nombre del PC y su arranque.

    El nombre solo es ambiguo -- hay dos PC «SIAR» --, y el id lleva detrás las
    seis letras del arranque (``Coordinacion.id``), que no tienen guiones.
    """
    nombre, guion, arranque = str(id_).rpartition("-")
    return f"{nombre} ({arranque})" if guion and nombre and arranque else str(id_)


def _instante(iso: object) -> float | None:
    """Una hora ISO de un latido, como número para ordenar; ``None`` si no se entiende."""
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _orden_de_sucesion(id_: str, latido: Mapping[str, object]) -> tuple[bool, float, str]:
    """El que se unió antes, primero; el que no dice cuándo, al final; a igualdad, el id menor."""
    instante = _instante(latido.get("unido"))
    return (instante is None, instante or 0.0, str(id_))


def _puede_ser_principal(latido: Mapping[str, object], corrida: str) -> bool:
    """Si un equipo puede ser el principal: vivo en esta corrida, sin decir «terminado» y sin orden de parar.

    El que tiene una orden de parar se va: si siguiera de principal mientras
    termina lo suyo, el que acaba antes se retiraría dejándole el cierre, y él
    -- con la orden -- tampoco cierra. Nadie cerraría.
    """
    return (
        latido.get("corrida") == corrida
        and bool(latido.get("vivo"))
        and latido.get("estado") not in ("terminado", UNIENDOSE)
        and _orden_en_la_pantalla(latido.get("orden")) is None
    )


def principal_de(
    latidos: Mapping[str, Mapping[str, object]],
    *,
    creador_id: str | None,
    creador_nombre: str | None,
    corrida: str | None,
) -> str | None:
    """El id del principal de la corrida compartida; ``None`` sin corrida o sin nadie que pueda serlo.

    ``latidos`` es lo de ``Coordinacion.latidos``: el de cada equipo con
    ``vivo`` ya calculado por quien mira.

    1. El que la empezó (``creada_por_id`` de ``corrida.json``), si sigue vivo
       en ella, no dice «terminado» y no tiene una orden de parar.
    2. Si no, la sucesión: de los que pueden serlo, el que se unió antes
       (``unido``, la hora del propio equipo); a igualdad, el id menor.
    3. Una corrida de una versión sin ``creada_por_id``: el creador se busca por
       su nombre (``creada_por``), y de varios con ese nombre -- hay dos PC
       «SIAR» --, el que se unió antes. Si no está, la sucesión.

    Es determinista sobre la misma foto: los equipos que ven los mismos latidos
    eligen el mismo. Si por un momento dos se creen principal, el rol «cierre»
    -- creado en exclusiva -- y el cerrojo «generales» impiden que trabajen
    dos a la vez.
    """
    if corrida is None:
        return None
    candidatos = {str(id_): latido for id_, latido in latidos.items() if _puede_ser_principal(latido, corrida)}
    if not candidatos:
        return None

    def sucesion(id_: str) -> tuple[bool, float, str]:
        return _orden_de_sucesion(id_, candidatos[id_])

    if creador_id:
        if creador_id in candidatos:
            return creador_id
    elif creador_nombre:
        con_su_nombre = [id_ for id_, latido in candidatos.items() if str(latido.get("equipo") or "") == creador_nombre]
        if con_su_nombre:
            return min(con_su_nombre, key=sucesion)
    return min(candidatos, key=sucesion)


# -- los recursos de cada PC y el aviso (2026-11-27) ------------------------------


def recursos_en_la_pantalla(valor: object) -> dict[str, object] | None:
    """Los recursos de un latido con las claves de siempre y sólo cifras; ``None`` si no los trae.

    El latido de otro equipo puede traer cualquier cosa -- uno de una versión
    anterior no los lleva --: lo que no es una cifra no negativa, ``None``.
    También limpia lo que mide el propio equipo antes de escribirlo en su
    latido: lo que no se puede pasar a JSON no llega a tumbarlo.
    """
    if not isinstance(valor, Mapping):
        return None
    recursos: dict[str, object] = {}
    for clave in CLAVES_DE_LOS_RECURSOS:
        dato = valor.get(clave)
        if clave == "disco":
            recursos[clave] = dato if isinstance(dato, str) and dato else None
        elif not _es_cifra(dato) or dato < 0:
            recursos[clave] = None
        elif clave == "cpu":
            recursos[clave] = round(float(dato), 1)
        elif clave == "carga":
            recursos[clave] = round(float(dato), 2)
        else:
            # Los núcleos y los bytes, enteros.
            recursos[clave] = int(dato)
    return recursos


def _activos(equipos: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Los PC activos de la corrida: vivos y de esta corrida -- también el que se une --, sin los terminados."""
    return [
        equipo
        for equipo in equipos
        if equipo.get("de_esta_corrida") and equipo.get("vivo") and equipo.get("estado") != "terminado"
    ]


def velocidad_de_la_corrida(equipos: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """La cabecera ``velocidad`` del monitoreo: cuántos PC activos y sus PDF por minuto (2026-11-27).

    ``equipos`` son las filas de la pantalla. ``actual`` suma la velocidad de
    ahora (``pdf_por_minuto``) de los activos que la tienen, y ``acumulada`` la
    de desde que se unieron (``pdf_por_minuto_promedio``); ``por_pc`` reparte
    el total entre los que tienen cifra: un PC recién unido, sin cifra
    todavía, no baja el promedio de los demás. ``None`` si ninguno la tiene.
    ``pc`` dice entre cuántos se repartió, para que la pantalla no divida el
    total entre ``pc_activos`` cuando alguno todavía está midiendo: «6,0 entre
    3 PC» con «3,0 por PC» no cuadraba (2026-11-27).
    """
    activos = _activos(equipos)

    def sumada(clave: str) -> dict[str, float | int | None]:
        cifras = [float(equipo[clave]) for equipo in activos if _es_cifra(equipo.get(clave))]
        if not cifras:
            return {"total": None, "por_pc": None, "pc": 0}
        total = sum(cifras)
        return {"total": round(total, 2), "por_pc": round(total / len(cifras), 2), "pc": len(cifras)}

    return {
        "pc_activos": len(activos),
        "actual": sumada("pdf_por_minuto"),
        "acumulada": sumada("pdf_por_minuto_promedio"),
    }


def _gb(bytes_: float) -> str:
    """Una cantidad de memoria para el operador: «7,7 GB», «16 GB» (de 1024³ bytes, como la pantalla)."""
    texto = f"{bytes_ / 1024**3:.1f}".replace(".", ",")
    return f"{texto.removesuffix(',0')} GB"


def aviso_de_recursos(equipos: Iterable[Mapping[str, object]], principal: str | None) -> str | None:
    """Si un PC activo tiene más RAM o más núcleos que el principal, el aviso para el operador; si no, ``None``.

    No cambia quién es el principal -- el operador dijo «el primero que se
    ejecute» --: dice que convenía lanzar primero en el otro. Primero la RAM
    (con ``RAM_QUE_CUENTA`` de margen); si no, los núcleos. Del que tiene más,
    el de más; el nombre de su PC, o su id si hay otro con el mismo nombre.
    """
    equipos = list(equipos)
    del_principal = next((equipo for equipo in equipos if equipo.get("id") == principal), None)
    suyos = (del_principal or {}).get("recursos")
    if principal is None or not isinstance(suyos, Mapping):
        return None
    otros = [
        equipo for equipo in _activos(equipos)
        if equipo.get("id") != principal and isinstance(equipo.get("recursos"), Mapping)
    ]
    def nombre(equipo: Mapping[str, object]) -> str:
        # Como el resto de la pantalla, «SIAR (6ad99c)»: hay dos PC «SIAR».
        return equipo_en_palabras(str(equipo.get("id")))

    def el_de_mas(clave: str, margen: float) -> Mapping[str, object] | None:
        propio = suyos.get(clave)
        if not _es_cifra(propio):
            return None
        con_mas = [
            equipo for equipo in otros
            if _es_cifra(equipo["recursos"].get(clave)) and equipo["recursos"][clave] - propio >= margen
        ]
        return max(con_mas, key=lambda equipo: equipo["recursos"][clave], default=None)

    quien = equipo_en_palabras(principal)
    cierre = "conviene lanzar primero en el PC con más recursos."
    if (con_mas := el_de_mas("memoria_total", RAM_QUE_CUENTA)) is not None:
        return (
            f"El principal {quien} tiene menos RAM ({_gb(suyos['memoria_total'])}) que "
            f"{nombre(con_mas)} ({_gb(con_mas['recursos']['memoria_total'])}): {cierre}"
        )
    if (con_mas := el_de_mas("nucleos", 1)) is not None:
        return (
            f"El principal {quien} tiene menos núcleos ({suyos['nucleos']}) que "
            f"{nombre(con_mas)} ({con_mas['recursos']['nucleos']}): {cierre}"
        )
    return None


def por_que_no_se_puede_parar(equipo: Mapping[str, object], *, activa: bool) -> str | None:
    """Por qué no se le puede ordenar parar a un equipo de la lista, en palabras; ``None`` si se puede.

    El orden es el de la respuesta del POST: la corrida terminada, el equipo de
    otra corrida, el que ya no late (sus PDF los toman los demás solos: no hace
    falta pararlo) y el que está cerrando la corrida (termina solo).
    """
    nombre = equipo.get("id")
    if not activa:
        return CORRIDA_TERMINADA
    if not equipo.get("de_esta_corrida"):
        return NO_ESTA_EN_LA_CORRIDA
    if not equipo.get("vivo"):
        return f"«{nombre}» ya no late: sus PDF los toman los demás solos y su latido se borra a los 3 minutos."
    if equipo.get("estado") == "cerrando":
        return f"«{nombre}» está cerrando la corrida: termina solo en unos minutos."
    return None


def _orden_en_la_pantalla(orden: object) -> dict[str, object] | None:
    """La orden de parar que cumple un equipo, sin el destinatario (es la fila)."""
    if not isinstance(orden, Mapping) or orden.get("modo") not in MODOS_DE_PARAR:
        return None
    return {clave: orden.get(clave) for clave in ("modo", "por", "equipo_que_ordena", "operador", "cuando")}


def _entero(valor: object) -> int:
    """Una cuenta del latido de otro equipo; lo que no se entiende es cero."""
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _cuantos_en_curso(latido: Mapping[str, object]) -> int:
    """Cuántos PDF tiene en curso un equipo: ``en_curso_n``, el número entero.

    Los nombres de ``en_curso`` van cortados en veinte: con más de veinte a la
    vez la pantalla decía veinte (2026-11-26). Sólo el latido de una versión
    sin ``en_curso_n`` se cuenta por sus nombres.
    """
    numero = latido.get("en_curso_n")
    if isinstance(numero, int) and not isinstance(numero, bool):
        return max(0, numero)
    nombres = latido.get("en_curso")
    return len(nombres) if isinstance(nombres, (list, tuple)) else _entero(nombres)


def _de_esta_corrida(latido: Mapping[str, object], corrida: str | None) -> bool:
    """Si el latido es de esta corrida, o de un equipo que se está uniendo y puede acabar en ella.

    El que se une late sin corrida mientras espera -- hasta minutos, con el
    servidor lento --: contado como de otra corrida salía aparte, sin botones,
    y «Parar todos con calma» no lo alcanzaba (2026-11-26).
    """
    if corrida is None:
        return False
    de_la_suya = latido.get("corrida")
    return de_la_suya == corrida or (de_la_suya is None and latido.get("estado") == UNIENDOSE)


def _equipo_en_la_pantalla(
    id_: str,
    latido: Mapping[str, object],
    *,
    este: str,
    corrida: str | None,
    version: str,
    activa: bool,
    principal: str | None = None,
) -> dict[str, object]:
    """Una fila del monitoreo. Lista blanca: un campo nuevo del latido no sale si no se añade aquí."""
    quieto = latido.get("quieto_hace")
    hechos = _entero(latido.get("hechos"))
    entregados = _entero(latido.get("entregados"))
    unido = latido.get("unido") if isinstance(latido.get("unido"), str) else None
    escrito = latido.get("escrito") if isinstance(latido.get("escrito"), str) else None
    orden = _orden_en_la_pantalla(latido.get("orden"))
    equipo: dict[str, object] = {
        "id": id_,
        "equipo": str(latido.get("equipo") or id_),
        "version": latido.get("version"),
        "misma_version": str(latido.get("version") or "") == str(version or ""),
        "corrida": latido.get("corrida"),
        "de_esta_corrida": _de_esta_corrida(latido, corrida),
        "estado": str(latido.get("estado") or ""),
        "vivo": bool(latido.get("vivo")),
        "este": id_ == este,
        "hechos": hechos,
        # El latido lleva los nombres (hasta veinte) y cuántos son; la pantalla, cuántos.
        "en_curso": _cuantos_en_curso(latido),
        "unido": unido,
        "escrito": escrito,
        "quieto_hace": round(float(quieto), 1) if isinstance(quieto, (int, float)) else None,
        "pdf_por_hora": pdf_por_hora(hechos, unido, escrito),
        "orden": orden,
        # 2026-11-27: el principal, la velocidad en PDF por minuto -- la de
        # ahora la calcula el propio equipo, con su reloj monótono; la
        # acumulada, con sus dos horas -- y los recursos de su PC.
        "principal": principal is not None and id_ == principal,
        "entregados": entregados,
        "pdf_por_minuto": _cifra(latido.get("pdf_por_minuto"), 2),
        # Un latido sin «entregados» (de una versión anterior) no dice cuántos
        # entregó: su velocidad acumulada no es cero, es desconocida.
        "pdf_por_minuto_promedio": (
            pdf_por_minuto_promedio(entregados, unido, escrito) if "entregados" in latido else None
        ),
        "recursos": recursos_en_la_pantalla(latido.get("recursos")),
    }
    por_que_no = por_que_no_se_puede_parar(equipo, activa=activa)
    if por_que_no is None and orden is not None and orden["modo"] == "ya":
        # «ya» manda sobre «calma»: no queda otra orden que darle.
        por_que_no = f"«{id_}» ya se está deteniendo: se le ordenó «Parar ya»."
    equipo["se_puede_parar"] = por_que_no is None
    equipo["por_que_no"] = por_que_no
    return equipo


def resumen_de_los_equipos(
    latidos: Mapping[str, Mapping[str, object]],
    *,
    este: str,
    corrida: str | None,
    version: str,
    activa: bool,
    creador_id: str | None = None,
    creador_nombre: str | None = None,
) -> dict[str, object]:
    """Los equipos de una corrida compartida, como los enseña el monitoreo.

    ``latidos`` es lo que dio ``Coordinacion.latidos``: el latido de cada
    equipo con ``vivo`` y ``quieto_hace`` ya calculados por quien mira. La
    lista va con los de esta corrida primero -- también el que se está
    uniendo, que todavía late sin corrida --, luego los vivos, luego el
    propio, y después por nombre y por id: los latidos que quedaron de otra
    corrida o de otra versión van al final, aparte y sin acciones.

    Desde el 2026-11-27, con ``creador_id`` y ``creador_nombre`` -- los de
    ``corrida.json`` --, la cabecera dice quién es el ``principal``
    (``principal_de``, sobre esta misma foto), la ``velocidad`` de la corrida
    (``velocidad_de_la_corrida``) y el ``aviso_de_recursos``.
    """
    principal = principal_de(latidos, creador_id=creador_id, creador_nombre=creador_nombre, corrida=corrida)
    equipos = [
        _equipo_en_la_pantalla(
            str(id_), latido, este=este, corrida=corrida, version=version, activa=activa, principal=principal
        )
        for id_, latido in latidos.items()
    ]
    equipos.sort(
        key=lambda e: (
            not e["de_esta_corrida"],
            not e["vivo"],
            not e["este"],
            str(e["equipo"]).casefold(),
            str(e["id"]),
        )
    )
    return {
        "compartida": True,
        "corrida": corrida,
        "version": version,
        "este": este,
        "activa": activa,
        "principal": principal,
        "velocidad": velocidad_de_la_corrida(equipos),
        "aviso_de_recursos": aviso_de_recursos(equipos, principal),
        "equipos": equipos,
    }


def resumen_de_la_corrida_sola(*, version: str, activa: bool) -> dict[str, object]:
    """Lo que contesta el monitoreo de una corrida que va sola: sin equipos, sin principal y sin velocidad."""
    return {
        "compartida": False,
        "corrida": None,
        "version": version,
        "este": None,
        "activa": activa,
        "principal": None,
        "velocidad": velocidad_de_la_corrida([]),
        "aviso_de_recursos": None,
        "equipos": [],
    }
