"""Los datos que se esperan de cada documento entregado, y lo que no cuadra en ellos.

Lo pidió el operador el 2026-11-06, antes de procesar Enfermería por segunda
vez: que los dos agentes -- el que revisa al procesar y el que audita al cerrar
-- «se aseguren de que lo que esperemos sea íntegro», no sólo los cortes:
«siempre y cuando tenga cédula, o TI, o libreta militar, al igual con los
nombres… que los documentos cumplan su margen de error y estén ok según el
patrón y los datos esperados»; y de las historias, «necesitamos muy bien las
fechas extremas, inicial y final de cada historia académica».

Cada habilidad dice qué espera de sus documentos. Aquí, lo de las **historias
académicas**: el nombre del estudiante, con qué se le identifica -- cédula,
tarjeta de identidad o libreta militar --, su código y los años de su primera y
su última nota. Cada cosa que no cuadra es un ``Hallazgo``:

- **error**: lo que no puede estar bien -- un nombre con cifras o con texto de
  la ficha, una cédula de nueve cifras, una fecha final anterior a la inicial,
  un año que no existe, un PDF que no se llama como su fila, una historia sin
  nombre o sin fechas (ninguna fila sin fecha) --;
- **duda**: lo que puede faltar en el papel y hay que mirar -- una ficha sin
  cédula, sin tarjeta y sin libreta; sin código; un código que dice otro año de
  ingreso; una historia de más de doce años --.

Sin leer nada: sólo con lo que ya se leyó, al procesar, o con lo que dice el
FUID entregado, al auditar.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .historia_academica import (
    CEDULA,
    EN_BLANCO,
    ILEGIBLE,
    LIBRETA,
    NO_APARECE,
    SIN_VERIFICAR,
    TARJETA,
)

ERROR = "error"
DUDA = "duda"
#: Lo que el agente buscó otra vez y el papel no trae: la casilla está en
#: blanco o no existe en esa ficha. No es un error ni algo que mirar: se dice,
#: para que nadie lo busque (2026-11-06).
VERIFICADO_EN_BLANCO = "en blanco"

NOMBRE = "nombre"
IDENTIFICACION = "identificacion"
CODIGO = "codigo"
FECHAS = "fechas"
ARCHIVO = "archivo"

#: Lo que se espera de una historia académica, en el orden en que se dice.
CAMPOS_DE_UNA_HISTORIA = (NOMBRE, IDENTIFICACION, CODIGO, FECHAS)

#: Cómo se nombra cada campo para el operador.
ETIQUETAS = {
    NOMBRE: "Nombre",
    IDENTIFICACION: "Cédula, TI o libreta",
    CODIGO: "Código",
    FECHAS: "Fechas extremas",
    ARCHIVO: "Nombre del PDF",
}

#: Los años posibles de una historia: desde la primera de la Universidad que
#: se ha visto hasta el año en curso.
DESDE = 1920
#: Más años que éstos entre la primera y la última nota no es imposible -- un
#: reingreso --, pero merece mirarse: una carrera de Enfermería dura cinco.
MAXIMO_DE_ANIOS = 12

#: Palabras de la plantilla que delatan que el nombre se leyó mal: el renglón
#: de al lado, el encabezado.
_DE_LA_PLANTILLA = frozenset({
    "HISTORIA", "ACADEMICA", "ESTUDIANTE", "NOMBRE", "NOMBRES", "APELLIDOS", "CEDULA", "CODIGO",
    "FACULTAD", "UNIVERSIDAD", "ENFERMERIA", "MEDICINA", "TARJETA", "LIBRETA", "MILITAR", "FECHA",
    "NACIMIENTO", "DIRECCION", "TELEFONO", "SEXO", "OBSERVACIONES", "REVISAR", "PAGINAS",
})


@dataclass(frozen=True, slots=True)
class Hallazgo:
    """Una cosa que no cuadra en los datos de un documento."""

    campo: str
    gravedad: str
    texto: str

    def as_dict(self) -> dict[str, str]:
        return {"campo": self.campo, "gravedad": self.gravedad, "texto": self.texto}


@dataclass(frozen=True, slots=True)
class DatosDeUnaHistoria:
    """Lo que se sabe de la historia de un estudiante: al procesarla o leído del FUID entregado.

    ``tipo_de_identificacion`` es «cédula», «tarjeta de identidad» o «libreta
    militar» si se sabe; del FUID sólo llegan las cifras. ``hoja_suelta`` es una
    matrícula, un certificado o un recibo de Medicina, que no traen cédula ni
    código. ``archivo`` es el PDF entregado, si se quiere comprobar su nombre.
    """

    nombre: str | None
    identificacion: str | None = None
    tipo_de_identificacion: str | None = None
    codigo: str | None = None
    anio_inicial: int | None = None
    anio_final: int | None = None
    hoja_suelta: bool = False
    archivo: str | None = None
    #: Cómo quedó cada casilla que el agente buscó otra vez: «cedula»,
    #: «tarjeta», «libreta», «codigo» -> «en blanco», «no aparece»,
    #: «ilegible» o «sin verificar» (``historia_academica``).
    verificado: Mapping[str, str] = field(default_factory=dict)


def plano(texto: str) -> str:
    """Mayúsculas sin tildes, sólo letras, cifras y un guion entre palabras: como se escribe el nombre del PDF."""
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "-", sin_tildes).strip("-")


def cifras(texto: str | None) -> str:
    """Sólo las cifras; «N/A» y lo vacío no tienen ninguna."""
    return re.sub(r"\D", "", texto or "")


def _parece_cedula(numero: str) -> bool:
    """De 6 a 8 cifras, o 10 si empieza por 1 (desde 2003); 5 las de los 40 y 50."""
    return 5 <= len(numero) <= 8 or (len(numero) == 10 and numero.startswith("1"))


def _identificacion_posible(numero: str, tipo: str | None) -> str | None:
    """Por qué ese número no puede ser lo que dice ser; ``None`` si puede."""
    if tipo == CEDULA and not _parece_cedula(numero):
        return f"la cédula {numero} tiene {len(numero)} cifras: ninguna cédula tiene tantas"
    if tipo == TARJETA and not 4 <= len(numero) <= 11:
        return f"la tarjeta de identidad {numero} tiene {len(numero)} cifras"
    if tipo == LIBRETA and not 5 <= len(numero) <= 10:
        return f"la libreta militar {numero} tiene {len(numero)} cifras"
    if tipo is None and not 4 <= len(numero) <= 11:
        return f"el documento {numero} tiene {len(numero)} cifras: no es una cédula, una tarjeta ni una libreta"
    return None


#: Las que van entre nombres y apellidos: «MARIA DEL CARMEN», «DE LA ROSA».
_CONECTORES = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VDA", "VIUDA"})
#: Cómo pueden empezar dos consonantes un nombre en castellano: BRAVO, CLARA, LLANOS.
_INICIOS = frozenset({
    "BL", "BR", "CH", "CL", "CR", "DR", "FL", "FR", "GL", "GR", "LL", "PL", "PR", "TR",
    # Los de fuera que se usan aquí: STELLA, STEPHANY, SHIRLEY, THOMAS, KHAROL.
    "TH", "SH", "RH", "KR", "WH", "ST", "SC", "SP", "KH", "GH", "PH", "JH", "DH",  # DHEIRY, DHAYANA
})
#: Lo corto que sí es de un nombre: «MA.» por María.
_CORTAS = frozenset({"MA"})


def palabra_dudosa(palabra: str) -> bool:
    """Si una palabra del nombre tiene una forma que ningún nombre tiene: es la OCR, no el estudiante.

    Medido en Enfermería con «Solo OCR» (2026-11-06): «EM», «II», «VE» y «Z»
    sueltas -- trozos del renglón --, «RDSA» por ROSA, «VIANJT» por DIANIT,
    «PALJYET» por PALMET. No se exige que la palabra esté en la lista de
    nombres conocidos: tiene 557 y le faltan apellidos de verdad -- ESPRIELLA,
    MAESTRE, BENEDETTI --.
    """
    if palabra in _CONECTORES or palabra in _CORTAS:
        return False
    if len(palabra) <= 2 or not re.search(r"[AEIOUY]", palabra):
        return True
    if re.search(r"(.)\1\1", palabra) or re.search(r"[^AEIOUY]{4,}", palabra):
        return True
    if not re.match(r"[AEIOUY]", palabra) and not re.match(r"[AEIOUY]", palabra[1]) and palabra[:2] not in _INICIOS:
        return True
    # Una J o una Q seguidas de consonante no se dan en un nombre castellano
    # (sí la J con H: JHON, JHONATAN).
    return bool(re.search(r"J[^AEIOUH]|Q[^U]|Q$", palabra))


def anio_del_codigo(codigo: str) -> int | None:
    """El año de ingreso que dice el código, cuando lo dice sin duda; ``None`` si no.

    Los códigos de la Universidad empiezan por el programa y el año de ingreso:
    «549310044» (54, 1993), «5420020056» (54, 2002); los de 1968 a 1990, de seis
    cifras, por el año: «840222» (1984). Otra forma no se interpreta.
    """
    if len(codigo) == 6:
        return 1900 + int(codigo[:2])
    if len(codigo) == 9:
        anio = 1900 + int(codigo[2:4])
        return anio if anio >= 1950 else None
    if len(codigo) == 10 and DESDE <= (anio := int(codigo[2:6])) <= 2099:
        return anio
    return None


def revisar_una_historia(datos: DatosDeUnaHistoria, *, este_anio: int) -> list[Hallazgo]:
    """Lo que no cuadra en los datos de una historia académica; vacía si todo está en su sitio."""
    hallazgos: list[Hallazgo] = []

    # El nombre: siempre lo hay en una ficha, y es con lo que se busca.
    nombre = " ".join((datos.nombre or "").split())
    palabras = plano(nombre).split("-") if nombre else []
    if not nombre:
        hallazgos.append(Hallazgo(NOMBRE, ERROR, "no se leyó el nombre del estudiante"))
    elif re.search(r"\d", nombre):
        hallazgos.append(Hallazgo(NOMBRE, ERROR, f"el nombre «{nombre}» trae cifras"))
    elif ajenas := [p for p in palabras if p in _DE_LA_PLANTILLA]:
        hallazgos.append(
            Hallazgo(NOMBRE, ERROR, f"el nombre «{nombre}» trae texto de la ficha ({', '.join(ajenas)})")
        )
    elif len(palabras) < 2:
        hallazgos.append(Hallazgo(NOMBRE, DUDA, f"el nombre «{nombre}» tiene una sola palabra"))
    elif raras := [p for p in palabras if palabra_dudosa(p)]:
        hallazgos.append(
            Hallazgo(NOMBRE, DUDA, f"el nombre «{nombre}» trae palabras que no parecen de un nombre: {', '.join(raras)}")
        )

    numero = cifras(datos.identificacion)
    if not datos.hoja_suelta:
        # Cédula, tarjeta de identidad o libreta militar: alguna, si el papel la trae.
        if not numero:
            hallazgos.append(_lo_que_falta(IDENTIFICACION, ("cedula", "tarjeta", "libreta"), datos.verificado))
        elif motivo := _identificacion_posible(numero, datos.tipo_de_identificacion):
            hallazgos.append(Hallazgo(IDENTIFICACION, ERROR, motivo))

        # El código del estudiante.
        codigo = cifras(datos.codigo)
        if not codigo:
            hallazgos.append(_lo_que_falta(CODIGO, ("codigo",), datos.verificado))
        elif not 6 <= len(codigo) <= 12:
            hallazgos.append(Hallazgo(CODIGO, ERROR, f"el código {codigo} tiene {len(codigo)} cifras"))
        elif codigo == numero:
            hallazgos.append(Hallazgo(CODIGO, ERROR, f"el código {codigo} es el mismo número que la identificación"))
        elif (
            datos.anio_inicial
            and (ingreso := anio_del_codigo(codigo))
            and abs(ingreso - datos.anio_inicial) > 1
        ):
            # El código va impreso o escrito con cuidado; la fecha inicial sale
            # de los años de las notas, y si faltan las primeras queda tarde:
            # lo que hay que mirar es la fecha (Enfermería, 2026-11-06: el
            # 549310006 de quien egresó en 1996 decía ingreso en 1993 y la
            # fecha inicial salía 1996).
            hallazgos.append(
                Hallazgo(
                    FECHAS,
                    DUDA,
                    f"la fecha inicial {datos.anio_inicial} no cuadra con el código {codigo}, "
                    f"que dice ingreso en {ingreso}",
                )
            )

    # Las fechas extremas: ninguna fila sin fecha, y en su orden.
    inicial, final = datos.anio_inicial, datos.anio_final
    faltan = [que for que, anio in (("inicial", inicial), ("final", final)) if anio is None]
    if faltan:
        hallazgos.append(Hallazgo(FECHAS, ERROR, f"sin fecha {' ni '.join(faltan)}"))
    imposibles = False
    for que, anio in (("inicial", inicial), ("final", final)):
        if anio is not None and not DESDE <= anio <= este_anio:
            hallazgos.append(Hallazgo(FECHAS, ERROR, f"la fecha {que} {anio} no es un año posible"))
            imposibles = True
    if inicial is not None and final is not None and not imposibles:
        if inicial > final:
            hallazgos.append(Hallazgo(FECHAS, ERROR, f"la fecha inicial {inicial} es posterior a la final {final}"))
        elif final - inicial > MAXIMO_DE_ANIOS:
            hallazgos.append(
                Hallazgo(FECHAS, DUDA, f"{final - inicial} años entre la fecha inicial {inicial} y la final {final}")
            )

    # El PDF se llama como su fila: su nombre y su identificación.
    if datos.archivo:
        hallazgos.extend(_el_archivo(datos.archivo, nombre, numero))
    return hallazgos


def patron_de_los_codigos(codigos: Sequence[str | None]) -> str | None:
    """Cómo empiezan los códigos de una caja -- «54» en Enfermería --, si lo dicen casi todos."""
    largos = [numero for codigo in codigos if len(numero := cifras(codigo)) >= 9]
    if len(largos) < CODIGOS_PARA_EL_PATRON:
        return None
    comun, veces = Counter(codigo[:2] for codigo in largos).most_common(1)[0]
    return comun if veces / len(largos) >= PARTE_DEL_PATRON else None


def codigo_por_el_patron(codigo: str | None, patron: str | None, anio_inicial: int | None) -> str | None:
    """El código con su primera cifra corregida por el patrón de la caja, si hay dos pruebas; ``None`` si no.

    «599010022» entre veinte «54…» (SOTO CHAQUIR) y «649010005» (VALDERRAMA,
    con el 5 escrito encima del rótulo) eran «549010022» y «549010005» en el
    papel (Enfermería, 2026-11-06). Se corrige sólo si difiere del patrón en
    **una** de sus dos primeras cifras y el año de ingreso que dice así
    corregido cuadra con su fecha inicial: dos pruebas, como el revisor.
    """
    numero = cifras(codigo)
    if not patron or len(numero) < 9 or numero.startswith(patron) or anio_inicial is None:
        return None
    if sum(1 for a, b in zip(numero[:2], patron, strict=True) if a != b) != 1:
        return None
    corregido = patron + numero[2:]
    ingreso = anio_del_codigo(corregido)
    return corregido if ingreso is not None and abs(ingreso - anio_inicial) <= 1 else None


#: Desde cuántos estudiantes, y con qué parte de ellos en orden, se cree que
#: una caja va por orden alfabético de su primer apellido.
DOCUMENTOS_PARA_EL_ORDEN = 8
PARTE_EN_ORDEN = 0.85


def _fuera_del_orden(datos: Sequence[DatosDeUnaHistoria]) -> dict[int, Hallazgo]:
    """Los nombres que rompen el orden alfabético de la caja: sus apellidos pueden ir al revés.

    Las cajas de Enfermería van por el primer apellido. Entre PERDOMO y RIOS
    salía «CASTRO REYES JACQUELINE», y el papel dice «Reyes Castro Jacqueline»
    (UPD3859734, 2026-11-06). Sólo si la caja va en orden -- casi todos sus
    vecinos lo están -- y el nombre no cabe entre los dos suyos, que sí lo están.
    """
    fuera: dict[int, Hallazgo] = {}
    for i, (antes, despues) in _los_que_no_caben([d.nombre for d in datos]).items():
        fuera[i] = Hallazgo(
            NOMBRE,
            DUDA,
            f"el nombre «{datos[i].nombre}» no sigue el orden alfabético de la caja "
            f"(va entre {antes} y {despues}): revisar el orden de los apellidos",
        )
    return fuera


def _clave_del_orden(nombre: str | None) -> str:
    """Por dónde se ordena un nombre: las dos primeras letras de su primer apellido.

    Dos letras y no la palabra entera: el archivista pone ESPRIELLA antes de
    ESPAÑA, y con la palabra entera las dos salían «fuera del orden».
    """
    return plano(nombre or "").split("-")[0][:2]


def _los_que_no_caben(nombres: Sequence[str | None]) -> dict[int, tuple[str, str]]:
    """Los nombres que no caben entre sus vecinos en una caja ordenada: posición -> (anterior, siguiente)."""
    primeras = [(i, _clave_del_orden(n), plano(n or "").split("-")[0]) for i, n in enumerate(nombres) if n]
    if len(primeras) < DOCUMENTOS_PARA_EL_ORDEN:
        return {}
    pares = list(zip(primeras, primeras[1:], strict=False))
    if sum(1 for a, b in pares if a[1] <= b[1]) / len(pares) < PARTE_EN_ORDEN:
        return {}
    fuera: dict[int, tuple[str, str]] = {}
    for k in range(1, len(primeras) - 1):
        antes, (i, clave, _), despues = primeras[k - 1], primeras[k], primeras[k + 1]
        if antes[1] <= despues[1] and not antes[1] <= clave <= despues[1]:
            fuera[i] = (antes[2], despues[2])
    return fuera


def apellidos_al_derecho(nombres: Sequence[str | None]) -> dict[int, str]:
    """Los nombres con los dos apellidos al revés, por el orden alfabético de su caja: posición -> nombre corregido.

    La IA dejaba a veces el segundo apellido delante: «CASTRO REYES JACQUELINE»
    por «Reyes Castro Jacqueline», «MARTELO CERA RUBYS» por «Cera Martelo
    Rubys» (UPD3859734, 2026-11-06). Con dos pruebas: la caja va por orden
    alfabético del primer apellido y el nombre no cabe entre sus vecinos; con
    los dos primeros nombres trocados, sí.
    """
    corregidos: dict[int, str] = {}
    for i, (antes, despues) in _los_que_no_caben(nombres).items():
        palabras = (nombres[i] or "").split()
        if len(palabras) < 3:
            continue
        trocado = " ".join([palabras[1], palabras[0], *palabras[2:]])
        if _clave_del_orden(antes) <= _clave_del_orden(trocado) <= _clave_del_orden(despues):
            corregidos[i] = trocado
    return corregidos


def _el_archivo(archivo: str, nombre: str, numero: str) -> list[Hallazgo]:
    """Si el PDF entregado lleva el nombre y la identificación de su fila del FUID."""
    base = re.sub(r"^\d{1,4}_", "", archivo.rsplit("/", 1)[-1].removesuffix(".pdf").removesuffix(".PDF"))
    hallazgos = []
    if numero and not base.endswith(numero):
        hallazgos.append(
            Hallazgo(ARCHIVO, ERROR, f"«{archivo}» no lleva la identificación {numero} de su fila")
        )
    if nombre:
        # El nombre del PDF se recorta para caber en la ruta: basta con que
        # empiece como la fila.
        esperado = plano(nombre)
        lleva = base.removesuffix(f"-{numero}") if numero else base
        if not (lleva and (esperado.startswith(lleva) or lleva.startswith(esperado))):
            hallazgos.append(Hallazgo(ARCHIVO, ERROR, f"«{archivo}» no lleva el nombre «{nombre}» de su fila"))
    return hallazgos


#: Lo que se dice de un dato que no está, según cómo quedó al buscarlo otra vez.
_FALTA = {
    IDENTIFICACION: (
        "sin cédula, tarjeta de identidad ni libreta militar: revisar en el papel",
        "la ficha no trae cédula, tarjeta de identidad ni libreta militar: sus casillas están en blanco (verificado)",
        "la cédula no se pudo confirmar en la ficha: revisarla en el papel",
        "no se leyó la cédula, la tarjeta ni la libreta militar; sin IA no se pudo verificar si la ficha la trae",
    ),
    CODIGO: (
        "no se leyó el código del estudiante",
        "la ficha no trae código ni carné estudiantil: la casilla está en blanco (verificado)",
        "el código no se pudo confirmar en la ficha: revisarlo en el papel",
        "no se leyó el código; sin IA no se pudo verificar si la ficha lo trae",
    ),
}


def _lo_que_falta(campo: str, casillas: Sequence[str], verificado: Mapping[str, str]) -> Hallazgo:
    """El hallazgo de un dato que no está: en blanco en el papel (verificado), ilegible o sin verificar.

    El operador, 2026-11-06: «haz que los agentes se aseguren cuando en
    realidad no encuentren algo». Sólo se dice que está en blanco si se miró
    otra vez cada casilla y ninguna trae nada.
    """
    sin_mirar, en_blanco, ilegible, sin_ia = _FALTA[campo]
    estados = [verificado.get(casilla) for casilla in casillas]
    if ILEGIBLE in estados:
        return Hallazgo(campo, DUDA, ilegible)
    if estados and all(estado in (EN_BLANCO, NO_APARECE) for estado in estados):
        return Hallazgo(campo, VERIFICADO_EN_BLANCO, en_blanco)
    if SIN_VERIFICAR in estados:
        return Hallazgo(campo, DUDA, sin_ia)
    return Hallazgo(campo, DUDA, sin_mirar)


#: Cuántos códigos hacen falta para saber cómo empiezan los de una caja, y qué
#: parte de ellos tiene que empezar igual.
CODIGOS_PARA_EL_PATRON = 5
PARTE_DEL_PATRON = 0.7


def revisar_entre_documentos(
    datos: Sequence[DatosDeUnaHistoria], nombres: Sequence[str] | None = None
) -> dict[int, list[Hallazgo]]:
    """Lo que no cuadra entre los documentos de un mismo PDF o de una misma caja.

    - **La misma cédula, tarjeta o libreta en dos estudiantes** es un error: la de
      VILLALOBOS GARI salía también en CONDE DIAZ, cuya ficha la trae en blanco
      (Retirados 2003, 2026-11-06). Si uno de los dos no tiene nombre, puede ser
      el mismo estudiante partido en dos PDF: también se dice.
    - **El mismo código en dos estudiantes**, igual.
    - **Un código que no empieza como los demás** de la caja -- «599010022» entre
      veinte «54…» de Enfermería -- es para mirar: una cifra mal leída.

    ``nombres`` son los de los documentos (el PDF entregado o sus páginas), para
    decir con quién choca cada uno. Devuelve, por posición, sus hallazgos.
    """
    rotulos = list(nombres) if nombres else [d.archivo or d.nombre or f"documento {i + 1}" for i, d in enumerate(datos)]
    hallazgos: dict[int, list[Hallazgo]] = {}

    def repetidos(clave, campo: str, que: str) -> None:
        por_numero: dict[str, list[int]] = {}
        for i, d in enumerate(datos):
            if numero := cifras(clave(d)):
                por_numero.setdefault(numero, []).append(i)
        for numero, suyos in por_numero.items():
            personas = {plano(datos[i].nombre or "") for i in suyos}
            if len(suyos) < 2 or (len(personas) == 1 and "" not in personas):
                continue
            for i in suyos:
                otros = ", ".join(rotulos[j] for j in suyos if j != i)
                hallazgos.setdefault(i, []).append(
                    Hallazgo(campo, ERROR, f"{que} {numero} sale también en {otros}: no puede ser de dos estudiantes")
                )

    repetidos(lambda d: d.identificacion, IDENTIFICACION, "la identificación")
    repetidos(lambda d: d.codigo, CODIGO, "el código")

    comun = patron_de_los_codigos([d.codigo for d in datos])
    if comun:
        for i, d in enumerate(datos):
            if len(codigo := cifras(d.codigo)) >= 9 and not codigo.startswith(comun):
                hallazgos.setdefault(i, []).append(
                    Hallazgo(
                        CODIGO,
                        DUDA,
                        f"el código {codigo} no empieza como los demás de esta caja ({comun}…): revisar la primera cifra",
                    )
                )
    for i, hallazgo in _fuera_del_orden(datos).items():
        hallazgos.setdefault(i, []).append(hallazgo)
    return hallazgos
