"""Lo que un acta de consejo dice de sí misma: su número, su sesión y su fecha.

Un acta de consejo -- de facultad, académico, superior -- llega ya como un PDF
por acta: portada, citación, planilla de asistencia, el acta y sus anexos. No
hay nada que cortar. Del inventario el operador pidió tres cosas, y las dictó
con un ejemplo: «ACTA ORDINARIA No. 022», «Lunes 17 de diciembre de 2012» y un
resumen de lo que se trató.

Las dos primeras están impresas en el encabezado del acta, que no es la primera
página: la del Consejo de Facultad de Odontología del 17 de diciembre de 2012 lo
trae en la quinta, detrás de la portada, la citación y la asistencia. Así que se
busca en todas.

Y no vale cualquier mención. Un acta cita otras actas -- «según consta en el Acta
No. 021» -- y ese número no es el suyo. Lo que distingue el encabezado de la cita
es que el encabezado **abre el renglón**; la cita va en mitad de una frase. Un
número que no se lee en un encabezado se queda en N/A: una celda con el número
de otra acta es una mentira que nadie va a poder rastrear hasta el papel.

Este módulo no sabe de OCR ni de proveedores: recibe el texto de cada página y
devuelve lo que se leyó en él.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .fechas import MESES

#: Lo que el operador pidió que el resumen no mencione nunca. Es el primer punto
#: del orden del día de todas las actas, una formalidad que no dice nada de lo
#: que se trató.
FRASE_PROHIBIDA = "LLAMADO A LISTA Y VERIFICACIÓN DEL QUORUM"

#: Los días de la semana, en el orden de `date.weekday()`.
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

_NOMBRE_DEL_MES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}

#: El año más antiguo que se le cree a la fecha de una sesión. No es el de
#: `fechas.ANIO_MINIMO`, que está pensado para correspondencia viva: un archivo
#: universitario guarda actas de hace décadas.
ANIO_MINIMO = 1900

#: Cuánto texto detrás del encabezado se mira buscando la fecha de la sesión.
#: En el acta de Odontología va en el renglón siguiente; trescientos caracteres
#: dan para un renglón con el nombre del consejo en medio.
VENTANA_DE_LA_FECHA = 300

#: Lo que se le quita a cada letra para comparar sin tildes. Es una sustitución
#: de uno por uno a propósito: las posiciones del texto normalizado son las
#: mismas que las del original, y así lo que se encuentra en uno se puede
#: recortar del otro.
_SIN_TILDES = str.maketrans("áéíóúüÁÉÍÓÚÜñÑ", "aeiouuAEIOUUnN")


def _plano(texto: str) -> str:
    return texto.translate(_SIN_TILDES)


_MES = "|".join(sorted(MESES, key=len, reverse=True))
_DIA = "lunes|martes|miercoles|jueves|viernes|sabado|domingo"

#: El encabezado del acta, al principio del renglón. Admite lo que se ha visto
#: en los libros de la caja 00C003284, de 2000 a 2012, y en su OCR:
#:
#: * «ACTA ORDINARIA No. 022», «Acta No. 022-2012» (2011-2012);
#: * «ACTA CONSEJO DE FACULTAD ORDINARIO No. 002», «ACTA CONSEJO DE FACULTAD
#:   ORDINARIO 013», sin «No.», y con el OCR de «EACULTAD» o «EXTRORDINARIO»
#:   (2007-2009);
#: * «ACTA CONSEJO DE FACULTAD ORDINARIO» con «No. 007» en el renglón siguiente
#:   (2005);
#: * «ACTA No. 17», «ACTA 024» (2002-2004);
#: * el número con letras donde el OCR vio cifras: «No.Oll» es el 011.
#:
#: Delante sólo se toleran unos pocos signos, que es lo que el OCR deja de los
#: bordes. Lo que no abre el renglón no es un encabezado: es una cita.
_ENCABEZADO = re.compile(
    # «ACTAN° 002»: el OCR pega la N a ACTA.
    r"^[^\w\n]{0,6}ACTA(?:\s+|(?=N[°º”“»\"']))"
    r"(?:DEL?\s+)?"
    r"(?:(?:LA\s+)?(?:SESION|REUNION)\s+)?"
    r"(?:CONSEJO\s+DE\s+[A-Z]{5,10}\s+)?"
    r"(?:(?P<sesion>ORDINARI[AO]|EXTRA?ORDINARI[AO])\s*[-–.]?\s*)?"
    # El «°» del número lo lee el OCR como comillas: «ACTA N” 019», «N» 023»;
    # y como asterisco o como «®»: «ACTA N* 22», «N** 01», «N® 09» (Odontología,
    # cuatro actas que no existían en el inventario, 2026-10-30).
    r"(?P<rotulo>N(?:RO|UM|O|º|°|[”“»\"'*®]{1,2})?\s*[.:°º,”“»\"'*®]?|NUMERO|#)?\s*"
    # Las letras que el OCR confunde con cifras: O/I/l, y en mayúscula S, B, G
    # y Z («ACTA No. OS» era el 08). Un número con letras se confirma después
    # con el membrete corrido de la hoja siguiente.
    r"(?P<numero>(?:[0-9OIl]|(?-i:[SBGZ])){1,3})(?!\w)",
    re.IGNORECASE | re.MULTILINE,
)

#: «ACTA No. 15 BIS»: la sesión que se celebró con el número de la anterior.
#: Odontología, UPD3859789 p. 168: la 15 BIS del 30 de octubre de 2015 se
#: fundía con la 015 del 13 de octubre.
_BIS = re.compile(r"[ \t]*[-–]?[ \t]*BIS\b", re.IGNORECASE)

#: El año pegado detrás del número: «Acta No. 022-2012», el membrete corrido.
_CORRIDO = re.compile(r"\s*[-–]\s*(?:19|20)\d\d\b")

#: Lo que el OCR pone en lugar de una cifra dentro del número del acta.
_CIFRAS_DEL_OCR = str.maketrans("OoIlSBGZ", "00115862")
#: Las letras que no son una lectura segura de una cifra: el número que las
#: lleva se coteja con el membrete corrido de las hojas que siguen.
_LETRAS_DUDOSAS = set("SBGZ")
#: Cuántas hojas detrás del encabezado se busca el membrete que lo confirma.
HOJAS_PARA_CONFIRMAR = 2

#: Los rótulos de la tabla con que abre un acta: «FECHA: / HORA: / LUGAR: /
#: ASISTENTES: / ORDEN DEL DÍA». Dos en la misma hoja dicen que ahí empieza una
#: sesión, y no que se cita una.
_ROTULOS_DE_APERTURA = (
    "FECHA", "HORA", "LUGAR", "ASISTENTES", "ORDEN DEL DIA", "MIEMBROS", "INVITADOS",
)

#: Qué órgano sesiona, dicho cerca del encabezado. Un libro del Consejo de
#: Facultad trae anexadas actas de comités, de reuniones de departamento o del
#: Consejo Académico, y ésas no son actas del libro: son anexos de una.
_ORGANOS = (
    ("COMITE", "comite"),
    ("CONSEJO ACADEMICO", "consejo academico"),
    ("CONSEJO SUPERIOR", "consejo superior"),
    ("REUNION DE DEPARTAMENTO", "reunion"),
    ("REUNION DEL DEPARTAMENTO", "reunion"),
    ("REUNION DEPARTAMENTO", "reunion"),
    # Las mesas de trabajo de la acreditación levantan sus propias actas, y el
    # consejo las recibe como anexo: «PROCESO DE REACREDITACIÓN / ACTA No 01».
    ("REACREDITACION", "comite"),
    ("AUTOEVALUACION", "comite"),
    ("REUNION DE DOCENTES", "reunion"),
    ("REUNION DE PROFESORES", "reunion"),
    ("CONSEJO DE FACULTAD", "consejo de facultad"),
    ("EACULTAD", "consejo de facultad"),
    # «íJonsejo de Facultad»: el OCR se come la C, y lo que queda sigue siendo
    # el consejo.
    ("DE FACULTAD", "consejo de facultad"),
)

#: Cuánto texto alrededor del encabezado se mira para saber de qué órgano es.
VENTANA_DEL_ORGANO = 220

#: La clase de sesión cuando el encabezado no la dice: «SESIÓN ORDINARIA» en la
#: citación, «CONSEJO DE FACULTAD ORDINARIO» en la planilla de asistencia.
_SESION = re.compile(
    r"\b(?:SESION|REUNION|CONSEJO(?:\s+DE\s+FACULTAD|\s+ACADEMICO|\s+SUPERIOR)?)\s+"
    r"(ORDINARI[AO]|EXTRAORDINARI[AO])\b",
    re.IGNORECASE,
)

#: Una fecha en letra, con el día de la semana delante si lo trae:
#: «Lunes 17 de diciembre de 2012», «17 DE DICIEMBRE DE 2012», «17 de diciembre
#: 2012». Sobre el texto sin tildes, para que «miércoles» y «miercoles» -- que
#: es como lo deja el OCR la mitad de las veces -- sean lo mismo.
_FECHA_DIA_MES = re.compile(
    rf"\b(?:({_DIA})\s*,?\s*)?(\d{{1,2}})\s+(?:de\s+)?({_MES})\s*,?\s*(?:del?\s+)?(\d{{4}})\b",
    re.IGNORECASE,
)

#: Y la otra forma que se escribe en Colombia: «diciembre 17 de 2012».
_FECHA_MES_DIA = re.compile(
    rf"\b(?:({_DIA})\s*,?\s*)?({_MES})\s+(\d{{1,2}})\s*(?:de|,)\s*(\d{{4}})\b",
    re.IGNORECASE,
)

#: La fecha rotulada: «FECHA: LUNES 17 DE DICIEMBRE DE 2012» en la citación,
#: «Fecha 17 de diciembre 2012» en la tabla del acta. Lo que sigue al rótulo se
#: lee con los dos patrones de arriba o en cifras.
_ROTULO_FECHA = re.compile(r"\bFECHA\s*:?\s*", re.IGNORECASE)
_EN_CIFRAS = re.compile(r"^(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})\b")


@dataclass(frozen=True, slots=True)
class ActaDeConsejo:
    """Lo que se leyó del acta. Todo puede faltar; nada se rellena."""

    #: El número tal como va impreso, con sus ceros: «022», no 22.
    numero: str | None = None
    #: «ORDINARIA» o «EXTRAORDINARIA», cuando el papel lo dice.
    sesion: str | None = None
    fecha: date | None = None
    #: El día de la semana que trae escrito el papel, si trae alguno.
    dia_impreso: str | None = None
    #: En qué página se encontró el encabezado.
    pagina: int | None = None
    #: Cómo se llama el acta: «ACTA» en un consejo, «ACTA DE GRADO» en un libro
    #: de grados. Es lo que abre su encabezado en el inventario.
    rotulo: str = "ACTA"
    #: De un acta de grado, quién se graduó y de qué: lo que lleva su fila del
    #: FUID. En un acta de consejo no hay graduado y quedan en ``None``.
    nombre: str | None = None
    titulo: str | None = None
    cedula: str | None = None
    #: Lo que se leyó pero no es seguro, dicho para la columna de notas.
    dudas: tuple[str, ...] = ()
    #: Si la hoja es una constancia de la secretaría que copia un acta antigua
    #: y no el acta misma: no trae cédula ni título, y su fecha es la de
    #: expedición.
    constancia: bool = False
    #: «ACTA No. 15 BIS»: otra sesión con el número de la anterior.
    bis: bool = False

    @property
    def encabezado(self) -> str | None:
        """«ACTA ORDINARIA No. 022», o ``None`` si no se leyó el número."""
        if self.numero is None:
            return None
        clase = f" {self.sesion}" if self.sesion else ""
        bis = " BIS" if self.bis else ""
        return f"{self.rotulo}{clase} No. {self.numero}{bis}"

    @property
    def fecha_larga(self) -> str | None:
        """«Lunes 17 de diciembre de 2012».

        El día de la semana sale del calendario y no del papel: el calendario no
        se equivoca, y así el acta que no lo trae escrito sale igual que la que
        sí. Si el papel trae otro, lo dice `dia_no_cuadra`.
        """
        if self.fecha is None:
            return None
        dia = DIAS[self.fecha.weekday()].capitalize()
        mes = _NOMBRE_DEL_MES[self.fecha.month]
        return f"{dia} {self.fecha.day} de {mes} de {self.fecha.year}"

    @property
    def dia_no_cuadra(self) -> bool:
        """Si el día de la semana escrito no es el que cae esa fecha.

        Es la única comprobación que la fecha admite sin salir del papel, y
        atrapa lo que más se equivoca el OCR: un 17 leído como 11 cae en otro
        día de la semana.
        """
        if self.fecha is None or self.dia_impreso is None:
            return False
        return _plano(self.dia_impreso.lower()) != _plano(DIAS[self.fecha.weekday()])

    @property
    def asunto(self) -> str:
        """El asunto de la fila: el encabezado y la fecha, como los dictó el operador."""
        partes = [self.encabezado or "ACTA", self.fecha_larga]
        return " - ".join(parte for parte in partes if parte)


@dataclass(frozen=True, slots=True)
class EncabezadoDeActa:
    """Un encabezado de acta encontrado en una página, y lo que dice de ella."""

    #: En qué página, contada desde 1 dentro de las páginas que se miraron.
    pagina: int
    #: El número como va impreso, con sus ceros y con las letras del OCR
    #: devueltas a cifras: «022», «011».
    numero: str
    sesion: str | None
    #: Si abre una sesión y no sólo la nombra: trae la clase de sesión o la
    #: tabla de apertura («FECHA / HORA / LUGAR»). El membrete corrido de las
    #: páginas siguientes («Acta No. 022-2012») no es fuerte.
    fuerte: bool
    #: Qué órgano sesiona, si se dice cerca: «consejo de facultad», «comite»…
    organo: str | None
    #: Dónde acaba el encabezado en el texto de la página, para buscar detrás
    #: la fecha de la sesión.
    fin: int
    #: «ACTA No. 15 BIS»: una sesión aparte con el número de la anterior.
    bis: bool = False

    @property
    def valor(self) -> int:
        return int(self.numero)

    @property
    def clave(self) -> tuple[int, bool]:
        """Lo que distingue una sesión de otra: el número, y si es «BIS»."""
        return (self.valor, self.bis)


def encabezados_de_acta(paginas: Sequence[str]) -> list[EncabezadoDeActa]:
    """Todos los encabezados de acta de esas páginas, en su orden."""
    encontrados: list[EncabezadoDeActa] = []
    for numero_de_pagina, texto in enumerate(paginas, start=1):
        plano = _plano(texto)
        mayusculas = plano.upper()
        apertura = sum(1 for rotulo in _ROTULOS_DE_APERTURA if rotulo in mayusculas) >= 2
        for match in _ENCABEZADO.finditer(plano):
            crudo = match.group("numero")
            cifras = crudo.translate(_CIFRAS_DEL_OCR)
            # Sin una sola cifra de verdad, sólo se cree si va detrás de «No.»:
            # «ACTA I» no es un número, «ACTA No.Oll» sí es el 011.
            # Ni el acta cero: es «No. 0» con el resto del número ilegible.
            if (
                not cifras.isdigit()
                or int(cifras) == 0
                or (not any(c.isdigit() for c in crudo) and not match.group("rotulo"))
            ):
                continue
            if _LETRAS_DUDOSAS & set(crudo):
                cifras = _confirmado_por_el_corrido(paginas, numero_de_pagina, cifras)
            sesion = _sesion(match.group("sesion"))
            # «Acta No. 20-2010»: el número con el año pegado es el membrete
            # corrido de las hojas que siguen al encabezado, nunca una apertura.
            # La segunda hoja de un acta lleva el orden del día y la fecha, y
            # con eso parecía abrir sesión; si además la secretaría copió la
            # plantilla de otra acta sin cambiarle el número, partía el acta en
            # dos por una errata. Un acta se abre con su encabezado completo.
            corrido = _CORRIDO.match(plano, match.end()) is not None
            encontrados.append(
                EncabezadoDeActa(
                    pagina=numero_de_pagina,
                    numero=cifras,
                    sesion=sesion,
                    fuerte=(bool(sesion) or apertura) and not corrido,
                    organo=_organo(mayusculas, match.start(), match.end()),
                    fin=match.end(),
                    bis=_BIS.match(plano, match.end()) is not None,
                )
            )
    return encontrados


def _confirmado_por_el_corrido(paginas: Sequence[str], pagina: int, cifras: str) -> str:
    """El número de un encabezado leído con letras, tal como lo dice su membrete.

    «ACTA No. OS» puede ser el 05 o el 08: la S se parece a las dos. La hoja
    siguiente lo dice sin dudas en su membrete corrido, «Acta No. 08-27-11-01»,
    y es ése el que vale. Si ninguna hoja cercana lo confirma, se queda la
    lectura más probable.
    """
    for siguiente in range(pagina, min(pagina + HOJAS_PARA_CONFIRMAR, len(paginas))):
        cabecera = re.sub(r"\s+", " ", _plano(paginas[siguiente][:CABECERA_DE_APERTURA]).upper())
        corrido = _CORRIDO_DE_OTRA.search(cabecera)
        if corrido:
            return corrido.group(1).zfill(len(cifras))
    return cifras


#: Lo que dice el «Lugar:» de la tabla del acta sobre quién sesiona, cuando el
#: encabezado no nombra ningún órgano: «OFICINA DE LA DECANATURA DE LA
#: FACULTAD» es el consejo; «Oficina Departamento …» y «Salón de profesores de
#: la Clínica» son reuniones que el consejo recibe como anexo (Odontología,
#: UPD3859793, UPD3859796 y UPD3859798, 2026-10-30).
_ORGANOS_POR_EL_LUGAR = (
    ("OFICINA DEPARTAMENTO", "reunion"),
    ("SALON DE PROFESORES", "reunion"),
    ("DECANATURA", "consejo de facultad"),
)


def _organo(texto: str, inicio: int, fin: int) -> str | None:
    """El órgano que se nombra en el encabezado o justo detrás, o justo delante.

    Si no se nombra ninguno, lo dice el lugar de la sesión. Sólo entonces: con
    el lugar primero, «PROCESO DE REACREDITACIÓN ACTA No 01 … LUGAR: Decanatura»
    pasaba de comité a consejo (UPD3859775, pág. 185).
    """
    for ventana in (
        texto[inicio : fin + VENTANA_DEL_ORGANO],
        texto[max(0, inicio - VENTANA_DEL_ORGANO // 2) : inicio],
    ):
        posiciones = [
            (ventana.find(frase), organo) for frase, organo in _ORGANOS if frase in ventana
        ]
        if posiciones:
            return min(posiciones)[1]
    ventana = texto[inicio : fin + VENTANA_DEL_ORGANO]
    posiciones = [(ventana.find(frase), organo) for frase, organo in _ORGANOS_POR_EL_LUGAR if frase in ventana]
    return min(posiciones)[1] if posiciones else None


def organo_dominante(encabezados: Sequence[EncabezadoDeActa]) -> str | None:
    """El órgano de la mayoría de los encabezados que abren sesión.

    Se deduce y no se fija: un libro del Consejo Académico tendría sus actas
    como dominantes, y filtrar por «Consejo de Facultad» lo dejaría vacío.
    """
    cuenta = Counter(e.organo for e in encabezados if e.fuerte and e.organo)
    # Un libro es de un consejo: las reuniones y los comités son sus anexos,
    # aunque sean más. Una sesión con cuatro actas de reunión anexadas tenía
    # «reunion» por mayoría, y la sesión del consejo quedaba como anexo.
    consejos = Counter({organo: n for organo, n in cuenta.items() if organo.startswith("consejo")})
    elegidos = consejos or cuenta
    # Y si ningún encabezado que abre sesión nombra su órgano, el libro es del
    # consejo de facultad: sin esto, un acta cuyo único encabezado lo nombra por
    # el lugar se tomaba por anexo de nadie (UPD3859799, 2026-10-30).
    return elegidos.most_common(1)[0][0] if elegidos else "consejo de facultad"


def encabezados_del_libro(encabezados: Sequence[EncabezadoDeActa]) -> list[EncabezadoDeActa]:
    """Los encabezados que son del órgano del libro: sin los de sus anexos.

    Y sin el membrete corrido de esos anexos cuando el OCR se comió el nombre
    del órgano: en UPD3859787 el «ACTA No. 3 CONSEJO ACADÉMICO» de la página 22
    se reconocía como anexo, pero su «Acta No. 03 de 2015» de la 26 -- con el
    órgano leído «ÑOnSftlO ArarlAmlm» -- abría un acta del libro que no existe.
    El mismo número pocas hojas después, sin órgano y sin que el libro haya
    abierto una suya en medio, es el mismo anexo.
    """
    dominante = organo_dominante(encabezados)
    propios: list[EncabezadoDeActa] = []
    anexo: EncabezadoDeActa | None = None
    for encabezado in encabezados:
        if encabezado.organo not in (None, dominante):
            anexo = encabezado
            continue
        if encabezado.organo is not None:
            anexo = None
        elif (
            anexo is not None
            and encabezado.valor == anexo.valor
            and encabezado.pagina - anexo.pagina <= HOJAS_DEL_MEMBRETE_DEL_ANEXO
        ):
            continue
        propios.append(encabezado)
    return propios


#: Hasta cuántas hojas después del encabezado de un anexo se toma su número
#: repetido, sin órgano legible, por su membrete corrido.
HOJAS_DEL_MEMBRETE_DEL_ANEXO = 15


def leer_acta(paginas: Sequence[str], *, hoy: date | None = None) -> ActaDeConsejo:
    """El número, la sesión y la fecha del acta, de las páginas que se le den."""
    encontrados = encabezados_del_libro(encabezados_de_acta(paginas))

    if not encontrados:
        fecha, dia = _fecha_rotulada(paginas, hoy=hoy)
        return ActaDeConsejo(sesion=_sesion_suelta(paginas), fecha=fecha, dia_impreso=dia)

    # El que dice la clase de sesión manda: es el encabezado de verdad, y los
    # que no la dicen suelen ser el membrete corrido de las páginas siguientes
    # («Acta No. 022-2012»). Después el que abre la tabla de la sesión, y entre
    # iguales, el primero.
    #
    # Pero sólo entre los de la hoja que abre el acta: cuando un tramo lleva
    # unidos sus anexos -- la sesión 17 con un correo impreso «ACTA 1 DE
    # AGOSTO» detrás --, el encabezado del anexo no puede ganarle al de la
    # sesión por decir «ordinaria».
    fuertes = [e for e in encontrados if e.fuerte]
    if fuertes:
        encontrados = [e for e in encontrados if e.pagina == fuertes[0].pagina]
    elegido = next(
        (e for e in encontrados if e.sesion),
        next((e for e in encontrados if e.fuerte), encontrados[0]),
    )
    sesion = elegido.sesion or _sesion_suelta(paginas)

    # La fecha de la sesión va justo detrás del encabezado. Si no está ahí, la
    # rotulada «FECHA:» de la citación o de la tabla del acta; y si la tabla
    # quedó volcada -- «FECHA: / HORA: / LUGAR:» y los valores después de la
    # lista de asistentes --, la primera fecha de la hoja del encabezado.
    texto = paginas[elegido.pagina - 1]
    fecha, dia = _fecha_en(texto[elegido.fin : elegido.fin + VENTANA_DE_LA_FECHA], hoy=hoy)
    if fecha is None:
        fecha, dia = _fecha_rotulada(paginas, hoy=hoy)
    if fecha is None:
        fecha, dia = _fecha_en(texto[elegido.fin :], hoy=hoy)
    if fecha is None:
        fecha = _fecha_del_corrido(paginas, elegido.valor, hoy=hoy)

    return ActaDeConsejo(
        numero=elegido.numero,
        sesion=sesion,
        fecha=fecha,
        dia_impreso=dia,
        pagina=elegido.pagina,
        bis=elegido.bis,
    )


#: El membrete corrido de los libros de 2000-2006, que lleva la fecha de la
#: sesión: «Acta No. 08-27-11-01» es el acta 08 del 27 de noviembre de 2001.
_CORRIDO_CON_FECHA = re.compile(
    r"\bACTA\s*\S{0,4}\s*0*(\d{1,3})\s*[-–]\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*[-–]\s*(\d{2,4})\b",
    re.IGNORECASE,
)


def _fecha_del_corrido(
    paginas: Sequence[str], numero: int, *, hoy: date | None
) -> date | None:
    """La fecha que trae el membrete corrido del acta, cuando el encabezado no la deja leer.

    Sólo del membrete de **esta** acta -- el mismo número --: el de un acta
    vecina citada en el texto daría la fecha de otra sesión.
    """
    for texto in paginas:
        for match in _CORRIDO_CON_FECHA.finditer(_plano(texto)):
            if int(match.group(1)) != numero:
                continue
            dia, mes, anio = int(match.group(2)), int(match.group(3)), int(match.group(4))
            if anio < 100:
                anio += 2000 if anio < 50 else 1900
            fecha = _valida(dia, mes, anio, hoy)
            if fecha is not None:
                return fecha
    return None


def _sesion(valor: str | None) -> str | None:
    if not valor:
        return None
    return "EXTRAORDINARIA" if valor.upper().startswith("EXT") else "ORDINARIA"


def _sesion_suelta(paginas: Sequence[str]) -> str | None:
    """La clase de sesión dicha fuera del encabezado, si alguna página la dice."""
    for texto in paginas:
        match = _SESION.search(_plano(texto))
        if match:
            return _sesion(match.group(1))
    return None


def _fecha_rotulada(
    paginas: Sequence[str], *, hoy: date | None
) -> tuple[date | None, str | None]:
    """La primera fecha que se lea detrás de un rótulo «FECHA:»."""
    for texto in paginas:
        for rotulo in _ROTULO_FECHA.finditer(_plano(texto)):
            cola = texto[rotulo.end() : rotulo.end() + 60]
            fecha, dia = _fecha_en(cola, hoy=hoy, al_principio=True)
            if fecha is not None:
                return fecha, dia
    return None, None


#: Un año con letras donde el OCR no vio cifras: «20Ü1» (que sin tildes queda
#: «20U1»), «2OO0», «2O11». Sólo cuatro caracteres que empiezan por 19 o 20.
_ANIO_DEL_OCR = re.compile(r"\b(?:19|2[0OoUuD])[0-9OoUuDIl]{2}\b")
_CIFRA_DEL_OCR = str.maketrans("OoUuDIl", "0000011")

#: Un mes entre el día y el año, escrito como sea: «15 DE NOVlEyBRE DEL 2000».
#: «07 DF, DiCIFMBRF DF 2007»: el «de» también sale como «DF».
_MES_ENTRE_DIA_Y_ANIO = re.compile(
    r"\b(\d{1,2})\s*,?\s+(?:d[ef][,.]?\s+)?([a-z]{4,11})\s*,?\s*(?:d[ef]l?[,.]?\s+)?((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
#: Un año con un guion o un punto colado: «26 DE JUNIO DE 200-3».
_ANIO_PARTIDO = re.compile(r"\b(19|20)(\d)\s*[-–.]\s*(\d)\b")

#: Cuánto tiene que parecerse una palabra a un mes para leerla como tal.
PARECIDO_DEL_MES = 0.7


def _fechas_sin_ocr(plano: str) -> str:
    """El texto con los años y los meses que el OCR desfiguró, devueltos a su forma.

    Las actas de 2000-2006 están escaneadas de copias con poco contraste y el
    OCR deja «12 DE SEPTIEMBRE DE 20Ü1» o «15 DE NOVlEyBRE DEL 2000»: la fecha
    está, pero no se lee. Se arregla sólo donde no hay duda de qué es -- un año
    de cuatro caracteres que empieza por 19 o 20, una palabra entre un día y un
    año que se parece a un mes -- y letra por letra, sin tocar nada más.
    """
    import difflib

    texto = _ANIO_DEL_OCR.sub(lambda m: m.group(0).translate(_CIFRA_DEL_OCR), plano)

    texto = _ANIO_PARTIDO.sub(r"\1\2\3", texto)

    def mes(match: re.Match[str]) -> str:
        dia, palabra, anio = match.groups()
        if palabra.lower() in MESES:
            nombre = palabra.lower()
        else:
            parecido = difflib.get_close_matches(
                palabra.lower(), list(MESES), n=1, cutoff=PARECIDO_DEL_MES
            )
            if not parecido:
                return match.group(0)
            nombre = parecido[0]
        # Con los «de» en su sitio, que es la forma que reconoce la fecha.
        return f"{dia} de {nombre} de {anio}"

    return _MES_ENTRE_DIA_Y_ANIO.sub(mes, texto)


def _fecha_en(
    texto: str, *, hoy: date | None, al_principio: bool = False
) -> tuple[date | None, str | None]:
    """La primera fecha válida del texto, con el día de la semana si lo trae.

    ``al_principio`` exige que la fecha abra el texto, que es lo que pide una
    fecha rotulada: lo que va detrás de «FECHA:» y no cualquiera de más allá.
    """
    plano = _fechas_sin_ocr(_plano(texto))
    candidatas: list[tuple[int, date, str | None]] = []
    for match in _FECHA_DIA_MES.finditer(plano):
        dia_semana, dia, mes, anio = match.groups()
        fecha = _valida(int(dia), MESES[mes.lower()], int(anio), hoy)
        if fecha is not None:
            candidatas.append((match.start(), fecha, dia_semana))
    for match in _FECHA_MES_DIA.finditer(plano):
        dia_semana, mes, dia, anio = match.groups()
        fecha = _valida(int(dia), MESES[mes.lower()], int(anio), hoy)
        if fecha is not None:
            candidatas.append((match.start(), fecha, dia_semana))
    cifras = _EN_CIFRAS.match(plano.lstrip()) if al_principio else None
    if cifras:
        fecha = _valida(int(cifras.group(1)), int(cifras.group(2)), int(cifras.group(3)), hoy)
        if fecha is not None:
            candidatas.append((len(plano) - len(plano.lstrip()), fecha, None))

    if not candidatas:
        return None, None
    inicio, fecha, dia_semana = min(candidatas, key=lambda candidata: candidata[0])
    if al_principio and plano[:inicio].strip():
        return None, None
    return fecha, dia_semana.lower() if dia_semana else None


def _valida(dia: int, mes: int, anio: int, hoy: date | None) -> date | None:
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return None
    if anio < ANIO_MINIMO or fecha > (hoy or date.today()):
        return None
    return fecha


# -- un PDF con varias actas: los libros --------------------------------------

#: La portada que separa un acta de la anterior en los libros de 2011-2012: una
#: hoja casi vacía con «No. 014 - 12 DE JULIO DE 2012». Desde ella empieza el
#: acta, con todo lo que venga detrás hasta el encabezado -- citación,
#: asistencia, y alguna carta anexa intercalada --.
_PORTADA = re.compile(r"\bN\s*[O0]?\s*[.:,]?\s*0*(\d{1,3})\s*[-–]\s*\d{1,2}\b")

#: El membrete corrido de un acta en lo alto de una hoja: «Acta No. 04-15-06-01»,
#: «Acta No. 022-2012», y lo que el OCR deja de ellos («Acta í^o. 04-15…»). El
#: número va seguido de un guion y una cifra, que es lo que lo distingue de un
#: encabezado que abre sesión.
_CORRIDO_DE_OTRA = re.compile(r"\bACTA\s*\S{0,4}\s*0*(\d{1,3})\s*[-–]\s*\d")

#: Por debajo de cuántos caracteres una hoja es una portada y no una página.
PORTADA_MAXIMA = 250

#: Cuánto de lo alto de una hoja se mira para saber si es la apertura de la
#: sesión siguiente: la portada «No. 11 - 25 DE JUNIO DE 2012», la citación o la
#: planilla de asistencia, que dicen la fecha de la sesión en su cabecera.
CABECERA_DE_APERTURA = 700


@dataclass(frozen=True, slots=True)
class TramoDeActa:
    """Las páginas de un PDF que forman un acta, contadas desde 1."""

    desde: int
    hasta: int
    #: Si son las hojas de una ceremonia de grado que no son de ningún
    #: graduado: el listado de graduandos, la resolución que la autoriza, la
    #: portada. Salen en su propio PDF y no llevan fila en el FUID.
    ceremonia: bool = False
    #: Cuántos folios ocupa, cuando se sabe por la forma del libro: el acta de
    #: un graduado es una hoja, con su reverso. ``None`` en las de consejo, que
    #: se cuentan por la tinta de la esquina.
    hojas: int | None = None

    @property
    def paginas(self) -> int:
        return self.hasta - self.desde + 1


@dataclass(frozen=True, slots=True)
class ActasDelPdf:
    """Cómo se reparte un PDF en actas."""

    tramos: tuple[TramoDeActa, ...]
    #: Las páginas del principio que no son de ninguna acta -- la portada del
    #: libro, una carta de remisión --, o ``None`` si el PDF empieza con una.
    previas: tuple[int, int] | None = None

    @property
    def es_libro(self) -> bool:
        return len(self.tramos) > 1


#: El acta que declara el nombre del archivo: «1ACTA N°22 16 DE DICIEMBRE 2013»,
#: «1SESION ORDINARIA N° 018 MARTES 09 DE SEPTIEMBRE 2014», «2N° 002-02 DE
#: FEBRERO DE 2012».
_DECLARADA = re.compile(
    r"(?<![A-Z])N\W{0,3}\s*(?P<numero>\d{1,3})\b.*?(?P<dia>\d{1,2})\s*(?:DE\s+)?(?P<mes>[A-Z]{3,})"
    r"\s*(?:DE\s+|DEL\s+)?(?P<anio>(?:19|20)\d\d)"
)


#: El número más alto que se cree como número de acta en el nombre de un libro:
#: «2011 N°1 AL 449» cuenta folios, no actas.
NUMERO_DE_ACTA_MAXIMO = 60


def _nombre_plano(nombre: str) -> str:
    """El nombre del archivo en mayúsculas, sin extensión y sin el número de orden pegado.

    «1ACTAS DE CONSEJO N°22 Y 23 2016»: con el «1» pegado, «ACTAS» no tenía
    frontera de palabra, el nombre no decía nada y un acta de una reunión de
    departamento pasaba por sesión del libro (UPD3859793, 2026-10-30).
    """
    return re.sub(r"^\d{1,3}(?=[A-Z])", "", _plano(nombre.rsplit(".", 1)[0]).upper())


def numeros_del_nombre(nombre: str) -> set[int] | None:
    """Las actas que el nombre de un libro dice traer, o ``None`` si no lo dice.

    «ACTAS 7 Y 8», «ACTAS DE CONSEJO N°13 AL 21 2016», «N°22 Y 23 2016», «N°
    2-3-4-10-11-13 20…». Un rango que pasa de las sesiones de un año -- «N°1
    AL 449» -- son folios, y no dice nada de las actas.
    """
    plano = _nombre_plano(nombre)
    rango = re.search(r"\b(\d{1,3})\s+AL\s+(\d{1,3})\b", plano)
    if rango:
        desde, hasta = int(rango.group(1)), int(rango.group(2))
        if desde <= hasta <= NUMERO_DE_ACTA_MAXIMO:
            return set(range(desde, hasta + 1))
        return None
    lista = re.search(r"\bACTAS\b.*?\b(\d{1,3}(?:\s*(?:-|,|\bY\b)\s*\d{1,3})+)\b", plano)
    if lista:
        numeros = {int(n) for n in re.findall(r"\d{1,3}", lista.group(1))}
        # Sin un año colado: «2-3-4-10-11-13 20» corta el «2018» del final.
        numeros = {n for n in numeros if 0 < n <= NUMERO_DE_ACTA_MAXIMO}
        return numeros if len(numeros) >= 2 else None
    return None


def sin_actas_ajenas_al_nombre(
    reparto: ActasDelPdf, paginas: Sequence[str], numeros: set[int]
) -> ActasDelPdf:
    """Une a la sesión anterior las actas cuyo número no está entre los que el nombre dice.

    «…DEPARTAMENTO ACADEMICO 2015- ACTAS 7 Y 8» trae delante de la sesión 007
    el «ACTA DE REUNIONES N° 40» de otra dependencia: no es el 7 ni el 8, así
    que es un anexo. Lo que va antes de la primera acta del nombre pasa a ser de
    las páginas previas. Si ninguna acta del libro está en el nombre, el nombre
    no sirve y no se toca nada.
    """
    actas = [leer_acta(paginas[t.desde - 1 : t.hasta]) for t in reparto.tramos]
    propias = [
        a.numero is not None and a.numero.isdigit() and int(a.numero) in numeros for a in actas
    ]
    if not any(propias):
        return reparto
    unidos: list[TramoDeActa] = []
    previas = reparto.previas
    for tramo, propia in zip(reparto.tramos, propias, strict=True):
        if propia:
            unidos.append(tramo)
        elif unidos:
            unidos[-1] = TramoDeActa(unidos[-1].desde, tramo.hasta)
        else:
            previas = (1, tramo.hasta)
    return ActasDelPdf(tramos=tuple(unidos), previas=previas)


def acta_del_nombre(nombre: str) -> tuple[int, date] | None:
    """El número y la fecha del acta que dice el nombre del archivo, si dice una.

    Un nombre en plural -- «ACTAS DE CONSEJO N°1 AL 449» -- no declara un acta,
    y uno sin fecha completa tampoco.
    """
    plano = _nombre_plano(nombre)
    if re.search(r"\bACTAS\b", plano):
        return None
    encontrado = _DECLARADA.search(plano)
    if not encontrado:
        return None
    mes = MESES.get(encontrado.group("mes").lower())
    if mes is None:
        return None
    try:
        fecha = date(int(encontrado.group("anio")), mes, int(encontrado.group("dia")))
    except ValueError:
        return None
    return int(encontrado.group("numero")), fecha


def sin_anexos_anteriores(
    reparto: ActasDelPdf, paginas: Sequence[str], numero: int, fecha: date
) -> ActasDelPdf:
    """Une a su acta las que el PDF trae dentro y son anexos suyos.

    El nombre del archivo dice qué acta es -- «1ACTA N°22 16 DE DICIEMBRE
    2013» --. Un acta de otro número fechada ese día o antes, que no es una
    sesión del consejo -- no dice si es ordinaria o extraordinaria, o su
    cabecera no nombra al consejo --, es un anexo de esa: el «ACTA DE REUNIONES
    / ACTA N° 01» de la División de Calidad que la sesión 22 trae en la página
    29, las actas de la vicedecanatura de la sesión 018. Una sesión del consejo
    anterior sigue siendo suya -- la extraordinaria 001 del 26-01-2012 dentro
    de «2N° 002-02 DE FEBRERO DE 2012» --, y las posteriores también.
    """
    unidos: list[TramoDeActa] = []
    for tramo in reparto.tramos:
        if unidos and _es_anexo_de(paginas[tramo.desde - 1 : tramo.hasta], numero, fecha):
            unidos[-1] = TramoDeActa(unidos[-1].desde, tramo.hasta)
        else:
            unidos.append(tramo)
    return ActasDelPdf(tramos=tuple(unidos), previas=reparto.previas)


#: Cuánto de la cabecera de un acta se mira para saber si es del consejo.
CABECERA_DEL_ACTA = 1500


def _es_anexo_de(paginas: Sequence[str], numero: int, fecha: date) -> bool:
    acta = leer_acta(paginas)
    if acta.fecha is None or acta.fecha > fecha:
        return False
    if acta.numero and acta.numero.isdigit() and int(acta.numero) == numero:
        return False
    cabecera = " ".join(_plano(pagina).upper() for pagina in paginas[:2])[:CABECERA_DEL_ACTA]
    return acta.sesion is None or "CONSEJO" not in cabecera


def actas_del_pdf(paginas: Sequence[str], *, hoy: date | None = None) -> ActasDelPdf:
    """Las actas que trae un PDF, cada una con sus páginas.

    Un PDF de un acta -- los de la carpeta UPD3859771 -- es un solo tramo que lo
    cubre entero, con su portada, su citación y sus anexos. Un libro -- los de
    UPD3859772 a UPD3859778, de noventa a doscientas cuarenta páginas -- se
    reparte por los encabezados que **abren** sesión:

    * cada número nuevo empieza un acta; el mismo número otra vez es la misma
      acta (su membrete corrido, o una segunda sesión con el mismo número);
    * las hojas que preceden al encabezado y dicen la fecha de esa sesión en su
      cabecera -- portada, citación, asistencia -- son de esa acta y no de la
      anterior;
    * lo que va entre dos actas y no es la apertura de la siguiente -- anexos,
      microcurrículos, cartas -- se queda con la anterior;
    * los encabezados de otro órgano -- un comité, el Consejo Académico -- no
      abren nada: son anexos del acta en que aparecen.
    """
    total = len(paginas)
    entero = ActasDelPdf(tramos=(TramoDeActa(1, max(1, total)),))
    inicios: list[EncabezadoDeActa] = []
    for encabezado in encabezados_del_libro(encabezados_de_acta(paginas)):
        if not encabezado.fuerte:
            continue
        if inicios and encabezado.clave == inicios[-1].clave:
            continue
        inicios.append(encabezado)
    if len(inicios) <= 1:
        return entero

    comienzos = [
        _apertura(paginas, encabezado, inicios[indice - 1].pagina + 1 if indice else 1, hoy)
        for indice, encabezado in enumerate(inicios)
    ]
    # Cada acta empieza después de la anterior. Varios encabezados en la misma
    # hoja -- un índice que cita las actas 3, 4 y 5 -- abrían un tramo cada uno
    # en esa hoja, y los de en medio salían vacíos: «páginas 51-50», sin número
    # ni fecha, y un PDF sin páginas al dividir. Ante la duda, unir.
    crecientes: list[int] = []
    for desde in comienzos:
        if not crecientes or desde > crecientes[-1]:
            crecientes.append(desde)
    comienzos = crecientes
    if len(comienzos) <= 1:
        return ActasDelPdf(
            tramos=(TramoDeActa(comienzos[0], max(comienzos[0], total)),),
            previas=(1, comienzos[0] - 1) if comienzos[0] > 1 else None,
        )
    tramos = tuple(
        TramoDeActa(desde, comienzos[indice + 1] - 1 if indice + 1 < len(comienzos) else total)
        for indice, desde in enumerate(comienzos)
    )
    reparto = ActasDelPdf(tramos=tramos, previas=(1, comienzos[0] - 1) if comienzos[0] > 1 else None)
    return sin_actas_fuera_de_serie(reparto, paginas, hoy=hoy)


#: Cuántas actas por delante se mira si la numeración del libro sigue.
ACTAS_PARA_SEGUIR_LA_SERIE = 8


def sin_actas_fuera_de_serie(
    reparto: ActasDelPdf, paginas: Sequence[str], *, hoy: date | None = None
) -> ActasDelPdf:
    """Une a la sesión anterior las actas que rompen la numeración seguida del libro.

    Un libro numera sus sesiones seguidas -- 13, 14, 15… -- y lo que trae en
    medio con otro número es un anexo: en «ACTAS DE CONSEJO N°13 AL 21 2016»
    van entre las sesiones un «ACTA DE COMITE NORMATIVO No. 5», el acta de una
    reunión de departamento «No. 1» y un correo impreso. Se reconocen porque
    su número es menor que el de la sesión anterior, son del mismo año, y
    detrás la numeración sigue donde iba: 17, «1», «02», 18.

    Un libro que empieza la numeración cada año -- de 2007 a 2009, 01 otra
    vez en enero -- no pierde nada: el número baja, pero cambia el año.
    """
    if len(reparto.tramos) < 3:
        return reparto
    actas = [leer_acta(paginas[t.desde - 1 : t.hasta], hoy=hoy) for t in reparto.tramos]
    numeros = [int(a.numero) if a.numero and a.numero.isdigit() else None for a in actas]
    unidos: list[TramoDeActa] = []
    ultimo: int | None = None  # el índice de la última sesión que se quedó
    for indice, tramo in enumerate(reparto.tramos):
        if ultimo is not None and _fuera_de_serie(indice, ultimo, numeros, actas):
            unidos[-1] = TramoDeActa(unidos[-1].desde, tramo.hasta)
            continue
        unidos.append(tramo)
        ultimo = indice
    return ActasDelPdf(tramos=tuple(unidos), previas=reparto.previas)


def _fuera_de_serie(
    indice: int, ultimo: int, numeros: Sequence[int | None], actas: Sequence[ActaDeConsejo]
) -> bool:
    numero, anterior = numeros[indice], numeros[ultimo]
    if numero is None or anterior is None or numero >= anterior:
        return False
    fecha, fecha_anterior = actas[indice].fecha, actas[ultimo].fecha
    if fecha is not None and fecha_anterior is not None and fecha.year != fecha_anterior.year:
        return False
    # La numeración sigue donde iba, y en el mismo año: en un libro ordenado de
    # la última sesión a la primera -- 09, 08… 01 de 2001 y luego 07… de 2000
    # -- el «07» que viene después es de otro año y no dice nada.
    for siguiente in range(indice + 1, min(indice + 1 + ACTAS_PARA_SEGUIR_LA_SERIE, len(numeros))):
        if numeros[siguiente] != anterior + 1:
            continue
        otra = actas[siguiente].fecha
        if otra is None or fecha_anterior is None or otra.year == fecha_anterior.year:
            return True
    return False


def _apertura(
    paginas: Sequence[str], encabezado: EncabezadoDeActa, limite: int, hoy: date | None
) -> int:
    """La primera hoja de un acta: su portada, las hojas de apertura delante o su encabezado."""
    for pagina in range(encabezado.pagina - 1, limite - 1, -1):
        hoja = _plano(paginas[pagina - 1]).upper()
        if len(hoja.strip()) <= PORTADA_MAXIMA:
            portada = _PORTADA.search(hoja)
            if portada and int(portada.group(1)) == encabezado.valor:
                return pagina
    texto = paginas[encabezado.pagina - 1]
    fecha, _dia = _fecha_en(texto[encabezado.fin : encabezado.fin + VENTANA_DE_LA_FECHA], hoy=hoy)
    if fecha is None:
        return encabezado.pagina
    mes = _NOMBRE_DEL_MES[fecha.month].upper()
    marcas = tuple(
        f"{dia} {enlace}{mes}"
        for dia in {str(fecha.day), f"{fecha.day:02d}"}
        for enlace in ("DE ", "")
    )
    desde = encabezado.pagina
    neutras = 0
    for pagina in range(encabezado.pagina - 1, limite - 1, -1):
        cabecera = re.sub(r"\s+", " ", _plano(paginas[pagina - 1][:CABECERA_DE_APERTURA]).upper())
        # Una hoja con el membrete corrido de otra acta es la continuación de
        # esa acta, aunque cite la fecha de la siguiente: «Acta No. 04-15-06-01
        # … con fecha 9 de mayo/01» es el acta 04 hablando de un oficio, no la
        # citación del acta 03.
        corrido = _CORRIDO_DE_OTRA.search(cabecera)
        if corrido and int(corrido.group(1)) != encabezado.valor:
            break
        if any(marca in cabecera for marca in marcas):
            desde = pagina
            neutras = 0
            continue
        # El registro de asistencia, el vuelto en blanco o la hoja con el día
        # mal leído («MIERCOLES U DE JUNIO») van entre la citación y el acta
        # sin decir la fecha: se cruzan, pero sólo son de esta acta si detrás
        # aparece la citación con la fecha. Antes paraban la búsqueda y la
        # citación se quedaba en el acta anterior (Odontología, UPD3859790
        # acta 018 y UPD3859792 actas 14 y 15, 2026-10-31).
        if neutras < HOJAS_SIN_FECHA_EN_LA_APERTURA and _sin_fecha_propia(
            paginas[pagina - 1], cabecera, f"{mes} DE {fecha.year}"
        ):
            neutras += 1
            continue
        break
    return desde


#: Cuántas hojas sin la fecha se cruzan buscando la citación de un acta.
HOJAS_SIN_FECHA_EN_LA_APERTURA = 3


def _sin_fecha_propia(texto: str, cabecera: str, mes_y_anio: str) -> bool:
    """Si la hoja puede ir entre la citación y el acta sin decir la fecha de la sesión."""
    return (
        "REGISTRO DE ASISTENCIA" in cabecera
        or len(texto.strip()) <= PORTADA_MAXIMA
        or ("FECHA" in cabecera and mes_y_anio in cabecera)
    )


# -- el folio -----------------------------------------------------------------

#: Dónde va el folio, en fracciones de la página: el extremo derecho del margen
#: superior, donde el archivista lo escribe a mano junto al escudo. Medido sobre
#: el acta de Odontología, el número cae entre el 93 y el 96 % del ancho y entre
#: el 2 y el 5 % del alto; el escudo y «Universidad de Cartagena» acaban en el
#: 88 %, y el código del formulario de los anexos («FO-DO/AR-005») en el 86 %.
#: Dejarlos fuera importa dos veces: no se cuentan como tinta -- harían parecer
#: foliada cualquier hoja con membrete -- y no se leen como número.
BANDA_DEL_FOLIO = (0.87, 0.0, 0.995, 0.09)

#: Desde cuánto trazo se cree que la esquina lleva folio. En esa franja una hoja
#: sin folio mide cero, porque no queda membrete que contar, y el folio más
#: flaco del acta -- un «1» de un solo trazo -- mide 0,008. El umbral queda a
#: medio camino. No es el de `folio_manuscrito`, calibrado para la banda más
#: ancha de los libros de diplomas, que aquí se comería el escudo.
TRAZO_DE_FOLIO = 0.004

#: El folio más alto que se le cree a una esquina. Una carpeta de archivo no
#: llega a mil folios; lo que pase de ahí es el año del membrete («Fundada en
#: 1827») o un código del formulario, no un folio.
FOLIO_MAXIMO = 999

#: Cuánto se le perdona al rango de folios leído frente a las hojas foliadas: dos
#: folios, o el diez por ciento en un acta larga. Medido sobre la carpeta
#: UPD3859771, las lecturas buenas se apartan uno o dos; las malas, decenas.
MARGEN_DE_FOLIOS = 2
MARGEN_RELATIVO = 0.10

#: Un número suelto de hasta tres cifras. No vale el que va pegado a una barra,
#: un guion o un punto: ése es parte de un código («AR-005») o de una fecha
#: («04-05-2011»), no un folio escrito a mano.
_NUMERO_SUELTO = re.compile(r"(?<![\d/.\-])\d{1,3}(?![\d/.\-])")


@dataclass(frozen=True, slots=True)
class FoliosDelActa:
    """El primer y el último folio del acta, y cuántas hojas llevan uno."""

    inicial: int | None = None
    final: int | None = None
    #: Cuántas páginas llevan tinta en la esquina del folio. Se mide sin leer y
    #: es lo que queda cuando el número no se pudo leer.
    foliadas: int = 0
    #: Por qué no hay folio inicial y final, cuando no los hay.
    motivo: str | None = None

    @property
    def cantidad(self) -> int | None:
        """Los folios del acta, contados entre el primero y el último leídos."""
        if self.inicial is None or self.final is None or self.final < self.inicial:
            return None
        return self.final - self.inicial + 1

    @property
    def rango(self) -> str | None:
        """«Folios 1 a 21», o ``None`` si no se leyeron."""
        if self.inicial is None or self.final is None:
            return None
        if self.inicial == self.final:
            return f"Folio {self.inicial}"
        return f"Folios {self.inicial} a {self.final}"


def numeros_escritos(texto: str) -> list[int]:
    """Los números que podrían ser un folio, en el orden en que se leyeron."""
    return [
        numero
        for numero in (int(match.group(0)) for match in _NUMERO_SUELTO.finditer(texto or ""))
        if 0 < numero <= FOLIO_MAXIMO
    ]


def folios_que_cuadran(numeros: Sequence[int], hojas: int) -> tuple[int, int] | None:
    """El primer y el último folio, si los números leídos lo dicen sin dudas.

    ``numeros`` es lo que se leyó de arriba abajo en el mosaico de la primera y
    la última esquina foliadas, y ``hojas`` cuántas hojas llevan tinta en la
    esquina. Se cree la pareja cuyo rango -- del primero al último, contando los
    dos -- se parece a ese número de hojas: es la comprobación que haría
    cualquiera con el acta delante, y la que separa un folio de un número que se
    coló del membrete, porque los dos tendrían que equivocarse a la vez y por la
    misma cuenta.

    Con margen y no exacto, porque la foliación real no cuadra siempre al número
    de páginas: medido sobre la carpeta UPD3859771, el acta de 42 hojas foliadas
    va del folio 194 al 236 (43) y la de 40 del 43 al 84 (42) -- una tinta que
    no se midió, un folio que se saltó --, y exigir la cuenta exacta tiraba esas
    lecturas buenas. Las malas fallan por mucho más: «381 a 421» en un acta de
    veinte hojas, o un final menor que el principio.

    Se exige que la respuesta sea una sola. Dos parejas igual de buenas son dos
    lecturas posibles, y elegir una sería adivinar.
    """
    if not numeros or hojas < 1:
        return None
    if hojas == 1:
        # Una sola hoja foliada: su número es el primero y el último.
        return (numeros[0], numeros[0]) if len(set(numeros)) == 1 else None
    margen = max(MARGEN_DE_FOLIOS, math.ceil(hojas * MARGEN_RELATIVO))
    candidatas: dict[int, set[tuple[int, int]]] = {}
    for indice, inicial in enumerate(numeros):
        for final in numeros[indice + 1 :]:
            if final <= inicial:
                continue
            desvio = abs((final - inicial + 1) - hojas)
            if desvio <= margen:
                candidatas.setdefault(desvio, set()).add((inicial, final))
    if not candidatas:
        return None
    mejores = candidatas[min(candidatas)]
    return next(iter(mejores)) if len(mejores) == 1 else None


#: Cuántas actas fechadas a cada lado se miran para saber si una fecha cuadra.
VECINAS_PARA_FECHAR = 4
#: Cuántos años se puede apartar una fecha de la de sus vecinas antes de que se
#: tenga por mal leída.
ANIOS_DE_DESVIO = 2
#: Cuántas vecinas fechadas hacen falta para tener una fecha por mal leída.
VECINAS_MINIMAS = 3


def fechas_fuera_de_lugar(fechas: Sequence[date | None]) -> dict[int, tuple[int, int]]:
    """Las fechas de un libro que no cuadran con las de sus actas vecinas.

    Un libro va en orden: las actas de 2007 a 2009 no traen una del 16-01-2000,
    ni las de grado de 1981 a 1983 una de 1947. Esas fechas salen de leer otra
    cosa -- el año de una resolución citada, la cédula, un número roto --, y una
    fecha mal puesta es peor que ninguna: se ordena y se filtra por ella. Se
    devuelve, por la posición de cada fecha que no cuadra, el rango de años de
    sus vecinas.
    """
    fechadas = [(indice, fecha) for indice, fecha in enumerate(fechas) if fecha is not None]
    fuera: dict[int, tuple[int, int]] = {}
    for posicion, (indice, fecha) in enumerate(fechadas):
        vecinas = [
            otra.year
            for _i, otra in (
                fechadas[max(0, posicion - VECINAS_PARA_FECHAR) : posicion]
                + fechadas[posicion + 1 : posicion + 1 + VECINAS_PARA_FECHAR]
            )
        ]
        # Con menos de tres vecinas fechadas no hay de qué fiarse.
        if len(vecinas) < VECINAS_MINIMAS:
            continue
        mediana = sorted(vecinas)[len(vecinas) // 2]
        if abs(fecha.year - mediana) > ANIOS_DE_DESVIO:
            fuera[indice] = (min(vecinas), max(vecinas))
    return fuera


def folios_por_continuidad(
    actas: Sequence[tuple[int | None, int | None, int]],
) -> list[tuple[int | None, int | None, bool]]:
    """Los folios de las actas que no se leyeron, deducidos de sus vecinas.

    ``actas`` va en el orden de la carpeta, y de cada una dice el folio inicial
    y el final leídos -- ``None`` si no se leyeron -- y cuántas hojas lleva
    foliadas. Devuelve lo mismo con los huecos rellenos donde se puede, y si
    cada valor se dedujo.

    Una carpeta se folia seguida: el primer folio de un acta es el siguiente al
    último de la anterior. Así que entre dos actas bien leídas -- la que acaba
    en el folio 126 y la que empieza en el 194 -- las del medio ocupan
    exactamente los folios 127 a 193, y si sus hojas suman justo esos 67, cada
    una queda en su sitio sin lugar a dudas. Si no suman exacto, no se deduce
    nada: alguna tiene una hoja de más o de menos y no hay forma de saber cuál.
    Tampoco se deduce un tramo sin una lectura buena a cada lado.
    """
    resultado: list[tuple[int | None, int | None, bool]] = [
        (inicial, final, False) for inicial, final, _hojas in actas
    ]
    leidas = [
        indice
        for indice, (inicial, final, _hojas) in enumerate(actas)
        if inicial is not None and final is not None
    ]
    for antes, despues in zip(leidas, leidas[1:], strict=False):
        tramo = range(antes + 1, despues)
        if not tramo:
            continue
        desde = actas[antes][1] + 1
        hasta = actas[despues][0] - 1
        if sum(actas[indice][2] for indice in tramo) != hasta - desde + 1:
            continue
        siguiente = desde
        for indice in tramo:
            hojas = actas[indice][2]
            resultado[indice] = (siguiente, siguiente + hojas - 1, True)
            siguiente += hojas
    return resultado


@dataclass(frozen=True, slots=True)
class FolioEncadenado:
    """Los folios de un acta del libro, cuadrados con los de sus vecinas."""

    inicial: int
    final: int
    #: Si los dos extremos salieron de lo leído en las esquinas -- de esta acta
    #: o de la vecina que lo confirma -- o alguno se dedujo contando hojas.
    leido: bool

    @property
    def cantidad(self) -> int:
        return self.final - self.inicial + 1


# -- la foliación página a página ----------------------------------------------

#: Lo que cuesta no creerle a la lectura de una hoja: una esquina con un folio
#: viejo tachado («249» tachado junto al 239) se descarta si cuadrarla costaría
#: más que esto en folios de desfase.
COSTO_DE_DESCARTAR = 4

#: Cuántas hojas leídas hacia atrás se miran para encadenar una lectura.
VENTANA_DE_LA_CADENA = 15

#: Qué parte de las hojas leídas tiene que caber en la cadena para creer que el
#: libro va foliado página a página. Uno foliado por hoja -- el vuelto sin
#: número -- no cabe, y se queda con la cuenta por las hojas con tinta.
PARTE_QUE_CUADRA = 0.5


def foliacion_por_pagina(candidatos: Mapping[int, Sequence[int]]) -> dict[int, int] | None:
    """El folio de cada hoja leída que cabe en la foliación seguida del libro.

    En los libros de consejo de Odontología cada página lleva su folio y van
    seguidos: folio = página + un desfase que se mueve poco (196 al principio
    de UPD3859792, 199 al final). Pero muchas esquinas traen también el folio
    viejo tachado -- «239» y «249» tachado --, y la IA lee a veces el tachado.
    ``candidatos`` dice, por página, todos los números que se leyeron en su
    esquina; se elige la cadena que mejor sigue a las páginas: entre dos hojas
    elegidas el folio sube lo mismo que la página, y cada folio de desfase o
    cada hoja descartada cuesta. El tachado no cabe y se descarta.

    Devuelve el folio de cada hoja que quedó en la cadena, o ``None`` si la
    cadena no explica al menos la mitad de las hojas leídas: el libro no va
    foliado página a página.
    """
    paginas = sorted(p for p, numeros in candidatos.items() if numeros)
    if len(paginas) < 2:
        return None
    opciones = [list(dict.fromkeys(candidatos[p])) for p in paginas]
    # mejor[j][k]: el menor costo de una cadena que acaba eligiendo el número
    # k de la página j; de dónde viene, para rehacerla.
    mejor: list[list[float]] = []
    previo: list[list[tuple[int, int] | None]] = []
    for j, pagina in enumerate(paginas):
        fila: list[float] = []
        origen: list[tuple[int, int] | None] = []
        for folio in opciones[j]:
            costo, desde = j * COSTO_DE_DESCARTAR, None
            for i in range(max(0, j - VENTANA_DE_LA_CADENA), j):
                saltadas = (j - i - 1) * COSTO_DE_DESCARTAR
                for k, anterior in enumerate(opciones[i]):
                    if folio <= anterior:
                        continue
                    total = mejor[i][k] + saltadas + abs((folio - anterior) - (pagina - paginas[i]))
                    if total < costo:
                        costo, desde = total, (i, k)
            fila.append(costo)
            origen.append(desde)
        mejor.append(fila)
        previo.append(origen)
    final, punto = float("inf"), None
    for j in range(len(paginas)):
        for k, costo in enumerate(mejor[j]):
            total = costo + (len(paginas) - 1 - j) * COSTO_DE_DESCARTAR
            if total < final:
                final, punto = total, (j, k)
    elegidos: dict[int, int] = {}
    while punto is not None:
        j, k = punto
        elegidos[paginas[j]] = opciones[j][k]
        punto = previo[j][k]
    if len(elegidos) < PARTE_QUE_CUADRA * len(paginas):
        return None
    return elegidos


def folio_de_la_pagina(elegidos: Mapping[int, int], pagina: int) -> tuple[int, bool] | None:
    """El folio de una página por la foliación seguida, y si se leyó (``True``) o se dedujo.

    La que no se leyó toma el desfase de las hojas leídas de alrededor: el de
    la más cercana, que es el que menos ha podido moverse.
    """
    if pagina in elegidos:
        return elegidos[pagina], True
    antes = max((p for p in elegidos if p < pagina), default=None)
    despues = min((p for p in elegidos if p > pagina), default=None)
    if antes is None and despues is None:
        return None
    if despues is None or (antes is not None and pagina - antes <= despues - pagina):
        cercana = antes
    else:
        cercana = despues
    return pagina + elegidos[cercana] - cercana, False


def folios_del_libro(
    lecturas: Sequence[tuple[Sequence[int], int]],
) -> list[FolioEncadenado] | None:
    """Los folios de todas las actas de un libro, encadenados.

    Un libro se folia seguido: el primer folio de un acta es el siguiente al
    último de la anterior. Así que cada frontera entre dos actas se lee **dos
    veces** -- el final de una y el principio de la otra -- y donde las dos
    lecturas coinciden, esa frontera es segura aunque el resto de la esquina se
    leyera mal. Una lectura que juzgada sola no cuadra ya no se tira entera: la
    mitad buena se confirma con la vecina.

    ``lecturas`` va en el orden del libro y de cada acta dice los números leídos
    en sus esquinas, en orden, y cuántas hojas lleva foliadas.

    1. Fronteras seguras: dos actas distintas leen el mismo valor.
    2. Las demás se resuelven de la más cercana a una segura a la más lejana:
       se predice el valor contando las hojas desde la frontera resuelta más
       próxima, y se cree la lectura que caiga cerca de esa predicción. Si
       ninguna cae cerca, vale la predicción, y el acta se marca como deducida.

    ``None`` si no hay ninguna frontera segura -- sin dos lecturas que se
    confirmen no hay en qué apoyarse -- o si el resultado no avanza: un libro
    no se folia hacia atrás.
    """
    total = len(lecturas)
    if total < 2:
        return None
    hojas = [max(1, foliadas) for _numeros, foliadas in lecturas]

    # Lo que se leyó de cada frontera, con el acta de la que salió. La frontera
    # j es el primer folio del acta j, o el último del acta j-1 más uno.
    observado: list[list[tuple[int, int]]] = [[] for _ in range(total + 1)]
    for indice, (numeros, _foliadas) in enumerate(lecturas):
        if not numeros:
            continue
        observado[indice].append((numeros[0], indice))
        observado[indice + 1].append((numeros[-1] + 1, indice))

    frontera: list[int | None] = [None] * (total + 1)
    for indice, valores in enumerate(observado):
        for valor, acta in valores:
            if any(otro == valor and de != acta for otro, de in valores):
                frontera[indice] = valor
                break
    if all(valor is None for valor in frontera):
        return None
    leida = [valor is not None for valor in frontera]

    while any(valor is None for valor in frontera):
        pendientes = []
        for indice, valor in enumerate(frontera):
            if valor is not None:
                continue
            izquierda = next(
                (j for j in range(indice - 1, -1, -1) if frontera[j] is not None), None
            )
            derecha = next(
                (j for j in range(indice + 1, total + 1) if frontera[j] is not None), None
            )
            distancia = min(
                indice - izquierda if izquierda is not None else total + 2,
                derecha - indice if derecha is not None else total + 2,
            )
            pendientes.append((distancia, indice, izquierda, derecha))
        _distancia, indice, izquierda, derecha = min(pendientes)

        predicciones: list[tuple[int, int, int]] = []
        if izquierda is not None:
            entre = sum(hojas[izquierda:indice])
            predicciones.append((indice - izquierda, frontera[izquierda] + entre, entre))
        if derecha is not None:
            entre = sum(hojas[indice:derecha])
            predicciones.append((derecha - indice, frontera[derecha] - entre, entre))
        predicciones.sort()
        _cerca, prevista, entre = predicciones[0]
        margen = max(MARGEN_DE_FOLIOS, math.ceil(entre * MARGEN_RELATIVO))

        cercanas = [
            valor
            for valor, _acta in observado[indice]
            if any(abs(valor - prediccion) <= margen for _c, prediccion, _e in predicciones)
        ]
        if cercanas:
            frontera[indice] = min(
                cercanas,
                key=lambda valor: min(abs(valor - p) for _c, p, _e in predicciones),
            )
            leida[indice] = True
        else:
            frontera[indice] = prevista

    resueltas = [valor for valor in frontera if valor is not None]
    if any(siguiente <= actual for actual, siguiente in zip(resueltas, resueltas[1:], strict=False)):
        return None
    return [
        FolioEncadenado(
            inicial=resueltas[indice],
            final=resueltas[indice + 1] - 1,
            leido=leida[indice] and leida[indice + 1],
        )
        for indice in range(total)
    ]


# -- el texto que se manda a resumir ----------------------------------------

#: Cuánto texto se manda a resumir como máximo. Un acta de veinte páginas, ya
#: limpia de membretes, son unos veinte mil caracteres; esto da para más del
#: doble y pone techo a lo que se paga por un PDF que traiga cien hojas de
#: anexos. Lo que sobra se recorta del medio: el principio dice qué se trató y
#: el final qué se decidió.
LIMITE_PARA_RESUMIR = 48_000

#: En cuántas páginas tiene que repetirse un renglón para ser membrete o pie de
#: página y no contenido: el «Fundada en 1827», la dirección del campus, el
#: sello de calidad. Se repiten en todas y no dicen nada de la sesión.
_REPETIDO_EN = 0.3

#: Lo que se quita del texto antes de mandarlo: el punto del orden del día que
#: el operador no quiere ver en el resumen y las frases que lo cuentan («se
#: verifica el quórum, suficiente para sesionar y decidir»). Quitarlo antes es
#: más seguro que pedirle al modelo que no lo diga, y además no se paga.
#:
#: Lo de alrededor no cruza renglones, porque una lista numerada no lleva
#: puntos que la corten y se llevaría el orden del día entero; la frase misma
#: sí, porque el OCR la parte donde la partía el renglón del papel.
#: Sólo la frase clave. La cláusula que la contiene -- desde el signo anterior
#: hasta el siguiente -- se recorta a mano en `sin_llamado_a_lista`: con
#: «[^.;\n]*» delante dentro de la expresión, el motor volvía a recorrer el
#: renglón entero desde cada posición, y un renglón largo sin puntos -- un
#: OCR sin saltos -- tardaba minutos en vez de milisegundos.
_LLAMADO_A_LISTA = re.compile(
    r"\b(?:"
    r"llamado\s+a\s+lista(?:\s+y\s+(?:la\s+)?verificacion\s+del\s+quorum)?"
    r"|verificacion\s+del\s+quorum"
    r"|se\s+verific\w*\s+(?:el\s+)?quorum"
    r"|quorum\s+(?:suficiente|reglamentario|para\s+(?:sesionar|deliberar|decidir))"
    r")\b",
    re.IGNORECASE,
)
_FIN_DE_CLAUSULA = ".;\n"


def renglones_repetidos(paginas: Sequence[str]) -> set[str]:
    """Los renglones de membrete y pie de un PDF: los que salen en muchas hojas.

    Se miden sobre el PDF entero y no acta por acta: en un libro, un acta de
    dos hojas no tiene con qué distinguir su membrete de su texto, y el libro
    sí.
    """
    return _repetidos(
        [[renglon.strip() for renglon in texto.splitlines() if renglon.strip()] for texto in paginas]
    )


def texto_para_resumir(
    paginas: Sequence[str],
    *,
    limite: int = LIMITE_PARA_RESUMIR,
    repetidos: set[str] | None = None,
) -> str:
    """El texto del acta que vale la pena mandar a resumir, y nada más.

    Se paga por lo que se manda, así que se quita lo que no aporta antes de que
    salga: los renglones que se repiten en casi todas las páginas -- membrete y
    pie --, los que el OCR dejó hechos ruido y el llamado a lista.

    ``repetidos`` son los membretes medidos sobre el PDF entero, cuando estas
    páginas son sólo un acta de un libro; sin ellos se miden sobre estas.
    """
    renglones_por_pagina = [
        [renglon.strip() for renglon in texto.splitlines() if renglon.strip()]
        for texto in paginas
    ]
    if repetidos is None:
        repetidos = _repetidos(renglones_por_pagina)

    bloques: list[str] = []
    for renglones in renglones_por_pagina:
        utiles = [
            renglon
            for renglon in renglones
            if _clave(renglon) not in repetidos and _tiene_letra(renglon)
        ]
        if utiles:
            bloques.append("\n".join(utiles))

    texto = sin_llamado_a_lista("\n\n".join(bloques))
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if len(texto) <= limite:
        return texto
    cabeza = int(limite * 0.75)
    return f"{texto[:cabeza].rstrip()}\n[…]\n{texto[-(limite - cabeza):].lstrip()}"


def sin_llamado_a_lista(texto: str) -> str:
    """El texto sin el llamado a lista ni la verificación del quórum."""
    plano = _plano(texto)
    partes: list[str] = []
    desde = 0
    for match in _LLAMADO_A_LISTA.finditer(plano):
        if match.start() < desde:
            continue  # dentro de una cláusula ya quitada
        # La cláusula entera: desde el signo que la abre hasta el que la cierra,
        # que se va con ella si es punto o punto y coma; el salto de línea no.
        inicio = max(plano.rfind(signo, desde, match.start()) for signo in _FIN_DE_CLAUSULA) + 1
        inicio = max(inicio, desde)
        cierres = [plano.find(signo, match.end()) for signo in _FIN_DE_CLAUSULA]
        fin = min((posicion for posicion in cierres if posicion != -1), default=len(plano))
        if fin < len(plano) and plano[fin] in ".;":
            fin += 1
        partes.append(texto[desde:inicio])
        desde = fin
    partes.append(texto[desde:])
    return "".join(partes)


def depurar_resumen(resumen: str) -> str:
    """El resumen sin ninguna frase que hable del llamado a lista o del quórum.

    Es la última defensa. El texto ya salió sin ellos y las instrucciones le
    piden al modelo que no los mencione, pero un modelo puede deducirlo de
    «se verificó la asistencia», y lo que el operador pidió es que no aparezca.
    """
    frases = re.split(r"(?<=[.!?])\s+", resumen.strip())
    limpias = [
        frase
        for frase in frases
        if not re.search(
            r"llamado\s+a\s+lista|qu[oó]rum|verificaci[oó]n\s+de\s+(?:la\s+)?asistencia",
            frase,
            re.IGNORECASE,
        )
    ]
    return re.sub(r"\s{2,}", " ", " ".join(limpias)).strip()


def _clave(renglon: str) -> str:
    return re.sub(r"\W+", "", _plano(renglon).lower())


def _repetidos(renglones_por_pagina: list[list[str]]) -> set[str]:
    """Los renglones que salen en tantas páginas que son membrete y no texto."""
    if len(renglones_por_pagina) < 3:
        return set()
    cuenta = Counter(
        clave
        for renglones in renglones_por_pagina
        for clave in {_clave(renglon) for renglon in renglones}
        if clave
    )
    umbral = max(3, round(len(renglones_por_pagina) * _REPETIDO_EN))
    return {clave for clave, veces in cuenta.items() if veces >= umbral}


def _tiene_letra(renglon: str) -> bool:
    """Si el renglón es texto: una palabra de tres letras y más letras que signos.

    Lo que el OCR saca de un sello o de una firma -- «■;», «f>C-C.F.RlS.3470» --
    es casi todo signos y cifras, y mandarlo es pagar por ruido. Las cifras no
    cuentan en contra: «HORA: 09:30 HORAS.» es un renglón bueno.
    """
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{3}", renglon):
        return False
    letras = sum(caracter.isalpha() for caracter in renglon)
    signos = sum(not caracter.isalnum() and not caracter.isspace() for caracter in renglon)
    return letras > signos * 2
