"""Los libros de nómina de la Universidad de Cartagena: qué es cada hoja y qué documento abre.

Lo pidió el operador el 2026-11-06 sobre «21. NOMINAS» del REPOSITORIO UDC --
veintisiete libros de 1966 a 2000, de la Oficina de Personal y la División de
Asuntos Laborales -- con su «ESTRUCTURA LIBROS UNICARTAGENA.pdf», cinco hojas
marcadas a mano con el asunto, el número de documento y las fechas extremas de
cada patrón. Inventariados con el FUID de la Universidad.

Las hojas de estos libros son de cinco clases:

- **La tarjeta de la Oficina de Personal** (1975 a 1981): «Apellidos …
  Nombre …», «C.C. o NIT No.», «Año de Acumulación». Una persona por tarjeta, y
  casi siempre en dos seguidas: la segunda, la del segundo semestre, repite el
  nombre sin la cédula. Asunto «NOMINAS - NOMBRE», documento = la cédula,
  fechas = el año de acumulación.
- **La hoja manuscrita con el nombre arriba** (libro de anotaciones de 1972,
  anotaciones de pago de 1974): el nombre a mano sobre la cuadrícula, a veces
  con «C.C.» y el año en su casilla. Asunto «<el libro> - NOMBRE»: «LIBRO DE
  ANOTACIONES - BEATRIZ BARRIOS J.».
- **La relación de empleados por código** (1977 a 1991), impresa: «es un
  paquete completo cuando las fechas son iguales; si las fechas extremas son
  diferentes hay que dividir el pdf». Asunto «NOMINA», fechas = la del listado.
- **Los comprobantes de nómina** impresos por computador (1991, 1992): tres o
  cuatro empleados por hoja, cada uno con su total y la fecha de pago en clave
  («910125 T O T A L»). Se parten por el mes de pago, como el listado por su
  fecha.
- **El hablador** «LISTADO DE NOMINA PERSONAL … AÑO 1992»: «divide las nóminas
  de cada año: hacer la división para cada año».

Y el índice del libro de tarjetas («INDICE AÑO 1.975 … de la página 1 a la 15»)
y, en otra carpeta, el certificado de tiempo de servicio («HACE CONSTAR»),
que abre y lleva detrás sus anexos.

Aquí sólo las reglas: qué es cada hoja por lo que dice, cómo se leen sus datos
de lo que devolvió la lectura, y cómo se juntan las hojas en documentos. Leer
es de ``api/worker/nominas.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .historia_academica import plano

#: El tipo de las filas de esta habilidad, en el informe y en el FUID.
NOMINA = "NOMINA"

# -- las plantillas de página -------------------------------------------------------

TARJETA = "tarjeta"
HOJA = "hoja"
LISTADO = "listado"
COMPROBANTE = "comprobante"
HABLADOR = "hablador"
INDICE = "indice"
CERTIFICADO = "certificado"

#: Las de una persona: cada una es de alguien, y lo que se lee de ella la nombra.
DE_PERSONA = frozenset({TARJETA, HOJA, CERTIFICADO})
#: Las de un paquete: se juntan mientras dicen la misma fecha.
DE_PAQUETE = frozenset({LISTADO, COMPROBANTE})

# -- los asuntos, como los marcó el operador -------------------------------------------

ASUNTO_DE_LA_TARJETA = "NOMINAS"
ASUNTO_DEL_LISTADO = "NOMINA"
ASUNTO_DEL_HABLADOR = "LISTADO DE NOMINA PERSONAL"
ASUNTO_DEL_INDICE = "INDICE"
ASUNTO_DEL_CERTIFICADO = "CERTIFICADO DE TIEMPO DE SERVICIO"
#: El de la hoja manuscrita cuando el nombre del libro no dice otro.
ASUNTO_DE_LA_HOJA = "LIBRO DE ANOTACIONES"

#: Lo que dice la tarjeta impresa; con dos basta (la capa rompe la mitad).
_DE_LA_TARJETA = ("OFICINA DE PERSON", "APELLIDO", "ACUMULA", "EXPEDICI", "DEDICACI", "INICIAL PRIMER")
#: Lo que dice la relación de empleados o el listado del centro de sistematización.
_DEL_LISTADO = re.compile(
    r"EMPLEA\w*\s*P\s?[O0]\s?R\s*C\s?[O0]|NOMBRE\s+DEL\s+EMPLEADO|NUM\.?\s?IDEN|SISTEMATIZACI|"
    r"LISTADO\s+DE\s+LOS\s+EMPLEADOS|RELACION\s+DE\s+EMPLEADOS"
)
#: Lo que dicen los comprobantes de nómina; con dos basta. La tarjeta también
#: imprime «Caja Previsión»: por eso dos y no uno.
_DEL_COMPROBANTE = (
    "SOBRETASA", "CAJA PREVISI", "CAP.DE PAGO", "CAP. DE PAGO", "T O T A L", "SUB.DE TRANSPORTE",
    "PRIMA DE ALIMENTA", "GTO.REPRES", "ALIMENTOS MENORES", "AFILIAC",
)


def plantilla_de(texto: str) -> str | None:
    """Qué hoja es, por lo que dice impreso; ``None`` si no lo dice (la hoja manuscrita, la tapa).

    Se mira en este orden: el certificado, el índice, el hablador, la
    relación de empleados, la tarjeta y el comprobante. La hoja manuscrita no
    trae nada impreso que la delate: es la del libro que no es de otra cosa
    (``plantilla_del_libro``).
    """
    p = plano(texto)
    if len(p) < 6:
        return None
    junto = p.replace(" ", "")
    cabeza = p[:700]
    if es_certificado(texto):
        return CERTIFICADO
    if re.search(r"\bINDICE\b", cabeza[:250]) and len(re.findall(r"PAGINA|PAG\b", p)) >= 3:
        return INDICE
    if "LISTADODENOMINA" in junto and not _DEL_LISTADO.search(p):
        return HABLADOR
    if _DEL_LISTADO.search(p):
        return LISTADO
    if sum(marca in p for marca in _DE_LA_TARJETA) >= 2:
        return TARJETA
    if sum(marca in p for marca in _DEL_COMPROBANTE) >= 2:
        return COMPROBANTE
    return None


def plantilla_del_libro(plantillas: Sequence[str | None]) -> str:
    """De qué es el libro: la plantilla de persona o de paquete que más hojas dicen; si ninguna, la hoja manuscrita.

    Un libro es de una sola cosa -- tarjetas, listados, comprobantes, hojas a
    mano --; las hojas que no dicen nada (su capa rota, una tapa) son de lo
    que es el libro. Las de 1974 no traen capa de texto ni nada impreso: son
    hojas manuscritas.
    """
    cuentas = Counter(p for p in plantillas if p in DE_PERSONA or p in DE_PAQUETE)
    return cuentas.most_common(1)[0][0] if cuentas else HOJA


# -- los años y las fechas ------------------------------------------------------------

#: «1.972» o «1972» en su casilla; no un importe («1.958,56»).
_ANIO_SUELTO = re.compile(r"(?<![\d.,$])1\.?\s?(9[0-9]\d)(?!\d|[.,]\d)")
#: «AÑO 1992», «AÑO 1.975»: sin tildes, «ANO»; la capa lo rompe en «AÑ0» o «aPo».
_ANIO_DEL_HABLADOR = re.compile(r"\bA\W?[NP]?\W?[O0]\W{0,3}(1)\W?(9\d\d)\b|\bA\W?[NP]?\W?[O0]\W{0,3}(20[0-2]\d)\b")


def anio_del_hablador(texto: str) -> int | None:
    """«LISTADO DE NOMINA PERSONAL … AÑO 1992» → 1992; también el «INDICE AÑO 1.975»."""
    hallado = _ANIO_DEL_HABLADOR.search(plano(texto))
    if not hallado:
        return None
    if hallado.group(3):
        return int(hallado.group(3))
    return int(hallado.group(1) + hallado.group(2))


#: La fecha de un listado: «3.07.84», «14.06.83», «FECHA 17.05.89». Con punto o
#: coma (Tesseract), nunca con guion: los renglones empiezan por «26-10-0001».
_FECHA_DEL_LISTADO = re.compile(r"(?<![\d.,])(\d{1,2})\s?[.,]\s?(\d{1,2})\s?[.,]\s?(\d{2})(?![\d.,]?\d)")
_PAGINA_DEL_LISTADO = re.compile(r"P\s?[AÁ4]\s?[GC6]\W{0,3}\s*(\d{1,3})\b")

#: Una fecha: día, mes y año de cuatro cifras.
Fecha = tuple[int, int, int]


#: Detrás de su rótulo, la fecha puede ir con barras y el año en dos o cuatro
#: cifras: «Fecha: 08/06/00» en los listados de Recursos Humanos de 2000.
_FECHA_CON_ROTULO = re.compile(r"FECHA\W{0,3}(\d{1,2})\s?[./\-]\s?(\d{1,2})\s?[./\-]\s?(\d{4}|\d{2})(?!\d)")


def _fecha_valida(dia: int, mes: int, anio: int) -> Fecha | None:
    """La fecha, si existe en el calendario: un «31» de un mes de treinta días es una mala lectura."""
    import calendar

    if 1 <= mes <= 12 and 1940 <= anio <= 2010 and 1 <= dia <= calendar.monthrange(anio, mes)[1]:
        return dia, mes, anio
    return None


def _siglo(anio: int) -> int:
    """«84» es 1984 y «00» es 2000: estos libros van de 1966 a 2000."""
    if anio >= 100:
        return anio
    return 2000 + anio if anio < 30 else 1900 + anio


def fecha_del_listado(texto: str) -> Fecha | None:
    """La fecha impresa en la cabecera de la relación de empleados; ``None`` si no se lee entera."""
    p = plano(texto)[:900]
    for patron in (_FECHA_CON_ROTULO, _FECHA_DEL_LISTADO):
        for hallado in patron.finditer(p):
            dia, mes, anio = (int(g) for g in hallado.groups())
            if fecha := _fecha_valida(dia, mes, _siglo(anio)):
                return fecha
    return None


def pagina_del_listado(texto: str) -> int | None:
    """El «PAG. 19» de la cabecera del listado."""
    hallado = _PAGINA_DEL_LISTADO.search(plano(texto)[:900])
    return int(hallado.group(1)) if hallado else None


#: La fecha de pago de un comprobante, en clave AAMMDD delante del total: «910125 T O T A L».
_FECHA_DE_PAGO = re.compile(r"(?<!\d)([6-9]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)\W{0,6}T\s?O\s?T\s?A\s?L")


def fechas_de_pago(texto: str) -> list[Fecha]:
    """Las fechas de pago de los comprobantes de una hoja, en su orden."""
    return [
        (int(dia), int(mes), 1900 + int(anio)) for anio, mes, dia in _FECHA_DE_PAGO.findall(plano(texto))
    ]


# -- lo que se lee de una hoja de persona ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatosDeLaHoja:
    """Lo que dice de su persona una tarjeta, una hoja manuscrita o un certificado."""

    nombre: str | None = None
    cedula: str | None = None
    anio: int | None = None
    #: La fecha entera, si la hoja la trae (el certificado).
    fecha: Fecha | None = None


#: Las palabras de la tarjeta y de la cuadrícula que no son de un nombre.
_NO_SON_DEL_NOMBRE = frozenset(
    {
        "APELLIDOS", "APELLIDO", "NOMBRE", "NOMBRES", "LUGAR", "EXPEDICION", "CARGO", "DEDICACION", "ANO",
        "ACUMULACION", "DETALLES", "SUELDO", "NETO", "PAGADO", "FECHA", "TOTAL", "DEVENGADO", "CC", "NIT",
        "NO", "PS", "PH", "SERV", "CO", "UNIVERSIDAD", "CARTAGENA", "OFICINA", "PERSONAL",
        # El rótulo «C.C.» leído como palabra: «RICARDO MORALES BOID CCI» (1974).
        "CCI", "CCL", "CCT",
    }
)


def _limpio(nombre: str) -> str | None:
    """El nombre en mayúsculas, sin tildes ni signos, sin cifras ni rótulos; ``None`` si no queda uno."""
    palabras = []
    for palabra in re.sub(r"[^A-Z\s]", " ", plano(nombre).replace(".", " ")).split():
        if palabra in _NO_SON_DEL_NOMBRE:
            continue
        # La IA a veces repite una letra suelta sin fin: «GONZALEZ D H S S S S … JACQUELINE»
        # (1977 tomo 2, 2026-11-06). Una inicial repetida seguida cuenta una vez.
        if len(palabra) == 1 and palabras and palabras[-1] == palabra:
            continue
        palabras.append(palabra)
    # Una inicial suelta al final vale («GUILLERMO PENA E»); lo que quede debe
    # traer al menos dos palabras de verdad.
    largas = [p for p in palabras if len(p) > 1]
    if len(largas) < 2:
        return None
    return " ".join(palabras)


def _cedula(trozo: str) -> str | None:
    cifras = re.sub(r"\D", "", trozo)
    return cifras if 4 <= len(cifras) <= 11 else None


_APELLIDOS = re.compile(r"APELLIDOS?\W*(.*?)\s*(?:\||NOMBRES?\b|$)")
_NOMBRE = re.compile(r"NOMBRES?\b\W*(.*?)\s*(?:\||$)")
#: La cédula tras «C. C. O NIT No.» de la tarjeta. También «N.I.T.» y «N°», que ``plano`` deja en
#: «N»; y, dentro del número, el «/» y el «|» de lo que la IA hace con él (``_cifras_de_la_tarjeta``).
_CEDULA_DE_LA_TARJETA = re.compile(r"N\W?I\W?T\W*(?:N\W?[O0º°]?\W*)?(\d(?:[\d.,\s-]|[/|](?=[\s/]*\d)){3,18})")
_ANIO_DE_LA_TARJETA = re.compile(r"ACUMULA\w*\W*(1\W?9\d\d|\d{2})\b")


def _cifras_de_la_tarjeta(crudo: str) -> str | None:
    """Las cifras de la cédula de la tarjeta, con lo que la IA hace de ellas (2026-11-06).

    - El «1» trazado como una raya larga lo transcribe «/»: «22.75/525» es
      22751525 -- salía 2275 en cuatro tarjetas --, «33/22//3» es 33122113.
    - La raya de la cuadrícula parte el número en dos celdas: «9077 | 722» es
      9077722 -- salía 9077 en tandas enteras --. Se junta sólo si lo de antes
      no es ya una cédula entera.
    """
    partes = [re.sub(r"\D", "", parte.replace("/", "1")) for parte in crudo.split("|")]
    cifras = partes[0]
    if len(cifras) < CIFRAS_DE_LA_CEDULA_DE_LA_HOJA[0] and len(partes) > 1:
        cifras += partes[1]
    return _cedula(cifras)


#: El rótulo «C.C.#» de la hoja manuscrita, como lo lee la IA. En el libro de anotaciones de
#: 1972 (2026-11-06): «c.c. f 889196», «c.e. $9064394», «ccf 3790692», «c.c.f. 3790692», «eef
#: 33114299», «26/885693»; en las anotaciones de pago de 1974, «CO/9645668», «60/9645668», «C of
#: 2933939», «CUF», «CA», «CCA», «CUA», «CCY», «ACF» y el «CCI» suelto. Dos o tres letras -- C, E
#: o A, y C, E, O, U o A -- con o sin punto, o «60», «GO», «26/»; el «#» que sale «f», «$» o «/»;
#: y nunca el principio de una palabra: «CORTEZERO» y «CERVANTES» no son un rótulo. Como dos
#: letras sueltas pueden ser de un apellido («CEA»), el rótulo vale cuando lleva detrás la
#: cédula o nada (``_tras_el_rotulo``).
_ROTULO_DE_LA_CEDULA = re.compile(
    r"(?<![A-Z0-9])(?:[CEA]\W?[CEOUA0](?:\W?[CEOAUY])?|6\W?[O0]|G\W?O|26(?=\s*/))(?:\W{0,2}[F#$/*]|[ILT])?(?![A-Z])"
)
#: Lo escrito tras el rótulo: cifras con sus puntos.
_NUMERO_TRAS_EL_ROTULO = re.compile(r"\W{0,3}(\d[\d.,]*)")
#: Un importe y no una cédula: acaba en dos decimales («9,062.00», que es «9.062.100» mal leída).
_IMPORTE = re.compile(r"[.,]\d{2}$")
#: Las cifras de una cédula entera de las hojas manuscritas: «885693», «9.062.100», «33114299».
#: Menos es una lectura a medias: la franja cortada daba «9.062».
CIFRAS_DE_LA_CEDULA_DE_LA_HOJA = (6, 11)

#: Cómo está la cédula de la hoja manuscrita tras su rótulo.
CEDULA_LEIDA = "leida"
CEDULA_EN_BLANCO = "en blanco"
CEDULA_INCOMPLETA = "incompleta"


def cedula_de_la_hoja(texto: str, *, renglones: int | None = 2) -> tuple[str | None, str | None]:
    """La cédula tras el rótulo «C.C.#» de la hoja manuscrita, y cómo está el rótulo.

    Devuelve ``(cédula, estado)``. Sin rótulo, ``(None, None)``: la hoja de
    «Dic» no lo lleva. Con un número entero detrás, ``(cifras, CEDULA_LEIDA)``.
    Sin nada escrito detrás, ``(None, CEDULA_EN_BLANCO)``: la mitad de las
    hojas de 1972 dejan el «cc#» vacío. Con cifras que no son una cédula
    entera -- menos de seis, o un importe --, ``(None, CEDULA_INCOMPLETA)``.

    El rótulo va en el renglón del nombre: se busca en los ``renglones``
    primeros desde el del nombre -- el folio de la esquina («64», «21 323») puede
    venir antes, solo -- (la cuadrícula de abajo no lo trae); en la media hoja
    de la segunda mirada, en más.
    """
    lineas = _desde_el_nombre(texto)
    estado = None
    for linea in lineas[:renglones] if renglones is not None else lineas:
        p = plano(linea)
        for rotulo in _ROTULO_DE_LA_CEDULA.finditer(p):
            # Lo de detrás del rótulo, en su celda.
            resto = p[rotulo.end() :].split("|", 1)[0]
            tras = _tras_el_rotulo(resto)
            if tras is None:
                continue
            crudo, cifras = tras
            minimo, maximo = CIFRAS_DE_LA_CEDULA_DE_LA_HOJA
            if minimo <= len(cifras) <= maximo and not _IMPORTE.search(crudo):
                return cifras, CEDULA_LEIDA
            if cifras:
                estado = CEDULA_INCOMPLETA
            elif estado is None:
                estado = CEDULA_EN_BLANCO
    return None, estado


def _tras_el_rotulo(resto: str) -> tuple[str, str] | None:
    """Lo escrito tras un rótulo de la cédula -- ``(crudo, cifras)`` --, o ``None`` si no lo es.

    Un rótulo lleva detrás su número o nada: «C OF 2933939», «CCF», «eef |».
    Lo que sigue con letras no era un rótulo sino dos letras de un nombre
    («EL DUARDO F. CEA BERMEJO C of 2001593»).
    """
    if numero := _NUMERO_TRAS_EL_ROTULO.match(resto):
        crudo = numero.group(1).rstrip(".,")
        return crudo, re.sub(r"\D", "", crudo)
    if re.search(r"[A-Z]", resto):
        return None
    return "", ""


def _desde_el_nombre(texto: str) -> list[str]:
    """Los renglones con algo escrito desde el primero con letras: el folio solo, de antes, no cuenta."""
    lineas = [linea for linea in texto.splitlines() if re.search(r"[A-Za-z0-9]", linea)]
    for i, linea in enumerate(lineas):
        if len(re.findall(r"[A-Za-z]", linea)) >= 3:
            return lineas[i:]
    return lineas


def leer_la_tarjeta(texto: str) -> DatosDeLaHoja:
    """Apellidos y nombre, cédula y año de acumulación de la cabecera de una tarjeta.

    La lectura vuelve como tabla: «| Apellidos CASTELLAR MEZA | Nombre TULIO |»,
    «| C. C. O NIT No. 9064111 | …», «| … | Año de Acumulación 1975 |». El
    nombre queda con los apellidos delante, como en la tarjeta.
    """
    p = plano(texto.replace("|", " | "))
    apellidos = _APELLIDOS.search(p)
    nombre = _NOMBRE.search(p[apellidos.end(1) :] if apellidos else p)
    completo = " ".join(parte for parte in (apellidos.group(1) if apellidos else "", nombre.group(1) if nombre else "") if parte)
    cedula = _CEDULA_DE_LA_TARJETA.search(p)
    anio = _ANIO_DE_LA_TARJETA.search(p)
    valor_del_anio = None
    if anio:
        cifras = re.sub(r"\D", "", anio.group(1))
        valor_del_anio = int(cifras) if len(cifras) == 4 else 1900 + int(cifras)
    return DatosDeLaHoja(
        nombre=_limpio(completo) if completo else None,
        cedula=_cifras_de_la_tarjeta(cedula.group(1)) if cedula else None,
        anio=valor_del_anio if valor_del_anio and 1940 <= valor_del_anio <= 2010 else None,
    )


def _sin_el_rotulo(texto: str) -> str:
    """Lo de antes del rótulo de la cédula que cierra el texto: «AINE FANDIDO FRANKY C OF » → el nombre.

    Sólo el rótulo que no lleva letras detrás: «CEA» en «EL DUARDO F. CEA
    BERMEJO C OF» es un apellido, y el nombre no se corta ahí.
    """
    for rotulo in _ROTULO_DE_LA_CEDULA.finditer(texto):
        if not re.search(r"[A-Z]", texto[rotulo.end() :]):
            return texto[: rotulo.start()]
    return texto


def leer_la_hoja(texto: str) -> DatosDeLaHoja:
    """El nombre escrito arriba de la hoja manuscrita, su «C.C.» y el año de su casilla.

    La lectura vuelve con el nombre en el primer renglón y detrás, a veces, el
    sueldo y la cédula («Guillermo Peña E. $4.223,62 c.c. f 889196»,
    «SEBASTIAN MERLANO MEZA CO/9645668»: ver ``cedula_de_la_hoja``); el año,
    «1.972», en el renglón de abajo.
    """
    # Los renglones con algo escrito, desde el primero con letras: los
    # separadores de la tabla («| --- |») no, ni el folio solo de la esquina
    # («64»), que con la franja ancha a veces va antes (1974, 2026-11-06).
    lineas = _desde_el_nombre(texto)
    nombre = None
    if lineas:
        # El nombre, en la primera celda del renglón del nombre que traiga uno:
        # lo de abajo es la cuadrícula («Sueldo devengado»), no un nombre.
        for celda in (" ".join(c.split()) for c in lineas[0].split("|")):
            p = plano(celda)
            # Lo de antes del sueldo, de la primera cifra o del rótulo de la cédula.
            corte = _sin_el_rotulo(re.split(r"\$|\d", p, maxsplit=1)[0])
            if limpio := _limpio(corte):
                nombre = limpio
                break
    cedula, _ = cedula_de_la_hoja(texto)
    anio = None
    for linea in lineas[:4]:
        if hallado := _ANIO_SUELTO.search(plano(linea)):
            anio = int("1" + hallado.group(1))
            break
    return DatosDeLaHoja(nombre=nombre, cedula=cedula, anio=anio)


_MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}
# -- el certificado de tiempo de servicio («22. CERTIFICADOS DE TIEMPO SERVICIOS») ------------

#: «CERTIFICADO No. 004», «CIRTIFICADO No. 013», «CERTIFICADO N2 086» (Nº), «Ne. 097»,
#: «CERTIFICADO NUMERO 001» (1986), también en blanco en el formulario: el certificado
#: numerado de la Sección de Archivo, y su número.
_CERTIFICADO_NUMERADO = re.compile(
    # El «2», la «E» o el «9» por la «º» sólo si no van pegados al número: «Nº 97»
    # queda «N 97» (sin la «º») y no se le puede comer el 9 (la revisión, 2026-11-06).
    r"C[EI]R?T[I1L]F[I1L]C?A[DL][O0]\s*(?:NUMERO|N\s?(?:[O0°º*%]|[2E9](?=\D))?|H\s?[O0]|#)\W{0,4}(\d{1,4})?(?!\d)"
)
#: Quién lo firma: el Secretario General, el Coordinador o el Jefe de la Sección de
#: Archivo, el Síndico habilitado (1964). No «ante el suscrito» de una copia de
#: posesión, ni los decanos ni las secretarías académicas de las facultades:
#: sus certificados son anexos.
_SUSCRITO = re.compile(
    r"(?<!ANTE )(?:EL|LA)\s+SUSCRIT[OA]\s+(?:SECRETARI[OA]\s+GENERAL|COORDINADOR\w*\s+ADMINISTRATIV|JEFE\s+DE\s+LA\s+SECCION|SINDICO)"
)
#: El encabezado del formulario: «Sección de Archivos y Correspondencia».
_FORMULARIO = re.compile(r"SECCI\w{0,2}N\s+DE\s+ARCHIV\w*\W+Y\W+CO\w*|SECC\W+CORRESPOND\w*\s+Y\s+ARCHIV")
#: La hoja que sigue un certificado de varias: «VIENEN:», «PASAN:», «HOJA Nº 2», o el «(2)»
#: pegado al número. No el verbo del cuerpo («viene laborando») ni el «(2)» de una
#: fecha («dos (2) de Febrero»), que pegaban el certificado siguiente al anterior
#: (la revisión, 2026-11-06). Se busca justo detrás del número.
_SIGUE = re.compile(r"\bVIENEN?\s*:|\bPASAN\s*:|HOJA\s+N\W{0,3}\s*[2-9]\b|^\W{0,6}\(\s*[2-9]\s*\)")
#: Lo que no es un certificado aunque lo parezca: la copia de una posesión.
_NO_ES_CERTIFICADO = re.compile(r"COPIA\s+DE\s+(?:LA\s+)?POSESION")
#: Cuánto de la hoja es su encabezado.
_ENCABEZADO = 700


@dataclass(frozen=True, slots=True)
class Encabezado:
    """Lo que dice de sí misma una hoja de certificado: si lo es, su número y si sigue otro."""

    es: bool
    numero: int | None = None
    sigue: bool = False


def encabezado_del_certificado(texto: str) -> Encabezado:
    """Si la hoja es de un certificado de tiempo de servicio, con qué número, y si continúa uno.

    Medido sobre «22. CERTIFICADOS DE TIEMPO SERVICIOS» (2026-11-06): un
    certificado es su número. Sus hojas segunda y siguientes repiten el
    encabezado con el mismo número y «VIENEN», «PASAN», «HOJA Nº 2» o «(2)»; el
    libro trae además el definitivo y sus borradores seguidos, con el mismo
    número. La carta con que se pidió, las hojas de cálculo a mano, los
    recibos, los contratos, las copias de posesión y los certificados de las
    facultades no dicen nada de eso: son anexos.
    """
    p = plano(texto)
    zona = p[:_ENCABEZADO]
    if _NO_ES_CERTIFICADO.search(zona):
        return Encabezado(es=False)
    junto = p.replace(" ", "")
    numerado = _CERTIFICADO_NUMERADO.search(zona)
    suscrito = _SUSCRITO.search(p[:1500])
    formulario = _FORMULARIO.search(zona) and "CONSTAR" in junto
    # Un «certificado No…» sin número sólo cuenta en el encabezado de verdad:
    # una carta puede decir «el certificado no se expidió» (la revisión, 2026-11-06).
    if numerado and not numerado.group(1) and not (suscrito or formulario or "SECRETARIA GENERAL" in zona):
        numerado = None
    es = bool(
        numerado
        or suscrito
        or formulario
        or ("SINDICATURA" in zona and ("HACECONSTAR" in junto or re.search(r"\bCERTIFICA\b", p)))
    )
    if not es:
        return Encabezado(es=False)
    numero = int(numerado.group(1)) if numerado and numerado.group(1) else None
    # Sin número, sólo lo que diga el principio de la hoja.
    tras_el_numero = zona[numerado.end() : numerado.end() + 250] if numerado else ""
    sigue = bool(_SIGUE.search(tras_el_numero) or re.match(r"\W*(?:VIENEN?|PASAN)\b", zona))
    return Encabezado(es=True, numero=numero, sigue=sigue)


def es_certificado(texto: str) -> bool:
    """Si la hoja es de un certificado de tiempo de servicio (la primera o una que lo continúa)."""
    return encabezado_del_certificado(texto).es


_TITULO = r"(?:SR|SRA|SENOR|SENORA|SENORITA|DR|DRA|DOCTOR|DOCTORA|LIC|LICENCIAD[OA]|ING|INGENIER[OA]|PROFESOR|PROFESORA)\.?"
#: «el (la)», que la IA lee «61 (1a)» o «él(1a)».
_ARTICULO = r"(?:EL|LA|61)\s*(?:\(\s*1?L?A\s*\))?|\(\s*1?L?A\s*\)"
#: Dónde empieza el nombre de quien se certifica: tras «Que el Doctor», tras la
#: «UNIVERSIDAD DE CARTAGENA: El (la) Señor» del formulario, o tras la
#: solicitud «formulada por el Dr.». Tras «Que» tiene que venir el artículo o el
#: título: «Que aparece como…», «que se elabore Resolución» no son nombres. Los
#: rótulos se buscan sueltos y el nombre desde cada uno: buscándolos con el
#: nombre, el «Que verificados los Libros…» se comía el «Cartagena: él (1a) Dr.
#: ANTONIO ORTEGA RODRIGUEZ» que venía detrás (1986).
_ROTULOS_DEL_NOMBRE = (
    re.compile(r"\bQUE\W+(?=(?:EL|LA|61|\(|" + _TITULO.rstrip("\\.?") + r")\b)|CARTAGENA\s*:\s*"),
    re.compile(r"FORMULADA\s+POR\s+"),
)
_NOMBRE_TRAS_EL_ROTULO = re.compile(rf"(?:{_ARTICULO})?\W*(?:{_TITULO}\W+)?([A-Z][A-Z .\-]{{3,90}})")
#: Dónde acaba: la cédula, la coma, los puntos de relleno, «identificado», «prestó», «el día».
_DESPUES_DEL_NOMBRE = re.compile(
    r"\s*(?:\.\s*\.|\.-|,|;|\bC\s?\.?\s?C\b|IDENTIFICAD|PORTADOR|PRESTO|PRESTA\b|LABORO|LABORA\b|HA\s+PRESTADO|"
    r"EXPEDID|MAYOR\s+DE|VECIN|CON\s+CEDULA|EN\s+OFICIO|DE\s+FECHA|MEDIANTE|QUIEN|EL\s+DIA\b|DESDE\b|RECIBIO|"
    r"DURANTE|DEVENGO|TRABAJO\b|SE\s+DESEMPEN|$)"
)
#: Lo que no es de un nombre: lo que trae la plantilla del certificado.
_NO_ES_UN_NOMBRE = frozenset(
    {
        "VERIFICADOS", "LIBROS", "CARPETAS", "SECCION", "ARCHIVO", "ARCHIVOS", "CORRESPONDENCIA", "UNIVERSIDAD",
        "CARTAGENA", "SOLICITUD", "OFICIO", "FECHA", "SERVICIOS", "CERTIFICA", "CONSTAR", "SECRETARIO", "GENERAL",
        "NOMINA", "NOMINAS", "DATOS", "INTERESADA", "INTERESADO", "APARECEN", "REGISTRADOS", "FIRMA", "APARECE",
        "ELABORE", "RESOLUCION", "CONTRATO", "PROFESOR", "SE", "HA",
    }
)
_CEDULA_DEL_CERTIFICADO = re.compile(
    r"(?:\bC\s?\.?\s?C\b\.?|CEDULA(?:\s+DE\s+CIUDADANIA)?)\s*(?:N\s?[O0]?\s?\.?|#|NUMERO|NRO\.?)?\s*[:.]?\s*"
    r"(\d{1,3}(?:[.,]\s?\d{3}){1,3}|\d{5,11})"
)


def _nombre_del_certificado(p: str) -> tuple[str | None, int]:
    """El nombre de quien se certifica y dónde acaba en el texto, o ``(None, 0)``."""
    for rotulo in _ROTULOS_DEL_NOMBRE:
        for hallado in rotulo.finditer(p):
            if not (nombre_hallado := _NOMBRE_TRAS_EL_ROTULO.match(p, hallado.end())):
                continue
            resto = nombre_hallado.group(1)
            corte = _DESPUES_DEL_NOMBRE.search(resto)
            crudo = resto[: corte.start()] if corte else resto
            if (nombre := _limpio(crudo)) and not set(nombre.split()) & _NO_ES_UN_NOMBRE:
                return " ".join(nombre.split()[:6]), nombre_hallado.start(1) + len(crudo)
    return None, 0


#: Un año, también partido por la máquina de escribir o por la IA: «1.993», «1.9 93», «2.000».
_ANIO_PARTIDO = r"(1\W{0,3}9\W{0,3}\d\W{0,3}\d|2\W{0,3}0\W{0,3}[0-3]\W{0,3}\d)"
#: La fecha en que se firma o se expide: «se firma en Cartagena, a los veintidós
#: (22) días del mes de Mayo del Dos Mil (2.000)», «se ha expedido el
#: Certificado número 001 … de Enero 18 de … 1.9 93».
_FECHA_DE_LA_FIRMA = (
    # «se firma [el presente certi- ficado] en Cartagena a los 26 días del mes de Enero de 1993».
    re.compile(
        r"FIRMA\w*\b.{0,80}?EN\s+CARTAGENA.{0,60}?\(?(\d{1,2})\)?\s*DIAS?\s+DEL\s+MES\s+DE\s+"
        r"([A-Z]+)\s+DE[L]?\b.{0,40}?" + _ANIO_PARTIDO
    ),
    # «Se ha expedido el Certificado número 013 de Enero 26 [de] 1.9 93».
    re.compile(
        r"(?:EXPEDIDO|EXPIDE)\s+(?:EL\s+)?CERTIFICADO.{0,40}?\bDE\s+([A-Z]+)\W{0,3}(\d{1,2})\W{0,8}(?:DE\W{0,8})?"
        + _ANIO_PARTIDO
    ),
)
#: Cualquier otra fecha: «22 de Mayo de 2000», «Enero 18 de 1993», «(22) días del mes de Mayo de 1993».
_OTRA_FECHA = (
    re.compile(r"\b(\d{1,2})\s+DE\s+([A-Z]+)\s+DE[L]?\s+" + _ANIO_PARTIDO),
    re.compile(r"\b([A-Z]+)\s+(\d{1,2})\s+DE[L]?\s+" + _ANIO_PARTIDO),
    re.compile(r"\((\d{1,2})\)\s*DIAS?\s+DEL\s+MES\s+DE\s+([A-Z]+)\s+DE[L]?\b.{0,40}?" + _ANIO_PARTIDO),
)
#: La fecha de la solicitud no es la del certificado.
_DE_LA_SOLICITUD = re.compile(r"(?:OFICIO|SOLICITUD)\s+DE\s+FECHA\W*$|\bFECHA\W*$")


def _fecha_de(hallado: re.Match) -> Fecha | None:
    """Día, mes y año de un hallazgo, sea «día de mes» o «mes día»."""
    a, b, anio = hallado.groups()
    dia, mes = (a, b) if a.isdigit() else (b, a)
    numero = _MESES.get(mes)
    cifras = re.sub(r"\D", "", anio)
    if not numero or len(cifras) != 4:
        return None
    return _fecha_valida(int(dia), numero, int(cifras))


def fecha_del_certificado(textos: Sequence[str], ventana: tuple[int, int] | None = None) -> Fecha | None:
    """La fecha de expedición del certificado, de sus hojas en su orden (puede firmarse en la segunda).

    Primero la de la firma o la expedición; si no se leyó, la última fecha que
    cae en los años del libro (el certificado trae también la fecha del oficio
    y los años de servicio: «del 29 de Marzo de 1979 al…»). La del oficio con
    que se pidió no cuenta.
    """
    firmas, ultima = _fechas_del_certificado(textos, ventana)
    return firmas[-1] if firmas else ultima


def fechas_del_certificado(textos: Sequence[str], ventana: tuple[int, int] | None = None) -> list[Fecha]:
    """Las fechas de firma de todas las versiones de un certificado -- el definitivo y sus borradores --, o la última que se lea.

    Son sus fechas extremas: el 083 de 1999 se firmó el 8 y el 12 de abril.
    """
    firmas, ultima = _fechas_del_certificado(textos, ventana)
    return firmas or ([ultima] if ultima else [])


def _fechas_del_certificado(textos: Sequence[str], ventana: tuple[int, int] | None) -> tuple[list[Fecha], Fecha | None]:
    """Las fechas de firma y la última fecha de los años del libro, en el texto seguido de sus hojas.

    Seguido, porque la frase de la firma se parte entre dos hojas: «se firma el
    presente certi-» y, en la siguiente, «… de 1993.» (AURA MACHUCA, 1993). Y
    con un año de holgura, pero si dos lecturas chocan gana la que cae en los
    años del libro: el formulario del 013 dice «Enero 26 de 1.9 93» arriba y
    «26 días del mes de Enero de 1992» al pie, en un libro de 1993.
    """

    def en_el_libro(fecha: Fecha | None, holgura: int = 1) -> bool:
        return fecha is not None and (ventana is None or ventana[0] - holgura <= fecha[2] <= ventana[1] + holgura)

    junto = plano("\n".join(textos))
    firmas: list[tuple[int, Fecha]] = []
    for patron in _FECHA_DE_LA_FIRMA:
        for hallado in patron.finditer(junto):
            if en_el_libro(fecha := _fecha_de(hallado)):
                firmas.append((hallado.start(), fecha))  # type: ignore[arg-type]
    candidatas: list[tuple[int, Fecha]] = []
    for patron in _OTRA_FECHA:
        for hallado in patron.finditer(junto):
            if _DE_LA_SOLICITUD.search(junto[max(0, hallado.start() - 30) : hallado.start()]):
                continue
            if en_el_libro(fecha := _fecha_de(hallado)):
                candidatas.append((hallado.start(), fecha))  # type: ignore[arg-type]
    de_la_firma = [f for _, f in sorted(firmas)]
    de_la_firma = [f for f in de_la_firma if en_el_libro(f, 0)] or de_la_firma
    estrictas = [c for c in candidatas if en_el_libro(c[1], 0)]
    ultima = max(estrictas or candidatas)[1] if candidatas else None
    return de_la_firma, ultima


def leer_el_certificado(texto: str, ventana: tuple[int, int] | None = None) -> DatosDeLaHoja:
    """El nombre, la cédula y la fecha del certificado de tiempo de servicio.

    «Que el Doctor JAVIER SEGOVIA FUENTES identificado con la cédula de
    ciudadanía No. 73.088.568 … a los veintidós (22) días del mes de Mayo del
    Dos Mil (2.000)»: el asunto, el número de documento y la fecha extrema que
    marcó el operador. En el formulario: «El (la) Señor TULIO CASTELLAR
    MEZA.- C.C.# 9.064.394».
    """
    p = plano(texto)
    nombre, donde = _nombre_del_certificado(p)
    # La cédula de esa persona: la primera después de su nombre; si no, la primera.
    cedula = _CEDULA_DEL_CERTIFICADO.search(p, donde) or _CEDULA_DEL_CERTIFICADO.search(p)
    fecha = fecha_del_certificado([texto], ventana)
    return DatosDeLaHoja(
        nombre=nombre,
        cedula=_cedula(cedula.group(1)) if cedula else None,
        anio=fecha[2] if fecha else None,
        fecha=fecha,
    )


def leer_los_datos(texto: str, plantilla: str) -> DatosDeLaHoja:
    """Lo que dice de su persona la hoja, según su plantilla."""
    if plantilla == TARJETA:
        return leer_la_tarjeta(texto)
    if plantilla == CERTIFICADO:
        return leer_el_certificado(texto)
    return leer_la_hoja(texto)


def _cifras(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


#: Cuánto se parecen dos lecturas del nombre para tomarlas por la misma persona.
PARECIDO_DEL_NOMBRE = 0.8


def mismo_nombre(a: str | None, b: str | None) -> bool:
    """Si dos lecturas del nombre son de la misma persona: iguales, casi iguales o una dentro de la otra.

    «SOTOMAYOR H. CARMELINA» y «SOTOMAYOR H CARMELINA», «JULIO CASTELLAR M.» y
    «JULIO CASTELLAR»: la segunda tarjeta repite el nombre con otra letra.
    """
    if not a or not b:
        return False
    uno, otro = plano(a).replace(".", ""), plano(b).replace(".", "")
    if uno == otro or SequenceMatcher(None, uno, otro).ratio() >= PARECIDO_DEL_NOMBRE:
        return True
    corto, largo = sorted((uno.split(), otro.split()), key=len)
    largas = [p for p in corto if len(p) > 1]
    return len(largas) >= 2 and all(any(q.startswith(p) or p.startswith(q) for q in largo) for p in corto)


#: Cuántas cifras pueden diferir dos lecturas de la misma cédula.
CIFRAS_MAL_LEIDAS = 2


def misma_persona(a: DatosDeLaHoja, b: DatosDeLaHoja) -> bool:
    """Si dos hojas seguidas son de la misma persona: por el nombre, y nunca con dos cédulas distintas.

    Dos lecturas de la misma cédula que difieren en una o dos cifras («9064111»
    y «906411») son la misma mal leída, no dos personas.
    """
    from .text_distance import damerau_levenshtein

    cedula_a, cedula_b = _cifras(a.cedula), _cifras(b.cedula)
    if cedula_a and cedula_b and damerau_levenshtein(cedula_a, cedula_b) > CIFRAS_MAL_LEIDAS:
        return False
    return mismo_nombre(a.nombre, b.nombre)


def sin_cedulas_copiadas(datos: Sequence[DatosDeLaHoja | None]) -> tuple[list[DatosDeLaHoja | None], dict[int, str]]:
    """Las lecturas sin la cédula que la IA copió de la hoja vecina; y, por posición, lo que se quitó.

    La tarjeta que continúa trae la casilla «C.C.» en blanco, y la IA, leyendo
    diez tarjetas seguidas, a veces la rellena con la de la tarjeta de abajo:
    SOTOMAYOR H. CARMELINA salió con la cédula de MERCADO SANTANA BENITO y se
    partió en dos (nómina de 1975, 2026-11-06); a veces la copia sale con una
    cifra cambiada («3313330P» por 33133308). La copia cae siempre en la
    tarjeta que continúa: si una hoja trae, con una o dos cifras de diferencia,
    la cédula de la siguiente, que es de otra persona, y su nombre es el de la
    anterior, la cédula no es suya.
    """
    from .text_distance import damerau_levenshtein

    limpias = list(datos)
    quitadas: dict[int, str] = {}
    for i in range(1, len(datos) - 1):
        actual, anterior, siguiente = datos[i], datos[i - 1], datos[i + 1]
        if actual is None or anterior is None or siguiente is None:
            continue
        cedula, de_la_siguiente = _cifras(actual.cedula), _cifras(siguiente.cedula)
        if (
            cedula
            and de_la_siguiente
            and damerau_levenshtein(cedula, de_la_siguiente) <= CIFRAS_MAL_LEIDAS
            and not mismo_nombre(actual.nombre, siguiente.nombre)
            and mismo_nombre(actual.nombre, anterior.nombre)
        ):
            limpias[i] = DatosDeLaHoja(nombre=actual.nombre, cedula=None, anio=actual.anio, fecha=actual.fecha)
            quitadas[i] = cedula
    return limpias, quitadas


# -- los documentos ----------------------------------------------------------------------------

#: Las clases de documento que salen de un libro.
PERSONA = "persona"
PAQUETE = "paquete"
DEL_INDICE = "indice"


@dataclass(slots=True)
class Hoja:
    """Lo que se sabe de una página para juntarla con las demás."""

    numero: int
    plantilla: str | None
    #: Sin nada escrito: el reverso en blanco, una hoja de guarda.
    vacia: bool = False
    datos: DatosDeLaHoja | None = None
    #: La fecha del listado o del comprobante.
    fecha: Fecha | None = None
    #: Todas las fechas de pago de un comprobante.
    fechas: tuple[Fecha, ...] = ()
    #: El «PAG. n» del listado.
    pagina: int | None = None
    #: El año del hablador o del índice.
    anio: int | None = None
    #: El número del certificado, y si la hoja continúa uno («VIENEN», «HOJA Nº 2»).
    certificado: int | None = None
    sigue: bool = False


@dataclass(slots=True)
class Documento:
    """Las páginas de un documento del libro y lo que se leyó de él."""

    clase: str
    plantilla: str | None
    paginas: list[int] = field(default_factory=list)
    lecturas: list[DatosDeLaHoja] = field(default_factory=list)
    fechas: list[Fecha] = field(default_factory=list)
    #: La clave que junta un paquete: la fecha del listado o el mes de pago.
    clave: tuple[int, ...] | None = None
    #: El año del hablador o del índice que lo abrió.
    anio: int | None = None
    #: El número del certificado.
    numero: int | None = None
    dudas: list[str] = field(default_factory=list)

    @property
    def nombre(self) -> str | None:
        """El nombre más leído entre sus hojas; a igual número de lecturas, el más largo."""
        nombres = [lectura.nombre for lectura in self.lecturas if lectura.nombre]
        if not nombres:
            return None
        votos = Counter(plano(n).replace(".", "") for n in nombres)
        mejor = max(votos.items(), key=lambda par: (par[1], len(par[0])))[0]
        return next(n for n in nombres if plano(n).replace(".", "") == mejor)

    @property
    def cedula(self) -> str | None:
        """La cédula más leída entre sus hojas."""
        cedulas = [_cifras(lectura.cedula) for lectura in self.lecturas if _cifras(lectura.cedula)]
        return Counter(cedulas).most_common(1)[0][0] if cedulas else None

    @property
    def anios(self) -> list[int]:
        """Los años que dicen sus hojas."""
        return sorted({lectura.anio for lectura in self.lecturas if lectura.anio})


def _clave(hoja: Hoja) -> tuple[int, ...] | None:
    """Lo que junta las hojas de un paquete: la fecha del listado, o el año y el mes del pago."""
    if hoja.plantilla == COMPROBANTE:
        if hoja.fechas:
            (anio, mes), _ = Counter((f[2], f[1]) for f in hoja.fechas).most_common(1)[0]
            return anio, mes
        return None
    if hoja.fecha:
        dia, mes, anio = hoja.fecha
        return anio, mes, dia
    return None


def _parecidas(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """Dos fechas de listado que difieren en una sola cifra: la misma, mal leída («2.07.84» y «3.07.84»)."""
    if len(a) != len(b):
        return False
    uno, otro = "".join(f"{x:02d}" for x in a), "".join(f"{x:02d}" for x in b)
    return len(uno) == len(otro) and sum(x != y for x, y in zip(uno, otro, strict=True)) <= 1


def claves_suavizadas(hojas: Sequence[Hoja], *, tolerante: bool = True) -> list[tuple[int, ...] | None]:
    """La clave de cada hoja de paquete, votada entre hojas seguidas.

    Una relación de cuarenta hojas lleva la misma fecha en todas. Tesseract
    lee una de cada tres, y a veces mal: «2.07.84» entre «3.07.84», «16,06,82» y
    «14,06,87» entre «14.06.83» (NOMINA 1977-1984, 2026-11-06). Por eso:

    - las lecturas seguidas que se parecen -- la misma fecha, o con
      ``tolerante`` una cifra distinta, nunca en el mes de pago de un
      comprobante -- son una corrida, y todas llevan la fecha que más se leyó
      en ella;
    - un paquete nuevo empieza sólo con una lectura distinta **que la
      siguiente confirma**, o cuyo «PAG. 1» o «PAG. 2» dice que empieza un
      listado; una lectura distinta sin confirmar es un error de lectura y no
      abre nada.

    Las hojas sin leer siguen sin clave: las sitúa ``documentos``. Con lo que
    lee la IA -- que acierta -- no se tolera ninguna cifra distinta.
    """
    claves = [_clave(h) for h in hojas]
    leidas = [i for i, clave in enumerate(claves) if clave is not None]

    def iguales(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
        return a == b or (tolerante and len(a) == 3 and _parecidas(a, b))

    corridas: list[list[int]] = []
    for posicion, i in enumerate(leidas):
        clave = claves[i]
        empieza = hojas[i].pagina is not None and hojas[i].pagina <= 2
        recientes = corridas[-1][-3:] if corridas else []
        # «PAG. 1» o «PAG. 2» con otra fecha abre aunque difiera en una sola
        # cifra: dos listados seguidos pueden ser del 14.06.82 y del 14.06.83
        # (la revisión, 2026-11-06). Antes de la tolerancia, no después.
        if corridas and empieza and not any(clave == claves[j] for j in recientes):
            corridas.append([i])
            continue
        if corridas and any(iguales(clave, claves[j]) for j in recientes):
            corridas[-1].append(i)
            continue
        siguiente = claves[leidas[posicion + 1]] if posicion + 1 < len(leidas) else None
        if not corridas or empieza or (siguiente is not None and iguales(clave, siguiente)):
            corridas.append([i])
    suaves: list[tuple[int, ...] | None] = [None] * len(claves)
    for corrida in corridas:
        votos = Counter(claves[i] for i in corrida)
        ganadora = max(votos.items(), key=lambda par: (par[1], -corrida.index(next(i for i in corrida if claves[i] == par[0]))))[0]
        for i in corrida:
            suaves[i] = ganadora
    return suaves


def documentos(hojas: Sequence[Hoja], *, tolerante: bool = True) -> list[Documento]:
    """Las hojas del libro juntadas en sus documentos, en su orden.

    - **El hablador abre** un paquete: el de su año. **El índice** es un
      documento.
    - **El certificado abre**, y lo que le sigue sin abrir nada son sus anexos.
    - **Una hoja de persona** se junta con la anterior si es de la misma
      persona (``misma_persona``); si no, abre. La que no se leyó abre
      también: juntarla a ciegas pegaría dos personas.
    - **Una hoja de paquete** se junta mientras dice la misma fecha (o el mismo
      mes de pago); otra fecha abre un paquete nuevo. Las hojas de en medio que
      no se leyeron van con la anterior, salvo que el «PAG. n» de la primera
      leída del paquete nuevo diga que empezó antes.
    - **Una hoja vacía o que no dice nada** va con el documento en curso; las de
      antes del primero, con el primero.

    ``tolerante``: si las fechas se leyeron con el OCR de casa (ver
    ``claves_suavizadas``).
    """
    suaves = claves_suavizadas(hojas, tolerante=tolerante)
    salida: list[Documento] = []
    pendientes: list[int] = []
    actual: Documento | None = None
    #: Dónde está, en ``actual.paginas``, la última hoja que dijo su clave.
    ultima_leida = 0

    def abrir(clase: str, hoja: Hoja, **datos) -> Documento:
        nonlocal actual, ultima_leida
        documento = Documento(clase=clase, plantilla=hoja.plantilla, paginas=[*pendientes, hoja.numero], **datos)
        pendientes.clear()
        salida.append(documento)
        actual = documento
        ultima_leida = len(documento.paginas) - 1
        return documento

    for hoja, clave in zip(hojas, suaves, strict=True):
        if hoja.plantilla == HABLADOR:
            abrir(PAQUETE, hoja, anio=hoja.anio)
            continue
        if hoja.plantilla == INDICE:
            abrir(DEL_INDICE, hoja, anio=hoja.anio)
            continue
        if hoja.plantilla == CERTIFICADO:
            # Un certificado es su número: la hoja que lo continúa o lo repite
            # -- su segunda hoja, un borrador, otra copia firmada -- va con él.
            # Si la hoja y el certificado abierto tienen número, manda el número:
            # «(2) PASAN» con otro número es la segunda hoja de otro certificado
            # cuya primera no se leyó, no la del abierto (la revisión, 2026-11-06).
            if (
                actual is not None
                and actual.plantilla == CERTIFICADO
                and (
                    hoja.certificado == actual.numero
                    if hoja.certificado is not None and actual.numero is not None
                    else hoja.sigue
                )
            ):
                actual.paginas.append(hoja.numero)
                if hoja.datos:
                    actual.lecturas.append(hoja.datos)
                if actual.numero is None:
                    actual.numero = hoja.certificado
                continue
            abrir(PERSONA, hoja, lecturas=[hoja.datos] if hoja.datos else [], numero=hoja.certificado)
            continue
        if hoja.plantilla in DE_PAQUETE:
            if actual is not None and actual.clase == PAQUETE and (clave is None or actual.clave in (None, clave)):
                actual.paginas.append(hoja.numero)
                if clave is not None:
                    if actual.clave is None:
                        actual.clave = clave
                        actual.plantilla = hoja.plantilla
                    ultima_leida = len(actual.paginas) - 1
                actual.fechas.extend(f for f in _fechas_de(hoja) if _de_la_clave(f, clave or actual.clave))
                continue
            if actual is not None and actual.clase == PAQUETE and clave is not None:
                # Otra fecha: un paquete nuevo. Las hojas sin leer de en medio
                # son del nuevo si su «PAG. n» dice que empezó antes.
                sin_leer = actual.paginas[ultima_leida + 1 :]
                atras = (hoja.pagina - 1) if hoja.pagina and 1 <= hoja.pagina - 1 <= len(sin_leer) else 0
                if atras:
                    pendientes.extend(sin_leer[-atras:])
                    del actual.paginas[len(actual.paginas) - atras :]
            documento = abrir(PAQUETE, hoja, clave=clave)
            documento.fechas.extend(f for f in _fechas_de(hoja) if _de_la_clave(f, clave))
            if clave is None:
                ultima_leida = -1
            continue
        if hoja.plantilla in DE_PERSONA:
            datos = hoja.datos or DatosDeLaHoja()
            if hoja.vacia and actual is not None:
                actual.paginas.append(hoja.numero)
                continue
            if actual is not None and actual.clase == PERSONA and actual.lecturas and misma_persona(_ultima(actual), datos):
                actual.paginas.append(hoja.numero)
                actual.lecturas.append(datos)
                continue
            if actual is not None and actual.clase == PERSONA and actual.plantilla == CERTIFICADO:
                # Lo que sigue a un certificado sin abrir otro es su anexo.
                actual.paginas.append(hoja.numero)
                continue
            abrir(PERSONA, hoja, lecturas=[datos])
            continue
        # Ni de persona ni de paquete, o vacía: con el documento en curso.
        if actual is None:
            pendientes.append(hoja.numero)
        else:
            actual.paginas.append(hoja.numero)
    if pendientes:
        if salida:
            salida[0].paginas[:0] = pendientes
        else:
            salida.append(Documento(clase=PAQUETE, plantilla=None, paginas=list(pendientes)))
    return salida


def _ultima(documento: Documento) -> DatosDeLaHoja:
    """La lectura más completa del documento: con la que se compara la hoja siguiente."""
    return DatosDeLaHoja(nombre=documento.nombre, cedula=documento.cedula)


def _fechas_de(hoja: Hoja) -> list[Fecha]:
    return list(hoja.fechas) if hoja.fechas else ([hoja.fecha] if hoja.fecha else [])


def _de_la_clave(fecha: Fecha, clave: tuple[int, ...] | None) -> bool:
    if clave is None:
        return True
    dia, mes, anio = fecha
    return (anio, mes, dia)[: len(clave)] == clave


# -- el asunto, las fechas extremas y el nombre del archivo -----------------------------------------

#: El año de un libro: su índice («INDICE AÑO 1.975») o su nombre («NOMINA 1975 TOMO 1»).
def tipo_de_la_hoja(nombre_del_libro: str) -> str:
    """El asunto de las hojas manuscritas: lo que dice el nombre del libro, sin la UPD, los años ni el tomo.

    «UPD3860692-LIBRO DE ANOTACIONES 1972 TOMO 1.pdf» → «LIBRO DE ANOTACIONES»;
    «UPD3860694-ANOTACIONES DE PAGO 1974.pdf» → «ANOTACIONES DE PAGO».
    """
    nombre = re.sub(r"\.PDF$", "", plano(nombre_del_libro))
    nombre = re.sub(r"^UPD\s?\d{7}\s*[-_]?\s*", "", nombre)
    nombre = re.sub(r"\bTOMO\b.*$|\b(?:19|20)\d\d\b.*$|\s-\s*\d.*$", "", nombre)
    nombre = re.sub(r"[^A-Z ]", " ", nombre)
    return " ".join(nombre.split()) or ASUNTO_DE_LA_HOJA


def asunto(documento: Documento, *, tipo_de_hoja: str = ASUNTO_DE_LA_HOJA) -> str:
    """El asunto del FUID: «NOMINAS - NOMBRE», «LIBRO DE ANOTACIONES - NOMBRE», «NOMINA», «INDICE»."""
    if documento.clase == DEL_INDICE:
        return ASUNTO_DEL_INDICE
    if documento.clase == PAQUETE:
        return ASUNTO_DEL_HABLADOR if documento.anio is not None else ASUNTO_DEL_LISTADO
    tipo = {
        TARJETA: ASUNTO_DE_LA_TARJETA,
        CERTIFICADO: ASUNTO_DEL_CERTIFICADO,
    }.get(documento.plantilla or "", tipo_de_hoja)
    nombre = documento.nombre
    return f"{tipo} - {nombre}" if nombre else tipo


def fechas_extremas(
    documento: Documento, *, anio_del_libro: int | None = None, ventana: tuple[int, int] | None = None
) -> tuple[Fecha | None, Fecha | None, str | None]:
    """La fecha inicial y la final del documento, y de dónde salieron si no fue del papel de sus hojas.

    - Un paquete: la fecha del listado o la primera y la última fecha de pago;
      sin ninguna leída, el año del hablador que lo abrió.
    - Una persona: el certificado, su fecha; la tarjeta y la hoja, el primer y
      el último año que dicen sus hojas; si no dicen ninguno, el año del libro.
    - El índice: el año que dice, o el del libro.

    ``ventana`` son los años del libro, de su nombre: un año de la hoja fuera
    de ellos -- «1927» en el libro de 1972, la IA leyó las cifras cambiadas --
    no se toma, y se dice.
    """
    if documento.clase == PAQUETE:
        if documento.fechas:
            ordenadas = sorted(documento.fechas, key=lambda f: (f[2], f[1], f[0]))
            return ordenadas[0], ordenadas[-1], None
        if documento.anio:
            return (1, 1, documento.anio), (31, 12, documento.anio), f"el año {documento.anio} del hablador"
        if anio_del_libro:
            return (1, 1, anio_del_libro), (31, 12, anio_del_libro), f"el año {anio_del_libro} del libro"
        return None, None, None
    if documento.clase == DEL_INDICE:
        anio = documento.anio or anio_del_libro
        return ((1, 1, anio), (31, 12, anio), None) if anio else (None, None, None)
    # El certificado: las fechas de firma de sus versiones, si se dieron; si no, las de sus hojas.
    exactas = list(documento.fechas) or [lectura.fecha for lectura in documento.lecturas if lectura.fecha]
    if exactas:
        ordenadas = sorted(exactas, key=lambda f: (f[2], f[1], f[0]))
        return ordenadas[0], ordenadas[-1], None
    fuera = [a for a in documento.anios if ventana and not ventana[0] - 1 <= a <= ventana[1] + 1]
    anios = [a for a in documento.anios if a not in fuera]
    dice = f"la hoja dice {', '.join(map(str, fuera))}, fuera de los años del libro" if fuera else ""
    if anios:
        return (1, 1, anios[0]), (31, 12, anios[-1]), (f"{dice}: revísela" if dice else None)
    if anio_del_libro:
        porque = (
            f"{dice}: va el año {anio_del_libro} del libro; revísela"
            if dice
            else f"el año {anio_del_libro} del libro: la hoja no lo dice"
        )
        return (1, 1, anio_del_libro), (31, 12, anio_del_libro), porque
    return None, None, None


def ventana_del_libro(nombre_del_libro: str) -> tuple[int, int] | None:
    """Los años del libro según su nombre: «NOMINA 1977-1984» → (1977, 1984); «NOMINA 1975 TOMO 1» → (1975, 1975)."""
    anios = sorted({int(a) for a in re.findall(r"(?<!\d)(19\d\d|20[0-2]\d)(?!\d)", plano(nombre_del_libro))})
    return (anios[0], anios[-1]) if anios else None


def anio_del_libro(nombre_del_libro: str, anios_de_los_indices: Sequence[int] = ()) -> int | None:
    """El año de todo el libro: el de su índice, o el de su nombre si dice uno solo.

    «NOMINA 1975 TOMO 1» es de 1975; «NOMINA 1977-1984» no es de ningún año.
    """
    if anios_de_los_indices:
        return Counter(anios_de_los_indices).most_common(1)[0][0]
    anios = sorted({int(a) for a in re.findall(r"(?<!\d)(19\d\d|20[0-2]\d)(?!\d)", plano(nombre_del_libro))})
    return anios[0] if len(anios) == 1 else None
