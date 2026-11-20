"""Los dos libros de la extracción de una entrega: sus métricas y su evidencia, documento por documento (2026-11-18).

- **«00.METRICAS DE LA EXTRACCION.xlsx»**: la auditoría de la entrega
  (2026-11-20) -- una fila por documento con su fecha, su RE y su Revisión;
  sólo lo pendiente; por UPD y por NIC -- y detrás el resumen, los parámetros
  por estado, el rendimiento de cada método, la Revisión por familia, lo que no
  pasó el verificador independiente, lo no recuperado con su causa y, si se
  pide, la comparación con la entrega anterior. Toda hoja con su filtro, su
  encabezado fijo y lo que falta en color.
- **«00.EVIDENCIA DE LA EXTRACCION.xlsx»**: una fila por documento y parámetro,
  con su valor, lo leído, la hoja, el fragmento, el método, los lectores, la
  confianza y los candidatos.

Con ``write_only``: una caja de 51.000 PDF deja más de medio millón de filas
de evidencia, y el libro no se carga entero en memoria.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from ..application.metricas_de_la_extraccion import (
    NO,
    PARAMETROS,
    SI,
    ComparacionDeUnNic,
    Metricas,
)
from .guardar_libro import guardar_libro

NOMBRE_DE_LAS_METRICAS = "00.METRICAS DE LA EXTRACCION.xlsx"
NOMBRE_DE_LA_EVIDENCIA = "00.EVIDENCIA DE LA EXTRACCION.xlsx"
#: Lo más largo que se escribe de un fragmento o de una causa en una celda.
LARGO_DE_LA_CELDA = 300
_ESTADOS = ("verificado", "encontrado", "requiere validación", "no encontrado", "contradictorio")
#: El aspecto de los libros: Arial, el encabezado oscuro, lo que falta en rojo,
#: lo que está bien en verde y lo que se mira en amarillo.
FUENTE = "Arial"
_FONDO_DEL_ENCABEZADO = "1F4E78"
_FONDO_DE_LO_QUE_FALTA = "F8CBAD"
_FONDO_DE_LO_QUE_ESTA_BIEN = "C6EFCE"
_FONDO_DE_LO_QUE_SE_MIRA = "FFEB9C"

#: Cómo se colorea una celda: devuelve su fondo, o ``None`` si va sin color.
Color = Callable[[object], "str | None"]


def _corto(valor: object) -> object:
    if isinstance(valor, str) and len(valor) > LARGO_DE_LA_CELDA:
        return valor[: LARGO_DE_LA_CELDA - 1] + "…"
    return valor


def _falta_si(*malos: object) -> Color:
    return lambda valor: _FONDO_DE_LO_QUE_FALTA if valor in malos else None


def _alerta(valor: object) -> str | None:
    if valor == "OK":
        return _FONDO_DE_LO_QUE_ESTA_BIEN
    return _FONDO_DE_LO_QUE_FALTA if valor else None


def _mas_de_cero(valor: object) -> str | None:
    return _FONDO_DE_LO_QUE_FALTA if isinstance(valor, int) and valor > 0 else None


def _se_mira(valor: object) -> str | None:
    return _FONDO_DE_LO_QUE_SE_MIRA if valor == SI else None


def _hoja(
    libro,
    nombre: str,
    columnas: Sequence[tuple[str, float]],
    filas: Iterable[Sequence[object]],
    *,
    colores: dict[int, Color] | None = None,
) -> None:
    """Una hoja con su encabezado fijo y oscuro, su filtro, el ancho de cada columna y lo que falta en color."""
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    hoja = libro.create_sheet(nombre)
    for indice, (_, ancho) in enumerate(columnas, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    hoja.freeze_panes = "A2"
    normal = Font(name=FUENTE, size=10)
    rellenos: dict[str, PatternFill] = {}

    def relleno(color: str) -> PatternFill:
        return rellenos.setdefault(color, PatternFill("solid", start_color=color, end_color=color))

    encabezado = []
    for titulo, _ in columnas:
        celda = WriteOnlyCell(hoja, value=titulo)
        celda.font = Font(name=FUENTE, size=10, bold=True, color="FFFFFF")
        celda.fill = relleno(_FONDO_DEL_ENCABEZADO)
        celda.alignment = Alignment(vertical="center", wrap_text=True)
        encabezado.append(celda)
    hoja.append(encabezado)
    colores = colores or {}
    cuantas = 0
    for fila in filas:
        cuantas += 1
        celdas = []
        for indice, valor in enumerate(fila):
            celda = WriteOnlyCell(hoja, value=_corto(valor))
            celda.font = normal
            if indice in colores and (color := colores[indice](valor)):
                celda.fill = relleno(color)
            celdas.append(celda)
        hoja.append(celdas)
    hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{cuantas + 1}"


def _por_nic(metricas: Metricas) -> list[list[object]]:
    """Las filas por NIC: la suma de sus UPD."""
    nics: dict[str, dict[str, int]] = {}
    for upd in metricas.por_upd:
        suma = nics.setdefault(
            upd["nic"],
            {"upd": 0, "documentos": 0, "sin_fecha": 0, "sin_re": 0, "en_revision": 0, "paginas": 0, "pagadas": 0},
        )
        suma["upd"] += 1
        suma["documentos"] += upd["documentos"]
        suma["sin_fecha"] += upd["sin_fecha"]
        suma["sin_re"] += upd["sin_re"]
        suma["en_revision"] += upd["en_revision"]
        suma["paginas"] += upd["paginas"]
        suma["pagadas"] += upd["paginas_pagadas"]
    return [
        [nic, s["upd"], s["documentos"], s["sin_fecha"], s["sin_re"], s["en_revision"], s["paginas"], s["pagadas"],
         "Revisar" if s["sin_fecha"] or s["sin_re"] or s["en_revision"] else "OK"]
        for nic, s in sorted(nics.items())
    ]  # fmt: skip


def _pendientes(metricas: Metricas) -> list[list[object]]:
    """Sólo lo que falta: un renglón por documento y problema, con su detalle."""
    filas = []
    for f in metricas.auditoria:
        problemas = []
        if f["tiene_fecha"] == NO:
            problemas.append(("Sin fecha", f["fecha_como"] or "la fecha no se pudo leer"))
        if f["tiene_re"] == NO:
            problemas.append(("Sin RE", f["re_como"] or "su tipo lleva RE y no se halló"))
        if f["en_revision"] == SI:
            problemas.append(("En Revisión", f["motivos"]))
        filas += [[f["nic"], f["upd"], f["orden"], f["archivo"], f["tipo"], p, d] for p, d in problemas]
    return filas


def _escribir_la_auditoria(libro, metricas: Metricas) -> None:
    """Las hojas de la auditoría, al frente del libro (el operador, 2026-11-20)."""
    _hoja(
        libro,
        "Documentos",
        (
            ("NIC", 11), ("UPD", 13), ("Nº", 5), ("Archivo", 52), ("Tipo documental", 40), ("Páginas", 8),
            ("Hojas del origen", 10), ("Fecha", 11), ("¿Tiene fecha?", 9), ("Cómo se fechó", 40), ("RE", 17),
            ("¿Lleva RE por su tipo?", 10), ("¿Tiene RE?", 9), ("Estado del RE", 16), ("Cómo se halló el RE", 40),
            ("¿En Revisión?", 9), ("Motivos de la Revisión", 70), ("Alerta", 28),
        ),
        (
            [f["nic"], f["upd"], f["orden"], f["archivo"], f["tipo"], f["paginas"], f["hojas"], f["fecha"],
             f["tiene_fecha"], f["fecha_como"], f["re"], f["lleva_re"], f["tiene_re"], f["re_estado"], f["re_como"],
             f["en_revision"], f["motivos"], f["alerta"]]
            for f in metricas.auditoria
        ),
        colores={8: _falta_si(NO), 12: _falta_si(NO), 15: _se_mira, 17: _alerta},
    )  # fmt: skip
    _hoja(
        libro,
        "Pendientes",
        (("NIC", 11), ("UPD", 13), ("Nº", 5), ("Archivo", 52), ("Tipo documental", 40), ("Problema", 14),
         ("Detalle", 100)),
        _pendientes(metricas),
        colores={5: _falta_si("Sin fecha", "Sin RE", "En Revisión")},
    )  # fmt: skip
    _hoja(
        libro,
        "Por UPD",
        (
            ("NIC", 11), ("UPD", 13), ("Estado", 11), ("Lectura", 11), ("Páginas", 8), ("Documentos", 11),
            ("Sin fecha", 9), ("Sin RE", 8), ("En Revisión", 10), ("Avisos de Revisión", 10),
            ("Páginas pagadas a la IA", 11), ("Duración", 12), ("Procesado", 17), ("Alerta", 34),
        ),
        (
            [u["nic"], u["upd"], u["estado"], u["lectura"], u["paginas"], u["documentos"], u["sin_fecha"],
             u["sin_re"], u["en_revision"], u["avisos"], u["paginas_pagadas"], u["duracion"], u["procesado"],
             u["alerta"]]
            for u in metricas.por_upd
        ),
        colores={6: _mas_de_cero, 7: _mas_de_cero, 8: _mas_de_cero, 13: _alerta},
    )  # fmt: skip
    _hoja(
        libro,
        "Por NIC",
        (("NIC", 11), ("UPD", 6), ("Documentos", 11), ("Sin fecha", 9), ("Sin RE", 8), ("En Revisión", 10),
         ("Páginas", 8), ("Páginas pagadas a la IA", 11), ("Estado", 10)),
        _por_nic(metricas),
        colores={3: _mas_de_cero, 4: _mas_de_cero, 5: _mas_de_cero, 8: lambda v: _alerta(v if v == "OK" else "x")},
    )  # fmt: skip


def escribir_metricas(
    destino: Path, metricas: Metricas, comparacion: list[ComparacionDeUnNic] | None = None
) -> list[Path]:
    """Escribe los dos libros en ``destino`` y devuelve sus rutas."""
    from openpyxl import Workbook

    libro = Workbook(write_only=True)
    _escribir_la_auditoria(libro, metricas)
    documentos = metricas.auditoria
    nics_pendientes = {f["nic"] for f in documentos if f["alerta"] != "OK"}
    _hoja(
        libro,
        "Resumen",
        (("Métrica", 48), ("Valor", 14)),
        (
            ("PDF de origen con constancia", metricas.pdf),
            *((f"PDF · {estado}", n) for estado, n in sorted(metricas.pdf_por_estado.items())),
            ("NIC", len({f["nic"] for f in metricas.por_upd})),
            ("NIC con algo pendiente", len(nics_pendientes)),
            ("Documentos entregados", metricas.documentos),
            ("Documentos sin fecha", sum(1 for f in documentos if f["tiene_fecha"] == NO)),
            ("Documentos sin RE (de los que lo llevan por su tipo)", sum(1 for f in documentos if f["tiene_re"] == NO)),
            ("Documentos en Revisión", sum(1 for f in documentos if f["en_revision"] == SI)),
            ("Páginas", metricas.paginas),
            ("Páginas pagadas a la IA", metricas.paginas_pagadas),
            ("Tiempo total de proceso (s, suma por PDF)", metricas.segundos),
            ("Tiempo medio por PDF (s)", round(metricas.segundos_por_pdf, 1)),
            ("Tiempo medio por documento (s)", round(metricas.segundos_por_documento, 1)),
            ("Hallazgos que no pasaron el verificador", len(metricas.reparos)),
            ("RE y fechas no recuperados o por validar", len(metricas.no_recuperados)),
        ),
    )
    _hoja(
        libro,
        "Por parámetro",
        (("Parámetro", 12), *((estado.capitalize(), 14) for estado in _ESTADOS), ("Total", 10)),
        (
            [parametro, *fila, sum(fila)]
            for parametro in PARAMETROS
            for fila in [[metricas.por_estado.get((parametro, estado), 0) for estado in _ESTADOS]]
        ),
    )
    _hoja(
        libro,
        "Por método",
        (("Parámetro", 12), ("Método", 50), ("Estado", 20), ("Documentos", 12)),
        (
            *([parametro, metodo, estado, n] for (parametro, metodo, estado), n in sorted(metricas.por_metodo.items())),
            *(["re · lector del RE que se cree", lector, "verificado o encontrado", n]
              for lector, n in metricas.lectores_del_re.most_common()),
        ),
    )  # fmt: skip
    _hoja(libro, "Revisión", (("Familia", 30), ("Avisos", 10)), ([f, n] for f, n in metricas.revision.most_common()))
    _hoja(
        libro,
        "Verificador",
        (("Documento", 30), ("Parámetro", 12), ("Por qué no se sostiene", 90)),
        ([r.documento, r.parametro, r.motivo] for r in metricas.reparos),
    )
    _hoja(
        libro,
        "No recuperados",
        (("Documento", 30), ("Parámetro", 12), ("Estado", 20), ("Causa", 90)),
        ([documento, parametro, estado, causa] for documento, parametro, estado, causa in metricas.no_recuperados),
    )
    if comparacion is not None:
        _hoja(
            libro,
            "Comparación",
            (
                ("NIC", 11), ("Documentos antes", 11), ("Documentos ahora", 11), ("Con RE antes", 10),
                ("Con RE ahora", 10), ("Sin fecha antes", 10), ("Sin fecha ahora", 10),
                ("Sólo en la entrega anterior", 60), ("Sólo en esta entrega", 60),
            ),
            (
                [f.nic, f.documentos_antes, f.documentos_ahora, f.con_re_antes, f.con_re_ahora, f.sin_fecha_antes,
                 f.sin_fecha_ahora, " | ".join(f.solo_antes), " | ".join(f.solo_ahora)]
                for f in comparacion
            ),
        )  # fmt: skip

    rutas = [guardar_libro(libro, destino / NOMBRE_DE_LAS_METRICAS)]

    evidencia = Workbook(write_only=True)
    columnas = (
        "documento", "parametro", "estado", "valor", "original", "pagina",
        "fragmento", "metodo", "lectores", "confianza", "candidatos",
    )  # fmt: skip
    _hoja(
        evidencia,
        "Evidencia",
        (
            ("Documento", 30), ("Parámetro", 11), ("Estado", 18), ("Valor", 18), ("Lo leído", 24), ("Hoja", 7),
            ("Fragmento", 50), ("Método", 36), ("Lectores", 20), ("Confianza", 11), ("Candidatos", 50),
        ),
        ([fila.get(c) for c in columnas] for fila in metricas.evidencia),
        colores={2: _falta_si("no encontrado", "requiere validación", "contradictorio")},
    )  # fmt: skip
    rutas.append(guardar_libro(evidencia, destino / NOMBRE_DE_LA_EVIDENCIA))
    return rutas
