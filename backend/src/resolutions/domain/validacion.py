"""Qué puede comprobar cada habilidad sobre una muestra de páginas.

`doctype` reconoce un documento por su vocabulario: frases impresas que, si
aparecen, inclinan la balanza hacia un tipo. Casi siempre basta. Cuando no basta
-- un escaneo cuya banda superior no dice nada, un papel que trae el vocabulario
de dos tipos a la vez, un libro donde sólo una de doce páginas lleva la leyenda
--, el despachador se quedaba sin respuesta y el documento acababa partido por
continuidad aunque sus hojas dijeran con todas sus letras qué eran.

Este módulo es la segunda pregunta, la que se hace cuando la primera no decidió.
No busca palabras sino lo que cada habilidad sabe **leer**:

* una resolución, un encabezado oficial que abre su renglón;
* un diploma, la cédula o el folio de registro junto al título o la fecha de
  grado;
* una matrícula, la carátula con el código y el nombre del estudiante, o la hoja
  de registro de estudios con sus años académicos;
* un acta de consejo, su número de acta con la sesión o la fecha.

Son los mismos lectores que después parten el documento, de modo que la
habilidad que valida aquí es una que va a encontrar algo que cortar.

Las actas de grado (`DocumentType.ACTA`) no están: su lectura es un borrador que
todavía no corta bien, y elegirla por su cuenta sería mandar un documento a la
única ruta que se sabe rota. Si los marcadores la reconocen, eso sigue siendo
decisión de `doctype`; lo que no hace este módulo es proponerla.

Tres reglas, y las tres vienen del operador:

* sólo cuenta la evidencia positiva. Que un lector no encuentre nada en una
  página no dice que la página sea de otro tipo: la ausencia de un dato nunca
  es evidencia en contra;
* ninguna habilidad gana por descarte. Si las demás fallan y ésta tampoco
  encontró nada, no gana nadie;
* un dato suelto no decide. Tiene que repetirse en la muestra y la ganadora
  tiene que sacarle ventaja clara a la segunda.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .acta_consejo import encabezados_de_acta, leer_acta
from .diploma import extract_diploma, lines_from_text
from .doctype import DocumentType
from .extraction import extract_candidates
from .matricula import extract_student_page
from .scoring import opens_a_resolution

#: Qué parte de la muestra tiene que traer evidencia para que una habilidad
#: pueda ganar. Es una fracción de las páginas muestreadas, no un conteo, para
#: que un documento de tres hojas y uno de cuatrocientas se midan igual.
#:
#: Quince centésimas son dos páginas de doce y una de seis o menos. Lo que se
#: quiere dejar fuera es exactamente el caso que obligó a desviar las cajas
#: revueltas a continuidad: la caja de correspondencia de 125 páginas en la que
#: un número suelto a media caja se llevó por delante todo lo que venía detrás.
#: Una página de doce no es un legajo; en un documento de cinco hojas, una sí es
#: una parte grande de lo que hay.
PUNTAJE_MINIMO = 0.15

#: Cuánto tiene que sacarle la ganadora a la segunda. El mismo espíritu que
#: `doctype.MIN_MARGIN`: un papel que valida para dos habilidades a la vez no se
#: zanja por un pelo, se declara sin decidir y sigue el camino conservador.
MARGEN = 1.6

#: Cuánto de un renglón se copia en la evidencia. Basta para reconocerlo en el
#: papel sin convertir el informe en una transcripción.
_LARGO_DE_LA_CITA = 70


@dataclass(frozen=True, slots=True)
class Validacion:
    """Lo que una habilidad comprobó sobre la muestra, página por página.

    ``puntaje`` es la fracción de las páginas muestreadas en que encontró
    evidencia positiva. No es una probabilidad ni un número elegido para
    tranquilizar a nadie: es cuántas hojas de las que se miraron dijeron, con un
    dato leído, que son de este tipo. ``evidencia`` lo dice en palabras, una
    frase por página, para que la decisión se pueda auditar y no sólo creer.
    """

    tipo: DocumentType
    paginas: tuple[int, ...] = ()
    evidencia: tuple[str, ...] = ()
    puntaje: float = 0.0
    muestreadas: int = 0

    @property
    def valida(self) -> bool:
        """Si encontró algo. Encontrar algo no basta para ganar; ver `ganadora`."""
        return bool(self.paginas)

    def as_dict(self) -> dict[str, object]:
        return {
            "tipo": str(self.tipo),
            "etiqueta": self.tipo.label,
            "valida": self.valida,
            "puntaje": round(self.puntaje, 4),
            "paginas": list(self.paginas),
            "muestreadas": self.muestreadas,
            "evidencia": list(self.evidencia),
        }


#: Lo que un lector dice de una página: una frase con lo que comprobó, o
#: ``None`` si no comprobó nada. Nunca una frase con lo que *no* encontró.
LectorDePagina = Callable[[str, int], str | None]


def _validar(
    tipo: DocumentType, muestra: Sequence[tuple[int, str]], leer: LectorDePagina
) -> Validacion:
    paginas: list[int] = []
    evidencia: list[str] = []
    for numero, texto in muestra:
        if not texto or not texto.strip():
            continue
        hallazgo = leer(texto, numero)
        if hallazgo:
            paginas.append(numero)
            evidencia.append(f"p{numero}: {hallazgo}")
    muestreadas = len(muestra)
    return Validacion(
        tipo=tipo,
        paginas=tuple(paginas),
        evidencia=tuple(evidencia),
        puntaje=len(paginas) / muestreadas if muestreadas else 0.0,
        muestreadas=muestreadas,
    )


def _cita(renglon: str) -> str:
    plano = " ".join(renglon.split())
    if len(plano) <= _LARGO_DE_LA_CITA:
        return plano
    return plano[: _LARGO_DE_LA_CITA - 1].rstrip() + "…"


# -----------------------------------------------------------------------------
#  Lo que cada habilidad sabe leer de una página
# -----------------------------------------------------------------------------


def _resolucion_en(texto: str, numero: int) -> str | None:
    """Un encabezado que podría abrir una resolución, con las mismas exigencias
    que el agrupador: forma oficial, ancla al principio del renglón, nada más
    que la fecha detrás, y sin un verbo de cita delante."""
    for candidata in extract_candidates(texto):
        if opens_a_resolution(candidata):
            return f"{_cita(candidata.line_text)} abre el renglón"
    return None


def _diploma_en(texto: str, numero: int) -> str | None:
    """Quién es el graduado y qué recibió, las dos cosas en la misma página.

    Una sola no basta. Una cédula rotulada aparece en cualquier oficio que
    identifique a alguien, y un "DOCTOR EN" en cualquier resolución que hable de
    un título; las dos juntas, con la identidad en la forma en que la escriben
    los libros de registro, son una ficha de diploma.

    La identidad es la cédula que se sostiene -- la misma condición con que se
    nombra el archivo -- o el folio de registro ("Registrado a folio No."), que
    es una fórmula de estos libros. El folio suelto no cuenta: "folio 3" lo
    escribe cualquiera que cite un expediente.
    """
    registro = extract_diploma(lines_from_text(texto), numero)
    if registro.identity_creible:
        identidad = f"cédula {registro.identity_number}"
    elif registro.registered_folio:
        identidad = f"registrado a folio {registro.registered_folio}"
    else:
        return None
    if registro.degree:
        dato = f"título {_cita(registro.degree)}"
    elif registro.graduation_date:
        dato = f"graduación {registro.graduation_date}"
    else:
        return None
    return f"{identidad} y {dato}"


def _matricula_en(texto: str, numero: int) -> str | None:
    """La carátula de un expediente, o una hoja de su registro de estudios.

    La carátula se comprueba con el código **y** el nombre: el nombre sólo sale
    si la fila de leyendas impresas del formulario está en la página, y el
    código suelto podría ser cualquier número con guion. La hoja de asignaturas
    se comprueba con dos años académicos por lo menos -- "PRIMER AÑO 1.950",
    "SEGUNDO AÑO 1.951" --: uno solo puede salir del período de una carátula, y
    eso no dice que la hoja sea de estudios.
    """
    hoja = extract_student_page(lines_from_text(texto), numero)
    if hoja.codigo and hoja.nombre:
        return f"carátula del estudiante {hoja.codigo} ({_cita(hoja.nombre)})"
    if len(hoja.anios) >= 2:
        return f"registro de estudios de {hoja.anios[0]} a {hoja.anios[-1]}"
    return None


def _acta_consejo_en(texto: str, numero: int) -> str | None:
    """El encabezado de un acta, con su número y algo que lo sitúe.

    El número solo no basta: "Acta No. 5" al principio de un renglón puede ser
    la continuación de una frase partida. Con la clase de sesión o la fecha de
    la sesión detrás, es el encabezado de un acta.
    """
    acta = leer_acta([texto])
    if acta.numero is not None and (acta.sesion or acta.fecha):
        return " del ".join(parte for parte in (acta.encabezado, acta.fecha_larga) if parte)
    return _membrete_corrido_de_acta(texto)


#: Entre cuántos renglones de lo alto de la hoja va el membrete corrido de un acta.
RENGLONES_DEL_MEMBRETE = 6

#: Los órganos cuyas actas son de un consejo: lo que no sea un comité o una reunión.
_CONSEJOS = {"consejo de facultad", "consejo academico", "consejo superior"}


def _membrete_corrido_de_acta(texto: str) -> str | None:
    """El membrete de las hojas de cuerpo de un acta: «Consejo de Facultad / Acta No. 08».

    En un libro de noventa páginas la muestra toma una de cada siete, y lo
    normal es que no caiga en ninguna primera hoja de acta: sólo en hojas de
    cuerpo, que llevan el membrete corrido arriba del todo. Eso también es un
    acta, y se cree si va **en lo alto de la hoja** y con el consejo nombrado al
    lado; una cita -- «según consta en el / Acta No. 021» -- va en mitad del
    texto y no cuenta.
    """
    for encabezado in encabezados_de_acta([texto]):
        renglon = sum(1 for linea in texto[: encabezado.fin].splitlines() if linea.strip())
        # El membrete es sólo la referencia -- «Acta No. 022-2012» --; un
        # renglón que sigue con palabras es una frase que cita un acta.
        fin_de_renglon = texto.find("\n", encabezado.fin)
        resto = texto[encabezado.fin : fin_de_renglon if fin_de_renglon >= 0 else None]
        if (
            renglon <= RENGLONES_DEL_MEMBRETE
            and encabezado.organo in _CONSEJOS
            and not _PALABRA.search(resto)
        ):
            return f"membrete corrido «Acta No. {encabezado.numero}» del {encabezado.organo}"
    return None


_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{3}")


# -----------------------------------------------------------------------------
#  Las cuatro validaciones, y quién gana
# -----------------------------------------------------------------------------


def validar_resoluciones(muestra: Sequence[tuple[int, str]]) -> Validacion:
    return _validar(DocumentType.RESOLUCION, muestra, _resolucion_en)


def validar_diplomas(muestra: Sequence[tuple[int, str]]) -> Validacion:
    return _validar(DocumentType.DIPLOMA, muestra, _diploma_en)


def validar_matriculas(muestra: Sequence[tuple[int, str]]) -> Validacion:
    return _validar(DocumentType.MATRICULA, muestra, _matricula_en)


def validar_acta_consejo(muestra: Sequence[tuple[int, str]]) -> Validacion:
    return _validar(DocumentType.ACTA_CONSEJO, muestra, _acta_consejo_en)


#: Las habilidades a las que se consulta cuando los marcadores no deciden. Todas,
#: siempre, y en este orden sólo para que el informe salga igual cada vez: el
#: orden no desempata nada.
VALIDADORES: dict[DocumentType, Callable[[Sequence[tuple[int, str]]], Validacion]] = {
    DocumentType.RESOLUCION: validar_resoluciones,
    DocumentType.DIPLOMA: validar_diplomas,
    DocumentType.MATRICULA: validar_matriculas,
    DocumentType.ACTA_CONSEJO: validar_acta_consejo,
}


def validar_todas(muestra: Sequence[tuple[int, str]]) -> dict[DocumentType, Validacion]:
    """Lo que cada habilidad comprobó sobre la misma muestra."""
    return {tipo: validar(muestra) for tipo, validar in VALIDADORES.items()}


def ganadora(
    validaciones: Mapping[DocumentType, Validacion],
) -> tuple[DocumentType | None, str]:
    """La habilidad que se comprobó, si hay una sola que se comprobó con claridad.

    Devuelve el tipo y el motivo en una frase, o ``None`` y por qué no ganó
    nadie. Gana la que encontró evidencia positiva en suficientes páginas
    (`PUNTAJE_MINIMO`) y le saca `MARGEN` a la siguiente que también encontró
    algo. Una habilidad sin evidencia no gana nunca, aunque sea la única que
    queda en pie.
    """
    con_evidencia = sorted(
        (validacion for validacion in validaciones.values() if validacion.valida),
        key=lambda validacion: validacion.puntaje,
        reverse=True,
    )
    if not con_evidencia:
        muestreadas = max(
            (validacion.muestreadas for validacion in validaciones.values()), default=0
        )
        return None, (
            f"ninguna habilidad encontró evidencia positiva en las {muestreadas} "
            "páginas muestreadas"
        )

    primera = con_evidencia[0]
    if primera.puntaje < PUNTAJE_MINIMO:
        return None, (
            f"{primera.tipo.label} sólo se comprobó en {len(primera.paginas)} de "
            f"{primera.muestreadas} páginas; un dato suelto no decide"
        )

    if len(con_evidencia) > 1:
        segunda = con_evidencia[1]
        if primera.puntaje < segunda.puntaje * MARGEN:
            return None, (
                f"{primera.tipo.label} ({len(primera.paginas)} págs.) y "
                f"{segunda.tipo.label} ({len(segunda.paginas)} págs.) se comprobaron "
                "las dos, sin ventaja clara de ninguna"
            )

    return primera.tipo, (
        f"{primera.tipo.label}: se comprobó en {len(primera.paginas)} de "
        f"{primera.muestreadas} páginas ({primera.evidencia[0]})"
    )
