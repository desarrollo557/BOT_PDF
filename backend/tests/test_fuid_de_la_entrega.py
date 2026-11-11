"""El mismo FUID para todas las habilidades, con la oficina de su carpeta.

Lo pidió el operador el 2026-10-29 sobre el REPOSITORIO UDC: seis carpetas --
Enfermería, Odontología, Secretaría, Medicina, Derecho y las actas de grado de
Medicina -- con «el mismo inventario general, el mismo FUID». Aquí se fija lo
que no depende de leer papel: de dónde sale la oficina productora de la
cabecera, cómo se convierte la fila de cada habilidad a la del FO-GD-008 y qué
queda escrito en la plantilla.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openpyxl")

from openpyxl import Workbook  # noqa: E402

from resolutions.adapters.fuid_actas_de_consejo import (  # noqa: E402
    asunto_del_acta,
)
from resolutions.adapters.fuid_actas_de_consejo import (  # noqa: E402
    fila_del_fuid as fila_de_acta,
)
from resolutions.adapters.fuid_de_la_entrega import (  # noqa: E402
    FILA_HECHA,
    archivo_de,
    escribir_fuid,
    fila_del_fuid,
    fila_generica,
    filas_del_fuid,
    ruta_del_fuid,
)
from resolutions.adapters.fuid_reader import leer_fuid  # noqa: E402
from resolutions.adapters.inventario_del_cliente import (  # noqa: E402
    es_del_bot,
    oficina_de_la_carpeta,
    oficina_del_excel,
)
from resolutions.application.fuid import FuidRow  # noqa: E402
from resolutions.domain.oficina_productora import (  # noqa: E402
    oficina_de_la_ruta,
    oficina_escrita,
)

UDC = "Z:\\Shared with Me\\REPOSITORIO UDC"


# -- la oficina productora ----------------------------------------------------


@pytest.mark.parametrize(
    ("carpeta", "oficina"),
    [
        ("14. ENFERMERIA 3277-3283 P", "FACULTAD DE ENFERMERIA"),
        ("15. ODONTOLOGIA 3284 - 3290 P", "FACULTAD DE ODONTOLOGIA"),
        ("16. SECRETARIA 3292", "SECRETARIA GENERAL"),
        ("17. FACULTAD DE MEDICINA 3261- 3268 P", "FACULTAD DE MEDICINA"),
        # Estas dos no nombran su facultad: la dice el Excel del cliente.
        ("18-RESOLUCIONES INTERNAS Y ACTAS 3303", None),
        ("20.ACTAS DE GRADO 3362", None),
    ],
)
def test_la_oficina_sale_del_nombre_de_la_carpeta(carpeta, oficina):
    assert oficina_de_la_ruta(f"{UDC}\\{carpeta}") == oficina


def test_manda_la_carpeta_mas_cercana_a_los_pdf():
    """«SECRETARIA ACADEMICA» dentro de Medicina es de Medicina, no de la Secretaría General."""
    assert oficina_de_la_ruta(f"{UDC}\\SECRETARIA\\17. FACULTAD DE MEDICINA") == "FACULTAD DE MEDICINA"
    assert oficina_de_la_ruta("/equipo/z/REPOSITORIO UDC/14. ENFERMERIA 3277") == "FACULTAD DE ENFERMERIA"


def test_una_palabra_suelta_no_es_una_facultad():
    """«MEDICINAS» o «INGENIERIAS» no son palabra completa: no nombran nada."""
    assert oficina_de_la_ruta(f"{UDC}\\FACTURAS DE MEDICINAS") is None
    assert oficina_de_la_ruta("") is None


def test_lo_que_escribe_el_operador_se_normaliza():
    assert oficina_escrita("  facultad   de  derecho ") == "FACULTAD DE DERECHO"
    assert oficina_escrita("") is None
    assert oficina_escrita(None) is None
    assert len(oficina_escrita("X" * 500)) == 120


def _excel_del_cliente(ruta, oficinas, *, fila_de_cabecera=4):
    libro = Workbook()
    hoja = libro.active
    hoja.cell(row=fila_de_cabecera, column=1, value="ITEM")
    hoja.cell(row=fila_de_cabecera, column=5, value="OFICINA PRODUCTORA")
    for desplazamiento, oficina in enumerate(oficinas, start=1):
        hoja.cell(row=fila_de_cabecera + desplazamiento, column=1, value=desplazamiento)
        hoja.cell(row=fila_de_cabecera + desplazamiento, column=5, value=oficina)
    libro.save(ruta)
    return ruta


def test_el_excel_del_cliente_dice_la_oficina_que_mas_se_repite(tmp_path):
    ruta = _excel_del_cliente(
        tmp_path / "RESOLUCIONES INTERNAS Y ACTAS.xlsx",
        [
            "FACULTAD DE DERECHO Y CIENCIAS POLITICAS",
            "FACULTAD  DE DERECHO Y CIENCIAS POLITICAS ",
            "VICERRECTORIA DE DOCENCIA",
        ],
    )
    assert oficina_del_excel(ruta) == "FACULTAD DE DERECHO Y CIENCIAS POLITICAS"


def test_sin_la_columna_el_excel_no_dice_nada(tmp_path):
    libro = Workbook()
    libro.active.append(["ITEM", "NOMBRE O ASUNTOS"])
    libro.active.append([1, "ACTAS"])
    libro.save(tmp_path / "otro.xlsx")
    assert oficina_del_excel(tmp_path / "otro.xlsx") is None
    assert oficina_del_excel(tmp_path / "no-existe.xlsx") is None


@pytest.mark.parametrize(
    "nombre",
    ["00.FUID GENERAL.xlsx", "UPD3859753__FUID.xlsx", "ACTAS UPD__inventario.xlsx", "~$abierto.xlsx"],
)
def test_los_excel_del_bot_no_cuentan_como_del_cliente(nombre):
    assert es_del_bot(nombre)


def test_la_carpeta_lee_el_suyo_y_no_el_del_bot(tmp_path):
    _excel_del_cliente(tmp_path / "00.FUID GENERAL.xlsx", ["FACULTAD DE INGENIERIA"])
    _excel_del_cliente(tmp_path / "ACTAS DE GRADO MEDICINA.xlsx", ["FACULTAD DE MEDICINA"])
    assert oficina_de_la_carpeta(tmp_path) == "FACULTAD DE MEDICINA"
    assert oficina_de_la_carpeta(tmp_path / "no-existe") is None


# -- la fila de cada habilidad -------------------------------------------------


def test_un_acta_de_consejo_lleva_su_consejo_y_su_sesion_sin_el_numero():
    """El operador, 2026-11-11: «que quede sin el número de acta». El número va en el consecutivo."""
    fila = fila_de_acta({"acta": "ACTA EXTRAORDINARIA No. 011", "numero": "011", "resumen": "El Consejo sesionó."})
    assert fila.asunto == "ACTA DE CONSEJO DE FACULTAD - EXTRAORDINARIA - El Consejo sesionó."
    assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("011", "011")
    assert asunto_del_acta({"acta": "Acta ordinaria", "numero": "022"}) == (
        "ACTA DE CONSEJO DE FACULTAD - ORDINARIA"
    )
    assert asunto_del_acta({"acta": "CONSEJO ACADÉMICO, sesión extraordinaria", "numero": "5"}) == (
        "ACTA DE CONSEJO ACADEMICO - EXTRAORDINARIA"
    )
    assert asunto_del_acta({"acta": "", "numero": ""}) == "ACTA DE CONSEJO DE FACULTAD"


def test_la_fila_de_un_acta_de_consejo():
    fila = fila_de_acta(
        {
            "acta": "ACTA ORDINARIA",
            "numero": "015",
            "fecha": "10-08-2012",
            "folios": 4,
            "folio_inicial": 120,
            "folio_final": 123,
            "carpeta": "15. ODONTOLOGIA\\00C003284\\UPD3859771",
            "archivo": "6N° 015-10 DE AGOSTO DE 2012.pdf",
            "pagina_inicial": 1,
        }
    )
    assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("015", "015")
    assert (fila.fecha_inicial, fila.fecha_final) == ("10/08/2012", "10/08/2012")
    assert (fila.caja, fila.carpeta) == ("00C003284", "UPD3859771")
    assert (fila.folios, fila.folios_siar) == (4, 4)
    assert fila.notas == "folios 120 a 123"


def test_el_asunto_del_acta_lleva_su_sesion_y_su_resumen_con_los_nombres():
    """El operador, 2026-11-09: «ACTA DE CONSEJO DE FACULTAD - ORDINARIA - RESUMEN», con
    «el nombre de las personas que mencionan». Sin el número del acta desde el 2026-11-11."""
    resumen = (
        "El Consejo de Facultad de Odontología, presidido por la doctora Luisa Leonor Arévalo Tovar, "
        "otorgó la distinción Ivo Seni Canata al docente investigador Antonio Díaz Caballero."
    )
    fila = fila_de_acta({"acta": "ACTA ORDINARIA", "numero": "022", "resumen": f"  {resumen}\n"})
    assert fila.asunto == f"ACTA DE CONSEJO DE FACULTAD - ORDINARIA - {resumen}"
    # Sin resumen («Solo OCR»), el asunto como antes: sin un «- N/A» colgando.
    sin_resumen = fila_de_acta({"acta": "ACTA EXTRAORDINARIA", "numero": "09"})
    assert sin_resumen.asunto == "ACTA DE CONSEJO DE FACULTAD - EXTRAORDINARIA"
    # Y al resumidor se le pide nombrar a las personas, no la lista de asistentes.
    from resolutions.adapters.mistral_resumen import INSTRUCCIONES

    assert "Nombra a las personas que el acta menciona" in INSTRUCCIONES
    assert "ni la lista de asistentes" in INSTRUCCIONES


def test_sin_fecha_ni_folios_queda_na_y_no_se_inventa():
    fila = fila_de_acta({"numero": "3", "fecha": "2012", "carpeta": "", "archivo": "acta.pdf"})
    assert (fila.fecha_inicial, fila.folios) == ("N/A", "N/A")
    assert (fila.caja, fila.carpeta) == ("", "")


def test_la_fila_generica_de_un_tipo_sin_reglas_propias():
    fila = fila_generica(
        {
            "tipo": "MATRICULA ACADEMICA",
            "nombre": "ANA PEREZ",
            "codigo": "5420011003",
            "fecha_inicial": 1990,
            "fecha_final": "3/7/1991",
            "folios": 1,
            "carpeta": "17. FACULTAD DE MEDICINA\\CAJA00C003268",
            "archivo": "UPD0077188 - MATRICULAS ESPECIALES.pdf",
        }
    )
    assert fila.asunto == "ANA PEREZ - MATRICULA ACADEMICA"
    assert (fila.consecutivo_inicial, fila.consecutivo_final) == ("N/A", "5420011003")
    assert (fila.fecha_inicial, fila.fecha_final) == ("01/01/1990", "03/07/1991")
    assert (fila.caja, fila.carpeta) == ("00C003268", "UPD0077188")


def _resolucion(**cambios):
    datos = {
        "orden": 3,
        "asunto": "RESOLUCION 00031 POR LA CUAL SE CONVOCA",
        "codigo_trd": "N/A",
        "consecutivo_inicial": "00031",
        "consecutivo_final": "00031",
        "fecha_inicial": "02-09-2010",
        "fecha_final": "02-09-2010",
        "caja": "N/A",
        "carpeta": "N/A",
        "tomo": "N/A",
        "otro": "N/A",
        "folios": 2,
        "folios_siar": 2,
        "soporte": "N/A",
        "frecuencia": "N/A",
        "notas": "Archivo: 02_RESOLUCION-00031.pdf",
        "pagina_inicial": 3,
    }
    return {**datos, **cambios}


def test_la_fila_hecha_toma_la_caja_y_la_upd_de_su_ruta():
    """La resolución no sabe en qué caja está; la corrida sí, por la ruta."""
    fila = fila_del_fuid(
        {
            "tipo": FILA_HECHA,
            "fuid": _resolucion(),
            "carpeta": "18-RESOLUCIONES INTERNAS Y ACTAS 3303\\00C003303",
            "archivo": "UPD3859990-RESOLUCIONES INTERNAS 2010 N°30-31-32.pdf",
            "pagina_inicial": 3,
        }
    )
    assert fila.asunto == "RESOLUCION 00031 POR LA CUAL SE CONVOCA"
    assert (fila.caja, fila.carpeta) == ("00C003303", "UPD3859990")
    assert fila.fecha_inicial == "02-09-2010"
    # Ya dice su archivo: no se le añade además el del original.
    assert fila.notas == "Archivo: 02_RESOLUCION-00031.pdf"


def test_la_fila_hecha_sin_ruta_conserva_lo_que_traia():
    fila = fila_del_fuid({"tipo": FILA_HECHA, "fuid": _resolucion(caja="3220", carpeta="UPD1"), "carpeta": "", "archivo": "x.pdf"})
    assert (fila.caja, fila.carpeta) == ("3220", "UPD1")


def test_el_archivo_entero_dice_su_nombre_sin_paginas():
    fila = {
        "tipo": FILA_HECHA,
        "fuid": _resolucion(asunto="EXAMENES PREPARATORIOS DE GRADO 1924-46", notas=""),
        "carpeta": "20.ACTAS DE GRADO 3362",
        "archivo": "UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf",
        "pagina_inicial": 1,
        "entero": True,
    }
    assert archivo_de(fila) == "UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf"
    assert fila_del_fuid(fila).notas == "Archivo: UPD3860000-EXAMENES PREPARATORIOS DE GRADO 1924-46.pdf"


@pytest.mark.parametrize(
    ("carpeta", "archivo", "caja", "upd"),
    [
        # Odontología: la caja y la UPD son subcarpetas.
        ("15. ODONTOLOGIA\\00C003284\\UPD3859771", "6N° 015.pdf", "00C003284", "UPD3859771"),
        # Enfermería: «CAJA 00C003282» y la UPD delante del nombre del PDF.
        ("14. ENFERMERIA\\CAJA 00C003282", "UPD3859755-1HISTORIAS.pdf", "00C003282", "UPD3859755"),
        # Medicina: el rótulo pegado y la UPD con un espacio.
        ("17. MEDICINA\\CAJA00C003261", "UPD 3859597 HISTORIAS ACADEMICAS 1948-1960.pdf", "00C003261", "UPD3859597"),
        ("17. MEDICINA\\CAJA00C003268", "UPD0077188 - MATRICULAS.pdf", "00C003268", "UPD0077188"),
        # Sin caja en la ruta no se inventa una.
        ("17. MEDICINA\\CAJA00C003265", "1HISTORIAS ACADEMICAS 1946-1990.pdf", "00C003265", ""),
        ("", "HISTORIAS 1993.pdf", "", ""),
    ],
)
def test_la_caja_y_la_upd_salen_de_la_ruta_como_la_nombre_cada_facultad(carpeta, archivo, caja, upd):
    from resolutions.adapters.fuid_actas_de_grado import ubicacion

    assert ubicacion(carpeta, archivo) == (caja, upd)


def test_una_fila_hecha_rota_no_lleva_fila():
    assert fila_del_fuid({"tipo": FILA_HECHA, "fuid": None}) is None


def test_el_archivo_de_una_fila_dice_sus_paginas():
    assert archivo_de({"archivo": "libro.pdf", "pagina_inicial": 4, "pagina_final": 9}) == "libro.pdf, págs. 4 a 9"
    assert archivo_de({"archivo": "libro.pdf", "pagina_inicial": 4, "pagina_final": 4}) == "libro.pdf, pág. 4"
    assert archivo_de({"archivo": "libro.pdf", "archivo_generado": "03_ACTA.pdf"}) == "03_ACTA.pdf"
    assert archivo_de({"archivo": "libro.pdf", "resultado": "Dividido en 02_ACTA-NO-3.pdf"}) == "02_ACTA-NO-3.pdf"


def test_las_filas_se_numeran_desde_uno_sin_contar_las_que_no_llevan_fila():
    filas = filas_del_fuid(
        [
            {"tipo": "SIN ESTUDIANTE", "archivo": "h.pdf", "pagina_inicial": 1},
            {"tipo": "HISTORIA ACADEMICA", "nombre": "ANA PEREZ", "folios": 2, "archivo": "h.pdf", "pagina_inicial": 2},
            {"tipo": FILA_HECHA, "fuid": _resolucion(), "carpeta": "", "archivo": "r.pdf"},
        ]
    )
    assert [fila.orden for fila in filas] == [1, 2]
    # Sólo el nombre (el operador, 2026-11-06).
    assert filas[0].asunto == "ANA PEREZ"


# -- lo que queda escrito -----------------------------------------------------


def test_el_fuid_lleva_la_oficina_de_su_carpeta_y_las_filas_de_todas_las_habilidades(tmp_path):
    destino = tmp_path / "00C003303__FUID.xlsx"
    escribir_fuid(
        [
            {
                "tipo": FILA_HECHA,
                "fuid": _resolucion(),
                "carpeta": "00C003303",
                "archivo": "UPD3859990-RESOLUCIONES.pdf",
            },
            {
                "acta": "ACTA ORDINARIA",
                "numero": "02",
                "fecha": "22-01-2004",
                "folios": 7,
                "carpeta": "00C003303",
                "archivo": "UPD3859988-ACTAS N° 02 AL 10- Y 13.pdf",
                "pagina_inicial": 1,
                "pagina_final": 7,
            },
        ],
        destino,
        oficina="FACULTAD DE DERECHO Y CIENCIAS POLITICAS",
    )
    planilla = leer_fuid(destino)
    assert planilla.oficina_productora.endswith("FACULTAD DE DERECHO Y CIENCIAS POLITICAS")
    assert [fila[0] for fila in planilla.filas] == ["1", "2"]
    assert planilla.filas[0][2].startswith("RESOLUCION 00031")
    assert planilla.filas[1][2] == "ACTA DE CONSEJO DE FACULTAD - ORDINARIA"
    assert planilla.filas[1][15] == ""  # NOTAS va vacía (2026-10-30)


def test_el_fuid_de_actas_es_el_formato_original_con_el_resumen_en_el_asunto(tmp_path):
    """El operador, 2026-11-09: «un FUID limpio, manejando el original». Sin ACTA #, OBJETIVO /
    RESUMEN ni las páginas del PDF a la derecha de NOTAS (de 2026-10-31): el resumen va en el asunto,
    entero, y la fila crece hasta leerlo."""
    from openpyxl import load_workbook

    resumen = (
        "El Consejo de Facultad de Odontología, presidido por la doctora Luisa Leonor Arévalo Tovar, "
        "aprobó el calendario académico y las correcciones de notas de los estudiantes Katyuska Medina "
        "Márquez y Johnny Ricardo Galindo Ruello, solicitadas por los docentes César Herrera Zárate y "
        "Luis Eduardo Carmona Arango..."
    )
    destino = escribir_fuid(
        [
            {
                "acta": "ACTA ORDINARIA",
                "numero": "022",
                "fecha": "13-12-2016",
                "folios": 15,
                "resumen": resumen,
                "carpeta": "15. ODONTOLOGIA\\00C003286\\UPD3859793",
                "archivo": "1ACTAS DE CONSEJO N°22 Y 23 2016.pdf",
                "pagina_inicial": 1,
                "pagina_final": 50,
            },
            {
                "acta": "ACTA EXTRAORDINARIA",
                "numero": "023",
                "fecha": "19-12-2016",
                "folios": 6,
                "resumen": "N/A",
                "carpeta": "15. ODONTOLOGIA\\00C003286\\UPD3859793",
                "archivo": "1ACTAS DE CONSEJO N°22 Y 23 2016.pdf",
                "pagina_inicial": 51,
                "pagina_final": 57,
            },
        ],
        tmp_path / "UPD3859793__FUID.xlsx",
    )
    hoja = load_workbook(destino)["INVENTARIO"]
    # Nada a la derecha de NOTAS: ni títulos ni filas.
    assert all(hoja.cell(row=f, column=c).value is None for f in (12, 13, 14, 15) for c in range(17, 21))
    # El asunto, entero y sin «...» al final.
    esperado = "ACTA DE CONSEJO DE FACULTAD - ORDINARIA - " + resumen[:-3] + "."
    assert hoja["C14"].value == esperado
    assert "..." not in hoja["C14"].value and "…" not in hoja["C14"].value
    # Se ajusta y la fila crece para que se lea; el acta sin resumen, como siempre.
    assert hoja["C14"].alignment.wrap_text
    assert hoja.row_dimensions[14].height > 20
    assert hoja["C15"].value == "ACTA DE CONSEJO DE FACULTAD - EXTRAORDINARIA"
    assert hoja.row_dimensions[15].height == 20
    # Las de siempre siguen donde estaban: fechas extremas y folios.
    assert (hoja["F14"].value, hoja["L14"].value) == ("13/12/2016", 15)


def test_un_fuid_viejo_como_plantilla_pierde_las_columnas_de_actas(tmp_path):
    """Si la plantilla es un FUID de antes del 2026-11-09, con ACTA # y OBJETIVO / RESUMEN, se limpian."""
    from pathlib import Path

    from openpyxl import load_workbook

    import resolutions
    from resolutions.adapters.fuid_inventory import FuidInventory

    libro = load_workbook(Path(resolutions.__file__).parent / "assets" / "fuid-fo-gd-008.xlsx")
    hoja = libro["INVENTARIO"]
    hoja["Q12"], hoja["R12"], hoja["S12"] = "ACTA #", "OBJETIVO / RESUMEN", "PÁGINAS DEL PDF"
    hoja.merge_cells("Q12:Q13")
    hoja.merge_cells("S12:T12")
    hoja["S13"], hoja["T13"] = "Desde", "Hasta"
    hoja["Q14"], hoja["R14"], hoja["S14"], hoja["T14"] = "022", "Un resumen viejo", 1, 22
    viejo = tmp_path / "viejo__FUID.xlsx"
    libro.save(viejo)

    destino = FuidInventory(viejo).write([FuidRow(orden=1, asunto="ACTA DE CONSEJO DE FACULTAD")], tmp_path / "x.xlsx")
    nuevo = load_workbook(destino)["INVENTARIO"]
    assert all(nuevo.cell(row=f, column=c).value is None for f in (12, 13, 14) for c in range(17, 21))
    assert not [str(r) for r in nuevo.merged_cells.ranges if r.min_col >= 17 and r.min_row in (12, 13)]
    assert nuevo["C14"].value == "ACTA DE CONSEJO DE FACULTAD"


def test_sin_actas_el_fuid_no_lleva_esas_columnas(tmp_path):
    from openpyxl import load_workbook

    destino = escribir_fuid([FuidRow(orden=1, asunto="X")], tmp_path / "x__FUID.xlsx")
    assert load_workbook(destino)["INVENTARIO"]["Q12"].value is None


def test_sin_oficina_la_cabecera_queda_como_la_plantilla(tmp_path):
    destino = escribir_fuid([FuidRow(orden=1, asunto="X")], tmp_path / "x__FUID.xlsx")
    assert "OFICINA PRODUCTORA" in leer_fuid(destino).oficina_productora


def test_el_fuid_de_una_subcarpeta_va_dentro_de_ella(tmp_path):
    carpeta = tmp_path / "15. ODONTOLOGIA" / "00C003284" / "UPD3859771"
    assert ruta_del_fuid(carpeta) == carpeta / "UPD3859771__FUID.xlsx"
