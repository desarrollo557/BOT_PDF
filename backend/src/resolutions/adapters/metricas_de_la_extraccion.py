"""Los dos libros de la extracción de una entrega: sus métricas y su evidencia, documento por documento (2026-11-18).

- **«00.METRICAS DE LA EXTRACCION.xlsx»**: el resumen, los parámetros por
  estado, el rendimiento de cada método, la Revisión por familia, lo que no
  pasó el verificador independiente, lo no recuperado con su causa y, si se
  pide, la comparación con la entrega anterior.
- **«00.EVIDENCIA DE LA EXTRACCION.xlsx»**: una fila por documento y parámetro,
  con su valor, lo leído, la hoja, el fragmento, el método, los lectores, la
  confianza y los candidatos.

Con ``write_only``: una caja de 51.000 PDF deja más de medio millón de filas
de evidencia, y el libro no se carga entero en memoria.
"""

from __future__ import annotations

from pathlib import Path

from ..application.metricas_de_la_extraccion import (
    PARAMETROS,
    ComparacionDeUnNic,
    Metricas,
)
from .guardar_libro import guardar_libro

NOMBRE_DE_LAS_METRICAS = "00.METRICAS DE LA EXTRACCION.xlsx"
NOMBRE_DE_LA_EVIDENCIA = "00.EVIDENCIA DE LA EXTRACCION.xlsx"
#: Lo más largo que se escribe de un fragmento o de una causa en una celda.
LARGO_DE_LA_CELDA = 300
_ESTADOS = ("verificado", "encontrado", "requiere validación", "no encontrado", "contradictorio")


def _corto(valor: object) -> object:
    if isinstance(valor, str) and len(valor) > LARGO_DE_LA_CELDA:
        return valor[: LARGO_DE_LA_CELDA - 1] + "…"
    return valor


def escribir_metricas(
    destino: Path, metricas: Metricas, comparacion: list[ComparacionDeUnNic] | None = None
) -> list[Path]:
    """Escribe los dos libros en ``destino`` y devuelve sus rutas."""
    from openpyxl import Workbook

    libro = Workbook(write_only=True)
    resumen = libro.create_sheet("Resumen")
    resumen.append(["Métrica", "Valor"])
    for nombre, valor in (
        ("PDF de origen con constancia", metricas.pdf),
        *((f"PDF · {estado}", n) for estado, n in sorted(metricas.pdf_por_estado.items())),
        ("Documentos entregados", metricas.documentos),
        ("Páginas", metricas.paginas),
        ("Páginas pagadas a la IA", metricas.paginas_pagadas),
        ("Tiempo total de proceso (s, suma por PDF)", metricas.segundos),
        ("Tiempo medio por PDF (s)", round(metricas.segundos_por_pdf, 1)),
        ("Tiempo medio por documento (s)", round(metricas.segundos_por_documento, 1)),
        ("Hallazgos que no pasaron el verificador", len(metricas.reparos)),
        ("RE y fechas no recuperados o por validar", len(metricas.no_recuperados)),
    ):
        resumen.append([nombre, valor])

    parametros = libro.create_sheet("Por parámetro")
    parametros.append(["Parámetro", *_ESTADOS, "Total"])
    for parametro in PARAMETROS:
        fila = [metricas.por_estado.get((parametro, estado), 0) for estado in _ESTADOS]
        parametros.append([parametro, *fila, sum(fila)])

    metodos = libro.create_sheet("Por método")
    metodos.append(["Parámetro", "Método", "Estado", "Documentos"])
    for (parametro, metodo, estado), n in sorted(metricas.por_metodo.items()):
        metodos.append([parametro, metodo, estado, n])
    metodos.append([])
    metodos.append(["Lectores del RE que se cree", "", "", ""])
    for lector, n in metricas.lectores_del_re.most_common():
        metodos.append(["re", lector, "verificado o encontrado", n])

    revision = libro.create_sheet("Revisión")
    revision.append(["Familia", "Avisos"])
    for familia, n in metricas.revision.most_common():
        revision.append([familia, n])

    verificador = libro.create_sheet("Verificador")
    verificador.append(["Documento", "Parámetro", "Por qué no se sostiene"])
    for reparo in metricas.reparos:
        verificador.append([reparo.documento, reparo.parametro, reparo.motivo])

    no_recuperados = libro.create_sheet("No recuperados")
    no_recuperados.append(["Documento", "Parámetro", "Estado", "Causa"])
    for documento, parametro, estado, causa in metricas.no_recuperados:
        no_recuperados.append([documento, parametro, estado, _corto(causa)])

    if comparacion is not None:
        hoja = libro.create_sheet("Comparación")
        hoja.append(
            [
                "NIC",
                "Documentos antes",
                "Documentos ahora",
                "Con RE antes",
                "Con RE ahora",
                "Sin fecha antes",
                "Sin fecha ahora",
                "Sólo en la entrega anterior",
                "Sólo en esta entrega",
            ]
        )
        for fila in comparacion:
            hoja.append(
                [
                    fila.nic,
                    fila.documentos_antes,
                    fila.documentos_ahora,
                    fila.con_re_antes,
                    fila.con_re_ahora,
                    fila.sin_fecha_antes,
                    fila.sin_fecha_ahora,
                    _corto(" | ".join(fila.solo_antes)),
                    _corto(" | ".join(fila.solo_ahora)),
                ]
            )

    rutas = [guardar_libro(libro, destino / NOMBRE_DE_LAS_METRICAS)]

    evidencia = Workbook(write_only=True)
    hoja = evidencia.create_sheet("Evidencia")
    columnas = (
        "documento", "parametro", "estado", "valor", "original", "pagina",
        "fragmento", "metodo", "lectores", "confianza", "candidatos",
    )  # fmt: skip
    hoja.append(
        [
            "Documento", "Parámetro", "Estado", "Valor", "Lo leído", "Hoja",
            "Fragmento", "Método", "Lectores", "Confianza", "Candidatos",
        ]
    )  # fmt: skip
    for fila in metricas.evidencia:
        hoja.append([_corto(fila.get(c)) for c in columnas])
    rutas.append(guardar_libro(evidencia, destino / NOMBRE_DE_LA_EVIDENCIA))
    return rutas
