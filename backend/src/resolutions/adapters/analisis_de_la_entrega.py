"""El análisis de la entrega de una carpeta: qué se procesó, qué no y por qué.

Lo pidió el operador el 2026-10-22: «estructúralo bien para que sea fácil
reconocer las carpetas y los PDF ya procesados y cuáles no… que me saque un
análisis de los procesados, los no procesados». Va en la raíz del destino,
«00.ANALISIS DE LA ENTREGA.xlsx», con cuatro hojas:

- **Resumen**: cuántos PDF, cuántos ya estaban entregados, cuántos se
  procesaron, se rehicieron, fallaron o quedan pendientes, y cuántas carpetas
  quedaron completas.
- **Por carpeta**: cada carpeta (el NIC), con sus cuentas y su estado.
- **Por PDF**: cada PDF, con lo que se decidió al verificarlo, por qué, y lo
  que pasó después.
- **Incidencias**: carpetas que no se pudieron leer y otros avisos que impiden
  interpretar la corrida como completa.

Con la auditoría de cierre, además, «Origen y destino», «Muestra auditada» y
«Margen por habilidad». La muestra es de PDF entregados o -- en una corrida que
sólo inventaría (2026-11-09) -- de filas del inventario, y la hoja lo dice con
sus propias columnas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .guardar_libro import guardar_libro

NOMBRE_DEL_ANALISIS = "00.ANALISIS DE LA ENTREGA.xlsx"

#: Lo que le pasó a cada PDF en la corrida.
YA_ENTREGADO = "Ya estaba entregado"
PROCESADO = "Procesado"
FALLO = "Falló"
EN_PROCESO = "En proceso"
PENDIENTE = "Pendiente"
REVISADO = "Sólo revisado"
CANCELADO = "Cancelado"

#: De qué es la muestra de la auditoría (2026-11-09): de PDF cortados o, en una
#: corrida que sólo inventaría, de filas del inventario. Sin la clave, de PDF:
#: lo que había antes de que hubiera muestra de filas.
MUESTRA_DE_FILAS = "filas"
#: El renglón de una muestra que no tuvo nada que revisar: la hoja no se queda
#: con la cabecera sola, sin decir por qué.
SIN_MUESTRA = "sin muestra"


@dataclass(frozen=True, slots=True)
class FilaDelAnalisis:
    carpeta: str
    pdf: str
    verificacion: str
    motivo: str
    resultado: str
    detalle: str = ""
    documentos: int = 0
    paginas: int = 0


def estado_de_la_carpeta(filas: list[FilaDelAnalisis]) -> str:
    """Completa, con fallos o con pendientes: lo primero que hay que mirar."""
    resultados = {fila.resultado for fila in filas}
    if FALLO in resultados:
        return "Con fallos"
    if resultados & {PENDIENTE, EN_PROCESO, CANCELADO}:
        return "Con pendientes"
    return "Completa"


def es_de_filas(muestra: dict) -> bool:
    """Si la muestra es de filas del inventario y no de PDF entregados."""
    return muestra.get("unidad") == MUESTRA_DE_FILAS


def por_que_no_hay_muestra(muestra: dict) -> str:
    """Por qué la muestra no revisó nada, dicho en palabras para el operador.

    Una muestra vacía no tiene margen de error: el intervalo de cero sobre cero
    no dice nada, y mostrarlo como «< 0 % de error» haría creer que la corrida
    salió perfecta (el operador, 2026-11-09). Se dice qué pasó y que no hay
    margen que dar.
    """
    de_filas = es_de_filas(muestra)
    nada = "No se auditó ninguna fila del inventario" if de_filas else "No se auditó ningún PDF"
    if not muestra.get("candidatos"):
        que = "filas del inventario" if de_filas else "PDF entregados"
        motivo = f"la corrida no dejó {que} que auditar"
    elif muestra.get("no_auditados"):
        cuantos = muestra["no_auditados"]
        if cuantos == 1:
            elegidos = "la fila elegida no se pudo" if de_filas else "el PDF elegido no se pudo"
        else:
            elegidos = f"las {cuantos} filas elegidas" if de_filas else f"los {cuantos} PDF elegidos"
            elegidos += " no se pudieron"
        motivo = f"{elegidos} auditar (el motivo, en la hoja «Muestra auditada»)"
    else:
        motivo = "la auditoría no llegó a revisar ninguno"
    return f"{nada}: {motivo}. Sin muestra no hay margen de error que dar."


def _texto_del_margen(margen: dict, de_filas: bool) -> str:
    """El error medido; en una muestra de filas sin nada revisado, dicho de filas y no de PDF."""
    if de_filas and not margen.get("revisados"):
        return "No se revisó ninguna fila."
    return str(margen.get("texto", ""))


def escribir_analisis(
    destino: Path,
    filas: list[FilaDelAnalisis],
    *,
    origen: str,
    fecha: str,
    avisos: list[str] | None = None,
    comparacion: dict | None = None,
    muestra: dict | None = None,
) -> Path:
    """Escribe el análisis en ``destino`` (entero o nada) y devuelve su ruta.

    Con la auditoría de cierre (2026-11-05), dos hojas más: «Origen y destino»
    -- lo que no cuadra entre los dos lados, con su evidencia -- y «Muestra
    auditada» -- cada PDF de la muestra y lo que se encontró --; y el resumen
    lleva sus cuentas y el margen de error de la corrida. Con una muestra de
    filas del inventario (2026-11-09, ``muestra["unidad"] == "filas"``), la hoja
    lleva las columnas de una fila y el resumen, lo que se preguntó a la IA.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    negrita = Font(bold=True)
    cabecera = PatternFill("solid", fgColor="DDE6F0")
    colores = {
        YA_ENTREGADO: "E2EFDA",
        PROCESADO: "C6EFCE",
        FALLO: "F8CBAD",
        PENDIENTE: "FFF2CC",
        EN_PROCESO: "FFF2CC",
        CANCELADO: "FFF2CC",
        "Completa": "C6EFCE",
        "Con fallos": "F8CBAD",
        "Con pendientes": "FFF2CC",
        # La auditoría de cierre.
        "Falta en el destino": "F8CBAD",
        "Índice que no cuadra": "F8CBAD",
        "Sin PDF en el origen": "FFF2CC",
        "Archivo suelto en la raíz": "FFF2CC",
        "Sobra en el destino": "FFF2CC",
        "bien": "C6EFCE",
        "error": "F8CBAD",
        "dudoso": "FFF2CC",
        "no se pudo auditar": "FFF2CC",
        "dentro del margen": "C6EFCE",
        "fuera del margen": "F8CBAD",
        "sin certeza": "FFF2CC",
        SIN_MUESTRA: "FFF2CC",
    }

    def tabla(hoja, columnas: list[tuple[str, int]], renglones: list[list], color_en: int | None = None) -> None:
        hoja.append([nombre for nombre, _ in columnas])
        for celda in hoja[1]:
            celda.font, celda.fill = negrita, cabecera
        for indice, (_, ancho) in enumerate(columnas, start=1):
            hoja.column_dimensions[hoja.cell(1, indice).column_letter].width = ancho
        for renglon in renglones:
            hoja.append(renglon)
            if color_en is not None and (color := colores.get(str(renglon[color_en]))):
                hoja.cell(hoja.max_row, color_en + 1).fill = PatternFill("solid", fgColor=color)
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions

    filas = sorted(filas, key=lambda f: (f.carpeta.lower(), f.pdf.lower()))
    avisos = avisos or []
    por_carpeta: dict[str, list[FilaDelAnalisis]] = {}
    for fila in filas:
        por_carpeta.setdefault(fila.carpeta, []).append(fila)
    resultados = Counter(fila.resultado for fila in filas)
    decisiones = Counter(fila.verificacion for fila in filas)
    estados = Counter(estado_de_la_carpeta(suyas) for suyas in por_carpeta.values())

    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen"
    renglones = [
        ["Origen", origen],
        ["Fecha del análisis", fecha],
        ["", ""],
        ["PDF vistos", len(filas)],
        *[
            [f"PDF · {nombre}", resultados.get(nombre, 0)]
            for nombre in (YA_ENTREGADO, PROCESADO, REVISADO, FALLO, CANCELADO, EN_PROCESO, PENDIENTE)
        ],
        ["", ""],
        *[[f"Verificación · {nombre}", cuantos] for nombre, cuantos in sorted(decisiones.items())],
        ["", ""],
        ["Incidencias", len(avisos)],
        ["", ""],
        ["Carpetas", len(por_carpeta)],
        *[[f"Carpetas · {nombre}", estados.get(nombre, 0)] for nombre in ("Completa", "Con pendientes", "Con fallos")],
    ]
    if comparacion:
        renglones += [
            ["", ""],
            ["Carpetas en la raíz del origen", comparacion.get("carpetas_origen", 0)],
            ["Carpetas en el destino", comparacion.get("carpetas_destino", 0)],
            ["Carpetas del origen con PDF", comparacion.get("carpetas_con_pdf", 0)],
            ["Carpetas completas en el destino", comparacion.get("carpetas_completas", 0)],
            ["PDF en el origen", comparacion.get("pdf_origen", 0)],
            ["PDF entregados enteros", comparacion.get("pdf_entregados", 0)],
            ["Documentos entregados", comparacion.get("documentos_entregados", 0)],
            ["Filas de los índices", comparacion.get("filas_del_indice", 0)],
            ["Entrega completa", "Sí" if comparacion.get("completa") else "No"],
        ]
    if muestra:
        margen = muestra.get("margen") or {}
        de_filas = es_de_filas(muestra)
        renglones += [
            ["", ""],
            [
                "Muestra auditada (filas del inventario)" if de_filas else "Muestra auditada (PDF)",
                muestra.get("revisados", 0),
            ],
        ]
        if muestra.get("revisados"):
            renglones += [
                ["Muestra · bien", muestra.get("bien", 0)],
                ["Muestra · con error", muestra.get("errores", 0)],
                ["Muestra · dudosos", muestra.get("dudosos", 0)],
                ["Muestra · semilla", muestra.get("semilla", "")],
                ["Margen de error de la corrida", margen.get("texto", "")],
                ["Dictamen de la corrida", margen.get("texto_del_dictamen", "")],
            ]
        else:
            # Ni cuentas en cero ni un «< 0 %»: por qué no hubo muestra.
            renglones += [
                ["Muestra · por qué está vacía", por_que_no_hay_muestra(muestra)],
                ["Muestra · semilla", muestra.get("semilla", "")],
                ["Margen de error de la corrida", "Sin muestra: no hay margen de error que dar"],
                ["Dictamen de la corrida", margen.get("texto_del_dictamen", "")],
            ]
        # Cada habilidad contra el margen de su perfil (2026-11-05): el error
        # de una no se diluye en los aciertos de las demás.
        renglones += [
            [
                f"Margen · {h['habilidad']}",
                f"{_texto_del_margen(h.get('margen') or {}, de_filas)} · "
                f"{(h.get('margen') or {}).get('texto_del_dictamen', '')}",
            ]
            for h in muestra.get("por_habilidad") or []
        ]
        # La IA de la auditoría de filas (2026-11-09): sólo se le pregunta si
        # la corrida se hizo con ella, y lo que costó va aquí, a la vista.
        if de_filas and "con_ia" in muestra:
            if muestra["con_ia"]:
                consumo = muestra.get("consumo_ia") or {}
                renglones += [
                    ["IA de la auditoría · datos que contestó", muestra.get("preguntadas_a_la_ia", 0)],
                    ["IA de la auditoría · tokens", consumo.get("tokens", 0)],
                ]
                if consumo.get("fallos"):
                    # Una IA caída o sin llave no revisó nada: se dice (2026-11-09).
                    renglones.append(["IA de la auditoría · filas sin respuesta", consumo["fallos"]])
            else:
                renglones.append(["IA de la auditoría: no (la corrida se hizo sin IA)", ""])
    tabla(resumen, [("Concepto", 42), ("Cantidad", 60)], renglones)

    tabla(
        libro.create_sheet("Por carpeta"),
        [("Carpeta", 22), ("Estado", 16), ("PDF", 8), ("Ya entregados", 14), ("Procesados", 12),
         ("Fallidos", 10), ("Pendientes o cancelados", 22), ("Documentos entregados", 22)],
        [
            [
                carpeta,
                estado_de_la_carpeta(suyas),
                len(suyas),
                sum(f.resultado == YA_ENTREGADO for f in suyas),
                sum(f.resultado == PROCESADO for f in suyas),
                sum(f.resultado == FALLO for f in suyas),
                sum(f.resultado in (PENDIENTE, EN_PROCESO, CANCELADO) for f in suyas),
                sum(f.documentos for f in suyas),
            ]
            for carpeta, suyas in por_carpeta.items()
        ],
        color_en=1,
    )
    tabla(
        libro.create_sheet("Por PDF"),
        [("Carpeta", 18), ("PDF", 22), ("Verificación", 22), ("Por qué", 60), ("Resultado", 18),
         ("Detalle", 60), ("Documentos", 12), ("Páginas", 10)],
        [
            [f.carpeta, f.pdf, f.verificacion, f.motivo, f.resultado, f.detalle, f.documentos, f.paginas]
            for f in filas
        ],
        color_en=4,
    )
    tabla(
        libro.create_sheet("Incidencias"),
        [("Aviso de la corrida", 100)],
        [[aviso] for aviso in avisos],
    )
    if comparacion:
        tabla(
            libro.create_sheet("Origen y destino"),
            [("Carpeta o PDF", 34), ("Estado", 24), ("Motivo", 50), ("Evidencia", 60)],
            [
                *[[f["carpeta"], "Falta en el destino", f["motivo"], f.get("evidencia", "")] for f in comparacion.get("faltan", [])],
                *[[r["pdf"], "Índice que no cuadra", r["motivo"], ""] for r in comparacion.get("registros_que_no_cuadran", [])],
                *[[s["carpeta"], "Sin PDF en el origen", s["motivo"], s.get("evidencia", "")] for s in comparacion.get("sin_pdf", [])],
                *[[a["carpeta"], "Archivo suelto en la raíz", "no es un PDF: no se procesa", ""] for a in comparacion.get("archivos_en_la_raiz", [])],
                *[[s["carpeta"], "Sobra en el destino", s["motivo"], s.get("evidencia", "")] for s in comparacion.get("sobran", [])],
                # Los PDF con dos o más sellos de RE distinto (2026-11-12).
                *[
                    [f"{v['pdf']} → {v['archivo']}", "PDF con 2 o más sellos", v.get("estado", ""), v.get("sellos", "")]
                    for v in comparacion.get("varios_sellos", [])
                ],
            ],
            color_en=1,
        )
    if muestra:
        de_filas = es_de_filas(muestra)
        if de_filas:
            # Una fila del inventario no tiene PDF entregados ni costuras: sus
            # páginas del original y lo que se preguntó a la IA (2026-11-09).
            columnas = [("Fila", 60), ("Habilidad", 24), ("Resultado", 16), ("Páginas", 10),
                        ("Preguntadas a la IA", 18), ("Hallazgos", 90)]
            de_la_muestra = [
                [
                    p["pdf"],
                    p.get("habilidad", ""),
                    p["estado"],
                    p.get("paginas", 0),
                    p.get("preguntadas_a_la_ia", 0),
                    "; ".join(p.get("hallazgos", [])),
                ]
                for p in muestra.get("pdfs", [])
            ]
        else:
            columnas = [("PDF", 40), ("Habilidad", 24), ("Resultado", 16), ("Páginas", 10), ("PDF entregados", 14),
                        ("Costuras", 10), ("Dentro del margen", 16), ("Preguntadas a la IA", 18), ("Hallazgos", 90)]
            de_la_muestra = [
                [
                    p["pdf"],
                    p.get("habilidad", ""),
                    p["estado"],
                    p.get("paginas", 0),
                    p.get("archivos", 0),
                    p.get("costuras", 0),
                    p.get("dentro_del_margen", 0),
                    p.get("preguntadas_a_la_ia", 0),
                    "; ".join(p.get("hallazgos", [])),
                ]
                for p in muestra.get("pdfs", [])
            ]
        if not de_la_muestra:
            # Sin nada que mostrar, la hoja dice por qué en vez de quedarse
            # con la cabecera sola (2026-11-09).
            relleno = [""] * (len(columnas) - 4)
            de_la_muestra = [
                ["Ninguna" if de_filas else "Ninguno", "", SIN_MUESTRA, *relleno, por_que_no_hay_muestra(muestra)]
            ]
        tabla(libro.create_sheet("Muestra auditada"), columnas, de_la_muestra, color_en=2)
        if muestra.get("por_habilidad"):
            tabla(
                libro.create_sheet("Margen por habilidad"),
                [("Habilidad", 28), ("Revisados", 11), ("Bien", 8), ("Con error", 11), ("Dudosos", 10),
                 ("No auditados", 13), ("Error medido", 30), ("Aceptable", 11), ("Dictamen", 18),
                 ("Por qué", 70)],
                [
                    [
                        h["habilidad"],
                        h.get("revisados", 0),
                        h.get("bien", 0),
                        h.get("errores", 0),
                        h.get("dudosos", 0),
                        h.get("no_auditados", 0),
                        _texto_del_margen(h.get("margen") or {}, de_filas),
                        f"{round(float((h.get('margen') or {}).get('aceptable') or 0) * 100, 1):g} %",
                        (h.get("margen") or {}).get("dictamen", ""),
                        (h.get("margen") or {}).get("texto_del_dictamen", ""),
                    ]
                    for h in muestra["por_habilidad"]
                ],
                color_en=8,
            )
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / NOMBRE_DEL_ANALISIS
    return guardar_libro(libro, ruta)
