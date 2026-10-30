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


def test_un_acta_de_consejo_lleva_su_consejo_su_numero_y_su_sesion():
    assert asunto_del_acta({"acta": "Acta ordinaria", "numero": "022"}) == (
        "ACTA DE CONSEJO DE FACULTAD No. 022 - ORDINARIA"
    )
    assert asunto_del_acta({"acta": "CONSEJO ACADÉMICO, sesión extraordinaria", "numero": "5"}) == (
        "ACTA DE CONSEJO ACADEMICO No. 5 - EXTRAORDINARIA"
    )
    assert asunto_del_acta({"acta": "", "numero": ""}) == "ACTA DE CONSEJO DE FACULTAD No. N/A"


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
    assert filas[0].asunto == "ANA PEREZ - HISTORIA ACADEMICA"


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
    assert planilla.filas[1][2] == "ACTA DE CONSEJO DE FACULTAD No. 02 - ORDINARIA"
    assert planilla.filas[1][15] == "Archivo: UPD3859988-ACTAS N° 02 AL 10- Y 13.pdf, págs. 1 a 7"


def test_sin_oficina_la_cabecera_queda_como_la_plantilla(tmp_path):
    destino = escribir_fuid([FuidRow(orden=1, asunto="X")], tmp_path / "x__FUID.xlsx")
    assert "OFICINA PRODUCTORA" in leer_fuid(destino).oficina_productora


def test_el_fuid_de_una_subcarpeta_va_dentro_de_ella(tmp_path):
    carpeta = tmp_path / "15. ODONTOLOGIA" / "00C003284" / "UPD3859771"
    assert ruta_del_fuid(carpeta) == carpeta / "UPD3859771__FUID.xlsx"
