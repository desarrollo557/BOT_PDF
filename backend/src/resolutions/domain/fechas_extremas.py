"""Las fechas extremas de un documento contra lo que dice su papel, con la regla de su habilidad y un margen de error.

Lo pidió el operador el 2026-11-10: «necesito estar muy seguro de cada fecha en
cada documento, sin importar la habilidad: que el agente se asegure de que la
fecha inicial y final sean las que son», y «recuerda saber manejar un margen de
errores». Eligió los dos agentes -- el que trabaja al procesar, con cada
documento, y la auditoría de cierre, con su muestra -- y **corregir sólo con
prueba**: lo que no la tenga va a Revisión con su motivo.

**Cada habilidad, su regla** (``REGLAS``). Medido sobre 100 actas de Odontología
(2026-11-10), la fecha más antigua del texto era la de la fila en 53 y la más
reciente en 48: las actas citan acuerdos viejos, la fecha de la plantilla
(«VERSIÓN 00 FECHA 04-05-2011») y la próxima reunión. Con la regla de su
habilidad -- la fecha de la apertura de la sesión --, la de la fila estaba en el
papel en 99 de 100.

**El margen de error**: lo que se aparta como lo aparta el OCR -- un dígito -- o
sólo por la precisión -- «1986» frente a «17/12/1986» -- no es un error: se
pregunta. Una fecha se **corrige** sólo con dos pruebas del papel: el lector
**fuerte** de su regla dice otra, y la de la fila no está escrita en ninguna
parte del documento. Con una sola, la decide la IA citando el texto (si la
corrida se hizo con ella), y si no, va a Revisión.

**Tras la revisión adversarial del 2026-11-10** -- 7 correcciones equivocadas en
actas reales alteradas y 6 en casos sintéticos -- la meta es cero:

- el lector **fuerte** es estricto: la apertura de la sesión; la fecha de grado
  por su forma entera o en letras (no por piezas); la fórmula de expedición de
  la propia resolución -- con el número y el año de su encabezado --; la firma
  del certificado (no «la última fecha»). Lo demás es un lector **débil**: sólo
  confirma o pregunta, nunca corrige;
- la fecha que la fila tomó de otra parte (``origen``: el libro, la serie, el
  código, la ceremonia) no se busca en el papel, ni se corrige, ni se le
  pregunta a la IA: sólo se mira si cae fuera de los años del libro;
- la ventana de años del libro vale también con precisión de día: la fecha de
  la fila fuera de ella es duda, y la del papel fuera de ella no es prueba;
- no se corrige hacia una fecha que las observaciones de la fila ya registran
  como descartada («el OCR leyó 16-01-2000 y la IA 16-01-2009»), ni cuando la de
  la fila se aparta como el OCR de otra fecha escrita en el papel;
- el mes y el año escritos confirman sólo si el papel no trae otra fecha entera
  de ese mes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

#: ``_PALABRA_DE_NUMERO`` es la palabra de número con que ``fechas_del_texto``
#: junta «dos mil doce (2012)»: la misma, para acotar sus rachas (``texto_acotado``).
from .acta_consejo import _PALABRA_DE_NUMERO, fechas_del_texto, leer_acta

#: La precisión de una fecha de la fila: un día, o sólo un año.
DIA = "dia"
ANIO = "anio"

#: Las reglas: qué fecha del papel es la inicial y la final de cada habilidad.
SESION = "sesion"  # actas de consejo: la de la apertura de la sesión, en las dos
GRADO = "grado"  # actas de grado y exámenes: la del acta, en las dos
EXPEDICION = "expedicion"  # resoluciones: la de su fórmula «Dada en…»
FIRMA = "firma"  # certificados: la de la firma (la primera y la última versión)
ANIOS = "anios"  # historias, nóminas, matrículas: el primer y el último año
EXTREMOS = "extremos"  # archivo entero, correspondencia, Kingspan, genérico
REGLAS = (SESION, GRADO, EXPEDICION, FIRMA, ANIOS, EXTREMOS)

#: El origen de una fecha que salió de su papel.
PAPEL = "papel"

#: De dónde salió la fecha de la fila cuando no salió de su papel: lo dicen sus
#: observaciones. Esas se buscan en el papel, y si el papel trae la suya, manda.
_DE_OTRA_PARTE = re.compile(
    r"DEL NOMBRE DEL ARCHIVO|DE SU TRAMITE|DE LA SERIE|DE LA VECINA|DE SUS VECINAS|DE LA CEREMONIA|DEL CODIGO|DEL LIBRO",
)
#: Sólo la parte de las observaciones que habla de la fecha dice su origen: «el
#: folio final … se dedujo de la foliación seguida del libro» habla del folio, y
#: «el número del acta … se tomó del nombre del archivo», del número. Leídas
#: enteras, las actas 019 y 015 de Odontología pasaban por fechas «del libro» y
#: el revisor dejaba de mirarlas (2026-11-10).
_HABLA_DE_LA_FECHA = re.compile(r"\bFECHAS?\b|\bANOS?\b")
#: «la fecha: el OCR leyó 16-01-2000 y la IA 16-01-2009; se dejó lo de la IA»
#: (``doble_lectura``): las dos lecturas están en disputa, y la que no quedó en
#: la fila ya se descartó. El revisor corregía el ACTA EXTRAORDINARIA 001 hacia
#: el 16/01/2000, la errata del papel que el trabajo ya había rechazado.
_OCR_CONTRA_IA = re.compile(
    r"\bEL OCR LEYO (\d{1,2}) (\d{1,2}) (\d{4})\b(?: EN \d+ LECTURAS)? Y LA IA (\d{1,2}) (\d{1,2}) (\d{4})\b"
)
#: Los años del libro en el nombre de su archivo: «ACTAS DE CONSEJO DE FACULTAD
#: 2007-2009 DE N°1 AL 439.pdf» (ya sin puntuación, «2007 2009»).
_ANIOS_DEL_NOMBRE = re.compile(r"(?<!\d)((?:19|20)\d{2}) (?:AL? )?((?:19|20)\d{2})(?!\d)")
#: Cuántos años puede abarcar un libro para que su nombre se lea como ventana.
_LARGO_DE_UN_LIBRO = 40
#: Un año suelto en el texto: «1986», «1.986», «AÑO 1.950».
_ANIO_EN_EL_TEXTO = re.compile(r"(?<!\d)(1[89]\d{2}|20[0-4]\d)(?!\d)")
_ANIO_CON_PUNTO = re.compile(r"(?<!\d)([12])[.,]\s?(\d{3})(?!\d)")
#: El encabezado de una resolución con su número y su año, en el texto plano
#: (sin puntuación): «RESOLUCIÓN No. 00390 DE 2025», «N° 0412/2024», «No.
#: 002-2023», «NUMERO 00412 DE 2024» y «No. 031 (15 de marzo de 2005)».
_ENCABEZADO_DE_RESOLUCION = re.compile(
    r"\bRESOLUCI[O0]N (?:NUMERO |NRO |N[O0] |N )?(\d{1,8}) (?:DE )?(?:\d{1,2} DE [A-Z]+ DEL? )?((?:19|20)\d{2})\b"
)
#: Cuántos días pueden separar dos sesiones de la misma acta: la 019 de
#: Odontología se abrió el 25 y siguió el 30 de octubre de 2012, y el trabajo
#: escribe la última.
_DIAS_ENTRE_SESIONES = 15
#: El rótulo con que el acta abre cada sesión: «FECHA: MARTES 30 DE OCTUBRE DE
#: 2012». Sólo la fecha que va detrás es de otra sesión; la de la próxima
#: reunión, citada en el cuerpo, no.
#:
#: Al principio del renglón, con los blancos de **ese** renglón delante
#: (``[^\S\n]``: todo blanco menos el salto). Con ``^\s*`` cada renglón vacío
#: volvía a recorrer todos los que le seguían: «a» + 20 000 saltos tardaba 1,9 s
#: y crecía al cuadrado (la revisión adversarial, 2026-11-10). Los rótulos que
#: encuentra, y dónde acaban -- lo único que se usa --, son los mismos: el
#: renglón del rótulo empieza tras el último salto, y lo que ``\s*`` cruzaba eran
#: renglones vacíos.
_ROTULO_DE_LA_SESION = re.compile(
    r"^[^\S\n]*FECHA(?:\s+DE\s+LA\s+SESI[OÓ]N)?\s*[:;]", re.IGNORECASE | re.MULTILINE
)


@dataclass(frozen=True, slots=True)
class FechasDeLaFila:
    """La fecha inicial y la final de una fila, con su precisión y de dónde salieron."""

    inicial: date | None
    final: date | None
    precision: str = DIA
    #: «papel», o de dónde se tomó si no salió de él (el nombre del archivo, la serie).
    origen: str = PAPEL
    #: Las fechas que sus observaciones registran en disputa («el OCR leyó X y
    #: la IA Y»): hacia ellas no se corrige.
    rechazadas: tuple[date, ...] = ()
    #: Los años del libro, si el nombre de su archivo los dice («2007-2009»).
    ventana: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class Correccion:
    """Una fecha de la fila que el papel contradice con prueba: la que va en su lugar."""

    campo: str
    dice_la_fila: date | None
    dice_el_papel: date
    prueba: str


@dataclass(frozen=True, slots=True)
class PreguntaDeFecha:
    """Una fecha de la fila que el papel no confirma ni contradice con prueba: para la IA o para Revisión."""

    campo: str
    valor: str
    duda: str
    #: Lo que dice el lector de la regla, si dice algo: con él y la cita de la
    #: IA se corrige.
    dice_el_papel: date | None = None
    #: ``False`` si la duda va derecho a Revisión, sin pagar la IA: la fecha
    #: cae fuera de los años del libro, o la fila la tomó de otra parte.
    para_la_ia: bool = True


@dataclass(frozen=True, slots=True)
class RevisionDeFechas:
    confirmadas: tuple[str, ...] = ()
    correcciones: tuple[Correccion, ...] = ()
    preguntas: tuple[PreguntaDeFecha, ...] = ()
    sin_dato: tuple[str, ...] = ()
    #: Los años en que puede caer una fecha corregida -- la de la IA también --:
    #: los del libro y, en una resolución, el de su encabezado.
    ventana: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class LoQueDiceElPapel:
    """Lo que el lector de la regla leyó en el papel: la fecha inicial y la final, y si es prueba."""

    inicial: date | None = None
    final: date | None = None
    como: str = ""
    #: Si el lector leyó la fecha donde va y no por un respaldo: sólo así es
    #: una prueba con la que se corrige. El débil sólo confirma o pregunta.
    fuerte: bool = False
    #: Las fechas que el lector da por buenas en cada punta: la suya, o -- el
    #: lector débil de las puntas -- la propia de cada hoja.
    aceptables_inicial: frozenset[date] = frozenset()
    aceptables_final: frozenset[date] = frozenset()
    #: Las fechas que abren sesión en el acta (regla de la sesión) y las que
    #: van detrás del rótulo «FECHA:» de alguna de sus hojas.
    aperturas: frozenset[date] = frozenset()
    rotuladas: frozenset[date] = frozenset()
    #: El año del encabezado de una resolución: la fecha corregida va en él.
    anio_del_documento: int | None = None


# -- leer la fecha de una fila --------------------------------------------------------------


def leer_fecha(valor: object) -> tuple[date | None, str]:
    """Una fecha de fila y su precisión: «17/12/2012», «17-12-2012», «2012-12-17», «1986», un ``date``; o ``None``."""
    if isinstance(valor, datetime):
        # Lo que devuelve una hoja de cálculo (2026-11-10): un ``datetime`` nunca
        # es igual a un ``date``, y la fecha de la fila nunca se confirmaría.
        return valor.date(), DIA
    if isinstance(valor, date):
        return valor, DIA
    if isinstance(valor, int) and not isinstance(valor, bool):
        return (date(valor, 1, 1), ANIO) if 1000 <= valor <= 2100 else (None, DIA)
    texto = str(valor or "").strip()
    if not texto or texto.upper() == "N/A":
        return None, DIA
    if hallada := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", texto):
        return _fecha(int(hallada.group(3)), int(hallada.group(2)), int(hallada.group(1))), DIA
    if hallada := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", texto):
        return _fecha(int(hallada.group(1)), int(hallada.group(2)), int(hallada.group(3))), DIA
    if re.fullmatch(r"\d{4}", texto):
        return date(int(texto), 1, 1), ANIO
    return None, DIA


def _fecha(dia: int, mes: int, anio: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def fechas_de_un_par(inicial: object, final: object, *, origen: str = PAPEL) -> FechasDeLaFila:
    """Las fechas de un par inicial-final; «01/01/1977» y «31/12/1983» son años, no días."""
    ini, p_ini = leer_fecha(inicial)
    fin, p_fin = leer_fecha(final)
    precision = ANIO if ANIO in (p_ini, p_fin) else DIA
    # El relleno de un año: el primero de enero y el treinta y uno de diciembre.
    if ini and fin and (ini.month, ini.day) == (1, 1) and (fin.month, fin.day) == (12, 31) and ini != fin:
        precision = ANIO
    return FechasDeLaFila(ini, fin, precision, origen)


def fechas_de_la_fila(fila: Mapping[str, object]) -> FechasDeLaFila | None:
    """Las fechas extremas de una fila de inventario, sea de la habilidad que sea; ``None`` si no trae.

    Las claves cambian con la habilidad: ``fecha`` (actas, una sola),
    ``anio_inicial``/``anio_final`` o ``fecha_exacta`` (historias),
    ``fecha_inicial``/``fecha_final`` (nóminas, certificados, Kingspan, la fila
    genérica) y la fila ya hecha del FUID (``fuid``). De sus observaciones salen
    el origen de la fecha y las lecturas descartadas; del nombre de su archivo,
    los años del libro.
    """
    observaciones = str(fila.get("observaciones") or "")
    if isinstance(fila.get("fuid"), Mapping):
        datos = fila["fuid"]
        observaciones = f"{observaciones}; {datos.get('notas') or ''}"
        par = fechas_de_un_par(datos.get("fecha_inicial"), datos.get("fecha_final"))
    elif fila.get("fecha_exacta"):
        par = fechas_de_un_par(fila["fecha_exacta"], fila["fecha_exacta"])
    elif fila.get("anio_inicial") or fila.get("anio_final"):
        ini, fin = _anio(fila.get("anio_inicial")), _anio(fila.get("anio_final"))
        par = FechasDeLaFila(
            date(ini, 1, 1) if ini else None, date(fin, 12, 31) if fin else None, ANIO
        )
    elif fila.get("fecha") is not None and fila.get("fecha_inicial") is None:
        par = fechas_de_un_par(fila.get("fecha"), fila.get("fecha"))
    elif fila.get("fecha_inicial") is not None or fila.get("fecha_final") is not None:
        par = fechas_de_un_par(fila.get("fecha_inicial"), fila.get("fecha_final"))
    else:
        return None
    if par.inicial is None and par.final is None:
        return None
    return FechasDeLaFila(
        par.inicial,
        par.final,
        par.precision,
        origen_de_la_fecha(observaciones),
        lecturas_descartadas(observaciones),
        ventana_del_nombre(str(fila.get("archivo") or "")),
    )


def origen_de_la_fecha(observaciones: str) -> str:
    """De dónde tomó la fila su fecha, por lo que dicen de la fecha sus observaciones: «papel» si no lo dicen."""
    for parte in re.split(r"[;\n]", observaciones or ""):
        plano = _plano(parte)
        if _HABLA_DE_LA_FECHA.search(plano) and (hallado := _DE_OTRA_PARTE.search(plano)):
            return hallado.group(0).lower()
    return PAPEL


def lecturas_descartadas(observaciones: str) -> tuple[date, ...]:
    """Las fechas que las observaciones registran en disputa («el OCR leyó X y la IA Y»)."""
    descartadas: list[date] = []
    for hallado in _OCR_CONTRA_IA.finditer(_plano(observaciones)):
        for dia, mes, anio in (hallado.group(1, 2, 3), hallado.group(4, 5, 6)):
            if (fecha := _fecha(int(dia), int(mes), int(anio))) is not None:
                descartadas.append(fecha)
    return tuple(dict.fromkeys(descartadas))


def ventana_del_nombre(nombre: str) -> tuple[int, int] | None:
    """Los años del libro que dice el nombre de su archivo («… 2007-2009 …»), o ``None``."""
    hallado = _ANIOS_DEL_NOMBRE.search(_plano(nombre))
    if hallado is None:
        return None
    desde, hasta = int(hallado.group(1)), int(hallado.group(2))
    return (desde, hasta) if 0 <= hasta - desde <= _LARGO_DE_UN_LIBRO else None


def _anio(valor: object) -> int | None:
    texto = re.sub(r"\D", "", str(valor or ""))
    return int(texto) if len(texto) == 4 else None


def _plano(texto: str) -> str:
    import unicodedata

    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_tildes.upper()).split())


# -- lo que dice el papel ------------------------------------------------------------------


#: Lo más largo que llega a ``fechas_del_texto`` una racha de blancos, y una de
#: palabras de número seguidas («dos mil doce», «treinta y uno»). Sus patrones
#: aceptan cualquier racha de blancos (``\s*``, ``\s+``, sin distinguir el salto
#: de renglón del espacio), y una racha de palabras de número sólo cuenta entera
#: y seguida de su cifra entre paréntesis («dos mil doce (2012)» → «2012»): una
#: racha más corta, pero no vacía, da las mismas fechas. Lo que sí cambia es el
#: costo, que sin tope crecía al cuadrado: «dos mil » × 20 000 tardaba 318 s en
#: un solo documento, «y » × 4 000 3 s y «lunes» + 20 000 blancos 28 s (la
#: revisión adversarial, 2026-11-10). En el texto real (62 129 hojas y 3 017
#: documentos) la racha más larga de palabras de número es de 12, y sólo dos
#: documentos de hojas vacías juntan más de 40 blancos: llega igual.
_BLANCOS_MAXIMOS = 40
_PALABRAS_DE_NUMERO_SEGUIDAS = 24
_BLANCOS_DE_MAS = re.compile(rf"\s{{{_BLANCOS_MAXIMOS + 1},}}")
#: La letra con que empieza cada palabra de número: la búsqueda no prueba las
#: treinta y tantas palabras donde no empieza ninguna (la mitad del costo).
#: Si se le escapara alguna, la racha se acotaría menos, nunca de otro modo.
_INICIALES = "".join(sorted({p[:1] for p in _PALABRA_DE_NUMERO.removeprefix("(?:").removesuffix(")").split("|")}))
_RACHA_DE_NUMEROS = re.compile(
    rf"\b(?=[{re.escape(_INICIALES)}]){_PALABRA_DE_NUMERO}(?:\s+{_PALABRA_DE_NUMERO})*", re.IGNORECASE
)
_ENTRE_PALABRAS = re.compile(r"\s+")


def texto_acotado(texto: str) -> str:
    """El texto con sus rachas de blancos y de palabras de número acortadas: las mismas fechas, a costo lineal.

    De la racha de palabras de número quedan las últimas, que son las que van
    pegadas a la cifra entre paréntesis: «… dos mil doce (2012)» sigue siendo
    «2012». De la de blancos, sus primeros ``_BLANCOS_MAXIMOS``. Vale para lo
    que lee con esas regex: ``fechas_del_texto`` y ``primera_fecha`` de
    ``acta_consejo`` (cuál es la primera tampoco cambia: nada cambia de orden).
    """
    texto = _BLANCOS_DE_MAS.sub(lambda racha: racha.group(0)[:_BLANCOS_MAXIMOS], texto)
    return _RACHA_DE_NUMEROS.sub(_las_ultimas_palabras, texto)


def _las_ultimas_palabras(racha: re.Match[str]) -> str:
    seguidas = racha.group(0)
    # Dónde empieza cada palabra de la racha, desde la segunda.
    inicios = [blanco.end() for blanco in _ENTRE_PALABRAS.finditer(seguidas)]
    if len(inicios) < _PALABRAS_DE_NUMERO_SEGUIDAS:
        return seguidas
    return seguidas[inicios[-_PALABRAS_DE_NUMERO_SEGUIDAS] :]


def fechas_escritas(texto: str) -> set[date]:
    """``fechas_del_texto`` con el costo acotado (``texto_acotado``): las mismas fechas, sin crecer al cuadrado."""
    return fechas_del_texto(texto_acotado(texto or ""))


@lru_cache(maxsize=32)
def _escritas(texto: str) -> frozenset[date]:
    """``fechas_escritas``, una vez por documento: la piden el contraste, la IA y la auditoría (2026-11-10)."""
    return frozenset(fechas_escritas(texto))


@lru_cache(maxsize=32)
def _anios_escritos(texto: str) -> frozenset[int]:
    anios = {f.year for f in _escritas(texto)}
    anios |= {int(a) for a in _ANIO_EN_EL_TEXTO.findall(texto)}
    anios |= {int(a + b) for a, b in _ANIO_CON_PUNTO.findall(texto)}
    return frozenset(anios)


def _junto(textos: Sequence[str]) -> str:
    return "\n".join(t or "" for t in textos)


def lo_que_dice_el_papel(
    textos: Sequence[str],
    regla: str,
    *,
    ventana: tuple[int, int] | None = None,
    fechas: FechasDeLaFila | None = None,
) -> LoQueDiceElPapel:
    """La fecha inicial y la final según el lector de la regla, cómo se leyeron y si son prueba.

    Lectores **fuertes** -- con ellos se corrige --: la apertura de la sesión, la
    fecha de grado por su forma o en letras, la fórmula de expedición de la
    propia resolución con el número y el año de su encabezado, la firma del
    certificado. Lo demás es **débil** -- sólo confirma o pregunta --: la fecha
    de grado por piezas, una fórmula que no cuadra con su encabezado, y las
    puntas de los papeles sin regla propia (``_las_puntas``).
    """
    if not textos:
        return LoQueDiceElPapel()
    if regla == SESION:
        from .acta_consejo import encabezados_de_acta
        from .auditoria_de_filas import fechas_de_la_apertura

        fecha = leer_acta(list(textos)).fecha
        aperturas = frozenset(fechas_de_la_apertura(textos, [e for e in encabezados_de_acta(list(textos)) if e.fuerte]))
        rotuladas = frozenset(
            f
            for t in textos
            for rotulo in _ROTULO_DE_LA_SESION.finditer(t or "")
            for f in fechas_del_texto(t[rotulo.end() : rotulo.end() + 60])
        )
        return _uno(
            fecha,
            "la apertura de la sesión",
            fecha is not None and fecha in aperturas,
            aperturas=aperturas,
            rotuladas=rotuladas,
        )
    if regla == GRADO:
        from .acta_grado import POR_LA_FORMA, POR_LAS_LETRAS, fecha_de_grado_y_como

        for texto in textos:
            fecha, como = fecha_de_grado_y_como(texto)
            if fecha is not None:
                return _uno(fecha, "la fecha del acta de grado", como in (POR_LA_FORMA, POR_LAS_LETRAS))
        return LoQueDiceElPapel()
    if regla == EXPEDICION:
        return _la_expedicion(textos)
    if regla == FIRMA:
        from .nomina import firmas_del_certificado

        firmas = [f for f in (_fecha(d, m, a) for d, m, a in firmas_del_certificado(textos, ventana)) if f]
        if firmas:
            return LoQueDiceElPapel(
                min(firmas), max(firmas), "la firma del certificado", True,
                frozenset({min(firmas)}), frozenset({max(firmas)}),
            )
        return LoQueDiceElPapel()
    if regla in (ANIOS, EXTREMOS) and fechas is not None:
        return _las_puntas(textos, regla, fechas, ventana)
    return LoQueDiceElPapel()


def _uno(fecha: date | None, como: str, fuerte: bool, **otros) -> LoQueDiceElPapel:
    if fecha is None:
        return LoQueDiceElPapel(**otros)
    return LoQueDiceElPapel(fecha, fecha, como, fuerte, frozenset({fecha}), frozenset({fecha}), **otros)


def _la_expedicion(textos: Sequence[str]) -> LoQueDiceElPapel:
    """La fórmula «Dada en…» de la propia resolución: fuerte sólo con el número y el año de su encabezado.

    Sin el número, la fórmula ilegible de la propia dejaba pasar la de la copia
    que viene detrás («RESOLUCION No. 00012 DE 2024 … tres (3) días del mes de
    marzo de 2024») y la fila de la serie se corregía a ella: el caso de la 00390
    que ``fecha_de_expedicion`` ya resuelve con ``numero`` (2026-11-10).
    """
    from .fechas import fecha_de_expedicion

    encabezado = _ENCABEZADO_DE_RESOLUCION.search(_plano(textos[0]))
    numero = encabezado.group(1).replace(" ", "") if encabezado else None
    anio = int(encabezado.group(2)) if encabezado else None
    fecha = fecha_de_expedicion(list(textos), numero=numero)
    fuerte = fecha is not None and anio is not None and fecha.year == anio
    return _uno(fecha, "la fórmula de expedición («Dada en…»)", fuerte, anio_del_documento=anio)


def _las_puntas(
    textos: Sequence[str], regla: str, fechas: FechasDeLaFila, ventana: tuple[int, int] | None
) -> LoQueDiceElPapel:
    """El lector débil de las puntas: sólo confirma o pregunta, nunca corrige.

    Con la regla de los años y basta con estar escrita, la historia de 1977-1983
    pasaba con 1978 o con 1958 (el nacimiento), y la carta con el plazo que cita
    (la revisión adversarial del 2026-11-10). Ahora:

    - **años**, con la ventana del libro: el primero y el último de sus años;
      sin ventana no hay lector (el nacimiento también es un año escrito);
    - **días**, en los papeles sin regla propia: la fecha propia de cada hoja
      (``fecha_propia_de_la_hoja``: la del encabezado, la de las casillas),
      leída una vez por documento (``_fechas_propias``). Una fila de una sola
      fecha es la propia de alguna de sus hojas; una de dos puntas, la más
      antigua y la más reciente -- de las propias o de todas, que es como fecha
      el archivo entero (``ficha``) --.
    """
    texto = _junto(textos)
    if fechas.precision == ANIO:
        if ventana is None:
            return LoQueDiceElPapel()
        anios = sorted(a for a in _anios_escritos(texto) if ventana[0] <= a <= ventana[1])
        if not anios:
            return LoQueDiceElPapel()
        primero, ultimo = date(anios[0], 1, 1), date(anios[-1], 12, 31)
        return LoQueDiceElPapel(
            primero, ultimo, "los años de sus hojas", False, frozenset({primero}), frozenset({ultimo})
        )
    if regla != EXTREMOS:
        return LoQueDiceElPapel()
    propias = list(_fechas_propias(tuple(t or "" for t in textos)))
    todas = sorted(_escritas(texto))
    if fechas.inicial is not None and fechas.inicial == fechas.final:
        if not propias:
            return LoQueDiceElPapel()
        return LoQueDiceElPapel(
            propias[0], propias[-1], "la fecha propia de sus hojas", False, frozenset(propias), frozenset(propias)
        )
    if not (propias or todas):
        return LoQueDiceElPapel()
    inicial = frozenset(f for f in (propias[:1] + todas[:1]))
    final = frozenset(f for f in (propias[-1:] + todas[-1:]))
    return LoQueDiceElPapel(
        (propias or todas)[0], (propias or todas)[-1], "la punta de sus hojas", False, inicial, final
    )


@lru_cache(maxsize=8)
def _fechas_propias(textos: tuple[str, ...]) -> tuple[date, ...]:
    """La fecha propia de las hojas con texto (``fecha_propia_de_la_hoja``), sin repetir y en orden: una vez por documento.

    Las puntas de Kingspan cuyo número no aparece se contrastan contra todo el
    original, y cada una volvía a leer la fecha de sus cientos de hojas: en
    UPD3854045, tres de sus cuatro puntas, 284 hojas cada vez (la revisión
    adversarial, 2026-11-10). Las mismas hojas, en el mismo orden, son el mismo
    documento: se leen una vez.
    """
    return tuple(sorted({f for t in textos if t.strip() and (f := fecha_propia_de_la_hoja(t)) is not None}))


#: Lo que ``fechas._LUGAR_Y_FECHA`` lee como el lugar de un encabezado
#: («SAHAGUN, 25/05/2021»): letras y puntos seguidos, desde una mayúscula al
#: principio de la racha o tras un punto. Cada comienzo recorre la racha hasta
#: el final, y tres más si van detrás («San Juan de Dios,»): con muchos
#: comienzos en una misma racha -- «A.A.A.…» -- el recorrido crece al cuadrado,
#: y «A.» × 10 000 tardaba 3,4 s en una sola hoja (2026-11-10).
_LETRAS_Y_PUNTOS = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ.]+")
_COMIENZO_DE_UN_LUGAR = re.compile(r"(?:^|\.)[A-ZÁÉÍÓÚÑ]")
#: Cuánto recorrido -- comienzos por caracteres que abarcan -- se le deja a una
#: racha. En el texto real ninguna llega: la mayor de 62 129 hojas es de 1 280
#: (una hoja de Kingspan, 2026-11-10), y la hoja se lee como está.
_RECORRIDO_MAXIMO = 20_000
#: Ninguna racha más corta que ésta llega al tope, ni con un comienzo cada dos
#: caracteres y tres tan largas detrás: sin ninguna así, ni se cuentan.
_LARGO_QUE_PUEDE_PASAR = next(m for m in range(1, _RECORRIDO_MAXIMO) if (m // 2 + 1) * 4 * m > _RECORRIDO_MAXIMO)
_RACHA_QUE_PUEDE_PASAR = re.compile(rf"[A-Za-zÁÉÍÓÚÑáéíóúñ.]{{{_LARGO_QUE_PUEDE_PASAR},}}")


def fecha_propia_de_la_hoja(texto: str) -> date | None:
    """La fecha que fecha una hoja (``fechas.fecha_de_la_pagina``), con el costo acotado (2026-11-10).

    Una racha de letras y puntos que el encabezado recorrería más de
    ``_RECORRIDO_MAXIMO`` se lee con sus puntos como espacios: «A.A.A.» no es el
    nombre de un lugar. El resto de la hoja, igual.
    """
    from .fechas import fecha_de_la_pagina

    return fecha_de_la_pagina(_sin_siglas_sin_fin(texto or ""))


def _sin_siglas_sin_fin(texto: str) -> str:
    if not _RACHA_QUE_PUEDE_PASAR.search(texto):
        return texto
    rachas = list(_LETRAS_Y_PUNTOS.finditer(texto))
    largos = [racha.end() - racha.start() for racha in rachas]
    partes: list[str] = []
    desde = 0
    for orden, racha in enumerate(rachas):
        abarca = sum(largos[orden : orden + 4])
        # Un comienzo cada dos caracteres, a lo sumo: sólo se cuentan si pueden pasar del tope.
        if (largos[orden] // 2 + 1) * abarca <= _RECORRIDO_MAXIMO:
            continue
        if len(_COMIENZO_DE_UN_LUGAR.findall(racha.group(0))) * abarca <= _RECORRIDO_MAXIMO:
            continue
        partes += [texto[desde : racha.start()], racha.group(0).replace(".", " ")]
        desde = racha.end()
    return "".join(partes) + texto[desde:] if partes else texto


def en_el_papel(fecha: date, precision: str, textos: Sequence[str]) -> bool:
    """Si la fecha está escrita en el papel, con su precisión: el día entero, o el año."""
    texto = _junto(textos)
    if precision == ANIO:
        return fecha.year in _anios_escritos(texto)
    return fecha in _escritas(texto)


def anios_del_texto(texto: str) -> set[int]:
    """Los años que trae el texto: de sus fechas, sueltos («1986») o con punto («1.986»)."""
    return set(_anios_escritos(texto or ""))


def difiere_como_el_ocr(una: date, otra: date, precision: str) -> bool:
    """Si dos fechas se apartan sólo como las aparta el OCR: un dígito del día o del año, el mismo mes."""
    if precision == ANIO:
        a, b = f"{una.year:04d}", f"{otra.year:04d}"
    else:
        if una.month != otra.month:
            return False
        a, b = f"{una.day:02d}{una.year:04d}", f"{otra.day:02d}{otra.year:04d}"
    return sum(x != y for x, y in zip(a, b, strict=True)) == 1


def iguales(una: date | None, otra: date | None, precision: str) -> bool:
    if una is None or otra is None:
        return False
    return una.year == otra.year if precision == ANIO else una == otra


def dentro(fecha: date, ventana: tuple[int, int] | None) -> bool:
    """Si la fecha cae en los años de la ventana; sin ventana, siempre."""
    return ventana is None or ventana[0] <= fecha.year <= ventana[1]


# -- el contraste --------------------------------------------------------------------------


def contrastar_las_fechas(
    fechas: FechasDeLaFila,
    textos: Sequence[str],
    *,
    regla: str,
    ventana: tuple[int, int] | None = None,
) -> RevisionDeFechas:
    """La fecha inicial y la final de la fila contra su papel: confirmadas, corregidas con prueba, o preguntas.

    Por cada extremo:

    - **fuera de la ventana** (los años del libro: los que se pasan, o los del
      nombre de su archivo) es pregunta para Revisión aunque esté escrita:
      ACOSTA BELLO, 1994-2001 en un libro de 1978-1988 (2026-11-10);
    - **tomada de otra parte** (``origen``): no se busca, ni se corrige, ni se le
      pregunta a la IA -- se paga por documento --; queda sin dato, salvo que el
      lector fuerte diga la misma;
    - **confirmada** si el lector de la regla la da por buena; o -- sin lector --
      si está escrita en el papel con su precisión, o su mes y su año sin otra
      fecha entera de ese mes;
    - **corregida** si el lector **fuerte** dice otra que no se aparta como el
      OCR, cae en la ventana, no es una lectura ya descartada, y la de la fila
      no está escrita en ninguna parte ni se aparta como el OCR de otra que sí:
      dos pruebas del papel;
    - **pregunta** en lo demás, con lo que dice el lector, para que la IA,
      citándolo, pueda corregir.
    """
    if not textos or not any((t or "").strip() for t in textos):
        return RevisionDeFechas(sin_dato=("sus páginas no traen texto en que buscar las fechas",))
    ventana = ventana or fechas.ventana
    papel = lo_que_dice_el_papel(textos, regla, ventana=ventana, fechas=fechas)
    destino = _ventana_del_destino(ventana, papel.anio_del_documento)
    texto = _junto(textos)
    escritas = _escritas(texto)
    anios = _anios_escritos(texto)
    precision = fechas.precision
    confirmadas: list[str] = []
    correcciones: list[Correccion] = []
    preguntas: list[PreguntaDeFecha] = []
    sin_dato: list[str] = []
    for campo, de_la_fila, del_papel, aceptables in (
        ("fecha_inicial", fechas.inicial, papel.inicial, papel.aceptables_inicial),
        ("fecha_final", fechas.final, papel.final, papel.aceptables_final),
    ):
        dicho = "la fecha inicial" if campo == "fecha_inicial" else "la fecha final"
        prueba_del_papel = (
            papel.fuerte
            and del_papel is not None
            and dentro(del_papel, destino)
            and del_papel not in fechas.rechazadas
        )
        if de_la_fila is None:
            # «La fila no la traía» sólo si de verdad venía vacía de su papel y
            # el lector fuerte la dice: una fecha que la fila tomó del libro no
            # se rellena con una sola prueba (2026-11-10).
            if fechas.origen == PAPEL and prueba_del_papel:
                correcciones.append(
                    Correccion(campo, None, del_papel, f"la fila no la traía y el papel la dice en {papel.como}")
                )
            else:
                sin_dato.append(dicho)
            continue
        escrita = _escrita(de_la_fila, precision)
        if not dentro(de_la_fila, ventana):
            preguntas.append(
                PreguntaDeFecha(
                    campo,
                    escrita,
                    f"{dicho} {escrita} cae fuera de los años del libro ({ventana[0]}-{ventana[1]})",
                    para_la_ia=False,
                )
            )
            continue
        dada_por_buena = any(iguales(de_la_fila, a, precision) for a in aceptables)
        if fechas.origen != PAPEL:
            if dada_por_buena and papel.fuerte:
                confirmadas.append(dicho)
            else:
                sin_dato.append(f"{dicho} (la fila la tomó {_origen_dicho(fechas.origen)}, no de su papel)")
            continue
        esta = de_la_fila.year in anios if precision == ANIO else de_la_fila in escritas
        if del_papel is not None:
            if dada_por_buena or _otra_sesion_de_la_misma_acta(de_la_fila, del_papel, papel, regla):
                confirmadas.append(dicho)
                continue
            # Dos pruebas, y fuertes: la de la fila no está escrita -- ni su mes
            # y su año, que el OCR deja aunque destroce el día: «I3DF, DICIEMBRE
            # DE 2007» es el 13 --, el lector la leyó donde va, no se aparta como
            # el OCR de ella ni de otra escrita -- «30/10/2011» es la «30/10/2012»
            # de la segunda sesión, no la apertura del 25 --.
            con_prueba = (
                prueba_del_papel
                and not esta
                and not mes_y_anio_en(de_la_fila, precision, textos)
                and not difiere_como_el_ocr(de_la_fila, del_papel, precision)
                and not _como_el_ocr_de_otra(de_la_fila, precision, escritas, anios)
            )
            dice = _escrita(del_papel, precision)
            if con_prueba:
                correcciones.append(
                    Correccion(campo, de_la_fila, del_papel, f"{papel.como} dice {dice} y {escrita} no está escrita en el documento")
                )
                continue
            duda = f"{dicho} {escrita}, pero {papel.como} dice {dice}"
            if not dentro(del_papel, destino):
                duda += (
                    f", fuera del año de su encabezado ({papel.anio_del_documento})"
                    if papel.anio_del_documento is not None
                    else f", fuera de los años del libro ({ventana[0]}-{ventana[1]})"
                )
            elif del_papel in fechas.rechazadas:
                duda += ", una lectura que sus observaciones ya descartaron"
            elif not esta and not papel.fuerte:
                # El lector débil no es prueba: el motivo es que no está
                # escrita; lo que él dice va a la IA en ``dice_el_papel``.
                duda = f"{dicho} {escrita} no está escrita en el documento"
            preguntas.append(PreguntaDeFecha(campo, escrita, duda, del_papel))
            continue
        if esta or _mes_y_anio_solos(de_la_fila, precision, textos, escritas):
            # Sin lector, basta con que esté escrita; o su mes y su año, si el
            # día va en otra forma («AAMMDD» de las nóminas) o el OCR lo deshizo
            # y el papel no trae otra fecha entera de ese mes.
            confirmadas.append(dicho)
        else:
            preguntas.append(PreguntaDeFecha(campo, escrita, f"{dicho} {escrita} no está escrita en el documento"))
    return RevisionDeFechas(tuple(confirmadas), tuple(correcciones), tuple(preguntas), tuple(sin_dato), destino)


def _ventana_del_destino(ventana: tuple[int, int] | None, anio: int | None) -> tuple[int, int] | None:
    """Los años en que puede caer una fecha corregida: los del libro y el del encabezado del documento."""
    if anio is None:
        return ventana
    if ventana is None:
        return (anio, anio)
    if not ventana[0] <= anio <= ventana[1]:
        # Un encabezado fuera del libro: ninguna corrección cabe.
        return (anio, anio - 1)
    return (anio, anio)


def _otra_sesion_de_la_misma_acta(de_la_fila: date, del_papel: date, papel: LoQueDiceElPapel, regla: str) -> bool:
    """Si el acta siguió en otra sesión y la fila trae la última: la 019 de Odontología, «25 Y 30 DE OCTUBRE DE 2012».

    La de la fila va detrás del rótulo «FECHA:» de una hoja, como la apertura,
    y unos días después de ella: la próxima reunión citada no lo está.
    """
    return (
        regla == SESION
        and de_la_fila in papel.aperturas
        and de_la_fila in papel.rotuladas
        and 0 < (de_la_fila - del_papel).days <= _DIAS_ENTRE_SESIONES
    )


def _como_el_ocr_de_otra(fecha: date, precision: str, escritas: frozenset[date], anios: frozenset[int]) -> bool:
    """Si la fecha se aparta como el OCR de otra escrita en el papel: entonces no hay prueba de que esté mal."""
    if precision == ANIO:
        return any(difiere_como_el_ocr(fecha, date(a, 1, 1), ANIO) for a in anios)
    return any(difiere_como_el_ocr(fecha, otra, DIA) for otra in escritas)


def _origen_dicho(origen: str) -> str:
    return {"de su tramite": "de su trámite", "del codigo": "del código"}.get(origen, origen)


_MESES = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
    "NOVIEMBRE", "DICIEMBRE",
)


def mes_y_anio_en(fecha: date, precision: str, textos: Sequence[str]) -> bool:
    """Si el mes y el año de la fecha están escritos («DICIEMBRE DE 2007», «12/2007»): apoyo parcial del papel.

    Basta para **no corregir** -- el OCR pudo deshacer el día --; para
    confirmar, ``_mes_y_anio_solos``.
    """
    if precision == ANIO:
        return False
    plano = _plano(_junto(textos))
    mes = _MESES[fecha.month - 1]
    if re.search(rf"\b{mes[:3]}\w*\s+(?:DE\s+|DEL\s+)?{fecha.year}\b", plano):
        return True
    return re.search(rf"(?<!\d)0?{fecha.month}\s+{fecha.year}\b", plano) is not None


def _mes_y_anio_solos(fecha: date, precision: str, textos: Sequence[str], escritas: frozenset[date]) -> bool:
    """El mes y el año escritos confirman sólo si el papel no trae otra fecha entera de ese mes.

    «17/12/2012» escrita entera no confirma una fila del 18/12 ni del 07/12; «I3DF,
    DICIEMBRE DE 2007», sin otra fecha de diciembre, sí apoya el 13 (2026-11-10).
    """
    if any((otra.year, otra.month) == (fecha.year, fecha.month) for otra in escritas):
        return False
    return mes_y_anio_en(fecha, precision, textos)


def _escrita(fecha: date, precision: str) -> str:
    return str(fecha.year) if precision == ANIO else fecha.strftime("%d/%m/%Y")
