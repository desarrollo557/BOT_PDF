"""El FUID de las actas de grado: una fila por graduado, en la plantilla oficial.

Es el formato que el operador entregó como modelo («16. SECRETARIA
INVENTARIO_ACTAS DE GRADO.xlsx»), que es el FO-GD-008 de la Universidad
rellenado así:

* **Nombre o asunto**: el nombre y la especialidad, «MARTHA LUCIA HERRERA
  VILLAMIZAR - ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD»: el
  mismo texto con que se llama su PDF (``asunto_del_graduado``).
* **Consecutivo inicial**: el número del acta tal como va impreso, «01/05»;
  **final**: la cédula del graduado, sin puntos. Lo pidió el operador el
  2026-11-05 para todas las actas de grado; antes la cédula iba en la D.
* **Fechas extremas**: la fecha del acta, la misma en las dos, «03/03/2005».
* **Caja** y **carpeta**: «00C003292» y «UPD3859821», de dónde está el PDF.
* **No. de folios**: cuántos folios -- hojas -- tiene el acta, «1»; **No. de
  folios SIAR**: cuántas páginas se escanearon. No el folio manuscrito de la
  esquina, que es el lugar del acta en el libro y no su tamaño (2026-10-31).
* Las demás columnas -- código TRD, tomo, otro, soporte, frecuencia -- en
  blanco, como en el modelo. **Notas** lleva lo que no se
  pudo leer, para quien revise.

Las hojas de la ceremonia que no son de ningún graduado -- listado,
resolución, portada -- no llevan fila: en el modelo no la tienen.

El acta colectiva del libro manuscrito (UPD3859802, 2026-11-12) gradúa a una
promoción en un PDF: una fila por graduado, cada una con su asunto, su número
del rango y su cédula, todas con el mismo archivo. Los folios del acta van en
la fila del primero; en las demás, 0 (``folios_en``), con la nota de dónde
están.

Las actas manuscritas de examen -- las de 1924-1946 de la caja 00C003362 y las
de Odontología de 1952-1971 -- van como cualquier persona desde el 2026-11-27
(el estándar único de la Universidad): «NOMBRE - DOCTOR EN ODONTOLOGIA»,
«NOMBRE - QUINTO PREPARATORIO»; desde, el número del acta si el papel lo trae y
si no el folio del libro; hasta, la cédula o N/A. Antes (2026-11-04) eran «ACTA
DE EXAMEN PREPARATORIO DE GRADO - QUINTO PREPARATORIO - NOMBRE» con el folio en
desde y hasta.

Lo que el libro trae cosido entre las actas y no es una hoja de la ceremonia --
la lista de alumnos o de la promoción, la carta con que un graduado autoriza a
otro a recibir su diploma, la constancia de paz y salvo -- lleva su fila con su
título (``fila_de_la_ceremonia``, 2026-11-27).

La cabecera -- entidad, unidad administrativa, oficina productora, objeto -- es
la de la plantilla y no se toca: el operador la dio por fija.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from ..application.fuid import FuidRow
from ..application.inventory_document import template_for
from ..domain.acta_grado import (
    asunto_del_examen,
    asunto_del_graduado,
    es_acta_de_examen,
    es_encabezado_con_fila,
    es_encabezado_de_lista,
    fecha_de_la_lista,
    fechas_extremas_de_la_lista,
)
from ..domain.doctype import DocumentType
from .fuid_inventory import FuidInventory

#: Lo que se escribe donde no se pudo leer un dato que el FUID pide.
NO_LEIDO = "N/A"
#: Las filas que no van al FUID: las hojas de la ceremonia.
CEREMONIA = "CEREMONIA DE GRADO"
ACTA_DE_GRADO = "ACTA DE GRADO"
#: Lo que lleva detrás el rótulo del acta anulada (``acta_consejo.ANULADA``).
ANULADA = "ANULADA"

#: «00C003284», también con el rótulo pegado: Medicina nombra sus cajas
#: «CAJA00C003268», sin espacio, y con ``\b`` delante no se encontraba ninguna.
_CAJA = re.compile(r"(?<!\d)(\d{2}C\d{6})(?!\d)")
#: «UPD3859771», también con un espacio en medio: Medicina escribe «UPD
#: 3859597 HISTORIAS ACADEMICAS 1948-1960.pdf». Se devuelve siempre junta.
_UPD = re.compile(r"\bUPD\s?(\d{7})(?!\d)")


def ubicacion(carpeta: str, archivo: str) -> tuple[str, str]:
    """La caja y la carpeta (UPD) del PDF, de su ruta: «00C003290», «UPD3859819».

    La carpeta va en el nombre del PDF cuando la caja trae los PDF sueltos
    («UPD3859819-ACTA DE GRADO 2023.pdf») y en la subcarpeta cuando van dentro
    de una («00C003284\\UPD3859771\\…»). Lo que no aparece queda en blanco: no
    se inventa una caja.
    """
    texto = f"{carpeta} {archivo}"
    caja = _CAJA.search(texto)
    upd = _UPD.search(f"{archivo} {carpeta}")
    return (caja.group(1) if caja else "", f"UPD{upd.group(1)}" if upd else "")


def _como_dict(fila: object) -> Mapping[str, object]:
    if is_dataclass(fila) and not isinstance(fila, type):
        return asdict(fila)
    return fila  # type: ignore[return-value]


def _fecha_del_fuid(fecha: object) -> str:
    """«03-03-2005» del inventario a «03/03/2005», como la escribe el modelo."""
    texto = str(fecha or "")
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", texto):
        return texto.replace("-", "/")
    return NO_LEIDO


def _es_numero(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _folio(inicial: object, final: object) -> int | str:
    """El folio de la fila: «140», o «140-141» si su acta ocupa dos hojas foliadas."""
    if not isinstance(inicial, int) or isinstance(inicial, bool):
        return NO_LEIDO
    if isinstance(final, int) and not isinstance(final, bool) and final != inicial:
        return f"{inicial}-{final}"
    return inicial


def _leido(valor: object) -> str | None:
    """El dato tal como se leyó, o ``None`` si no se leyó: vacío o N/A."""
    texto = str(valor or "").strip()
    return texto if texto and texto != NO_LEIDO else None


#: El PDF en que quedó la fila, en su columna de resultado: «Dividido en
#: 03_X.pdf» al partir un libro, o «Ya era un acta…; se entrega como 01_X.pdf»
#: (``acta_consejo.SE_ENTREGA_COMO``, 2026-11-13).
SU_PDF = re.compile(r"(?:^Dividido en |; se entrega como )(.+\.pdf)$", re.IGNORECASE)


def nombre_del_pdf(fila: Mapping[str, object]) -> str | None:
    """El nombre del PDF de la fila sin su orden ni su extensión: «ACTA DE GRADO NO. 01 - 27-11-1980».

    Es lo que el operador ve en la carpeta y busca desde el FUID; ``None`` si
    la fila no dice en qué PDF quedó (sólo se inventarió).
    """
    archivo = str(fila.get("archivo_generado") or "")
    if not archivo and (su_pdf := SU_PDF.search(str(fila.get("resultado") or ""))):
        archivo = su_pdf.group(1)
    nombre = re.split(r"[\\/]", archivo)[-1]
    nombre = re.sub(r"^\d+_", "", re.sub(r"\.pdf$", "", nombre, flags=re.IGNORECASE)).strip()
    return nombre or None


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.upper().split())


def con_su_acta(asunto: str, pdf: str | None) -> str:
    """El asunto del graduado de un acta colectiva con el nombre del PDF de su acta delante.

    «ACTA DE GRADO NO. 01 - 27-11-1980 - CARMEN TERESA PEREZ BOHANQUEZ -
    ENFERMERA»: el acta colectiva lleva a toda su promoción en un PDF, y la
    fila de cada graduado no se encontraba en la carpeta por su nombre (el
    operador, 2026-11-13: «busco los PDF con el nombre que está en el
    inventario y no aparecen»). Eligió seguir con un PDF por acta y que la fila
    empiece por el nombre de ese PDF. Si el PDF ya se llama como el asunto, o
    el asunto es el comienzo del nombre del PDF, el asunto es el PDF.
    """
    if not pdf:
        return asunto
    if _plano(pdf) == _plano(asunto) or _plano(pdf).startswith(_plano(asunto)):
        return pdf
    return f"{pdf} - {asunto}"


#: El número tras «No.» en el encabezado del acta: «ACTA DE GRADO No. 01/05».
_NUMERO_DEL_ENCABEZADO = re.compile(r"\bNo\.\s*(\S.*)$")


def _numero_del_acta(fila: Mapping[str, object]) -> str:
    """El número del acta tal como va impreso -- «01/05», «082-2005», «054231116» --, o N/A.

    Del encabezado, que lo trae con su «BIS» si lo lleva; si no, del número
    suelto que guardan las filas de antes.
    """
    encabezado = _NUMERO_DEL_ENCABEZADO.search(str(fila.get("acta") or ""))
    if encabezado:
        return encabezado.group(1).strip()
    return _leido(fila.get("numero")) or NO_LEIDO


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila del FUID de un graduado, o ``None`` para las hojas de su ceremonia.

    El número de orden lo pone quien junta las filas (``fuid_de_la_entrega``).
    """
    if fila.get("tipo") == CEREMONIA:
        return None
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    acta = str(fila.get("acta") or NO_LEIDO)
    examen = es_acta_de_examen(acta)
    cedula = _leido(fila.get("cedula")) or NO_LEIDO
    fecha = _fecha_del_fuid(fila.get("fecha"))
    # Cuántos folios tiene el acta y cuántas páginas se escanearon: no el
    # folio manuscrito de la esquina, que es su lugar en el libro.
    # Un acta con su vuelto es un folio y dos páginas.
    desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
    paginas = hasta - desde + 1 if isinstance(desde, int) and isinstance(hasta, int) and hasta >= desde else 1
    if fila.get("hojas_del_pdf"):
        # Las del PDF cuando no van seguidas: el libro colectivo en el orden de
        # su folio impreso, «98, 2» (UPD3859802, 2026-11-13).
        paginas = len(fila["hojas_del_pdf"])  # type: ignore[arg-type]
    inicial, final = fila.get("folio_inicial"), fila.get("folio_final")
    if _es_numero(inicial) and _es_numero(final) and final >= inicial:
        folios = final - inicial + 1
    else:
        folios = max(1, (paginas + 1) // 2)
    # La hoja que comparte con la siguiente acta va en los dos PDF y se cuenta
    # en la que empieza en ella: la carpeta no suma dos veces la misma hoja.
    en_otra = len(fila.get("hojas_contadas_en_otra") or ())  # type: ignore[arg-type]
    if en_otra:
        paginas, folios = max(0, paginas - en_otra), max(0, folios - en_otra)
    if fila.get("folios_en"):
        # Un graduado de un acta colectiva que no es el primero: el acta y sus
        # folios ya se cuentan en la fila del primero, y aquí van en 0 para que
        # la carpeta no sume la misma hoja treinta veces (UPD3859802,
        # 2026-11-12). Su nota dice en qué fila están.
        folios = paginas = 0
    if examen:
        # El examen, como cualquier persona (el estándar único, 2026-11-27):
        # «NOMBRE - DOCTOR EN ODONTOLOGIA», «NOMBRE - QUINTO PREPARATORIO», el
        # mismo texto que su PDF. Desde, el número del acta si el papel lo trae
        # -- Odontología, «Acta No 132» -- y si no el folio del libro (la 3362
        # no lo trae); hasta, la cédula o N/A.
        numero = _leido(fila.get("numero"))
        asunto = asunto_del_examen(
            _leido(fila.get("nombre")), _leido(fila.get("titulo")), acta=acta, numero=numero, folio=inicial
        )
        desde_hasta = (numero or (str(inicial) if _es_numero(inicial) else NO_LEIDO), cedula)
    elif acta.endswith(ANULADA):
        # El acta anulada no gradúa a nadie (UPD3859802, 2026-11-13): su fila
        # es la del acta, que lo dice, y no la de un graduado en blanco. Con el
        # nombre de su PDF, que es el del acta con su fecha, para encontrarlo.
        rotulo = (nombre_del_pdf(fila) if fila.get("acta_colectiva") else None) or acta
        asunto = " - ".join(parte for parte in (rotulo, _leido(fila.get("titulo"))) if parte)
        desde_hasta = (_numero_del_acta(fila).removesuffix(f" {ANULADA}"), NO_LEIDO)
    else:
        # El graduado (2026-11-05): el asunto es el nombre y la especialidad,
        # el mismo texto con que se llama su PDF; desde, el número del acta; y
        # hasta, su cédula.
        asunto = asunto_del_graduado(
            _leido(fila.get("nombre")),
            _leido(fila.get("titulo")),
            acta=_leido(fila.get("acta")),
            cedula=_leido(fila.get("cedula")),
        )
        if fila.get("acta_colectiva"):
            # El acta colectiva va en un PDF con toda su promoción: la fila del
            # graduado empieza por el nombre de ese PDF (2026-11-13).
            asunto = con_su_acta(asunto, nombre_del_pdf(fila))
        desde_hasta = (_numero_del_acta(fila), cedula)
    return FuidRow(
        orden=0,
        asunto=asunto,
        codigo_trd="",
        consecutivo_inicial=desde_hasta[0],
        consecutivo_final=desde_hasta[1],
        fecha_inicial=fecha,
        fecha_final=fecha,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=folios,
        folios_siar=paginas,
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )


def _asunto_como_su_pdf(acta: str, pdf: str | None) -> str:
    """El asunto de la resolución de la ceremonia: el nombre de su PDF, «RESOLUCION 02214 - … DE- ENFERMERO (A) - 15-12-2021».

    El asunto «… TITULO DE: ENFERMERO» no encontraba el PDF «… TITULO DE-
    ENFERMERO … - 15-12-2021»: Windows no deja «:» en un nombre y el PDF lleva
    la fecha (Odontología, 2026-11-13: 46 resoluciones). El mismo texto, también
    si el nombre se recortó para caber en la ruta: el asunto entero ya no se
    encontraba buscándolo en la carpeta (13 de las 46), y el operador pidió el
    2026-11-05 que el PDF y el FUID digan lo mismo.
    """
    return pdf or acta


def _fecha_del_fuid_de(fecha: object) -> str:
    return fecha.strftime("%d/%m/%Y") if fecha is not None else NO_LEIDO  # type: ignore[attr-defined]


def _fila_de_lo_cosido(fila: Mapping[str, object], acta: str) -> FuidRow:
    """La fila de una lista, una carta o una constancia cosida entre las actas (2026-11-27).

    El asunto es su título, el mismo que su PDF; desde y hasta, N/A en la lista
    y en el documento de una persona la cédula de quien lo firma en hasta. La
    lista lleva las fechas de su promoción, o del 1 de enero al 31 de diciembre
    del año de su periodo; el documento, la suya.
    """
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
    paginas = hasta - desde + 1 if isinstance(desde, int) and isinstance(hasta, int) and hasta >= desde else 1
    if es_encabezado_de_lista(acta):
        texto = str(fila.get("fecha") or "")
        leida = fecha_de_la_lista(texto) if re.fullmatch(r"\d{2}-\d{2}-\d{4}", texto) else None
        inicial, final = fechas_extremas_de_la_lista(acta, leida)
        fechas = (_fecha_del_fuid_de(inicial), _fecha_del_fuid_de(final))
        consecutivos = (NO_LEIDO, NO_LEIDO)
    else:
        fecha = _fecha_del_fuid(fila.get("fecha"))
        fechas = (fecha, fecha)
        consecutivos = (NO_LEIDO, _leido(fila.get("cedula")) or NO_LEIDO)
    return FuidRow(
        orden=0,
        asunto=_asunto_como_su_pdf(acta, nombre_del_pdf(fila)),
        codigo_trd="",
        consecutivo_inicial=consecutivos[0],
        consecutivo_final=consecutivos[1],
        fecha_inicial=fechas[0],
        fecha_final=fechas[1],
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=max(1, (paginas + 1) // 2),
        folios_siar=paginas,
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )


def fila_de_la_ceremonia(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila de la resolución que autoriza los grados y de lo cosido entre las actas; ``None`` para las hojas de la ceremonia.

    Lo pidió el operador el 2026-11-12 (Odontología): la «RESOLUCIÓN No. 01633,
    por medio de la cual se autorizan grados secretariales», con su lista de
    egresados, es un documento del libro y va al FUID con su número; la hoja de
    la ceremonia que sólo lista a los graduados, no. Y el 2026-11-27: la lista
    de alumnos o de la promoción, «su PDF y su fila», y la carta o la
    constancia de una persona, la suya; la portada «ACTAS», ninguna.
    """
    acta = str(fila.get("acta") or "")
    if es_encabezado_con_fila(acta):
        return _fila_de_lo_cosido(fila, acta)
    if not acta.startswith("RESOLUCION"):
        return None
    numero = re.search(r"\d{3,6}", acta)
    fecha = _fecha_del_fuid(fila.get("fecha"))
    # El número completo, con su año, como en las resoluciones de la caja 3303:
    # «01633-2021» (el operador, 2026-11-12).
    anio = re.search(r"(19|20)\d{2}$", str(fila.get("fecha") or ""))
    completo = f"{numero.group(0)}-{anio.group(0)}" if numero and anio else (numero.group(0) if numero else NO_LEIDO)
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
    paginas = hasta - desde + 1 if isinstance(desde, int) and isinstance(hasta, int) and hasta >= desde else 1
    return FuidRow(
        orden=0,
        asunto=_asunto_como_su_pdf(acta, nombre_del_pdf(fila)),
        codigo_trd="",
        consecutivo_inicial=completo,
        consecutivo_final=completo,
        fecha_inicial=fecha,
        fecha_final=fecha,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=max(1, (paginas + 1) // 2),
        folios_siar=paginas,
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )


def filas_del_fuid(filas: Sequence[object]) -> list[FuidRow]:
    """Las filas del FUID, una por graduado y en el orden en que llegan."""
    resultado: list[FuidRow] = []
    for fila in map(_como_dict, filas):
        convertida = fila_del_fuid(fila)
        if convertida is not None:
            resultado.append(replace(convertida, orden=len(resultado) + 1))
    return resultado


def escribir_fuid_de_actas_de_grado(
    filas: Sequence[object], destino: Path, *, plantilla: Path | None = None
) -> Path:
    """Escribe el FUID de las actas de grado en ``destino`` y devuelve su ruta."""
    return FuidInventory(plantilla or template_for(DocumentType.ACTA)).write(
        filas_del_fuid(filas), destino
    )
