"""Cada fila del inventario contra el texto de sus páginas en el original: lo que la auditoría revisa de una.

Lo pidió el operador el 2026-11-09, al ver la auditoría de una corrida de «Solo
inventario» con «muestra: 0 de 0»: sin PDF cortados no había qué revisar, y lo
que se entrega en esa corrida son **filas**. «Necesito que hagas un buen
trabajo»: la muestra de 100 se hace entonces con filas del inventario, y cada
una se compara con el papel de donde salió, con lo que **su habilidad** espera
de él -- «que la auditoría tome como margen de error cada patrón de cada
habilidad» --:

- **Acta de consejo**: el número del acta, la fecha de la sesión, si es
  ordinaria o extraordinaria, que los folios cuadren, y que cada nombre propio
  del resumen esté en el acta (un nombre que la IA puso y el acta no trae).
- **Una persona** -- historia académica, acta de grado, nómina, certificado --:
  su cédula, tarjeta, libreta, código o número, y su nombre.
- **Una fila del FUID** -- resoluciones, matrículas --: su número.
- **Sus fechas extremas**, en toda clase de fila (2026-11-10, el revisor de
  fechas): la inicial y la final contra su papel con la regla de su habilidad
  (``fechas_extremas.contrastar_las_fechas``). Lo pidió el operador: «estar muy
  seguro de cada fecha en cada documento, sin importar la habilidad», y que los
  auditores cubran «todas las habilidades, todos los documentos, todos los
  patrones, todo el margen de errores». Una fecha que el papel corrige con dos
  pruebas es **error**; la que sólo no confirma -- o se aparta como el OCR -- es
  ``Pregunta`` para la IA. El acta conserva su regla de la apertura de la
  sesión, y la corrección con prueba la vuelve error.

**Tras la revisión adversarial del revisor de fechas** (2026-11-10) dos guardas,
para que el margen mida errores y no la letra:

- **Un texto que no se deja leer no prueba nada en contra** (``texto_legible``).
  La capa de un escaneo sobre letra a mano son las etiquetas impresas del
  formulario y basura donde va lo escrito: las 88 filas de dos PDF de
  Enfermería salían «en duda» sin alterar nada. Con más de ``BASURA_MAXIMA`` de
  palabras rotas, lo que el papel confirma cuenta, y lo que no encuentra queda
  **sin dato** con su motivo: ni duda ni error. Medido (2026-11-10): ninguna de
  las 88 filas de Enfermería pasa por legible, y 214 de las 227 actas de
  Odontología sí; la capa de Afinia y de Kingspan, también.
- **La ventana de años del libro** (``ventana``) llega a la revisión de las
  fechas: la fecha fuera de ella es duda sin pagar la IA, como al procesar.

Error es lo que el papel **contradice**: los encabezados que abren sesión en
esas páginas dicen otro número u otra clase de sesión, o los folios no suman.
Lo que el papel sólo **no confirma** -- la lectura de la auditoría no lo
encuentra, que puede ser la letra o el OCR -- es duda, y va como ``Pregunta``
a la IA si la corrida se hizo con ella: es ella quien, citando el papel, lo
confirma o lo vuelve error (``application/auditoria_de_filas.py``).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache

from .acta_consejo import (
    MARGEN_DE_FOLIOS,
    MARGEN_RELATIVO,
    VENTANA_DE_LA_FECHA,
    encabezados_de_acta,
    fechas_del_texto,
    leer_acta,
    primera_fecha,
)
from .fechas_extremas import (
    ANIO,
    EXTREMOS,
    SESION,
    Correccion,
    FechasDeLaFila,
    RevisionDeFechas,
    contrastar_las_fechas,
    fechas_de_la_fila,
    texto_acotado,
)

#: Lo que no se leyó, como va en el inventario.
NO_LEIDO = "N/A"
#: Qué tan parecida tiene que ser una palabra del texto a una del dato para
#: darla por la misma: el OCR cambia una letra en cada palabra larga.
PARECIDO = 0.8
#: Cuántas palabras de un nombre pueden faltar en el texto: «LUISA LEONOR
#: ARÉVALO TOVAR» en un acta que dice «Luisa Arévalo Tovar».
PALABRAS_QUE_PUEDEN_FALTAR = 1
#: Las palabras que unen un nombre y no lo identifican.
_PARTICULAS = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "Y", "E", "SAN", "SANTA", "VDA", "VIUDA"})
#: Lo que abre una frase o un cargo y no es un nombre propio: una frase del
#: resumen que sólo trae esto no se busca.
_COMUNES = frozenset(
    {
        "EL", "LA", "LOS", "LAS", "UN", "UNA", "SE", "EN", "CON", "POR", "PARA", "AL", "ADEMAS",
        "TRAS", "ASIMISMO", "FINALMENTE", "TAMBIEN", "DURANTE", "ESTE", "ESTA", "DOCTOR", "DOCTORA",
        "DR", "DRA", "SR", "SRA", "PROFESOR", "PROFESORA", "LIC", "ING",
        # Los cargos que preceden al nombre: «Decano Eduardo Ordosgoitia Osorio».
        "DECANO", "DECANA", "VICEDECANO", "VICEDECANA", "RECTOR", "RECTORA", "VICERRECTOR",
        "VICERRECTORA", "JEFE", "COORDINADOR", "COORDINADORA", "DIRECTOR", "DIRECTORA", "SECRETARIO",
        "SECRETARIA", "REPRESENTANTE", "ESTUDIANTE", "ESTUDIANTES", "DOCENTE", "DOCENTES",
        "PRESIDENTE", "PRESIDENTA", "ENCARGADA", "ENCARGADO", "CURRICULAR", "ACADEMICO", "ACADEMICA",
    }
)
#: Lo que hace de una frase con mayúsculas una institución o un tema, no una
#: persona: «Universidad de Burdeos», «Semiología y Diagnóstico».
_INSTITUCIONALES = frozenset(
    {
        "UNIVERSIDAD", "FACULTAD", "CONSEJO", "PROGRAMA", "PROGRAMAS", "DEPARTAMENTO", "COMITE",
        "MAESTRIA", "DOCTORADO", "ESPECIALIZACION", "OFICINA", "DIVISION", "VICERRECTORIA",
        "DECANATURA", "CENTRO", "INSTITUTO", "CLINICA", "HOSPITAL", "REVISTA", "SEMINARIO",
        "CONGRESO", "JORNADA", "JORNADAS", "PLAN", "SISTEMA", "ASIGNATURA", "AREA", "ESCUELA",
        "COLEGIO", "MINISTERIO", "ASOCIACION", "FUNDACION", "ACREDITACION", "REGISTRO",
        "RESOLUCION", "ACUERDO", "DECRETO", "LEY", "CONVENIO", "GRUPO", "BIENESTAR", "SECRETARIA",
        "GOBERNACION", "ALCALDIA", "EMPRESA", "COOPERATIVA", "BANCO", "PROYECTO", "CURSO",
        "DIPLOMADO", "SALUD", "CIENCIAS", "ODONTOLOGIA", "MEDICINA", "ENFERMERIA", "DERECHO",
    }
)
#: «lleva delante, como anexo, las páginas 1 a 7 del PDF, escaneadas antes que
#: el acta»: esas páginas suman a los folios de la fila (``_con_las_previas``).
_ANEXO_PREVIO = re.compile(r"LAS PAGINAS (\d+) A (\d+) DEL PDF ESCANEADAS ANTES QUE EL ACTA")
#: Una frase con mayúsculas del resumen: dos palabras o más que empiezan por
#: mayúscula, con «de», «del», «la» entre ellas.
#: Sin el punto dentro de la palabra: «…Carolina Mendoza Pájaro. Consejo
#: Académico aprobó…» son dos frases, no una que acaba descartada por
#: «Consejo» (las pruebas, 2026-11-09).
_FRASE_PROPIA = re.compile(
    r"[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü\-]*"
    r"(?:[ \t]+(?:(?:de|del|la|las|los|y)[ \t]+)?[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü\-]*)+"
)
#: Hasta cuántas cifras se mira en el texto: un número más corto que esto se
#: encuentra en cualquier parte y no prueba nada.
CIFRAS_MINIMAS = 4

#: Los campos de las fechas extremas, como se le preguntan a la IA (2026-11-10).
CAMPOS_DE_FECHA = ("fecha_inicial", "fecha_final")

#: Desde qué parte de palabras rotas el texto de un documento ya no prueba lo
#: que no trae (2026-11-10). Medido por documento, con ``basura_del_texto``:
#: las 88 filas de Enfermería escritas a mano dan de 0,193 a 0,6 (mediana
#: 0,367); las 227 actas de Odontología, mediana 0,04 y el 90 % bajo 0,118;
#: Afinia, de 0,05 a 0,09; Kingspan, de 0,10 a 0,14 con sus códigos y facturas.
BASURA_MAXIMA = 0.18
#: Por qué una fecha o un dato que el texto no trae queda sin dato y no en duda.
TEXTO_ILEGIBLE = (
    "el texto de sus hojas no se deja leer (letra a mano o capa con basura): lo que no "
    "trae no prueba nada en contra"
)
_PALABRA = re.compile(r"[(«\"'¿¡]?[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}[.,;:)»\"'?!]{0,2}")
_VOCAL = re.compile(r"[AEIOUYaeiouyÁÉÍÓÚáéíóú]")
_NUMERO = re.compile(r"[($#Nº°]{0,2}\d[\d.,:/\-°º]*[%)]?[.,;:]?")
#: Un código: «RE2310202405234», «001-FC-00012345», «UPD3859724». Su primer
#: tramo, hasta el primer «-», «/» o «.», lleva alguna cifra: lo mira la
#: búsqueda por delante, que no vuelve atrás. Con ``[A-Z0-9]*\d[A-Z0-9]*`` cada
#: reparto del tramo entre los dos asteriscos se probaba: «1» × 12 000 + «x»
#: tardaba 2,9 s en ``basura_del_texto`` y crecía al cuadrado (la revisión
#: adversarial, 2026-11-10). Las fichas que reconoce son las mismas.
_CODIGO = re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]+(?:[-/.][A-Z0-9]+)*[.,;:]?")

#: Los campos de una fila de persona que son números, en el orden en que se dicen.
_CAMPOS_DE_NUMERO = (
    ("cedula", "la cédula"),
    ("tarjeta", "la tarjeta de identidad"),
    ("libreta", "la libreta militar"),
    ("codigo", "el código"),
    ("certificado", "el número del certificado"),
)


@dataclass(frozen=True, slots=True)
class Pregunta:
    """Un dato de la fila que el papel no confirmó, para que la IA lo busque citando el texto."""

    campo: str
    valor: str
    #: Qué se le dice al operador si queda sin confirmar.
    duda: str
    #: De una fecha (2026-11-10): la que dice el lector de la regla de su
    #: habilidad, si dice alguna. La IA sólo la vuelve error citando ésa: una
    #: cita con la próxima reunión o con la fecha de la plantilla no basta.
    dice_el_papel: date | None = None
    #: ``False`` si va derecho a duda, sin pagar la IA (2026-11-10): una fecha
    #: fuera de los años del libro no la decide una cita.
    para_la_ia: bool = True


@dataclass(frozen=True, slots=True)
class RevisionDeLaFila:
    """Lo que el papel contradice, lo que no confirma y lo que confirma de una fila."""

    errores: tuple[str, ...] = ()
    preguntas: tuple[Pregunta, ...] = ()
    confirmados: tuple[str, ...] = ()
    #: Lo que no se pudo mirar -- la fila no lo trae --: ni error ni duda.
    sin_dato: tuple[str, ...] = ()

    @property
    def dudas(self) -> tuple[str, ...]:
        return tuple(p.duda for p in self.preguntas)


def plano(texto: object) -> str:
    """Mayúsculas sin tildes, con sólo letras y cifras separadas por un espacio."""
    sin_tildes = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_tildes.upper()).split())


def cifras(valor: object) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def basura_del_texto(textos: Sequence[str]) -> float:
    """La parte de las fichas del texto que no es una palabra, un número ni un código: lo que deja el OCR de la letra a mano.

    No cuentan los signos sueltos («—», «•») ni las letras solas; una palabra
    es de dos letras o más con alguna vocal. Sin fichas, 1: no hay qué leer.

    Una vez por documento (2026-11-10): las puntas de Kingspan que se miran
    contra todo el original lo pedían, cada una, de las mismas cientos de hojas.
    """
    return _basura(tuple(texto or "" for texto in textos))


@lru_cache(maxsize=8)
def _basura(textos: tuple[str, ...]) -> float:
    total = rotas = 0
    for texto in textos:
        for ficha in texto.split():
            if not any(c.isalnum() for c in ficha):
                continue
            total += 1
            if len(ficha) == 1:
                continue
            if _PALABRA.fullmatch(ficha) and _VOCAL.search(ficha):
                continue
            if _NUMERO.fullmatch(ficha) or _CODIGO.fullmatch(ficha):
                continue
            rotas += 1
    return rotas / total if total else 1.0


def texto_legible(textos: Sequence[str]) -> bool:
    """Si el texto de un documento se deja leer: hasta ``BASURA_MAXIMA`` de fichas rotas (2026-11-10)."""
    return basura_del_texto(textos) <= BASURA_MAXIMA


def _leido(valor: object) -> str | None:
    texto = " ".join(str(valor or "").split())
    return texto if texto and texto.upper() != NO_LEIDO else None


def _entero(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    texto = cifras(valor)
    return int(texto) if texto and str(valor).strip().isdigit() else None


def numero_en_el_texto(numero: str, texto: str) -> bool:
    """Si esas cifras están escritas en el texto, con o sin puntos de miles («45.466.499»)."""
    junto = re.sub(r"(?<=\d)[\s.,'’\-](?=\d)", "", texto or "")
    return bool(numero) and re.search(rf"(?<!\d){re.escape(numero)}(?!\d)", junto) is not None


#: Cuántas palabras de más puede haber entre las de un nombre en el texto:
#: «LUISA LEONOR (doctora) ARÉVALO TOVAR», un salto de renglón con basura.
HOLGURA_DEL_NOMBRE = 4


def nombre_en_el_texto(nombre: str, texto: str, *, palabras_del_texto: Sequence[str] | None = None) -> bool:
    """Si el nombre está en el texto: sus palabras **juntas**, con una letra cambiada por el OCR, faltando una a lo sumo.

    Juntas: dentro de una ventana del largo del nombre más ``HOLGURA_DEL_NOMBRE``
    palabras. Buscadas sueltas por todo el texto, «Ricardo Pérez Gómez» --
    inventado -- «aparecía» en una de cada cuatro actas de Odontología (la
    revisión, 2026-11-09). Las partículas («de», «del») y las palabras de menos
    de tres letras no cuentan; un nombre de dos palabras necesita las dos.
    """
    palabras = [p for p in plano(nombre).split() if len(p) >= 3 and p not in _PARTICULAS]
    if not palabras:
        return True
    fichas = list(palabras_del_texto) if palabras_del_texto is not None else plano(texto).split()
    if not fichas:
        return False
    vocabulario = set(fichas)
    # Qué palabras del texto valen por cada una del nombre, y dónde están.
    donde: list[list[int]] = []
    for palabra in palabras:
        parecidas = _parecidas(palabra, vocabulario)
        donde.append([i for i, ficha in enumerate(fichas) if ficha in parecidas])
    necesarias = len(palabras) - (PALABRAS_QUE_PUEDEN_FALTAR if len(palabras) >= 3 else 0)
    ancho = len(palabras) + HOLGURA_DEL_NOMBRE
    # Alrededor de la primera palabra -- el nombre de pila, o el primer
    # apellido --, que nunca puede ser la que falta: «Raúl Muskus López» no lo
    # confirma «Helena Muskus López» (la segunda revisión, 2026-11-09).
    for ancla in donde[0]:
        dentro = sum(1 for posiciones in donde if any(ancla - ancho < i < ancla + ancho for i in posiciones))
        if dentro >= necesarias:
            return True
    return False


def _parecidas(palabra: str, vocabulario: set[str]) -> set[str]:
    """Las palabras del texto que valen por ésta: ella misma, o con una letra cambiada por el OCR."""
    if palabra in vocabulario:
        return {palabra}
    candidatas = [p for p in vocabulario if abs(len(p) - len(palabra)) <= 2 and p[:1] == palabra[:1]]
    return set(difflib.get_close_matches(palabra, candidatas, n=3, cutoff=PARECIDO))


def frases_propias(
    resumen: str, *, de_pila: frozenset[str] | None = None, apellidos: frozenset[str] | None = None
) -> list[str]:
    """Los nombres de persona del resumen: cada frase de dos palabras o más con mayúscula, sin su cargo.

    «presidido por la doctora LUISA LEONOR ARÉVALO TOVAR» da «LUISA LEONOR
    ARÉVALO TOVAR»; «Decano Eduardo Ordosgoitia Osorio», «Eduardo Ordosgoitia
    Osorio». Con la lista de nombres y apellidos, sólo las que tienen uno de
    ellos y ninguna palabra de institución: «Universidad de Burdeos» y
    «Semiología y Diagnóstico» no son personas (el operador pidió los nombres
    de las personas, 2026-11-09). Sin la lista, todas.
    """
    frases: list[str] = []
    trozos = []
    for hallada in _FRASE_PROPIA.finditer(resumen or ""):
        # «Katyuska Medina Márquez y Johnny Ricardo Galindo Ruello» son dos
        # personas: se buscan cada una por su lado, porque juntas no están en
        # el acta (la medida del 2026-11-09). «María del Carmen» sigue entera.
        trozos.extend(re.split(r"[ 	]+y[ 	]+", hallada.group(0)))
    for trozo in trozos:
        palabras = trozo.split()
        while palabras and plano(palabras[0]) in _COMUNES | _PARTICULAS:
            palabras.pop(0)
        llanas = [plano(p) for p in palabras]
        propias = [p for p in llanas if p not in _PARTICULAS and p not in _COMUNES]
        if len(propias) < 2:
            continue
        if de_pila is not None or apellidos is not None:
            if any(p in _INSTITUCIONALES for p in llanas):
                continue
            if not any(p in (de_pila or ()) or p in (apellidos or ()) for p in propias):
                continue
        frase = " ".join(palabras).strip(" .,;:")
        if frase not in frases:
            frases.append(frase)
    return frases


# -- qué espera cada clase de fila ------------------------------------------------------


def clase_de_la_fila(fila: Mapping[str, object]) -> str:
    """«acta», «persona», «fuid» o «otra»: qué se puede comprobar de esta fila en su papel."""
    tipo = plano(fila.get("tipo"))
    if tipo == "FILA DEL FUID" or isinstance(fila.get("fuid"), Mapping):
        return "fuid"
    if tipo == "ACTA DE CONSEJO" or (not tipo and fila.get("acta") is not None and fila.get("numero") is not None):
        return "acta"
    if any(_leido(fila.get(campo)) for campo, _ in _CAMPOS_DE_NUMERO) or _leido(fila.get("nombre")):
        return "persona"
    return "otra"


def revisar_la_fila(
    fila: Mapping[str, object],
    textos: Sequence[str],
    *,
    de_pila: frozenset[str] | None = None,
    apellidos: frozenset[str] | None = None,
    regla_de_fechas: str = EXTREMOS,
    ventana: tuple[int, int] | None = None,
    legible: bool | None = None,
) -> RevisionDeLaFila:
    """La fila contra el texto de sus páginas (``textos``, en orden desde su primera página).

    ``de_pila`` y ``apellidos`` dicen qué frases del resumen de un acta son
    nombres de persona (``frases_propias``). ``regla_de_fechas`` es la de su
    habilidad (``perfil.regla_de_fechas``): con ella se contrastan las fechas
    extremas de toda fila que las traiga (2026-11-10). El acta lleva siempre la
    de la sesión, dentro de su propia revisión de la fecha.

    ``ventana`` son los años del libro para las fechas; ``legible``, si el texto
    se deja leer (``texto_legible`` si no se dice). Con un texto que no se deja
    leer, lo que el papel no trae -- la fecha, la cédula, el nombre -- queda
    sin dato y no en duda: la letra a mano no es un error de la entrega
    (2026-11-10). Lo que no depende del texto -- los folios contra las
    páginas, una fecha fuera de los años del libro -- se sigue diciendo.
    """
    if legible is None:
        legible = texto_legible(textos)
    clase = clase_de_la_fila(fila)
    if clase == "acta":
        return _revisar_un_acta(fila, textos, de_pila=de_pila, apellidos=apellidos, legible=legible)
    if clase == "persona":
        revision = _revisar_una_persona(fila, textos)
    elif clase == "fuid":
        revision = _revisar_una_fila_del_fuid(fila, textos)
    else:
        revision = RevisionDeLaFila()
    if not legible:
        revision = _sin_lo_que_no_se_lee(revision)
    juntas = juntar(
        revision,
        revisar_las_fechas_de_la_fila(fila, textos, regla=regla_de_fechas, ventana=ventana, legible=legible),
    )
    if not (juntas.errores or juntas.preguntas or juntas.confirmados or juntas.sin_dato):
        return RevisionDeLaFila(sin_dato=("la fila no trae datos que buscar en el papel",))
    return juntas


def juntar(*revisiones: RevisionDeLaFila) -> RevisionDeLaFila:
    """Lo que dicen varias revisiones de la misma fila, en una."""
    return RevisionDeLaFila(
        tuple(e for r in revisiones for e in r.errores),
        tuple(p for r in revisiones for p in r.preguntas),
        tuple(c for r in revisiones for c in r.confirmados),
        tuple(s for r in revisiones for s in r.sin_dato),
    )


def _sin_lo_que_no_se_lee(revision: RevisionDeLaFila) -> RevisionDeLaFila:
    """Lo que el texto no confirmó, sin dato: con un texto que no se deja leer no es duda (2026-11-10)."""
    return RevisionDeLaFila(
        errores=revision.errores,
        preguntas=tuple(p for p in revision.preguntas if not p.para_la_ia),
        confirmados=revision.confirmados,
        sin_dato=revision.sin_dato
        + tuple(f"{p.duda}: {TEXTO_ILEGIBLE}" for p in revision.preguntas if p.para_la_ia),
    )


def fechas_sin_prueba_si_no_se_leen(revision: RevisionDeFechas, *, legible: bool) -> RevisionDeFechas:
    """Las fechas de un documento cuyo texto no se deja leer: lo confirmado vale, lo demás queda sin dato.

    La guarda que ya tiene el revisor al procesar con el texto a medias
    (``inventario.SIN_TODO_EL_TEXTO``), ahora en las dos muestras de la
    auditoría (2026-11-10): sin ella, las 88 filas de dos PDF de Enfermería
    escritos a mano salían «en duda» sin alterar nada. Una corrección tampoco
    vale: sus dos pruebas salen de un texto que no se lee. Lo que no depende
    del texto -- la fecha fuera de los años del libro (``para_la_ia=False``) --
    sigue en duda.
    """
    if legible:
        return revision
    sueltas = [c.campo for c in revision.correcciones]
    sueltas += [p.campo for p in revision.preguntas if getattr(p, "para_la_ia", True)]
    dichos = {"fecha_inicial": "la fecha inicial", "fecha_final": "la fecha final"}
    return replace(
        revision,
        correcciones=(),
        preguntas=tuple(p for p in revision.preguntas if not getattr(p, "para_la_ia", True)),
        sin_dato=revision.sin_dato
        + tuple(f"{dichos.get(campo, campo)}: {TEXTO_ILEGIBLE}" for campo in dict.fromkeys(sueltas)),
    )


# -- las fechas extremas de toda fila (2026-11-10) ------------------------------------------


def revisar_las_fechas_de_la_fila(
    fila: Mapping[str, object],
    textos: Sequence[str],
    *,
    regla: str = EXTREMOS,
    ventana: tuple[int, int] | None = None,
    legible: bool = True,
) -> RevisionDeLaFila:
    """La fecha inicial y la final de la fila contra su papel, con la regla de su habilidad.

    Es ``contrastar_las_fechas`` -- el mismo margen que el revisor de fechas al
    procesar: un dígito del OCR o la precisión son duda -- dicho como la
    auditoría dice una fila:

    - lo que el papel **corrige con prueba** es error («la fecha inicial dice
      01/02/2005 y el papel 15/03/2005 (…)»): lo entregado no es lo que dice;
    - lo que no confirma es una ``Pregunta`` para la IA, con lo que dice el
      lector de la regla;
    - la fila sin fechas no se mira ni dice nada: no toda habilidad las lleva.

    Si la fila trae una sola fecha -- un acta de grado, un certificado -- se
    revisa una vez y se dice «la fecha», no «la inicial» y «la final»: dos
    preguntas iguales a la IA son tokens pagados dos veces.

    La fecha que la fila tomó de otra parte -- el libro, la serie -- la deja sin
    dato el contraste, y sólo pregunta si cae fuera de la ``ventana``: no infla
    el margen ni paga la IA (2026-11-10). Con ``legible=False``, lo que el texto
    no confirma queda sin dato (``fechas_sin_prueba_si_no_se_leen``).
    """
    fechas = fechas_de_la_fila(fila)
    if fechas is None:
        return RevisionDeLaFila()
    revision = fechas_sin_prueba_si_no_se_leen(
        contrastar_las_fechas(fechas, textos, regla=regla, ventana=ventana), legible=legible
    )
    una_sola = fechas.inicial is not None and fechas.inicial == fechas.final

    def dicho(texto: str) -> str:
        return texto.replace("la fecha inicial", "la fecha") if una_sola else texto

    def suya(campo_o_dicho: str) -> bool:
        return not una_sola or campo_o_dicho in ("fecha_inicial", "la fecha inicial")

    return RevisionDeLaFila(
        errores=tuple(dicho(error_de_fecha(c, fechas)) for c in revision.correcciones if suya(c.campo)),
        preguntas=tuple(
            Pregunta(p.campo, p.valor, dicho(p.duda), p.dice_el_papel, getattr(p, "para_la_ia", True))
            for p in revision.preguntas
            if suya(p.campo)
        ),
        confirmados=tuple(dicho(c) for c in revision.confirmadas if suya(c)),
        sin_dato=tuple(dicho(s) for s in revision.sin_dato if not una_sola or not s.startswith("la fecha final")),
    )


def error_de_fecha(correccion: Correccion, fechas: FechasDeLaFila, *, dicho: str | None = None) -> str:
    """«la fecha inicial dice X y el papel Y (prueba)»: una corrección con prueba, dicha como error de la auditoría."""
    dicho = dicho or ("la fecha inicial" if correccion.campo == "fecha_inicial" else "la fecha final")
    papel = fecha_escrita(correccion.dice_el_papel, fechas.precision)
    if correccion.dice_la_fila is None:
        return f"{dicho} falta en la fila y el papel dice {papel} ({correccion.prueba})"
    return f"{dicho} dice {fecha_escrita(correccion.dice_la_fila, fechas.precision)} y el papel {papel} ({correccion.prueba})"


def fecha_escrita(fecha: date, precision: str) -> str:
    """Una fecha como va en el informe: «17/12/2012», o el año solo."""
    return str(fecha.year) if precision == ANIO else fecha.strftime("%d/%m/%Y")


def _revisar_un_acta(
    fila: Mapping[str, object],
    textos: Sequence[str],
    *,
    de_pila: frozenset[str] | None = None,
    apellidos: frozenset[str] | None = None,
    legible: bool = True,
) -> RevisionDeLaFila:
    errores: list[str] = []
    preguntas: list[Pregunta] = []
    confirmados: list[str] = []
    sin_dato: list[str] = []
    texto = "\n".join(textos)

    # El número: los encabezados que abren sesión en sus páginas lo dicen. Con
    # ellos, sólo ellos confirman: «APROBACIÓN DEL ACTA ANTERIOR 3» no es el
    # número del acta (la revisión, 2026-11-09). Sin ellos, el membrete
    # corrido o «ACTA No. N» escrito así.
    numero = _leido(fila.get("numero"))
    encabezados = encabezados_de_acta(list(textos))
    fuertes = [e for e in encabezados if e.fuerte]
    if numero is None or not cifras(numero):
        sin_dato.append("el número del acta")
    else:
        valor = int(cifras(numero))
        if fuertes:
            if valor in {e.valor for e in fuertes}:
                confirmados.append("el número del acta")
            else:
                dice = ", ".join(sorted({e.numero for e in fuertes}))
                dicho = f"el acta dice No. {dice} y la fila No. {numero}"
                # Un dígito, o una diferencia que la fila ya registró entre el
                # OCR y la IA («el OCR leyó 006 y la IA 005»), es la lectura,
                # no el papel: lo decide la IA.
                if _difiere_en_un_digito(cifras(numero), [e.numero for e in fuertes]) or _ocr_contra_ia(fila):
                    preguntas.append(Pregunta("numero", numero, dicho))
                else:
                    errores.append(dicho)
        elif valor in {e.valor for e in encabezados} or re.search(
            rf"\bACTA\s+(?:N|NO|NUM|NUMERO)\s*0*{valor}\b", plano(texto)
        ):
            confirmados.append("el número del acta")
        else:
            preguntas.append(
                Pregunta("numero", numero, f"el número {numero} no aparece en el encabezado de su acta")
            )

    # La fecha de la sesión: la que va detrás del encabezado que abre la
    # sesión o de «FECHA:», o la que lee de ella el lector de actas. Otra
    # fecha de la misma hoja no la confirma: «concertó reunión el martes 18 de
    # diciembre», «de fecha 05 de marzo» o «hasta el 9 de febrero» confirmaban
    # la fila de otro día (las revisiones, 2026-11-09).
    fecha = _fecha_de_la_fila(fila.get("fecha"))
    leida = leer_acta(list(textos))
    if fecha is None:
        sin_dato.append("la fecha de la sesión")
    else:
        escrita = fecha.strftime("%d/%m/%Y")
        if leida.fecha == fecha or fecha in fechas_de_la_apertura(textos, fuertes):
            confirmados.append("la fecha de la sesión")
        elif not legible:
            # Un acta cuyo texto no se deja leer no prueba otra fecha (2026-11-10).
            sin_dato.append(f"la fecha de la sesión: {TEXTO_ILEGIBLE}")
        elif corregida := _corregida_por_la_sesion(fecha, textos):
            # La regla de la sesión del revisor de fechas (2026-11-10): con dos
            # pruebas del papel -- la apertura dice otra, y ésta no está escrita
            # en el acta, ni su mes y su año -- lo entregado está mal: error.
            errores.append(error_de_fecha(corregida, FechasDeLaFila(fecha, fecha), dicho="la fecha de la sesión"))
        else:
            preguntas.append(Pregunta("fecha", escrita, f"la fecha {escrita} no es la de la apertura de su acta"))

    # La sesión: si el encabezado que abre la sesión dice otra.
    # La del encabezado que abre la sesión de este número; si el papel dice
    # las dos -- «ORDINARIO» en la primera hoja y «EXTRAORDINARIO» en el
    # membrete de las siguientes --, lo decide la IA (la revisión, 2026-11-09).
    de_la_fila = _sesion_de(fila.get("acta"))
    if de_la_fila:
        valor_de_la_fila = int(cifras(numero)) if numero and cifras(numero) else None
        propios = [e for e in fuertes if e.valor == valor_de_la_fila]
        # La que dicen los encabezados de esta sesión, no todos los de la hoja.
        del_papel = {s for e in (propios or fuertes) if (s := _sesion_de(e.sesion))}
        if del_papel == {de_la_fila}:
            confirmados.append("la sesión")
        elif len(del_papel) > 1 or (del_papel and _ocr_contra_ia(fila)):
            dice = " y ".join(sorted(del_papel))
            preguntas.append(Pregunta("sesion", de_la_fila, f"el acta dice sesión {dice}; la fila {de_la_fila}"))
        elif del_papel:
            errores.append(f"el acta dice sesión {' / '.join(sorted(del_papel))} y la fila {de_la_fila}")
        elif leida.sesion == de_la_fila:
            # El encabezado no la dice -- «ACTA No. 015» --: la dice el acta
            # en otra parte, como la leyó el lector.
            confirmados.append("la sesión")
        else:
            # Nadie la dice, o el acta dice otra: lo decide la IA. Antes no
            # se revisaba: 13 de 104 sesiones invertidas pasaban sin ver.
            dicho = (
                f"el acta dice sesión {leida.sesion}; la fila {de_la_fila}"
                if leida.sesion
                else f"la sesión {de_la_fila} no la dice su acta"
            )
            preguntas.append(Pregunta("sesion", de_la_fila, dicho))

    # Los folios: los extremos escritos y la cuenta tienen que sumar -- más las
    # páginas de anexo escaneadas delante, que la fila suma a propósito --, y
    # un acta no tiene más folios que páginas: cada folio es una hoja, con una
    # cara o con dos.
    inicial, final = _entero(fila.get("folio_inicial")), _entero(fila.get("folio_final"))
    folios = _entero(fila.get("folios"))
    previas = sum(
        int(b) - int(a) + 1 for a, b in _ANEXO_PREVIO.findall(plano(fila.get("observaciones")))
    )
    paginas = len(textos)
    # La tolerancia es la del lector de folios de las actas: «las lecturas
    # buenas se apartan uno o dos; las malas, decenas» (``MARGEN_DE_FOLIOS``).
    # Dentro de ella es duda -- una hoja foliada sin escanear, un folio
    # deducido de la foliación del libro --; fuera, error.
    tolerancia = max(MARGEN_DE_FOLIOS, round(paginas * MARGEN_RELATIVO))
    folios_bien = True
    if folios is not None and paginas and folios > paginas:
        folios_bien = False
        dicho = f"la fila dice {folios} folios y el acta tiene {paginas} páginas"
        if folios - paginas > tolerancia:
            errores.append(dicho)
        else:
            preguntas.append(Pregunta("folios", str(folios), f"{dicho} (dentro del margen de los folios)"))
    elif folios and paginas > 2 * folios + tolerancia:
        # De menos: un folio son dos caras a lo sumo. Sólo 1 de 227 actas de
        # Odontología pasa de dos páginas por folio: duda, no error.
        folios_bien = False
        preguntas.append(Pregunta("folios", str(folios), f"la fila dice {folios} folios para {paginas} páginas"))
    if inicial is not None and final is not None:
        if final < inicial:
            folios_bien = False
            errores.append(f"el folio final {final} es menor que el inicial {inicial}")
        elif folios is not None and final - inicial + 1 + previas != folios:
            folios_bien = False
            cuenta = final - inicial + 1
            mas = f" más {previas} de anexo" if previas else ""
            errores.append(f"los folios {inicial} a {final} son {cuenta}{mas} y la fila dice {folios}")
    if folios_bien and folios is not None:
        confirmados.append("los folios")

    # Los nombres de persona del resumen: cada uno, en su acta.
    resumen = _leido(fila.get("resumen"))
    if resumen:
        del_texto = plano(texto).split()
        for frase in frases_propias(resumen, de_pila=de_pila, apellidos=apellidos):
            if nombre_en_el_texto(frase, texto, palabras_del_texto=del_texto):
                continue
            preguntas.append(
                Pregunta(f"nombre:{frase}", frase, f"«{frase}», del resumen, no aparece en su acta")
            )
        if not any(p.campo.startswith("nombre:") for p in preguntas):
            confirmados.append("los nombres del resumen")
    return RevisionDeLaFila(tuple(errores), tuple(preguntas), tuple(confirmados), tuple(sin_dato))


def _revisar_una_persona(fila: Mapping[str, object], textos: Sequence[str]) -> RevisionDeLaFila:
    preguntas: list[Pregunta] = []
    confirmados: list[str] = []
    texto = "\n".join(textos)
    for campo, dicho in _CAMPOS_DE_NUMERO:
        numero = cifras(_leido(fila.get(campo)))
        if len(numero) < CIFRAS_MINIMAS:
            continue
        if numero_en_el_texto(numero, texto):
            confirmados.append(dicho)
        else:
            preguntas.append(Pregunta(campo, numero, f"{dicho} {numero} no aparece en su papel"))
    nombre = _leido(fila.get("nombre"))
    if nombre:
        if nombre_en_el_texto(nombre, texto):
            confirmados.append("el nombre")
        else:
            preguntas.append(Pregunta("nombre", nombre, f"el nombre «{nombre}» no aparece en su papel"))
    return RevisionDeLaFila(preguntas=tuple(preguntas), confirmados=tuple(confirmados))


def _revisar_una_fila_del_fuid(fila: Mapping[str, object], textos: Sequence[str]) -> RevisionDeLaFila:
    datos = fila.get("fuid") if isinstance(fila.get("fuid"), Mapping) else fila
    numero = cifras(_leido(datos.get("consecutivo_inicial")))  # type: ignore[union-attr]
    if len(numero) < 2:
        return RevisionDeLaFila(sin_dato=("el número del documento",))
    texto = "\n".join(textos)
    # «RESOLUCION 00031»: el número tras su rótulo, con o sin ceros; suelto,
    # sólo con todas sus cifras y tres o más: «0031» no lo confirma «31 de
    # marzo», ni «05» el «artículo 5» (la revisión, 2026-11-09).
    sin_ceros = numero.lstrip("0") or "0"
    rotulado = re.search(
        rf"\b(?:RESOLUCION|ACUERDO|DECRETO|CIRCULAR|ACTA|N|NO|NUM|NUMERO)\s*0*{sin_ceros}\b", plano(texto)
    )
    if rotulado or (len(numero) >= 3 and numero_en_el_texto(numero, texto)):
        return RevisionDeLaFila(confirmados=("el número del documento",))
    return RevisionDeLaFila(
        preguntas=(Pregunta("consecutivo", numero, f"el número {numero} no aparece en su papel"),)
    )


def _corregida_por_la_sesion(fecha: date, textos: Sequence[str]) -> Correccion | None:
    """La corrección con prueba de la fecha de un acta, por la regla de la sesión; ``None`` si no la hay.

    La misma pieza que el revisor de fechas al procesar, no otra: el margen de
    las actas es uno solo (2026-11-10).
    """
    revision = contrastar_las_fechas(FechasDeLaFila(fecha, fecha), textos, regla=SESION)
    return next((c for c in revision.correcciones if c.campo == "fecha_inicial"), None)


def fechas_de_la_apertura(textos: Sequence[str], fuertes: Sequence) -> set[date]:
    """Las fechas que van detrás de los encabezados que abren sesión, o de «FECHA:» en sus hojas.

    Es donde va la fecha de la sesión. Sin encabezados que la abran, las hojas
    que se miran son las dos primeras.

    La primera hoja entera se lee con su costo acotado (``texto_acotado``): con
    las mismas regex que ``fechas_del_texto``, «y » × 10 000 en ella pasaba de 5 s
    (la revisión adversarial, 2026-11-10). La primera fecha es la misma.
    """
    fechas: set[date] = set()
    hojas = sorted({e.pagina for e in fuertes[:3]}) or [1, 2]
    if not fuertes and textos and (abre := primera_fecha(texto_acotado(textos[0] or ""))) is not None:
        # Sin encabezado que abra la sesión, la primera fecha de la primera
        # hoja: «Cartagena, 17 de diciembre de 2012».
        fechas.add(abre)
    for encabezado in fuertes[:3]:
        texto = textos[encabezado.pagina - 1]
        fechas |= fechas_del_texto(texto[encabezado.fin : encabezado.fin + VENTANA_DE_LA_FECHA])
    for hoja in hojas:
        if 1 <= hoja <= len(textos):
            texto = textos[hoja - 1]
            for rotulo in re.finditer(r"FECHA(?:\s+DE\s+LA\s+SESI[OÓ]N)?\s*:", texto, re.IGNORECASE):
                fechas |= fechas_del_texto(texto[rotulo.end() : rotulo.end() + 60])
    return fechas


def hojas_de_la_apertura(textos: Sequence[str]) -> str:
    """El texto de la hoja del encabezado que abre la sesión y de la siguiente: donde va su fecha."""
    fuertes = [e for e in encabezados_de_acta(list(textos)) if e.fuerte]
    hoja = fuertes[0].pagina if fuertes else 1
    return "\n".join(textos[max(0, hoja - 1) : hoja + 1])


def _difiere_en_un_digito(numero: str, otros: Sequence[str]) -> bool:
    """Si algún otro número es éste con un solo dígito cambiado, con o sin sus ceros."""
    for otro in otros:
        a, b = numero.lstrip("0") or "0", cifras(otro).lstrip("0") or "0"
        if len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1:
            return True
    return False


#: «el OCR leyó 006 y la IA 005; se dejó lo de la IA»: la fila ya sabe que la
#: lectura de casa y la de pago no coinciden.
_OCR_CONTRA_IA = re.compile(r"\bEL OCR LEYO\b.{0,60}\bLA IA\b")


def _ocr_contra_ia(fila: Mapping[str, object]) -> bool:
    return bool(_OCR_CONTRA_IA.search(plano(fila.get("observaciones"))))


def _fecha_de_la_fila(valor: object) -> date | None:
    """«17-12-2012» o «17/12/2012», como va la fecha de un acta en su fila."""
    hallada = re.fullmatch(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*", str(valor or ""))
    if not hallada:
        return None
    try:
        return date(int(hallada.group(3)), int(hallada.group(2)), int(hallada.group(1)))
    except ValueError:
        return None


def _sesion_de(acta: object) -> str | None:
    texto = plano(acta)
    if "EXTRAORDINARI" in texto:
        return "EXTRAORDINARIA"
    if "ORDINARI" in texto:
        return "ORDINARIA"
    return None


# -- qué páginas son de la fila -----------------------------------------------------------


def paginas_de_la_fila(fila: Mapping[str, object], total: int | None = None) -> tuple[int, int] | None:
    """La primera y la última página del original que son de esta fila, contadas desde 1.

    La fila del FUID no guarda su última página: va hasta donde digan sus
    folios, o sólo la primera.
    """
    datos = fila.get("fuid") if isinstance(fila.get("fuid"), Mapping) else {}
    inicial = _entero(fila.get("pagina_inicial")) or _entero(datos.get("pagina_inicial"))  # type: ignore[union-attr]
    if not inicial or inicial < 1:
        return None
    final = _entero(fila.get("pagina_final"))
    if final is None:
        folios = _entero(fila.get("folios")) or _entero(datos.get("folios_siar")) or _entero(datos.get("folios"))  # type: ignore[union-attr]
        final = inicial + max(0, (folios or 1) - 1)
    final = max(final, inicial)
    if total:
        if inicial > total:
            return None
        final = min(final, total)
    return inicial, final


def id_de_la_fila(relativa: str, fila: Mapping[str, object]) -> str:
    """Cómo se nombra la fila en la muestra: su PDF y sus páginas, y lo que la identifica."""
    paginas = paginas_de_la_fila(fila)
    donde = f"págs. {paginas[0]}-{paginas[1]}" if paginas and paginas[0] != paginas[1] else (
        f"pág. {paginas[0]}" if paginas else "sin páginas"
    )
    quien = (
        _leido(fila.get("nombre"))
        or (f"acta {_leido(fila.get('numero'))}" if _leido(fila.get("numero")) else None)
        or _leido((fila.get("fuid") or {}).get("asunto") if isinstance(fila.get("fuid"), Mapping) else None)
    )
    return f"{relativa} · {donde}" + (f" · {quien[:60]}" if quien else "")
