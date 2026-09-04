"""Leer el expediente académico de un estudiante, que ocupa varias páginas.

Un libro de diplomas es una página, un registro. Esto no. El expediente de un
estudiante es una carátula de MATRÍCULA ACADÉMICA -- donde constan su código,
sus apellidos, sus nombres, la carrera y el período -- seguida de una o más
hojas de REGISTRO DE ESTUDIOS, que son la lista de asignaturas año por año y no
repiten el nombre de nadie. La unidad documental es el estudiante, no la hoja.

De ahí salen las dos cosas que este módulo tiene que decidir y que el lector de
diplomas no necesitaba:

  * **Dónde empieza un expediente y dónde termina.** Empieza en la página que
    trae identidad -- código o nombre -- y se extiende por las que no la traen,
    porque una hoja de asignaturas sin nombre pertenece a quien la preceda.
  * **Cuáles son sus fechas extremas.** No hay una fecha de graduación que
    copiar dos veces: hay una columna de años -- "PRIMER AÑO 1.950" ...
    "SEXTO AÑO 1.955" -- y las fechas extremas del FUID son el primero y el
    último de esos años. Es exactamente lo que el instructivo pide, la fecha
    inicial y la final de la unidad documental.

Como en todo lo demás del sistema, lo que no se pudo leer queda en ``None`` y
llega al inventario como N/A. Un año deducido del código del estudiante o
copiado de la hoja vecina sería una fecha que nadie puede rastrear hasta el
papel.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from .diploma import TextLine, has_caption

# -----------------------------------------------------------------------------
#  Las leyendas impresas de los dos formularios
# -----------------------------------------------------------------------------
#  Se comparan con la misma tolerancia difusa que las del libro de diplomas,
#  porque estos cartones son de los años cincuenta y el escaneo los trata igual
#  de mal: "Cód. Estudiante" llega como "Cod, Estudianfe" más veces de las que
#  llega limpio.
# -----------------------------------------------------------------------------

CAPTION_CODIGO = "COD ESTUDIANTE"
CAPTION_APELLIDOS = "APELLIDOS"
CAPTION_NOMBRES = "NOMBRES"
CAPTION_CARRERA = "CARRERA"
CAPTION_ANIO = "ANO"
CAPTION_PERIODO = "PERIODO"

#: El orden en que el formulario imprime sus columnas, de izquierda a derecha.
#: Es el que se usa para repartir los valores cuando las leyendas no se pudieron
#: localizar una a una y sólo queda la posición.
COLUMNAS = (
    CAPTION_CODIGO,
    CAPTION_APELLIDOS,
    CAPTION_NOMBRES,
    CAPTION_CARRERA,
    CAPTION_ANIO,
    CAPTION_PERIODO,
)

#: Encabezados que dicen qué clase de hoja es. Una carátula abre expediente; una
#: hoja de registro de estudios continúa el que venga abierto.
CAPTION_REGISTRO_DE_ESTUDIOS = "REGISTRO DE ESTUDIOS"
CAPTION_MATRICULA = "MATRICULA ACADEMICA"


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in descompuesto if not unicodedata.combining(ch))


# -----------------------------------------------------------------------------
#  Los valores, tal como los escriben estos formularios
# -----------------------------------------------------------------------------

#: El código del estudiante de la Universidad de Cartagena: dos cifras de
#: facultad, un guion y el consecutivo -- "51-8710099".
_CODIGO = re.compile(r"\b(\d{2})\s*[-–—]\s*(\d{5,10})\b")

#: El mismo código en las carátulas que lo imprimen sin guion, reconocido por su
#: leyenda para no confundirlo con una cédula ni con un número de folio.
_CODIGO_SIN_GUION = re.compile(
    r"C[O0]D[.:]?\s*(?:ESTUD[I¡]ANTE)?\s*[.:]?\s*(\d{6,12})\b", re.I
)

#: El período académico: "1o/93", "2°/1993", "1/93".
_PERIODO = re.compile(r"\b(\d)\s*[o°º.]?\s*/\s*(\d{2,4})\b")

#: El año que cursa, tal como lo escribe la casilla: "6o.", "1o", "3°".
_ANIO_EN_CURSO = re.compile(r"^\s*(\d{1,2})\s*[o°º]?\.?\s*$")

#: Un año académico anunciado en la columna de asignaturas del REGISTRO DE
#: ESTUDIOS. La máquina de escribir de la época separaba los miles con un punto,
#: así que "1.950" y "1950" son la misma cosa.
_ANIO_ACADEMICO = re.compile(
    r"\b(?:PR[I¡]MER[O]?|SEGUND[O0]|TERCER[O]?|CUART[O0]|QU[I¡]NT[O0]|SEXT[O0]|"
    r"SEPT[I¡]M[O0]|OCTAV[O0]|N[O0]VEN[O0]|DEC[I¡]M[O0])\s+A[NÑ]?[O0]\s*[.:]?\s*"
    r"(\d\s*\.?\s*\d{3})\b",
    re.I,
)

#: Un año a secas, para el período escrito con cuatro cifras. El rango acota lo
#: que puede ser un año de estudios de esta Universidad, fundada en 1827: fuera
#: de él es un número de otra columna que se coló.
_ANIO_SUELTO = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_ANIO_MINIMO = 1827
_ANIO_MAXIMO = 2100

#: Un nombre en las mayúsculas de estos cartones. Igual que en el libro de
#: diplomas se admite el dígito dentro de la palabra, porque el escaneo escribe
#: "AREVAL0 P0SADA" y rechazarlo no evitaría el daño: sólo haría que el
#: expediente se archivara sin nombre.
_NOMBRE = re.compile(r"^[A-ZÑ0-9][A-ZÑ0-9'.\-]*(?:\s+[A-ZÑ0-9][A-ZÑ0-9'.\-]*){0,6}$")
_LARGO_MINIMO_NOMBRE = 4

#: Lo que no puede formar parte de un nombre. No lo repara: lo declara dudoso.
_DANO_EN_EL_NOMBRE = re.compile(r"[^A-ZÑÁÉÍÓÚÜ'. \-]", re.I)

#: Leyendas impresas que caen donde caen los valores y no son de nadie.
_MOBILIARIO = (
    "UNIVERSIDAD DE CARTAGENA",
    "ADMISIONES REGISTRO Y CONTROL ACADEMICO",
    "MATRICULA ACADEMICA",
    "REGISTRO DE ESTUDIOS",
    "ASIGNATURAS",
    "COD MATERIA",
    "FIRMA ALUMNO",
    "FIRMA SECRETARIO ACADEMICO",
    "NOTA DE EXAMEN TRIMESTRAL",
    "CALIFICACION DE PRACTICAS",
    "NOTA DE EXAMEN FINAL",
    "CALIFICACION DEFINITIVA",
    "HABILITACION O SUPLETORIO",
)


def _es_mobiliario(linea: str) -> bool:
    return any(has_caption(linea, frase) for frase in _MOBILIARIO)


def _anio(bruto: str) -> str | None:
    """El año con el punto de los millares quitado, si es un año posible."""
    digitos = "".join(ch for ch in bruto if ch.isdigit())
    if len(digitos) != 4:
        return None
    return digitos if _ANIO_MINIMO <= int(digitos) <= _ANIO_MAXIMO else None


# -----------------------------------------------------------------------------
#  Lo que dice una página
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudentPage:
    """Lo que se leyó de una sola hoja del expediente.

    Una carátula trae identidad y ningún año; una hoja de asignaturas trae años
    y ninguna identidad. Las dos son esta misma cosa con campos distintos en
    ``None``, y es la agrupación la que las junta en un expediente.
    """

    page_number: int
    codigo: str | None = None
    apellidos: str | None = None
    nombres: str | None = None
    carrera: str | None = None
    anio_en_curso: str | None = None
    periodo: str | None = None
    #: Los años académicos que anuncia la hoja, en el orden en que están.
    anios: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)

    @property
    def nombre(self) -> str | None:
        """Apellidos y nombres, en el orden en que los imprime el formulario."""
        partes = [parte for parte in (self.apellidos, self.nombres) if parte]
        return " ".join(partes) if partes else None

    @property
    def abre_expediente(self) -> bool:
        """Si esta hoja empieza el expediente de alguien.

        Basta con el código o con el nombre. Son las dos formas que tiene el
        cartón de decir de quién es, y exigir las dos partiría en dos el
        expediente cuyo código no se dejó leer.
        """
        return bool(self.codigo or self.nombre)

    @property
    def needs_review(self) -> bool:
        """Si a esta hoja le falta algo que sólo la propia hoja puede dar.

        Una hoja de asignaturas sin nombre no necesita revisión: el nombre está
        en su carátula, que es otra hoja. Lo que sí la necesita es la hoja que
        no dijo absolutamente nada, porque entonces no se sabe ni de qué clase
        de hoja se trata.
        """
        return bool(self.warnings) or not (
            self.abre_expediente or self.anios or self.periodo
        )

    @property
    def review_reason(self) -> str | None:
        """Por qué hay que mirar esta hoja, en una frase. ``None`` si no hay que."""
        if not self.needs_review:
            return None
        if self.warnings:
            return "; ".join(self.warnings)
        return "la hoja no dice de quién es ni qué años cubre"

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page_number,
            "codigo": self.codigo,
            "apellidos": self.apellidos,
            "nombres": self.nombres,
            "carrera": self.carrera,
            "anio_en_curso": self.anio_en_curso,
            "periodo": self.periodo,
            "anios": list(self.anios),
            "warnings": list(self.warnings),
        }


# -----------------------------------------------------------------------------
#  La fila de valores que va debajo de la fila de leyendas
# -----------------------------------------------------------------------------


def _tolerancia(lineas: Sequence[TextLine]) -> float:
    """Cuánto puede separar en vertical a dos trozos de la misma fila.

    Se deduce del propio documento en vez de fijarse: la capa de texto de un PDF
    mide en puntos y el OCR, que no tiene coordenadas, numera las líneas de una
    en una. Media distancia entre alturas consecutivas separa las filas en los
    dos casos sin que nadie tenga que decir cuál es cuál.
    """
    alturas = sorted({linea.y for linea in lineas})
    saltos = [b - a for a, b in zip(alturas, alturas[1:], strict=False) if b > a]
    if not saltos:
        return 0.0
    saltos.sort()
    return saltos[len(saltos) // 2] * 0.6


def _fila_debajo(lineas: Sequence[TextLine], desde: float) -> list[TextLine]:
    """Los trozos de la primera fila que hay por debajo de ``desde``."""
    debajo = [linea for linea in lineas if linea.y > desde]
    if not debajo:
        return []
    primera = min(linea.y for linea in debajo)
    margen = _tolerancia(lineas)
    return sorted(
        (linea for linea in debajo if linea.y - primera <= margen),
        key=lambda linea: linea.x,
    )


def _partir_en_columnas(fila: Sequence[TextLine]) -> list[str]:
    """La fila como una lista de valores, venga en trozos o en una sola línea.

    La capa de texto entrega una celda por línea y ya están separadas. El OCR
    entrega la fila entera de corrido, y entonces lo único que queda para saber
    dónde acaba una columna y empieza la otra es el hueco que la máquina dejó,
    que Tesseract conserva como dos o más espacios.
    """
    if len(fila) > 1:
        return [
            texto
            for linea in fila
            if (texto := linea.text.strip(" _.:|"))
        ]
    if not fila:
        return []
    trozos = [pieza.strip(" _.:|") for pieza in re.split(r"\s{2,}", fila[0].text)]
    return [pieza for pieza in trozos if pieza]


#: Cuántas leyendas de la carátula hacen falta para dar por hecho que la hoja es
#: una carátula. Dos, y en la misma fila.
#:
#: No es una cautela de más: "Año" es una palabra de tres letras, y una hoja de
#: REGISTRO DE ESTUDIOS la imprime en cada curso -- "PRIMER AÑO 1.950". Sin esta
#: condición, esa línea pasaba por la fila de leyendas de una carátula y el
#: expediente se abría en nombre de la primera asignatura de la lista.
MIN_LEYENDAS = 2


def _leyendas(lineas: Sequence[TextLine]) -> dict[str, TextLine]:
    """Las leyendas de la carátula, si la hoja las lleva y en una sola fila.

    Que compartan fila es lo que las hace leyendas y no palabras sueltas: el
    formulario las imprime todas en el mismo renglón, encima de sus casillas.
    """
    candidatas: dict[str, TextLine] = {}
    for columna in COLUMNAS:
        for linea in lineas:
            if has_caption(linea.text, columna):
                candidatas.setdefault(columna, linea)
                break
    if len(candidatas) < MIN_LEYENDAS:
        return {}

    margen = _tolerancia(lineas)
    mejor: dict[str, TextLine] = {}
    for referencia in candidatas.values():
        misma_fila = {
            columna: linea
            for columna, linea in candidatas.items()
            if abs(linea.y - referencia.y) <= margen
        }
        if len(misma_fila) > len(mejor):
            mejor = misma_fila
    return mejor if len(mejor) >= MIN_LEYENDAS else {}


def _repartir(
    valores: Sequence[str],
    leyendas: dict[str, TextLine],
    fila: Sequence[TextLine],
) -> dict[str, str]:
    """A qué columna pertenece cada valor de la fila.

    Cuando las leyendas se localizaron y la fila vino en trozos, cada valor va a
    la leyenda que tiene encima -- la de la x más cercana -- que es como lo lee
    una persona. Cuando no, se reparte por el orden en que el formulario imprime
    las columnas, que es lo único que queda y sigue siendo un hecho del papel.
    """
    if len(valores) == len(fila) and len(leyendas) >= 2:
        reparto: dict[str, str] = {}
        for valor, trozo in zip(valores, fila, strict=False):
            columna = min(leyendas, key=lambda nombre: abs(leyendas[nombre].x - trozo.x))
            reparto.setdefault(columna, valor)
        if len(reparto) >= 2:
            return reparto
    return dict(zip(COLUMNAS, valores, strict=False))


def _nombre_valido(valor: str | None) -> str | None:
    if not valor:
        return None
    limpio = valor.strip(" _.:|")
    if len(limpio) < _LARGO_MINIMO_NOMBRE or _es_mobiliario(limpio):
        return None
    return limpio if _NOMBRE.match(_sin_tildes(limpio).upper()) else None


def _despegar_anio(carrera: str | None, anio: str | None) -> tuple[str | None, str | None]:
    """Devuelve el año en curso a su casilla cuando vino pegado a la carrera.

    Las dos columnas van seguidas y sus valores son cortos, así que cuando el
    hueco que las separa es más estrecho de lo que el lector considera una
    separación, "ODONTOLOGIA" y "3o." llegan como una sola cosa. Se despega sólo
    en el caso en que no cabe otra lectura: la casilla del año quedó vacía y lo
    que sobra al final de la carrera tiene exactamente la forma de un año en
    curso. No se está adivinando nada -- las dos partes están escritas -- sino
    deshaciendo una unión que hizo el lector y no el papel.
    """
    if anio or not carrera:
        return carrera, anio
    partes = carrera.rsplit(" ", 1)
    if len(partes) != 2:
        return carrera, anio
    cabeza, cola = partes
    encontrado = _ANIO_EN_CURSO.match(cola)
    if not encontrado or not cabeza.strip():
        return carrera, anio
    return cabeza.strip(), encontrado.group(1)


def _caratula(lineas: Sequence[TextLine]) -> dict[str, str]:
    """Los valores de la carátula, leídos de la fila que hay bajo las leyendas."""
    leyendas = _leyendas(lineas)
    if not leyendas:
        return {}
    ancla = min(leyendas.values(), key=lambda linea: linea.y)
    fila = _fila_debajo(lineas, ancla.y)
    valores = _partir_en_columnas(fila)
    if not valores:
        return {}
    return _repartir(valores, leyendas, fila)


def extract_student_page(lineas: Sequence[TextLine], page_number: int) -> StudentPage:
    """Leer una hoja del expediente, sea carátula o sea registro de estudios."""
    plano = _sin_tildes("\n".join(linea.text for linea in lineas))
    reparto = _caratula(lineas)

    codigo: str | None = None
    con_guion = _CODIGO.search(plano)
    if con_guion:
        codigo = f"{con_guion.group(1)}-{con_guion.group(2)}"
    else:
        sin_guion = _CODIGO_SIN_GUION.search(plano)
        if sin_guion:
            codigo = sin_guion.group(1)
        else:
            desde_columna = (reparto.get(CAPTION_CODIGO) or "").strip()
            if desde_columna and any(ch.isdigit() for ch in desde_columna):
                codigo = desde_columna

    periodo: str | None = None
    marca = _PERIODO.search(plano)
    if marca:
        periodo = f"{marca.group(1)}/{marca.group(2)}"
    else:
        periodo = (reparto.get(CAPTION_PERIODO) or "").strip() or None

    anio_en_curso: str | None = None
    en_curso = _ANIO_EN_CURSO.match((reparto.get(CAPTION_ANIO) or "").strip())
    if en_curso:
        anio_en_curso = en_curso.group(1)

    apellidos = _nombre_valido(reparto.get(CAPTION_APELLIDOS))
    nombres = _nombre_valido(reparto.get(CAPTION_NOMBRES))
    carrera = _nombre_valido(reparto.get(CAPTION_CARRERA))
    carrera, anio_en_curso = _despegar_anio(carrera, anio_en_curso)

    # Los años que la hoja de asignaturas anuncia curso por curso. Se conservan
    # en el orden en que están impresos y sin quitar repetidos: dos veces el
    # mismo año en una hoja es un dato del papel, no un descuido de la lectura.
    anios = tuple(
        anio
        for anio in (_anio(encontrado) for encontrado in _ANIO_ACADEMICO.findall(plano))
        if anio
    )
    if not anios and periodo:
        # El período con el año en cuatro cifras -- "1o/1993" -- fecha la hoja
        # igual de bien. Con dos cifras no: "93" es 1993 por costumbre y 1893
        # por aritmética, y aquí no se completa lo que el papel no dice.
        del_periodo = _ANIO_SUELTO.search(periodo)
        if del_periodo:
            anios = (del_periodo.group(1),)

    warnings: list[str] = []
    for etiqueta, valor in (("los apellidos", apellidos), ("los nombres", nombres)):
        if valor and _DANO_EN_EL_NOMBRE.search(valor):
            warnings.append(f"{etiqueta} traen un carácter que no es una letra: {valor}")

    return StudentPage(
        page_number=page_number,
        codigo=codigo,
        apellidos=apellidos,
        nombres=nombres,
        carrera=carrera,
        anio_en_curso=anio_en_curso,
        periodo=periodo,
        anios=anios,
        warnings=warnings,
    )


# -----------------------------------------------------------------------------
#  El expediente: una unidad documental por estudiante
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudentRecord:
    """El expediente de un estudiante, con las páginas que ocupa.

    Es la unidad documental que va al inventario: una fila, tantos folios como
    hojas, y por fechas extremas el primero y el último de los años que sus
    hojas declaran.
    """

    page_numbers: list[int]
    codigo: str | None = None
    apellidos: str | None = None
    nombres: str | None = None
    carrera: str | None = None
    anio_en_curso: str | None = None
    periodo: str | None = None
    anios: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)

    @property
    def page_number(self) -> int:
        """La primera hoja, que es donde se cita el expediente."""
        return self.page_numbers[0]

    @property
    def nombre(self) -> str | None:
        partes = [parte for parte in (self.apellidos, self.nombres) if parte]
        return " ".join(partes) if partes else None

    @property
    def fecha_inicial(self) -> str | None:
        """El primer año que declara el expediente -- "PRIMER AÑO 1.950"."""
        return min(self.anios) if self.anios else None

    @property
    def fecha_final(self) -> str | None:
        """El último -- "SEXTO AÑO 1.955"."""
        return max(self.anios) if self.anios else None

    @property
    def folios(self) -> int:
        return len(self.page_numbers)

    @property
    def is_complete(self) -> bool:
        return bool(self.nombre and self.codigo and self.anios)

    @property
    def needs_review(self) -> bool:
        return bool(self.warnings) or not self.is_complete

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": list(self.page_numbers),
            "codigo": self.codigo,
            "apellidos": self.apellidos,
            "nombres": self.nombres,
            "carrera": self.carrera,
            "anio_en_curso": self.anio_en_curso,
            "periodo": self.periodo,
            "anios": list(self.anios),
            "fecha_inicial": self.fecha_inicial,
            "fecha_final": self.fecha_final,
            "folios": self.folios,
            "warnings": list(self.warnings),
        }


def _mismo_estudiante(anterior: StudentPage, actual: StudentPage) -> bool:
    """Si la carátula que empieza es la del expediente que ya venía abierto.

    Pasa en los expedientes de varios períodos: el mismo estudiante tiene una
    carátula por matrícula, y son un solo expediente. El código es lo que lo
    dice; cuando falta, el nombre.
    """
    if anterior.codigo and actual.codigo:
        return anterior.codigo == actual.codigo
    if anterior.nombre and actual.nombre:
        return anterior.nombre == actual.nombre
    return False


def group_students(paginas: Sequence[StudentPage]) -> list[StudentRecord]:
    """Juntar las hojas en expedientes, uno por estudiante.

    Una hoja con identidad abre expediente salvo que sea del mismo estudiante
    que el anterior. Una hoja sin identidad continúa el que esté abierto. Y las
    hojas que aparecen antes de la primera carátula no se pierden: forman un
    expediente sin nombre, declarado como tal, para que alguien las mire.
    """
    expedientes: list[list[StudentPage]] = []
    for pagina in paginas:
        if not expedientes:
            expedientes.append([pagina])
            continue
        actual = expedientes[-1]
        identidad = next((hoja for hoja in actual if hoja.abre_expediente), None)
        continua = identidad is not None and _mismo_estudiante(identidad, pagina)
        if pagina.abre_expediente and not continua:
            expedientes.append([pagina])
        else:
            actual.append(pagina)
    return [_consolidar(grupo) for grupo in expedientes]


def _consolidar(hojas: Sequence[StudentPage]) -> StudentRecord:
    """Un expediente a partir de sus hojas, sin rellenar lo que ninguna dijo."""

    def primero(campo: str) -> str | None:
        for hoja in hojas:
            valor = getattr(hoja, campo)
            if valor:
                return valor
        return None

    anios: list[str] = []
    for hoja in hojas:
        anios.extend(hoja.anios)

    registro = StudentRecord(
        page_numbers=[hoja.page_number for hoja in hojas],
        codigo=primero("codigo"),
        apellidos=primero("apellidos"),
        nombres=primero("nombres"),
        carrera=primero("carrera"),
        anio_en_curso=primero("anio_en_curso"),
        periodo=primero("periodo"),
        anios=tuple(anios),
    )
    return _con_avisos(registro, hojas)


def _con_avisos(registro: StudentRecord, hojas: Sequence[StudentPage]) -> StudentRecord:
    """Lo que no se sostiene del expediente ya armado."""
    warnings: list[str] = []
    for hoja in hojas:
        warnings.extend(hoja.warnings)
    if not registro.nombre:
        warnings.append("no se pudo leer el nombre del estudiante")
    if not registro.codigo:
        warnings.append("no se pudo leer el código del estudiante")
    if not registro.anios:
        warnings.append("no se pudo leer ningún año, así que no hay fechas extremas")
    return StudentRecord(
        page_numbers=registro.page_numbers,
        codigo=registro.codigo,
        apellidos=registro.apellidos,
        nombres=registro.nombres,
        carrera=registro.carrera,
        anio_en_curso=registro.anio_en_curso,
        periodo=registro.periodo,
        anios=registro.anios,
        warnings=warnings,
    )


def merge_pages(primera: StudentPage, segunda: StudentPage) -> StudentPage:
    """Completar con una segunda lectura lo que la primera dejó en blanco.

    Sólo lo que faltaba. Un valor que la capa de texto ya leyó no lo pisa el
    OCR, porque dos lecturas que discrepan es un hecho que el operador tiene que
    ver y no un empate que gane el último en escribir.
    """

    def elegir(campo: str):
        return getattr(primera, campo) or getattr(segunda, campo)

    fundida = StudentPage(
        page_number=primera.page_number,
        codigo=elegir("codigo"),
        apellidos=elegir("apellidos"),
        nombres=elegir("nombres"),
        carrera=elegir("carrera"),
        anio_en_curso=elegir("anio_en_curso"),
        periodo=elegir("periodo"),
        anios=primera.anios or segunda.anios,
    )
    # Los avisos se vuelven a calcular sobre lo fundido: un hueco que la segunda
    # lectura llenó ya no es un hueco.
    warnings: list[str] = []
    for etiqueta, valor in (
        ("los apellidos", fundida.apellidos),
        ("los nombres", fundida.nombres),
    ):
        if valor and _DANO_EN_EL_NOMBRE.search(valor):
            warnings.append(f"{etiqueta} traen un carácter que no es una letra: {valor}")
    return StudentPage(
        page_number=fundida.page_number,
        codigo=fundida.codigo,
        apellidos=fundida.apellidos,
        nombres=fundida.nombres,
        carrera=fundida.carrera,
        anio_en_curso=fundida.anio_en_curso,
        periodo=fundida.periodo,
        anios=fundida.anios,
        warnings=warnings,
    )
