"""El patrón de cada tipo de documento: lo que sólo ese tipo trae.

Los marcadores de `doctype` puntúan todo lo que una página dice, y en un
expediente real eso incluye sus anexos: un acta de consejo trae formatos de
Admisiones -- «ADMISIONES REGISTRO Y CONTROL ACADÉMICO», que es un marcador de
matrícula -- y listados de resoluciones. Sumado todo, un acta de consejo salía
«matrícula». Medido sobre la carpeta de Odontología (103 PDF de las cajas
00C003284 a 00C003290: actas de consejo y actas de grado), el reconocedor sólo
con marcadores erraba en 10.

El **núcleo** de un tipo es lo que ningún otro trae: el encabezado de una
sesión con su fecha, hora y lugar, o «verificación del quórum», en un acta de
consejo; «ceremonia solemne de graduación» en un acta de grado; «registro del
alumno» en una matrícula. Un anexo puede traer las palabras de otro tipo, pero
no su núcleo. De ahí las tres reglas de `reconocer`:

1. Los marcadores deciden, como siempre.
2. **Veto**: si el tipo que ganó no tiene una sola página de núcleo y otro sí
   en varias, lo que ganó vino de los anexos, y gana el del núcleo.
3. Si los marcadores no deciden, decide el núcleo claramente mayoritario; y si
   ni eso, el **nombre** del archivo o de su carpeta, como último recurso y
   dicho así, para que se revise.

Medido así: 103 de 103 en Odontología (101 sin mirar el nombre), y en las
cajas de diplomas, resoluciones, matrículas y correspondencia el mismo
resultado que sólo con marcadores. Todo sobre texto, sin leer imágenes.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from .acta_consejo import encabezados_de_acta
from .doctype import DocumentType, TypeVerdict

#: Lo que sólo ese tipo trae, sobre el texto sin tildes y en mayúsculas.
NUCLEOS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.ACTA_CONSEJO: (
        r"VERIFICACION DEL QUORUM",
        r"LLAMADO A LISTA",
        r"ACTA (?:EXTRA)?ORDINARIA",
        r"SESION (?:EXTRA)?ORDINARIA",
        r"APROBACION (?:DEL )?ACTA ANTERIOR",
        r"PROPOSICIONES (?:Y|O) VARIOS",
        r"CONSEJO DE FACULTAD (?:EXTRA)?ORDINARIO",
        r"ORDEN DEL DIA",
    ),
    DocumentType.ACTA: (
        r"ACTAS? DE GRADO",
        r"CEREMONIA SOLEMNE DE GRADUACION",
        r"OTORGA EL TITULO DE",
        r"JURAMENTO DE RIGOR",
        r"SE LLEVO A CABO (?:LA )?CEREMONIA",
        r"PORTADORA? DE LA CEDULA",
        r"ACTA DE GRADUACION",
        r"GRADUANDOS?",
    ),
    DocumentType.MATRICULA: (
        r"REGISTRO DEL ALUMNO",
        r"NOMBRE DEL ALUMNO",
        r"MATRICULA ACADEMICA",
        r"REGISTRO DE ESTUDIOS",
        r"HISTORIAS? ACADEMICAS?",
    ),
    DocumentType.DIPLOMA: (
        r"REGISTRO DE DIPLOMAS?",
        r"REGISTRADO AL FOLIO",
        r"LE EXPIDE EL PRESENTE DIPLOMA",
        r"PARA CONSTANCIA ES FIRMADO EL PRESENTE REGISTRO",
    ),
    DocumentType.RESOLUCION: (
        r"POR MEDIO DE LA CUAL SE",
        # Las resoluciones internas de facultad (caja 00C003303): «Por la cual
        # se…», «RESUELVE:» y «Comuníquese, publíquese y cúmplase». Las de 2022
        # piden ceremonias de grado con su lista de graduandos, y sin esto el
        # núcleo de actas de grado vetaba a las resoluciones.
        r"\bPOR LA CUAL SE\b",
        r"\bRESUELVE\s*:",
        r"COMUNIQUESE,? (?:PUBLIQUESE,? )?Y CUMPLASE",
    ),
}
_NUCLEOS = {
    tipo: tuple(re.compile(patron) for patron in patrones) for tipo, patrones in NUCLEOS.items()
}

#: Lo que dice el nombre del archivo o de su carpeta, en el orden en que se
#: pregunta: «ACTAS DE GRADO» antes que «ACTA», que también la nombra.
NOMBRES: tuple[tuple[DocumentType, str], ...] = (
    # «GRADUADOS POSTGRADO Y PREGRADO … ACTAS» sí; «ALUMNOS NO GRADUADOS» no: es
    # una lista de quienes justamente no tienen acta de grado. Y los libros
    # manuscritos de 1924-1946, «EXAMENES PREPARATORIOS DE GRADO 1924-46»: su
    # capa de texto es basura, nadie los reconocía, e iban por resoluciones
    # (el libro entero en un «RESOLUCION_023», caja 00C003362, 2026-11-04).
    # Y los tomos de Odontología «ACTAS DECADA. 1980-1984 TOMO I» (cajas
    # 3194-3198, 2026-11-27): la carpeta los llama actas de grado sin decirlo.
    (
        DocumentType.ACTA,
        r"ACTAS? DE GRADO|(?<!NO )GRADUADOS|ACTAS? DE (?:PRE|POS)T?GRADO"
        r"|EXAMEN(?:ES)? (?:PREPARATORIOS? |FINAL(?:ES)? )?DE GRADO|\bACTAS? DECADA\b",
    ),
    (DocumentType.ACTA_CONSEJO, r"SESION|CONSEJO DE FACULTAD|ACTAS? DE CONSEJO"),
    (DocumentType.DIPLOMA, r"DIPLOMA"),
    (DocumentType.RESOLUCION, r"RESOLUCION"),
    (DocumentType.MATRICULA, r"MATRICULA|HISTORIA ACADEMICA"),
)
_NOMBRES = tuple((tipo, re.compile(patron)) for tipo, patron in NOMBRES)

#: Cuántas páginas de núcleo de otro tipo hacen falta para vetar al ganador.
PAGINAS_PARA_VETAR = 2
#: Cuántas veces más páginas de núcleo que el segundo para decidir sin marcadores.
VENTAJA_DEL_NUCLEO = 2

#: Cuántas páginas de la capa de texto se miran para el núcleo. Leer texto ya
#: extraído no cuesta nada, y veinticuatro bastan: con ellas se acertaron los
#: 103 PDF de Odontología.
PAGINAS_DEL_NUCLEO = 24


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper())


def tipos_de_la_pagina(texto: str) -> set[DocumentType]:
    """Los tipos cuyo núcleo aparece en esta página."""
    plano = _plano(texto)
    tipos = {
        tipo for tipo, patrones in _NUCLEOS.items() if any(p.search(plano) for p in patrones)
    }
    # El encabezado que abre una sesión de consejo -- «ACTA No. 21» con su
    # fecha, hora y lugar -- es su núcleo aunque no diga «ordinaria». No cuenta
    # en una página de acta de grado, que también lleva «ACTA No.».
    if DocumentType.ACTA not in tipos and any(
        encabezado.fuerte and encabezado.organo in (None, "consejo de facultad")
        for encabezado in encabezados_de_acta([texto])
    ):
        tipos.add(DocumentType.ACTA_CONSEJO)
    return tipos


def paginas_con_nucleo(paginas: Sequence[str]) -> Counter[DocumentType]:
    """En cuántas páginas aparece el núcleo de cada tipo."""
    cuenta: Counter[DocumentType] = Counter()
    for texto in paginas:
        cuenta.update(tipos_de_la_pagina(texto))
    return cuenta


def pista_del_nombre(nombre: str) -> DocumentType | None:
    """Qué tipo dice el nombre del archivo o de sus carpetas, si dice alguno."""
    plano = _plano(nombre)
    return next((tipo for tipo, patron in _NOMBRES if patron.search(plano)), None)


@dataclass(frozen=True, slots=True)
class Reconocimiento:
    """Qué tipo es el documento según su patrón, y por qué."""

    tipo: DocumentType
    #: «marcadores», «veto», «nucleo» o «nombre»; vacío si no se decidió.
    por: str
    motivo: str
    nucleo: dict[str, int] = field(default_factory=dict)

    @property
    def decidido(self) -> bool:
        return self.tipo is not DocumentType.DESCONOCIDO


def reconocer(
    veredicto: TypeVerdict, nucleo: Counter[DocumentType], nombre: str = ""
) -> Reconocimiento:
    """El tipo del documento: los marcadores, corregidos por el núcleo y el nombre."""
    cuenta = {tipo.value: veces for tipo, veces in nucleo.items()}

    if veredicto.is_identified:
        ganador = veredicto.document_type
        # El nombre que dice lo mismo que los marcadores no se veta: «RESOLUCIONES
        # INTERNAS 2022» es un legajo de resoluciones aunque pidan grados.
        if nucleo[ganador] == 0 and pista_del_nombre(nombre) is not ganador:
            rivales = [
                (veces, tipo)
                for tipo, veces in nucleo.items()
                if tipo is not ganador and veces >= PAGINAS_PARA_VETAR
            ]
            if rivales:
                veces, tipo = max(rivales)
                return Reconocimiento(
                    tipo=tipo,
                    por="veto",
                    motivo=(
                        f"los marcadores decían {ganador.label} sin una sola página de su "
                        f"núcleo, y {veces} páginas tienen el de {tipo.label}: lo otro "
                        "venía de los anexos"
                    ),
                    nucleo=cuenta,
                )
        return Reconocimiento(
            tipo=ganador, por="marcadores", motivo="lo decidieron los marcadores", nucleo=cuenta
        )

    if nucleo:
        (primero, veces), *resto = nucleo.most_common()
        segundo = resto[0][1] if resto else 0
        # Una sola página no decide: puede ser un anexo, o una cita.
        if veces >= PAGINAS_PARA_VETAR and (segundo == 0 or veces >= VENTAJA_DEL_NUCLEO * segundo):
            return Reconocimiento(
                tipo=primero,
                por="nucleo",
                motivo=f"{veces} páginas tienen el núcleo de {primero.label}",
                nucleo=cuenta,
            )
        pista = pista_del_nombre(nombre)
        if pista in nucleo:
            return Reconocimiento(
                tipo=pista,
                por="nucleo",
                motivo=(
                    f"el núcleo de {pista.label} y el de otro tipo empatan; desempata el "
                    "nombre del archivo"
                ),
                nucleo=cuenta,
            )

    pista = pista_del_nombre(nombre)
    if pista is not None:
        return Reconocimiento(
            tipo=pista,
            por="nombre",
            motivo=(
                f"el contenido no dice qué es; el nombre «{nombre}» dice {pista.label}. "
                "Conviene revisarlo"
            ),
            nucleo=cuenta,
        )
    return Reconocimiento(
        tipo=DocumentType.DESCONOCIDO, por="", motivo="ningún patrón lo reconoce", nucleo=cuenta
    )


# -- un PDF entero ---------------------------------------------------------------
#
# El operador, 2026-11-27, sobre «8. ACTA 9 FACULTAD DE ODONTOLOGIA CALIFICACIONES
# 3194 - 3198» (libros de calificaciones, de actas de grado y de resoluciones en
# la misma carpeta): «que el bot sepa con mucha, pero mucha precisión qué
# habilidad tomar automáticamente en el medio del proceso». La muestra de
# veinticuatro hojas basta para reconocer; para **contradecir** al operador se
# mira el PDF entero, gratis, sobre su capa de texto: una hoja suelta de otro
# tipo -- un anexo, una cita -- no cambia lo que es el libro.

#: Lo del núcleo de las actas de grado que también escriben otros papeles: la
#: resolución que autoriza una ceremonia nombra a sus «graduandos» y manda
#: expedir sus «actas de grado». En «RESOLUCIONES DECANATURA 2003-2010 TOMO 2»
#: son 18 hojas de 115, y ninguna abre un acta (2026-11-27). Para medir cuánto
#: de un PDF es de actas de grado, esas dos sólo cuentan en la hoja que abre un
#: acta (``acta_grado.apertura``).
_CITAS_DEL_GRADO = frozenset({r"ACTAS? DE GRADO", r"GRADUANDOS?"})
_GRADO_FUERTE = tuple(
    re.compile(patron) for patron in NUCLEOS[DocumentType.ACTA] if patron not in _CITAS_DEL_GRADO
)

#: Cuántas veces más hojas que lo declarado necesita otro tipo para contradecirlo.
#: Una pieza de otro tipo dentro de un libro -- el acta de soporte de una
#: resolución, la constancia suelta de un libro de actas -- no llega: en
#: «RESOLUCIONES DE RECTORIA 03272-03275» (2026-10-29) son 48 hojas de actas de
#: consejo contra 50 de resoluciones, sobre el PDF entero (2026-11-27).
VECES_PARA_CONTRADECIR = 3

#: Con cuántos caracteres una hoja trae capa de texto (el mismo umbral con que
#: el orquestador decide pasarla por Tesseract, ``MIN_SAMPLE_CHARS``).
CARACTERES_DE_CAPA = 80
#: Qué parte de las hojas tiene que traer capa para que su silencio sea del
#: papel -- un manuscrito que el escáner leyó como basura -- y no de un escaneo
#: sin capa, que sí se lee con Tesseract.
PARTE_CON_CAPA = 0.5


def hojas_de_cada_tipo(paginas: Sequence[str]) -> Counter[DocumentType]:
    """En cuántas hojas de un PDF entero hay evidencia fuerte de cada tipo.

    Es el núcleo de cada hoja (``tipos_de_la_pagina``), salvo en las actas de
    grado: la hoja cuenta como suya si abre un acta o trae lo que sólo un acta
    dice -- la ceremonia, el juramento, «otorga el título de» --, no si sólo
    cita las actas o a los graduandos.
    """
    from .acta_grado import apertura

    cuenta: Counter[DocumentType] = Counter()
    for numero, texto in enumerate(paginas, start=1):
        texto = texto or ""
        tipos = tipos_de_la_pagina(texto)
        if DocumentType.ACTA in tipos:
            plano = _plano(texto)
            if not (any(patron.search(plano) for patron in _GRADO_FUERTE) or apertura(texto, numero)):
                tipos.discard(DocumentType.ACTA)
        cuenta.update(tipos)
    return cuenta


def lo_que_lo_arrolla(hojas: Counter[DocumentType], declarado: DocumentType | None) -> DocumentType | None:
    """El tipo que arrolla a lo declarado en un PDF entero, o ``None`` si ninguno.

    Lo declarado manda salvo que otro tipo tenga el triple de sus hojas y dos
    por lo menos. Sin una sola hoja de lo declarado bastan las dos: un tomo de
    resoluciones declarado como actas de grado no trae ninguna hoja que abra un
    acta (las que citan a los graduandos no cuentan, ``hojas_de_cada_tipo``).
    """
    propio = hojas[declarado] if declarado is not None else 0
    rivales = [
        (veces, str(tipo), tipo)
        for tipo, veces in hojas.items()
        if tipo is not declarado
        and veces >= PAGINAS_PARA_VETAR
        and veces >= VECES_PARA_CONTRADECIR * propio
    ]
    return max(rivales)[2] if rivales else None


def capa_que_no_dice_nada(paginas: Sequence[str], hojas: Counter[DocumentType]) -> bool:
    """Si el PDF trae capa de texto y en ella ningún tipo tiene evidencia: la basura de un manuscrito.

    Los libros de actas de grado manuscritos de Odontología (1952-1959 y
    1960-1965, 2026-11-27) y los exámenes de la caja 3362 tienen capa en casi
    todas las hojas, y ninguna dice nada: el escáner leyó la cursiva como
    «cmmjG mmcTWO tt tá ubh». Un escaneo sin capa no es esto: ése se lee con
    Tesseract.
    """
    if not paginas:
        return False
    con_capa = sum(1 for texto in paginas if len((texto or "").strip()) >= CARACTERES_DE_CAPA)
    return con_capa >= PARTE_CON_CAPA * len(paginas) and max(hojas.values(), default=0) < PAGINAS_PARA_VETAR
