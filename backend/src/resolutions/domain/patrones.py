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
        r"COMUNIQUESE Y CUMPLASE",
    ),
}
_NUCLEOS = {
    tipo: tuple(re.compile(patron) for patron in patrones) for tipo, patrones in NUCLEOS.items()
}

#: Lo que dice el nombre del archivo o de su carpeta, en el orden en que se
#: pregunta: «ACTAS DE GRADO» antes que «ACTA», que también la nombra.
NOMBRES: tuple[tuple[DocumentType, str], ...] = (
    # «GRADUADOS POSTGRADO Y PREGRADO … ACTAS» sí; «ALUMNOS NO GRADUADOS» no: es
    # una lista de quienes justamente no tienen acta de grado.
    (DocumentType.ACTA, r"ACTAS? DE GRADO|(?<!NO )GRADUADOS|ACTAS? DE (?:PRE|POS)T?GRADO"),
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
        if nucleo[ganador] == 0:
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
